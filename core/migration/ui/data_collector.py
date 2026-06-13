"""
Migration data collection and preparation.

This module handles the complex logic for collecting, analyzing, and structuring
migration data from various sources (applied migrations, pending migrations,
filesystem) for display purposes.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set, Tuple, Union

from core.logger import Log, NullLog
from core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.state.migration_display_state import MigrationDisplayState
from core.migration.state.migration_state import MigrationState
from core.migration.version_utils import compare_versions as _compare_versions_shared
from core.migration.version_utils import (
    is_migration_failure,
    is_migration_success,
)


class MigrationDataCollector:
    """Collects and structures migration data for display."""

    def __init__(self, log: Log, script_manager: Optional[MigrationScriptManager] = None):
        """Initialize the data collector.

        Args:
            log: Logger instance
            script_manager: Script manager instance (optional)
        """
        self.log = log if log is not None else NullLog()
        self.script_manager = script_manager
        self._target_version: Optional[str] = None

    def _format_installed_on(self, installed_on: Any) -> str:
        """Format installed_on timestamp for display.

        Handles both datetime objects and ISO string formats (e.g., from CosmosDB).

        Args:
            installed_on: Timestamp as datetime object or ISO string

        Returns:
            Formatted timestamp string or empty string
        """
        if not installed_on:
            return ""

        try:
            if hasattr(installed_on, "strftime"):
                # It's a datetime object
                return str(installed_on.strftime("%Y-%m-%d %H:%M:%S"))
            elif isinstance(installed_on, str):
                # It's an ISO string (e.g., from CosmosDB)
                from datetime import datetime

                try:
                    # Try to parse ISO format and reformat
                    # Handle both with and without timezone
                    if installed_on.endswith("Z"):
                        dt = datetime.fromisoformat(installed_on.replace("Z", "+00:00"))
                    else:
                        dt = datetime.fromisoformat(installed_on)
                    return dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    # If parsing fails, use the string as-is (truncate if too long)
                    return installed_on[:19] if len(installed_on) > 19 else installed_on
            else:
                return str(installed_on)
        except Exception as e:
            self.log.debug(f"Could not format installed_on timestamp: {e}")
            return str(installed_on) if installed_on else ""

    def _get_migration_type_string(self, migration_type: Any) -> str:
        """Safely get migration type as string, handling both enum and string types.

        Delegates to the shared helper in ``core.migration._type_match``;
        kept as a method for backwards compatibility with existing call sites.
        """
        from core.migration._type_match import migration_type_name

        return migration_type_name(migration_type)

    @staticmethod
    def _status_to_display_state(status: str) -> str:
        """Map internal status string to UI label (aligned with MigrationDisplayState)."""
        if status == "SUCCESS":
            return MigrationDisplayState.SUCCESS.value
        if status == "OUT OF ORDER":
            return MigrationDisplayState.OUT_OF_ORDER.value
        if status == "BASELINE":
            return MigrationDisplayState.BASELINE.value
        return status.capitalize()

    def _is_migration_type_equal(self, migration_type: Any, target_type: str) -> bool:
        """Check if migration type matches target type, handling both enum and string types.

        Delegates to the shared helper in ``core.migration._type_match``;
        kept as a method for backwards compatibility with existing call sites.
        """
        from core.migration._type_match import is_migration_type

        return is_migration_type(migration_type, target_type)

    def _is_versioned_type(self, migration_type: Any) -> bool:
        """Return True for any versioned script type (SQL, PYTHON, etc.).

        Delegates to the shared VERSIONED_SCRIPT_TYPES constant so adding a new
        versioned type (e.g. SHELL) registers here automatically.
        """
        return any(self._is_migration_type_equal(migration_type, t) for t in VERSIONED_SCRIPT_TYPES)

    def get_migration_data(
        self,
        applied_migrations: Union[List[Migration], None] = None,
        pending_migrations: Optional[List[Migration]] = None,
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
        migration_state: Optional[MigrationState] = None,
        all_applied_migrations: Optional[List[Migration]] = None,
    ) -> List[Dict[str, Any]]:
        """Get structured migration data suitable for any formatter (console, HTML, JSON).

        This method supports two modes:
        1. New mode: Uses MigrationState to get all state information (preferred)
        2. Legacy mode: Uses applied_migrations and pending_migrations lists

        Args:
            applied_migrations: List of applied migrations (legacy parameter)
            pending_migrations: List of pending migrations (legacy parameter)
            scripts_dir: Directory containing migration scripts
            target_version: Target version for filtering
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude
            migration_state: MigrationState object (preferred, contains all state info)
            all_applied_migrations: All migrations from history in chronological order (required with migration_state)
        """
        # Use new signature if migration_state is provided
        if migration_state is not None and all_applied_migrations is not None:
            return self._get_migration_data_from_state(
                migration_state=migration_state,
                all_applied_migrations=all_applied_migrations,
                scripts_dir=scripts_dir,
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )

        # Legacy signature
        self._target_version = target_version
        if pending_migrations is None:
            pending_migrations = []
        if applied_migrations is None:
            applied_migrations = []
        shown_versions = set()
        shown_script_names = set()

        if self.script_manager is None:
            # Use the provided logger directly to avoid creating additional log files
            logger = self.log
            self.script_manager = MigrationScriptManager(logger, "utf-8")  # Default encoding

        undo_versions = self._find_undo_versions(scripts_dir)
        current_version, baseline_version = self._find_current_and_baseline_version(
            applied_migrations
        )
        versioned_migrations = self._collect_versioned_migrations(applied_migrations)
        self._detect_out_of_order_migrations(versioned_migrations)
        undone_versions = self._get_undone_versions(applied_migrations)
        repeatable_checksums = self._build_repeatable_checksums(applied_migrations)
        sorted_applied_migrations = self._sort_applied_migrations(applied_migrations)

        migrations_data = []

        # Create a simplified applied_migrations lookup that handles reapplications correctly
        latest_applied_by_script = {}
        for migration in sorted_applied_migrations:
            script_name = migration.script_name
            if script_name not in latest_applied_by_script:
                latest_applied_by_script[script_name] = migration
            else:
                # For reapplied migrations, we want to keep the most recent successful one
                current = latest_applied_by_script[script_name]
                # Compare by installed_rank (higher rank = more recent)
                current_rank = getattr(current, "installed_rank", 0) or 0
                migration_rank = getattr(migration, "installed_rank", 0) or 0
                if migration_rank > current_rank:
                    latest_applied_by_script[script_name] = migration

        # Process applied migrations first - show ALL migrations from history table in chronological order
        for migration in sorted_applied_migrations:
            migration_type = getattr(migration, "type", None)
            version = getattr(migration, "version", None)
            script_name = migration.script_name
            success = getattr(migration, "success", None)
            installed_on = getattr(migration, "installed_on", None)
            execution_time = getattr(migration, "execution_time", 0)
            installed_rank = getattr(migration, "installed_rank", None)
            checksum = getattr(migration, "checksum", None)
            installed_by = getattr(migration, "installed_by", None)
            description = self._clean_delete_description(getattr(migration, "description", ""))

            # Skip if this version should be excluded based on filters
            if version and self._should_exclude_migration(
                version,
                script_name,
                tags or [],
                exclude_tags or [],
                versions or [],
                exclude_versions or [],
            ):
                continue

            # Determine status based on migration type and success field
            # Check DELETE/MISSING type FIRST before checking success flag
            if self._get_migration_type_string(migration_type) in ("DELETE", "MISSING"):
                status = "DELETED"
            elif is_migration_success(success):
                if self._is_migration_type_equal(migration_type, "BASELINE"):
                    status = "BASELINE"
                # For SQL migrations, check if this specific instance was undone
                elif version and migration_type and self._is_versioned_type(migration_type):
                    current_rank = getattr(migration, "installed_rank", 0) or 0

                    # Check if there's an UNDO_SQL for this version applied after this specific migration
                    was_undone = False

                    for other_migration in sorted_applied_migrations:
                        other_type = getattr(other_migration, "type", None)
                        other_version = getattr(other_migration, "version", None)
                        other_success = getattr(other_migration, "success", None)
                        other_rank = getattr(other_migration, "installed_rank", 0) or 0

                        if other_rank <= current_rank:
                            continue  # Only look at migrations applied after this one

                        # Check for UNDO_SQL
                        is_undo_sql = self._is_migration_type_equal(other_type, "UNDO_SQL")

                        if (
                            is_undo_sql
                            and other_version == version
                            and is_migration_success(other_success)
                        ):
                            was_undone = True
                            break

                    if was_undone:
                        status = "UNDONE"
                    else:
                        status = "SUCCESS"
                else:
                    status = "SUCCESS"
            elif is_migration_failure(success):
                status = "FAILED"
            else:
                status = "UNKNOWN"

            # Track shown scripts and versions
            shown_script_names.add(script_name)
            if version:
                shown_versions.add(version)

            # For repeatable migrations, check if checksum has changed
            if self._is_migration_type_equal(migration_type, "REPEATABLE"):
                if script_name in repeatable_checksums:
                    latest_checksum = repeatable_checksums[script_name]
                    if checksum and checksum != latest_checksum:
                        # This is an older execution of the repeatable migration
                        continue

            state = self._status_to_display_state(status)

            migrations_data.append(
                {
                    "category": self._get_category_from_type(
                        self._get_migration_type_string(migration_type), migration
                    ),
                    "version": self._format_version(version),
                    "description": description,
                    "type": self._get_type_from_migration_type(migration_type, script_name),
                    "installed_on": self._format_installed_on(installed_on),
                    "installed_by": installed_by or "",
                    "state": state,
                    "undoable": version in undo_versions if version else False,
                    "filepath": getattr(migration, "filepath", ""),
                    "script": script_name,
                    "execution_time": execution_time or 0,
                    "installed_rank": installed_rank,
                    "checksum": checksum,
                }
            )

        # Process pending migrations (in execution order: versioned first, then repeatable)
        sorted_pending_legacy = sorted(
            pending_migrations or [],
            key=lambda m: (
                # Versioned migrations (type 0) come before repeatable (type 1)
                0 if self._is_versioned_type(getattr(m, "type", None)) else 1,
                # Then sort by version (for versioned) or script name (for repeatable)
                getattr(m, "version", "") or "",
                getattr(m, "script_name", ""),
            ),
        )
        for migration in sorted_pending_legacy:
            script_name = migration.script_name
            version = getattr(migration, "version", None)
            migration_type = getattr(migration, "type", None)

            # Skip if already shown or should be excluded
            # BUT allow undone migrations to be shown as PENDING for reapplication
            should_skip = False

            # Check if this script has been shown
            if script_name in shown_script_names:
                # If this is an undone migration, don't skip it - show it as PENDING too
                if not (version and version in undone_versions):
                    should_skip = True
            elif (version and version in shown_versions) or (
                version
                and self._should_exclude_migration(
                    version,
                    script_name,
                    tags or [],
                    exclude_tags or [],
                    versions or [],
                    exclude_versions or [],
                )
            ):
                should_skip = True

            if should_skip:
                continue

            shown_script_names.add(script_name)
            if version:
                shown_versions.add(version)

            # Determine pending status
            status = self._determine_pending_migration_status(
                migration, target_version, current_version, baseline_version
            )

            # Format state with only first letter uppercase
            state = status.capitalize()

            migrations_data.append(
                {
                    "category": self._get_category_from_type(
                        self._get_migration_type_string(migration_type), migration
                    ),
                    "version": self._format_version(version),
                    "description": self._clean_delete_description(
                        getattr(migration, "description", "")
                    ),
                    "type": self._get_type_from_migration_type(migration_type, script_name),
                    "installed_on": "",
                    "installed_by": "",
                    "state": state,
                    "undoable": version in undo_versions if version else False,
                    "filepath": getattr(migration, "filepath", ""),
                    "script": script_name,
                    "execution_time": 0,
                    "installed_rank": None,
                }
            )

        return migrations_data

    def _get_migration_data_from_state(
        self,
        migration_state: MigrationState,
        all_applied_migrations: List[Migration],
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get migration data from MigrationState (new implementation).

        This method uses the StateManager's state to show:
        1. All migrations in chronological order by installed_rank
        2. Undone migrations marked as "UNDONE" (not "SUCCESS")
        3. Pending migrations at the end

        Args:
            migration_state: MigrationState object containing all state information
            all_applied_migrations: All migrations from history table (not filtered)
            scripts_dir: Directory containing migration scripts
            target_version: Target version for filtering
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude

        Returns:
            List of migration data dictionaries
        """
        self._target_version = target_version

        if self.script_manager is None:
            logger = self.log
            self.script_manager = MigrationScriptManager(logger, "utf-8")

        # Get undone versions from state (this is the source of truth)
        undone_versions_set = set(migration_state.undone_versions)
        self.log.debug(f"Undone versions from state: {undone_versions_set}")

        # Get undo script versions from filesystem
        undo_versions = self._find_undo_versions(scripts_dir)

        # Sort all migrations by installed_rank to show complete sequential history
        sorted_applied_migrations = sorted(
            all_applied_migrations, key=lambda m: getattr(m, "installed_rank", 0) or 0
        )

        # Get pending migrations from state (already sorted by migration order)
        pending_migrations = migration_state.pending_objects

        # Build repeatable checksums map to filter out old repeatable executions
        repeatable_checksums = migration_state.repeatable_checksums

        migrations_data = []

        # Process all applied migrations in chronological order
        for migration in sorted_applied_migrations:
            migration_type = getattr(migration, "type", None)
            version = getattr(migration, "version", None)
            script_name = migration.script_name
            success = getattr(migration, "success", None)
            installed_on = getattr(migration, "installed_on", None)
            execution_time = getattr(migration, "execution_time", 0)
            installed_rank = getattr(migration, "installed_rank", None)
            checksum = getattr(migration, "checksum", None)
            installed_by = getattr(migration, "installed_by", None)

            # Skip if this version should be excluded based on filters
            if version and self._should_exclude_migration(
                version,
                script_name,
                tags or [],
                exclude_tags or [],
                versions or [],
                exclude_versions or [],
            ):
                continue

            # For repeatable migrations, only show the latest execution (by checksum)
            if self._is_migration_type_equal(migration_type, "REPEATABLE"):
                if script_name in repeatable_checksums:
                    latest_checksum = repeatable_checksums[script_name]
                    if checksum and checksum != latest_checksum:
                        # This is an older execution of the repeatable migration, skip it
                        continue

            # Determine status based on migration type and success field
            # Check DELETE/MISSING type FIRST before checking success flag
            if self._get_migration_type_string(migration_type) in ("DELETE", "MISSING"):
                status = "DELETED"
            elif is_migration_success(success):
                # Default: any successful migration (REPEATABLE, native-driver, future types, etc.)
                status = "SUCCESS"
                if self._is_migration_type_equal(migration_type, "BASELINE"):
                    status = "BASELINE"
                elif (
                    self._is_versioned_type(migration_type)
                    and version
                    and version in undone_versions_set
                ):
                    # Version in undone_versions: only SQL migrations may be marked UNDONE
                    # after a successful UNDO_SQL applied later (other types keep SUCCESS).
                    current_rank = getattr(migration, "installed_rank", 0) or 0
                    has_undo_after = False

                    for other_migration in sorted_applied_migrations:
                        other_type = getattr(other_migration, "type", None)
                        other_version = getattr(other_migration, "version", None)
                        other_success = getattr(other_migration, "success", None)
                        other_rank = getattr(other_migration, "installed_rank", 0) or 0

                        if other_rank <= current_rank:
                            continue

                        if (
                            self._is_migration_type_equal(other_type, "UNDO_SQL")
                            and other_version == version
                            and is_migration_success(other_success)
                        ):
                            has_undo_after = True
                            break

                    if has_undo_after:
                        status = "UNDONE"
            elif is_migration_failure(success):
                status = "FAILED"
            else:
                status = "UNKNOWN"

            state = self._status_to_display_state(status)

            migrations_data.append(
                {
                    "category": self._get_category_from_type(
                        self._get_migration_type_string(migration_type), migration
                    ),
                    "version": self._format_version(version),
                    "description": self._clean_delete_description(
                        getattr(migration, "description", "")
                    ),
                    "type": self._get_type_from_migration_type(migration_type, script_name),
                    "installed_on": self._format_installed_on(installed_on),
                    "installed_by": installed_by or "",
                    "state": state,
                    "undoable": version in undo_versions if version else False,
                    "filepath": getattr(migration, "filepath", ""),
                    "script": script_name,
                    "execution_time": execution_time or 0,
                    "installed_rank": installed_rank,
                    "checksum": checksum,
                }
            )

        # Process pending migrations at the end (in execution order)
        # Execution order: versioned first (sorted by version), then repeatable (sorted by script name)
        sorted_pending = sorted(
            pending_migrations,
            key=lambda m: (
                # Versioned migrations (type 0) come before repeatable (type 1)
                0 if self._is_versioned_type(getattr(m, "type", None)) else 1,
                # Then sort by version (for versioned) or script name (for repeatable)
                getattr(m, "version", "") or "",
                getattr(m, "script_name", ""),
            ),
        )

        for migration in sorted_pending:
            script_name = migration.script_name
            version = getattr(migration, "version", None)
            migration_type = getattr(migration, "type", None)

            # Skip if should be excluded
            if version and self._should_exclude_migration(
                version,
                script_name,
                tags or [],
                exclude_tags or [],
                versions or [],
                exclude_versions or [],
            ):
                continue

            # Determine pending status
            status = self._determine_pending_migration_status(
                migration,
                target_version,
                migration_state.current_version,
                migration_state.baseline_version,
            )

            # Format state with only first letter uppercase
            state = status.capitalize()

            migrations_data.append(
                {
                    "category": self._get_category_from_type(
                        self._get_migration_type_string(migration_type), migration
                    ),
                    "version": self._format_version(version),
                    "description": self._clean_delete_description(
                        getattr(migration, "description", "")
                    ),
                    "type": self._get_type_from_migration_type(migration_type, script_name),
                    "installed_on": "",
                    "installed_by": "",
                    "state": state,
                    "undoable": version in undo_versions if version else False,
                    "filepath": getattr(migration, "filepath", ""),
                    "script": script_name,
                    "execution_time": 0,
                    "installed_rank": None,
                }
            )

        return migrations_data

    def _find_undo_versions(self, scripts_dir: Optional[Path]) -> Set[str]:
        """Find versions that have undo capability available.

        A version is undoable if it has a U*.sql companion script (SQL migrations)
        or if its V*.py file contains a ``def undo(`` function (Python migrations).
        """
        undo_versions = set()
        if scripts_dir and scripts_dir.exists() and self.script_manager is not None:
            for file_path in scripts_dir.rglob("U*.sql"):
                version = self.script_manager.extract_version(file_path.name)
                if version:
                    undo_versions.add(version)
            for file_path in scripts_dir.rglob("V*.py"):
                try:
                    content = file_path.read_text(encoding="utf-8", errors="replace")
                    if "def undo(" in content:
                        version = self.script_manager.extract_version(file_path.name)
                        if version:
                            undo_versions.add(version)
                except OSError:
                    pass
        return undo_versions

    def _find_current_and_baseline_version(
        self, applied_migrations: List[Migration]
    ) -> Tuple[Optional[str], Optional[str]]:
        """Find the current version and baseline version."""
        current_version = None
        baseline_version = None

        for migration in applied_migrations:
            migration_type = getattr(migration, "type", None)
            version = getattr(migration, "version", None)
            success = getattr(migration, "success", None)

            if version and is_migration_success(success):
                if self._is_migration_type_equal(migration_type, "BASELINE"):
                    baseline_version = version
                elif self._is_versioned_type(migration_type):
                    if (
                        current_version is None
                        or self._compare_versions(version, current_version) > 0
                    ):
                        current_version = version

        return current_version, baseline_version

    def _collect_versioned_migrations(
        self, applied_migrations: List[Migration]
    ) -> List[Dict[str, Any]]:
        """Collect versioned migrations for analysis."""
        versioned_migrations = []
        for migration in applied_migrations:
            migration_type = getattr(migration, "type", None)
            if self._is_versioned_type(migration_type):
                version = getattr(migration, "version", None)
                if version:
                    versioned_migrations.append({"version": version, "migration": migration})
        return versioned_migrations

    def _build_repeatable_checksums(self, applied_migrations: List[Migration]) -> Dict[str, str]:
        """Build a dictionary of the latest checksums for repeatable migrations."""
        checksums = {}
        repeatable_migrations = [
            m
            for m in applied_migrations
            if self._is_migration_type_equal(getattr(m, "type", None), "REPEATABLE")
            and getattr(m, "success", False)
        ]

        # Sort by installed_rank to get the latest execution of each repeatable migration
        repeatable_migrations.sort(key=lambda m: getattr(m, "installed_rank", 0) or 0, reverse=True)

        for migration in repeatable_migrations:
            script_name = migration.script_name
            checksum = getattr(migration, "checksum", None)
            if script_name not in checksums and checksum:
                checksums[script_name] = checksum

        return checksums

    def _sort_applied_migrations(self, applied_migrations: List[Migration]) -> List[Migration]:
        """Sort applied migrations by installed_rank."""
        return sorted(applied_migrations, key=lambda m: getattr(m, "installed_rank", 0) or 0)

    def _mark_reapplied_duplicates(
        self, sorted_applied_migrations: List[Migration], reapplied_versions: Set[str]
    ) -> Set[Migration]:
        """Mark duplicate migrations that should be kept for reapplication display."""
        keep_duplicates = set()
        script_counts: dict[str, int] = {}

        for migration in sorted_applied_migrations:
            script_name = migration.script_name
            version = getattr(migration, "version", None)

            if version in reapplied_versions:
                script_counts[script_name] = script_counts.get(script_name, 0) + 1
                if script_counts[script_name] > 1:
                    keep_duplicates.add(migration)

        return keep_duplicates

    def _detect_out_of_order_migrations(
        self, versioned_migrations: List[Dict[str, Any]]
    ) -> Set[str]:
        """Detect out-of-order migrations."""
        out_of_order = set()
        versions = [m["version"] for m in versioned_migrations]

        for i in range(len(versions) - 1):
            current_version = versions[i]
            next_version = versions[i + 1]
            if self._compare_versions(current_version, next_version) > 0:
                out_of_order.add(versioned_migrations[i + 1]["migration"].script_name)

        return out_of_order

    def _get_undone_versions(self, applied_migrations: List[Migration]) -> Set[str]:
        """Get versions that have been undone and not reapplied."""
        undone_versions = set()

        # First, find all successful UNDO_SQL migrations
        successful_undos = {}
        for migration in applied_migrations:
            migration_type = getattr(migration, "type", None)
            success = getattr(migration, "success", None)
            version = getattr(migration, "version", None)

            # Handle both enum object and string comparisons
            is_undo_sql = self._is_migration_type_equal(migration_type, "UNDO_SQL")

            if is_undo_sql and version and is_migration_success(success):
                undo_rank = getattr(migration, "installed_rank", 0)
                successful_undos[version] = undo_rank
                self.log.debug(f"Found undo operation for version: {version} (rank={undo_rank})")

        # For each undone version, check if it was reapplied after the undo
        for version, undo_rank in successful_undos.items():
            # Find the most recent successful SQL migration for this version
            most_recent_versioned_rank = 0
            for migration in applied_migrations:
                migration_type = getattr(migration, "type", None)
                success = getattr(migration, "success", None)
                migration_version = getattr(migration, "version", None)

                # Handle both enum object and string comparisons
                is_versioned = self._is_versioned_type(migration_type)

                if is_versioned and migration_version == version and is_migration_success(success):
                    versioned_rank = getattr(migration, "installed_rank", 0)
                    if versioned_rank > most_recent_versioned_rank:
                        most_recent_versioned_rank = versioned_rank

            # Only mark as undone if the undo was more recent than the most recent versioned migration
            if undo_rank >= most_recent_versioned_rank:
                undone_versions.add(version)
                self.log.debug(
                    f"Version {version} is undone (undo_rank={undo_rank} >= versioned_rank={most_recent_versioned_rank})"
                )
            else:
                self.log.debug(
                    f"Version {version} was reapplied after undo (undo_rank={undo_rank} < versioned_rank={most_recent_versioned_rank})"
                )

        return undone_versions

    def _get_reapplied_versions(self, applied_migrations: List[Migration]) -> Set[str]:
        """Get versions that have been reapplied."""
        version_counts: dict[str, int] = {}
        for migration in applied_migrations:
            version = getattr(migration, "version", None)
            if version and getattr(migration, "success", False):
                version_counts[version] = version_counts.get(version, 0) + 1

        return {v for v, count in version_counts.items() if count > 1}

    def _should_exclude_migration(
        self,
        version: str,
        script_name: str,
        tags: List[str],
        exclude_tags: List[str],
        versions: List[str],
        exclude_versions: List[str],
    ) -> bool:
        """Check if migration should be excluded based on filters."""
        # Versions inclusion filter
        if versions and version not in versions:
            return True

        # Versions exclusion filter
        if exclude_versions and version in exclude_versions:
            return True

        # Extract tags from script name if script_manager is available
        migration_tags = []
        if self.script_manager is not None:
            migration_tags = self.script_manager.extract_tags(script_name) or []

        # Tags inclusion filter: migration must have at least one matching tag
        if tags:
            if not migration_tags or not any(tag in migration_tags for tag in tags):
                return True

        # Tags exclusion filter: migration must not have any excluded tags
        if exclude_tags:
            if migration_tags and any(tag in migration_tags for tag in exclude_tags):
                return True

        return False

    def _clean_delete_description(self, description: str) -> str:
        """Remove [DELETE:TYPE] prefix from description.

        Args:
            description: Original description

        Returns:
            Cleaned description
        """
        if description and description.startswith("[DELETE:") and "]" in description:
            try:
                return description[description.index("]") + 1 :].strip()
            except (ValueError, IndexError):
                return description
        return description

    def _get_category_from_type(self, migration_type: str, migration: Any = None) -> str:
        """Get display category from migration type.

        For DELETE entries, extracts the original type from the description.

        Args:
            migration_type: Migration type string
            migration: Optional migration object (needed for DELETE entries)

        Returns:
            Display category string
        """
        type_to_category = {
            "SQL": "Versioned",
            "PYTHON": "Versioned",
            "REPEATABLE": "Repeatable",
            "CALLBACK": "Callback",
            "BASELINE": "Baseline",
            "UNDO_SQL": "Undo",
        }

        # For DELETE entries, extract original type from description
        if migration_type == "DELETE" and migration:
            description = getattr(migration, "description", "")
            if description and "[DELETE:" in description:
                try:
                    # Extract original type from [DELETE:TYPE] prefix
                    start = description.index("[DELETE:") + 8
                    end = description.index("]", start)
                    original_type = description[start:end].strip()
                    # Return category for original type
                    return type_to_category.get(original_type, original_type.capitalize())
                except (ValueError, IndexError):
                    pass

            # Fallback: infer from script name
            script_name = getattr(migration, "script_name", "")
            if script_name.startswith("V"):
                return "Versioned"
            elif script_name.startswith("R"):
                return "Repeatable"
            elif script_name.startswith("U"):
                return "Undo"

            # Last fallback
            return "Deleted"

        return type_to_category.get(migration_type, "Unknown")

    def _get_type_from_migration_type(self, migration_type: Any, script_name: str = "") -> str:
        """Get display type from migration type enum.

        Args:
            migration_type: MigrationType enum or string
            script_name: Script file name — used to distinguish Python from SQL
                repeatable migrations (history stores type=REPEATABLE for both).
        """
        if not migration_type:
            return "UNKNOWN"

        # Get the enum name or string value using helper function
        type_name = self._get_migration_type_string(migration_type)

        # REPEATABLE covers both .sql and .py scripts; the history table stores
        # type=REPEATABLE regardless of the script's extension.  Infer the real
        # format from the filename so Python repeatables show "Python", not "SQL".
        if type_name == "REPEATABLE" and (script_name or "").lower().endswith(".py"):
            return "Python"

        # Map migration types to display types
        type_mapping = {
            "SQL": "SQL",
            "PYTHON": "Python",
            "REPEATABLE": "SQL",
            "CALLBACK": "SQL",
            "BASELINE": "SQL",
            "UNDO_SQL": "UNDO_SQL",
            "DELETE": "SQL",
        }

        return type_mapping.get(type_name, "UNKNOWN")

    def _format_version(self, version: Optional[str]) -> str:
        """Format version for display."""
        return version if version else ""

    def _determine_pending_migration_status(
        self,
        migration: Migration,
        target_version: Optional[str],
        current_version: Optional[str],
        baseline_version: Optional[str],
    ) -> str:
        """Determine status for pending migration."""
        # Simplified implementation
        return "PENDING"

    def _compare_versions(self, version1: Optional[str], version2: Optional[str]) -> int:
        """Compare two version strings. Delegates to shared compare_versions utility."""
        return _compare_versions_shared(version1, version2)
