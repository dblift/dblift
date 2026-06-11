"""MigrationStateManager orchestrates history + script data into JSON state snapshots."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple, cast

from core.logger import Log
from core.migration.history.migration_history_manager import MigrationHistoryManager
from core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration, MigrationType
from core.migration.rules.migration_rules import MigrationRules
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.state.migration_data_service import MigrationDataService
from core.migration.state.migration_display_state import (
    MigrationDisplayState,  # re-export for compatibility
)
from core.migration.state.migration_formatter import (
    MigrationFormatter,  # backwards-compat public API
)
from core.migration.state.migration_state import (
    ChecksumChange,
    MigrationEntry,
    MigrationState,
)
from core.migration.state.migration_state_service import MigrationStateService
from core.migration.version_utils import is_migration_failure


class StrictModeError(ValueError):
    """Raised by ``_is_versioned_pending`` when ``strict_mode=True`` and an
    out-of-order migration is detected. Subclasses :class:`ValueError` so
    callers that haven't migrated to the narrower type still catch it,
    but lets ``MigrateCommand`` distinguish strict-mode violations from
    arbitrary :class:`ValueError` instances raised elsewhere in the
    migrate flow (PR #241 Bugbot)."""


@dataclass(slots=True)
class _HistoryAnalysis:
    applied: List[Migration]
    undone_versions: Set[str]
    reapplied_versions: Set[str]
    executed_scripts: Set[str]
    executed_versions: Set[str]  # For versioned migrations, track by version
    repeatable_checksums: Dict[str, str]
    deleted_scripts: Set[str]
    failed_migrations: List[Migration]


class MigrationStateManager:
    """Central coordinator for building migration state snapshots."""

    def __init__(
        self,
        logger: Log,
        history_manager: MigrationHistoryManager,
        script_manager: MigrationScriptManager,
        migration_rules: MigrationRules,
    ) -> None:
        """Wire the history/script/rules collaborators and instantiate the state and formatter helpers."""
        self.logger = logger
        self.history_manager = history_manager
        self.script_manager = script_manager
        self.migration_rules = migration_rules

        self.state_service = MigrationStateService(logger)
        self.formatter = MigrationFormatter(logger)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------
    def build_state(
        self,
        scripts_dir: Optional[Path],
        *,
        recursive: bool = True,
        additional_dirs: Optional[Sequence[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        target_version: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        exclude_tags: Optional[Sequence[str]] = None,
        versions: Optional[Sequence[str]] = None,
        exclude_versions: Optional[Sequence[str]] = None,
        strict_mode: bool = False,
    ) -> MigrationState:
        """Rebuild and return the current migration state as a JSON-ready snapshot."""

        applied_migrations = self.history_manager.get_applied_migrations()
        self.logger.debug(f"Loaded {len(applied_migrations)} applied migrations from history")

        data_service = MigrationDataService(
            self.logger, scripts_dir=scripts_dir, target_version=target_version
        )
        analysis_context = data_service._build_analysis_context(applied_migrations)
        analysis_context["target_version"] = target_version
        analysis_context["scripts_dir"] = scripts_dir

        history = self._analyse_history(applied_migrations, analysis_context)

        pending_migrations: List[Migration] = []
        if scripts_dir:
            # Use NEW centralized pending computation method
            pending_migrations = self._compute_pending_migrations(
                scripts_dir,
                history.executed_scripts,
                applied_migrations,
                history.undone_versions,
                history.repeatable_checksums,
                history.executed_versions,
                recursive=recursive,
                additional_dirs=list(additional_dirs) if additional_dirs else None,
                target_version=target_version,
                tags=self._normalize_filter(tags),
                exclude_tags=self._normalize_filter(exclude_tags),
                versions=self._normalize_filter(versions),
                exclude_versions=self._normalize_filter(exclude_versions),
                strict_mode=strict_mode,
                baseline_version=analysis_context.get("baseline_version"),
            )

        self._mark_resolved_status(
            applied_migrations,
            pending_migrations,
            scripts_available=bool(scripts_dir),
        )

        checksum_changes = self._determine_checksum_changes(
            pending_migrations,
            history.repeatable_checksums,
        )

        applied_entries, failed_entries = self._build_applied_entries(
            applied_migrations, analysis_context
        )
        pending_entries = self._build_pending_entries(pending_migrations, analysis_context)

        # Filter out undone migrations from applied_objects (unless they were reapplied)
        # This ensures that migrations that were undone don't appear in the applied list
        undone_but_not_reapplied = history.undone_versions - history.reapplied_versions
        applied_objects_filtered = [
            m
            for m in applied_migrations
            if (
                # Keep non-versioned migrations (repeatable, callback, etc.)
                self._get_type_name(m) not in VERSIONED_SCRIPT_TYPES
                # Keep versioned migrations that haven't been undone
                or str(getattr(m, "version", "")) not in undone_but_not_reapplied
            )
        ]

        # Apply tag/version filters to applied_objects if filters are provided
        # This is needed for undo command to only consider migrations matching the filters
        if tags or exclude_tags or versions or exclude_versions:
            applied_objects_filtered = [
                m
                for m in applied_objects_filtered
                if self._passes_filters(
                    m,
                    target_version,
                    self._normalize_filter(tags),
                    self._normalize_filter(exclude_tags),
                    self._normalize_filter(versions),
                    self._normalize_filter(exclude_versions),
                )
            ]

        state = MigrationState(
            current_version=analysis_context.get("current_version"),
            baseline_version=analysis_context.get("baseline_version"),
            applied=applied_entries,
            pending=pending_entries,
            failed=failed_entries,
            undone_versions=sorted(
                version
                for version in history.undone_versions
                if version not in history.reapplied_versions
            ),
            deleted_scripts=sorted(history.deleted_scripts),
            checksum_changes=checksum_changes,
            applied_objects=applied_objects_filtered,
            all_applied_objects=list(applied_migrations),
            pending_objects=pending_migrations,
            failed_objects=history.failed_migrations,
            executed_scripts=sorted(history.executed_scripts),
            repeatable_checksums=dict(history.repeatable_checksums),
        )

        self.logger.debug("Migration state snapshot generated")
        return state

    # ------------------------------------------------------------------
    # Legacy formatting helpers (kept for compatibility with older callers)
    # ------------------------------------------------------------------
    def format_state(self, state: str) -> str:
        """Return a display-friendly capitalised form of a state name (``""`` for falsy input)."""
        return (state or "").lower().capitalize()

    def format_category(self, category: str) -> str:
        """Capitalise only the first letter of ``category`` (preserves embedded casing)."""
        if not category:
            return ""
        return category[0].upper() + category[1:].lower()

    def format_version(self, version: Optional[str]) -> str:
        """Render a version string in display form (underscores replaced with dots)."""
        if not version:
            return ""
        return str(version).replace("_", ".")

    def get_category_and_display_type(self, m_type: str) -> Tuple[str, str]:
        """Return ``(category, display_type)`` for ``m_type`` (enums coerced to upper-case strings)."""
        # m_type may be an enum; coerce to string before uppercasing
        display_type = str(m_type or "UNKNOWN").upper()
        return self.format_category(display_type), display_type

    def format_as_table(self, migration_data: List[Dict[str, Any]]) -> str:
        """Delegate to :class:`MigrationFormatter` to render ``migration_data`` as a CLI table."""
        return self.formatter.format_as_table(migration_data)

    def format_as_json(self, migration_data: List[Dict[str, Any]]) -> Dict[str, Any]:
        """Delegate to :class:`MigrationFormatter` to render ``migration_data`` as a JSON-ready dict."""
        return self.formatter.format_as_json(migration_data)

    def format_as_html(self, migration_data: List[Dict[str, Any]]) -> str:
        """Delegate to :class:`MigrationFormatter` to render ``migration_data`` as an HTML fragment."""
        return self.formatter.format_as_html(migration_data)

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------
    def _mark_resolved_status(
        self,
        applied_migrations: List[Migration],
        pending_migrations: List[Migration],
        *,
        scripts_available: bool,
    ) -> None:
        """Mark whether applied history rows still have a matching script resource."""
        if not scripts_available:
            for migration in applied_migrations:
                migration.resolved = True
            return

        resolved_script_names: Set[str] = set()
        for migration in pending_migrations:
            script_name = getattr(migration, "script_name", "")
            if script_name:
                resolved_script_names.add(script_name)
                resolved_script_names.add(Path(script_name).name)
            migration.resolved = True

        for migration in applied_migrations:
            script_name = getattr(migration, "script_name", "")
            basename = Path(script_name).name if script_name else ""
            migration.resolved = bool(
                not script_name
                or script_name in resolved_script_names
                or basename in resolved_script_names
            )

    def _analyse_history(
        self,
        applied_migrations: List[Migration],
        context: Dict[str, Optional[str]],
    ) -> _HistoryAnalysis:
        undone_versions_raw: Optional[Any] = context.get("undone_versions", set())
        undone_versions = set(undone_versions_raw) if undone_versions_raw else set()
        reapplied_versions_raw: Optional[Any] = context.get("reapplied_versions", set())
        reapplied_versions = set(reapplied_versions_raw) if reapplied_versions_raw else set()

        executed_scripts: Set[str] = set()
        repeatable_successes: Dict[str, Migration] = {}
        deleted_scripts: Set[str] = set()
        failed_migrations: List[Migration] = []
        version_groups: Dict[str, List[Migration]] = {}

        for migration in applied_migrations:
            migration_type = self._get_type_name(migration)
            script_name = getattr(migration, "script_name", "")

            if migration_type == "DELETE":
                deleted_scripts.add(script_name)
                continue

            # Only add to failed_migrations if explicitly failed (success=False)
            # NULL/None means the migration can be retried (e.g., after repair)
            success_value = getattr(migration, "success", None)
            is_explicitly_failed = is_migration_failure(success_value)
            if is_explicitly_failed:
                failed_migrations.append(migration)

            is_success = self.migration_rules.is_success(migration)

            if migration_type in VERSIONED_SCRIPT_TYPES and is_success:
                version = str(getattr(migration, "version", "") or "")
                if version:
                    version_groups.setdefault(version, []).append(migration)
            elif migration_type == "REPEATABLE" and is_success:
                recorded = repeatable_successes.get(script_name)
                if not recorded or self._installed_rank(migration) > self._installed_rank(recorded):
                    repeatable_successes[script_name] = migration
                executed_scripts.add(script_name)
            elif migration_type == "CALLBACK" and is_success:
                executed_scripts.add(script_name)

        # Track executed versions for versioned migrations
        # For versioned migrations, we check by version (not script_name) because:
        # 1. Each version is unique and should only be executed once
        # 2. Avoids issues with script name normalization (relative paths vs filenames)
        executed_versions: Set[str] = set()

        for version, migrations in version_groups.items():
            migrations.sort(key=self._installed_rank, reverse=True)
            most_recent = migrations[0]
            if version in undone_versions and version not in reapplied_versions:
                continue
            # For versioned migrations, track by version (primary key)
            executed_versions.add(str(version))
            # Also keep script_name for backward compatibility and traceability
            script_name = getattr(most_recent, "script_name", "")
            executed_scripts.add(script_name)
            # Also add basename for comparison (handle both relative paths and filenames)
            if "/" in script_name:
                basename = Path(script_name).name
                executed_scripts.add(basename)

        repeatable_checksums: Dict[str, str] = {}
        for script, migration in repeatable_successes.items():
            checksum = getattr(migration, "checksum", None)
            if checksum:
                repeatable_checksums[script] = checksum

        # Prevent failed migrations from appearing as Pending:
        # add their versions/script names to the executed sets so
        # _is_versioned_pending() returns False for them.
        for _fm in failed_migrations:
            _fv = str(getattr(_fm, "version", "") or "")
            if _fv:
                executed_versions.add(_fv)
            _fs = getattr(_fm, "script_name", "")
            if _fs:
                executed_scripts.add(_fs)
                if "/" in _fs:
                    executed_scripts.add(Path(_fs).name)

        return _HistoryAnalysis(
            applied=applied_migrations,
            undone_versions=undone_versions,
            reapplied_versions=reapplied_versions,
            executed_scripts=executed_scripts,
            executed_versions=executed_versions,
            repeatable_checksums=repeatable_checksums,
            deleted_scripts=deleted_scripts,
            failed_migrations=failed_migrations,
        )

    def _build_applied_entries(
        self, applied_migrations: List[Migration], context: Dict[str, Optional[str]]
    ) -> Tuple[List[MigrationEntry], List[MigrationEntry]]:
        applied_entries: List[MigrationEntry] = []
        failed_entries: List[MigrationEntry] = []

        for migration in applied_migrations:
            display_state = self.state_service.determine_state(migration, context)
            entry = MigrationEntry.from_migration(migration, status=display_state.value)
            applied_entries.append(entry)

            if entry.status and entry.status.upper().startswith("FAILED"):
                failed_entries.append(entry)
            elif entry.status == MigrationDisplayState.NEEDS_REPAIR.value:
                failed_entries.append(entry)

        return applied_entries, failed_entries

    def _build_pending_entries(
        self, pending_migrations: List[Migration], context: Dict[str, Optional[str]]
    ) -> List[MigrationEntry]:
        pending_entries: List[MigrationEntry] = []

        for migration in pending_migrations:
            state = self.state_service.determine_pending_state(migration, context)
            pending_entries.append(MigrationEntry.from_migration(migration, status=state.value))

        return pending_entries

    def _determine_checksum_changes(
        self,
        pending_migrations: Iterable[Migration],
        previous_checksums: Dict[str, str],
    ) -> List[ChecksumChange]:
        changes: List[ChecksumChange] = []

        for migration in pending_migrations:
            if getattr(migration, "type", None) != MigrationType.REPEATABLE:
                continue

            current_checksum = getattr(migration, "checksum", None)
            if not current_checksum:
                continue

            script_key = getattr(migration, "script_name", "")
            previous_checksum = self._lookup_checksum(previous_checksums, script_key)

            if previous_checksum and previous_checksum != current_checksum:
                changes.append(
                    ChecksumChange(
                        script_name=script_key,
                        previous_checksum=previous_checksum,
                        current_checksum=current_checksum,
                    )
                )

        return changes

    # ------------------------------------------------------------------
    # Utility helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _normalize_filter(value: Optional[Sequence[str]]) -> Optional[List[str]]:
        if value is None:
            return None
        if isinstance(value, str):
            return [part.strip() for part in value.split(",") if part.strip()]
        return [str(item) for item in value if str(item).strip()]

    @staticmethod
    def _get_type_name(migration: Migration) -> str:
        m_type = getattr(migration, "type", None)
        if isinstance(m_type, MigrationType):
            return m_type.name
        return str(m_type or "").upper()

    @staticmethod
    def _installed_rank(migration: Migration) -> int:
        return int(getattr(migration, "installed_rank", 0) or 0)

    @staticmethod
    def _lookup_checksum(checksums: Dict[str, str], script_name: str) -> Optional[str]:
        if script_name in checksums:
            return checksums[script_name]

        # Fallback to basename for historical records stored without directory prefixes
        basename = Path(script_name).name
        return checksums.get(basename)

    # ------------------------------------------------------------------
    # Pending migration computation (NEW - Phase 1)
    # ------------------------------------------------------------------
    def _compute_pending_migrations(
        self,
        scripts_dir: Path,
        executed_scripts: Set[str],
        applied_migrations: List[Migration],
        undone_versions: Set[str],
        repeatable_checksums: Dict[str, str],
        executed_versions: Optional[Set[str]] = None,
        *,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
        strict_mode: bool = False,
        baseline_version: Optional[str] = None,
    ) -> List[Migration]:
        """Compute which migrations need to be executed.

        This is the NEW centralized method that replaces MigrationScriptManager.get_pending_migrations().
        It handles:
        1. Scripts that have never been executed
        2. Repeatable scripts that have changed (new checksum)
        3. Versioned scripts that were executed but later undone

        Args:
            scripts_dir: Directory containing migration scripts
            executed_scripts: Set of script names that have been executed
            applied_migrations: List of applied Migration objects from history
            undone_versions: Set of versions that have been undone
            repeatable_checksums: Dict of script name to checksum for repeatables
            recursive: Whether to scan subdirectories
            additional_dirs: Additional directories to scan
            target_version: Optional target version to migrate to
            tags: Optional list of tags to filter by (inclusion)
            exclude_tags: Optional list of tags to exclude
            versions: Optional list of versions to include
            exclude_versions: Optional list of versions to exclude
            strict_mode: Whether strict mode is enabled

        Returns:
            List of Migration objects that need to be executed
        """
        # Step 1: Get all scripts from filesystem
        all_script_paths = self.script_manager.get_all_scripts(
            scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )
        self.logger.debug(f"Found {len(all_script_paths)} total scripts on filesystem")

        # Step 2: Load and parse all scripts
        all_migrations = self.script_manager.load_migration_scripts(
            scripts_dir,
            recursive=recursive,
            additional_dirs=additional_dirs,
            dir_recursive_map=dir_recursive_map,
        )

        # Flatten into a single list for processing
        all_scripts: List[Migration] = []
        for migration_type, migration_list in all_migrations.items():
            all_scripts.extend(migration_list)

        self.logger.debug(f"Loaded {len(all_scripts)} migration objects")

        # Step 3: Determine current version from applied migrations (excluding undone ones)
        # Filter out undone migrations before calculating current version
        # Note: reapplied_versions are versions that were undone but then reapplied
        # We can determine this by checking if a version appears in both undone_versions
        # and in the applied_migrations list with success status
        version_status: Dict[str, Dict[str, int]] = {}
        for m in applied_migrations:
            m_type = self._get_type_name(m)
            if m_type not in VERSIONED_SCRIPT_TYPES | {"UNDO_SQL"}:
                continue

            version = str(getattr(m, "version", "") or "")
            if not version or version not in undone_versions:
                continue

            is_success = self.migration_rules.is_success(m)
            if not is_success:
                continue

            status = version_status.setdefault(version, {"versioned": 0, "undo": 0})
            installed_rank = self._installed_rank(m)

            if m_type in VERSIONED_SCRIPT_TYPES:
                status["versioned"] = max(status["versioned"], installed_rank)
            elif m_type == "UNDO_SQL":
                status["undo"] = max(status["undo"], installed_rank)

        reapplied_versions = {
            version
            for version, status in version_status.items()
            if status["versioned"] > status["undo"]
        }

        effective_undone_versions = undone_versions - reapplied_versions
        applied_migrations_filtered = [
            m
            for m in applied_migrations
            if (
                # Keep non-versioned migrations (repeatable, callback, etc.)
                self._get_type_name(m) not in VERSIONED_SCRIPT_TYPES
                # Keep versioned migrations that haven't been undone
                or str(getattr(m, "version", "")) not in effective_undone_versions
            )
        ]
        current_version = self.get_current_version(applied_migrations_filtered)
        if current_version:
            self.logger.debug(f"Current applied version: {current_version}")

        # Step 4: Determine highest applied version for strict mode
        highest_applied_version = None
        if strict_mode and current_version:
            highest_applied_version = current_version
            self.logger.debug(f"Strict mode: highest applied version is {highest_applied_version}")

        # Step 5: Filter and determine pending migrations
        pending: List[Migration] = []

        for migration in all_scripts:
            script_name = migration.script_name
            migration_type_name = self._get_type_name(migration)
            migration_version = cast(Optional[str], getattr(migration, "version", None))

            # Check if script is pending based on type
            if migration_type_name in VERSIONED_SCRIPT_TYPES:
                # Apply filters first, then check if pending
                if self._passes_filters(
                    migration,
                    target_version,
                    tags,
                    exclude_tags,
                    versions,
                    exclude_versions,
                ):
                    if self._is_versioned_pending(
                        script_name,
                        migration_version,
                        executed_scripts,
                        executed_versions if executed_versions is not None else set(),
                        effective_undone_versions,
                        current_version,
                        highest_applied_version,
                        strict_mode,
                        baseline_version,
                    ):
                        pending.append(migration)

            elif migration_type_name == "REPEATABLE":
                # Apply filters FIRST for repeatable migrations to respect tag filtering
                # Only check if pending if the migration passes tag filters
                if self._passes_filters(migration, None, tags, exclude_tags, None, None):
                    if self._is_repeatable_pending(
                        script_name, migration, executed_scripts, repeatable_checksums
                    ):
                        pending.append(migration)

            elif migration_type_name == "UNDO_SQL":
                # Undo migrations are never "pending" for migrate command
                # They're only used by the undo command
                continue

            elif migration_type_name in ("CALLBACK", "BASELINE"):
                # Callbacks and baselines are handled separately
                continue

        self.logger.debug(f"Computed {len(pending)} pending migrations after filtering")
        return pending

    def get_current_version(self, applied_migrations: List[Migration]) -> Optional[str]:
        """Highest successfully applied version among SQL and BASELINE migrations.

        Args:
            applied_migrations: Applied migration rows (e.g. from state or history)

        Returns:
            Version string, or ``None`` if none qualify.
        """
        return self._get_current_version(applied_migrations)

    def _get_current_version(self, applied_migrations: List[Migration]) -> Optional[str]:
        """Get the highest successfully applied version."""
        applied_versions = []

        for m in applied_migrations:
            m_type = self._get_type_name(m)
            # Include both SQL and BASELINE migrations
            if m_type in VERSIONED_SCRIPT_TYPES | {"BASELINE"}:
                is_success = self.migration_rules.is_success(m)
                if is_success and getattr(m, "version", None):
                    applied_versions.append(m.version)

        if not applied_versions:
            return None

        # Find highest version
        highest = applied_versions[0]
        for v in applied_versions[1:]:
            if self.script_manager.compare_versions(v, highest) > 0:
                highest = v

        return highest

    def _is_versioned_pending(
        self,
        script_name: str,
        version: Optional[str],
        executed_scripts: Set[str],
        executed_versions: Set[str],
        undone_versions: Set[str],
        current_version: Optional[str],
        highest_applied_version: Optional[str],
        strict_mode: bool,
        baseline_version: Optional[str] = None,
    ) -> bool:
        """Check if a versioned migration is pending.

        For versioned migrations, we check by VERSION (not script_name) because:
        - Each version is unique and should only be executed once
        - Avoids issues with script name normalization (relative paths vs filenames)
        - More robust and simpler logic

        Returns True if the migration should be executed, False otherwise.
        In strict mode, prevents out-of-order migrations (versions <= current_version).
        Migrations with versions <= baseline are considered already applied (only if baseline exists).
        """
        # For versioned migrations, check by version first (primary key)
        # Fall back to script_name for backward compatibility
        is_executed_by_version = version and str(version) in executed_versions

        # Also check script_name for backward compatibility (if version check fails)
        if not is_executed_by_version:
            script_basename = Path(script_name).name
            is_executed_by_name = (
                script_name in executed_scripts or script_basename in executed_scripts
            )
        else:
            is_executed_by_name = False

        is_executed = is_executed_by_version or is_executed_by_name

        # Was undone - always pending if undone
        if version and str(version) in undone_versions:
            return True

        # Check if version is covered by baseline
        # ONLY skip if there's an actual BASELINE migration and version <= baseline_version
        # This allows out-of-order migrations when no baseline exists
        if not is_executed and baseline_version and version:
            if self.script_manager.compare_versions(version, baseline_version) <= 0:
                # This version is at or below the baseline version
                # It's implicitly covered by the baseline
                self.logger.debug(
                    f"Skipping migration {script_name} (version {version}) - "
                    f"covered by baseline version {baseline_version}"
                )
                return False

        # Never executed - check strict mode
        if not is_executed:
            # BUG-05: out-of-order detection — a pending migration whose
            # version is <= the highest applied version.
            if current_version and version:
                if self.script_manager.compare_versions(version, current_version) <= 0:
                    if strict_mode:
                        # Strict mode must FAIL the migrate command, not
                        # silently skip — callers (CI, operators) need a
                        # non-zero exit so the out-of-order file surfaces.
                        raise StrictModeError(
                            f"Strict mode: out-of-order migration {script_name} "
                            f"(version {version} <= current version {current_version}). "
                            f"Renumber the script above {current_version} or run "
                            f"without --strict to apply it anyway."
                        )
                    # Non-strict: warn but still include so historical
                    # behaviour (apply in-order files older than current)
                    # is preserved.
                    self.logger.warning(
                        f"Out-of-order migration {script_name} "
                        f"(version {version} <= current version {current_version}). "
                        f"Applying anyway; use --strict to enforce strict ordering."
                    )
            # Not executed and passes all checks
            return True

        # Already executed and not undone - not pending
        return False

    def _is_repeatable_pending(
        self,
        script_name: str,
        migration: Migration,
        executed_scripts: Set[str],
        repeatable_checksums: Dict[str, str],
    ) -> bool:
        """Check if a repeatable migration is pending."""
        # Never executed
        if script_name not in executed_scripts:
            return True

        # Check if checksum changed
        current_checksum = getattr(migration, "checksum", None)
        if not current_checksum:
            # Calculate checksum if not already set
            if migration.content:
                current_checksum = self.script_manager.calculate_checksum(migration.content)

        stored_checksum = self._lookup_checksum(repeatable_checksums, script_name)

        # If checksum changed, it's pending
        if stored_checksum and current_checksum != stored_checksum:
            return True

        return False

    def _passes_filters(
        self,
        migration: Migration,
        target_version: Optional[str],
        tags: Optional[List[str]],
        exclude_tags: Optional[List[str]],
        versions: Optional[List[str]],
        exclude_versions: Optional[List[str]],
    ) -> bool:
        """Check if migration passes all filter criteria."""
        version = getattr(migration, "version", None)
        migration_tags = getattr(migration, "tags", []) or []

        # Target version filter
        if target_version and version:
            if self.script_manager.compare_versions(version, target_version) > 0:
                return False

        # Versions inclusion filter
        if versions and version:
            if str(version) not in versions:
                return False

        # Versions exclusion filter
        if exclude_versions and version:
            if str(version) in exclude_versions:
                return False

        # Tags inclusion filter
        if tags:
            # Ensure migration_tags is a list (defensive check)
            if not isinstance(migration_tags, list):
                migration_tags = list(migration_tags) if migration_tags else []
            # Normalize tags for comparison (strip whitespace, handle case)
            normalized_migration_tags = [str(tag).strip().lower() for tag in migration_tags if tag]
            normalized_filter_tags = [str(tag).strip().lower() for tag in tags if tag]
            # If migration has no tags and we're filtering by tags, exclude it
            # If migration has tags but none match the filter tags, exclude it
            if not normalized_migration_tags or not any(
                tag in normalized_migration_tags for tag in normalized_filter_tags
            ):
                return False

        # Tags exclusion filter
        if exclude_tags:
            # Ensure migration_tags is a list (defensive check)
            if not isinstance(migration_tags, list):
                migration_tags = list(migration_tags) if migration_tags else []
            # Normalize tags for comparison
            normalized_migration_tags = [str(tag).strip().lower() for tag in migration_tags if tag]
            normalized_exclude_tags = [str(tag).strip().lower() for tag in exclude_tags if tag]
            if normalized_migration_tags and any(
                tag in normalized_migration_tags for tag in normalized_exclude_tags
            ):
                return False

        return True

    def apply_filters_to_migrations(
        self,
        migrations: List[Migration],
        target_version: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        exclude_tags: Optional[Sequence[str]] = None,
        versions: Optional[Sequence[str]] = None,
        exclude_versions: Optional[Sequence[str]] = None,
    ) -> List[Migration]:
        """Apply filter criteria to a list of migrations.

        This is a PUBLIC method that can be used by migration-state commands.
        to filter migrations by version, tags, etc.

        Args:
            migrations: List of migrations to filter
            target_version: Optional target version filter
            tags: Optional list of tags to include
            exclude_tags: Optional list of tags to exclude
            versions: Optional list of versions to include
            exclude_versions: Optional list of versions to exclude

        Returns:
            Filtered list of migrations
        """
        normalized_tags = self._normalize_filter(tags)
        normalized_exclude_tags = self._normalize_filter(exclude_tags)
        normalized_versions = self._normalize_filter(versions)
        normalized_exclude_versions = self._normalize_filter(exclude_versions)

        filtered = []
        for migration in migrations:
            if self._passes_filters(
                migration,
                target_version,
                normalized_tags,
                normalized_exclude_tags,
                normalized_versions,
                normalized_exclude_versions,
            ):
                filtered.append(migration)

        return filtered
