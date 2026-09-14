"""Migration-validator entry point — verifies migration scripts against applied history."""

from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Union

from dblift.core.constants import TEST_PLACEHOLDER_TIME_MS
from dblift.core.exceptions import UnsupportedMigrationFormatError
from dblift.core.logger import Log, NullLog
from dblift.core.migration._type_match import is_migration_type, is_versioned
from dblift.core.migration.executors.executor_factory import check_format_supported
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.migration.migration import (
    Migration,
    MigrationType,
)
from dblift.core.migration.rules.migration_rules import MigrationRules
from dblift.core.migration.scripting.migration_script_manager import (  # noqa: F401
    MigrationScriptManager,
    _last_successful_non_delete_record,
)
from dblift.core.migration.state.migration_selector import (
    normalize_filter,
    passes_filters,
    prune_baseline_migrations,
    select_migrations,
)
from dblift.core.migration.state.migration_state import (
    MigrationReadSnapshot,
    MigrationValidationSnapshot,
)
from dblift.core.migration.state.migration_state_manager import MigrationStateManager
from dblift.core.migration.version_utils import compare_versions, is_migration_failure
from dblift.db.base_quirks import BaseQuirks


class ValidationResult:
    """Result of a migration validation.

    Attributes:
        success: Whether the validation was successful
        error_message: Error message if validation failed
        repeatable_migrations_to_reapply: List of repeatable migrations that need to be reapplied
        migrations: List of migration objects (populated by validator)
        execution_time: Time taken for validation (ms)
        issues: List of issues found during validation
        failed_scripts: Script names an issue was raised against
    """

    def __init__(self) -> None:
        """Initialize a fresh, successful result with empty migration/issue lists."""
        self.success = True
        self.error_message = ""
        self.repeatable_migrations_to_reapply: List[Dict[str, Union[str, int]]] = []
        self.migrations: List[Migration] = []
        self.execution_time = 0
        self.issues: List[str] = []
        self.failed_scripts: List[str] = []
        self.checked_scripts: List[str] = []
        self._checked_script_names: set[str] = set()
        self._failed_script_names: set[str] = set()

    def add_checked_script(self, script_name: Optional[str]) -> None:
        """Record that a check actually ran against *script_name*.

        Collection is wider than checking: undo scripts are gathered with the
        rest, then exempted from drift detection and skipped by the
        duplicate-version check — so they receive no verification at all.
        Reporting them as validated would claim a check that never ran.
        Recording it at the point of the check is what keeps the reported set
        honest if a validator's scope later changes.
        """
        if script_name and script_name not in self._checked_script_names:
            self._checked_script_names.add(script_name)
            self.checked_scripts.append(script_name)

    def add_failed_script(self, script_name: Optional[str]) -> None:
        """Record that an issue was raised against *script_name*.

        ``issues`` is free text and several entries are summaries that name no
        single script, so the script identity a caller needs cannot be recovered
        from it. Recording it here is what lets the command layer report which
        migrations failed instead of only that validation failed. Duplicates are
        dropped: a script can raise more than one issue and is still one failed
        migration.
        """
        if script_name and script_name not in self._failed_script_names:
            self._failed_script_names.add(script_name)
            self.failed_scripts.append(script_name)

    def add_modified_repeatable(
        self, script_name: str, checksum: Union[str, int], current_checksum: Union[str, int]
    ):
        """Add a repeatable migration that needs to be reapplied due to checksum changes.

        Args:
            script_name: Name of the script
            checksum: Original checksum
            current_checksum: Current checksum
        """
        self.repeatable_migrations_to_reapply.append(
            {
                "script": script_name,
                "database_checksum": checksum,
                "filesystem_checksum": current_checksum,
            }
        )


class MigrationValidator:
    """Validates migration scripts and their execution history."""

    def __init__(
        self,
        script_manager: MigrationScriptManager,
        history_manager: MigrationHistoryManager,
        log: Log,
        placeholders: Optional[Dict[str, Any]] = None,
        *,
        state_manager: Optional[MigrationStateManager] = None,
        quirks: Optional[BaseQuirks] = None,
    ):
        """Initialize the validator.

        Args:
            script_manager: Script manager instance
            history_manager: History manager instance
            log: Logger instance
            placeholders: Optional placeholders for SQL replacement
        """
        self.log = log if log is not None else NullLog()
        self.placeholders = placeholders or {}
        self.state_manager = state_manager or MigrationStateManager(
            self.log, history_manager, script_manager, MigrationRules(self.log)
        )
        self._quirks = quirks if quirks is not None else self.state_manager.get_validation_quirks()
        self._history_schema = getattr(history_manager, "schema", "")
        self._history_table = getattr(history_manager, "history_table", "")

    def validate_flyway_compatibility(self) -> Dict[str, object]:
        """Compare the current StateManager read phase's Flyway inputs."""
        from dblift.core.sql_validator._flyway_compatibility import validate_flyway_compatibility

        return validate_flyway_compatibility(self.state_manager.get_flyway_compatibility_snapshot())

    def check_flyway_history_table(self) -> ValidationResult:
        """Apply Flyway import checks to manager-owned inputs."""
        from dblift.core.sql_validator._flyway_compatibility import check_flyway_history_table

        return check_flyway_history_table(self.state_manager.get_flyway_compatibility_snapshot())

    def _check_table_compatibility(self, issues: List[str]) -> None:
        """Preserve the 4.x history initialization entry point."""
        self.state_manager.ensure_history_table()

    _normalize_filter = staticmethod(normalize_filter)
    _passes_filters = staticmethod(passes_filters)
    _apply_filters = staticmethod(select_migrations)
    _handle_baseline_filtering = staticmethod(prune_baseline_migrations)

    def _validate_format_supported(
        self, scripts: List[Migration], result: ValidationResult, issues: List[str]
    ) -> bool:
        """Reject a script whose format the dialect cannot run (DBLIFT-NOSQL-001).

        Uses the same pure check ``ExecutionEngine.execute_migration`` runs
        before a real (non-dry-run) migration executes, so ``validate``,
        ``migrate --validate-only``, and ``migrate --dry-run`` — which all
        resolve through this method — surface the same rejection up front
        instead of reporting success for a ``.sql`` migration this dialect
        can never run.
        """
        for script in scripts:
            # ``format`` is set by every real Migration (from the file
            # extension); test doubles built as bare SimpleNamespace/Mock
            # objects for unrelated checks may omit it, and have nothing
            # for this check to evaluate.
            format = getattr(script, "format", None)
            if format is None:
                continue
            try:
                check_format_supported(self._quirks, format, script.script_name)
            except UnsupportedMigrationFormatError as e:
                result.success = False
                result.error_message = str(e)
                issues.append(str(e))
                result.add_failed_script(script.script_name)
                return False
        return True

    def _validate_prepared_migrations(
        self,
        *,
        valid_scripts: List[Migration],
        all_valid_scripts: List[Migration],
        applied_migrations: List[Migration],
        repeatable_history: List[Migration],
        validation_result: ValidationResult,
        issues: List[str],
        history_table_exists: bool,
        command: str,
        strict_mode: bool,
    ) -> ValidationResult:
        """Run the common checks over already prepared catalog and history inputs."""
        self._check_repeatable_migrations(
            valid_scripts, repeatable_history, validation_result, command
        )

        if not self._validate_duplicate_repeatable_names(valid_scripts, validation_result, issues):
            validation_result.issues = issues
            return validation_result

        if all(
            script.type in (MigrationType.REPEATABLE, MigrationType.CALLBACK)
            for script in valid_scripts
        ):
            if validation_result.success and not issues:
                validation_result.success = True
                validation_result.error_message = ""
            validation_result.migrations = valid_scripts
            validation_result.execution_time = TEST_PLACEHOLDER_TIME_MS
            validation_result.issues = issues
            return validation_result

        if not self._validate_duplicate_versions(valid_scripts, validation_result, issues):
            validation_result.issues = issues
            return validation_result

        validation_result.migrations = valid_scripts

        if history_table_exists:
            if strict_mode and command in ("migrate", "validate"):
                self.log.info("Strict mode is enabled. Validating with strict migration rules.")
                if not self._validate_strict_mode_rules(
                    valid_scripts, applied_migrations, validation_result, issues
                ):
                    validation_result.issues = issues
                    return validation_result

            self._validate_failed_migrations(applied_migrations, validation_result, issues)
            self._validate_checksums(
                valid_scripts,
                applied_migrations,
                validation_result,
                issues,
                strict_mode,
                all_valid_scripts,
            )
            self._validate_reappeared_migrations(
                valid_scripts, applied_migrations, validation_result, issues
            )

        if issues:
            validation_result.success = False
            if not validation_result.error_message:
                validation_result.error_message = issues[0]
            validation_result.execution_time = TEST_PLACEHOLDER_TIME_MS
            validation_result.issues = issues
            return validation_result

        validation_result.success = True
        validation_result.error_message = ""
        validation_result.issues = issues
        return validation_result

    def validate_snapshot(
        self, snapshot: MigrationValidationSnapshot, command: str = "migrate"
    ) -> ValidationResult:
        """Validate immutable inputs without collecting scripts or history."""
        result = ValidationResult()
        issues: List[str] = []
        if not snapshot.scripts_directory_exists:
            result.success = False
            result.error_message = (
                f"Migration scripts directory not found: {snapshot.scripts_directory}"
            )
            return result
        try:
            scripts = list(snapshot.selected_migrations)
            if not self._validate_format_supported(scripts, result, issues):
                result.execution_time = TEST_PLACEHOLDER_TIME_MS
                result.issues = issues
                return result
            if not scripts:
                if snapshot.strict_mode and snapshot.history_read_error:
                    result.success = False
                    result.error_message = f"Validation failed: {snapshot.history_read_error}"
                    return result
                result.success = not (snapshot.strict_mode and snapshot.all_applied_migrations)
                result.execution_time = TEST_PLACEHOLDER_TIME_MS
                return result
            return self._validate_prepared_migrations(
                valid_scripts=scripts,
                all_valid_scripts=list(snapshot.resolved_migrations),
                applied_migrations=list(snapshot.scoped_applied_migrations),
                repeatable_history=list(snapshot.all_applied_migrations),
                validation_result=result,
                issues=issues,
                history_table_exists=snapshot.history_table_exists,
                command=command,
                strict_mode=snapshot.strict_mode,
            )
        except Exception as error:
            result.success = False
            result.error_message = f"Validation failed: {error}"
            result.issues = issues
            return result

    def validate_resolved_migrations(
        self, migrations: List[Migration], command: str = "migrate"
    ) -> ValidationResult:
        """Adapt the public 4.x resolved-list entry point through StateManager."""
        try:
            return self.validate_snapshot(
                self.state_manager.build_validation_snapshot(
                    None,
                    command,
                    resolved_migrations=migrations,
                ),
                command,
            )
        except Exception as error:
            result = ValidationResult()
            result.success = False
            result.error_message = f"Validation failed: {error}"
            return result

    def validate_migrations(
        self,
        scripts_dir: Path,
        command: str = "migrate",
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        target_version: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        exclude_tags: Optional[Sequence[str]] = None,
        versions: Optional[Sequence[str]] = None,
        exclude_versions: Optional[Sequence[str]] = None,
        *,
        resolved_migrations: Optional[List[Migration]] = None,
        preloaded_records: Optional[List[Migration]] = None,
        read_snapshot: Optional[MigrationReadSnapshot] = None,
    ) -> ValidationResult:
        """Adapt the public 4.x directory entry point through StateManager."""
        try:
            return self.validate_snapshot(
                self.state_manager.build_validation_snapshot(
                    scripts_dir,
                    command,
                    recursive,
                    additional_dirs,
                    target_version,
                    tags,
                    exclude_tags,
                    versions,
                    exclude_versions,
                    resolved_migrations=resolved_migrations,
                    applied_migrations=preloaded_records,
                    read_snapshot=read_snapshot,
                ),
                command,
            )
        except Exception as error:
            result = ValidationResult()
            result.success = False
            result.error_message = f"Validation failed: {error}"
            return result

    def _validate_duplicate_versions(
        self, scripts: List[Migration], result: ValidationResult, issues: List[str]
    ) -> bool:
        # Map to track version numbers and corresponding scripts
        version_map: Dict[Any, Any] = {}
        versioned_migration_count = 0
        repeatable_migration_count = 0
        callback_migration_count = 0
        for script in scripts:
            # Count migrations by type
            if script.type == MigrationType.REPEATABLE:
                repeatable_migration_count += 1
                continue
            elif script.type == MigrationType.CALLBACK:
                callback_migration_count += 1
                continue
            elif script.type == MigrationType.UNDO_SQL or script.type == MigrationType.BASELINE:
                continue
            elif script.type in (MigrationType.SQL, MigrationType.PYTHON):
                versioned_migration_count += 1
            else:
                continue
            # Skip scripts with no version (like callbacks)
            if script.version is None:
                continue
            # Check if version already exists in our map
            if script.version in version_map:
                # Allow baseline and versioned (SQL or PYTHON) to share the same version
                existing_type = version_map[script.version].type
                versioned_types = (MigrationType.SQL, MigrationType.PYTHON)
                if (existing_type == MigrationType.BASELINE and script.type in versioned_types) or (
                    existing_type in versioned_types and script.type == MigrationType.BASELINE
                ):
                    continue
                if result.success:
                    self.log.debug(
                        f"[DEBUG] _validate_duplicate_versions: setting success=False for duplicate version {script.version}"
                    )
                    result.success = False
                    result.error_message = "Found migration scripts with duplicate versions"
                # script_name is the bare filename, which is identical for two
                # same-named scripts from different --scripts directories; use
                # the full path (when available) so colliding files remain
                # distinguishable.
                existing_display = getattr(version_map[script.version], "path", None) or (
                    version_map[script.version].script_name
                )
                script_display = getattr(script, "path", None) or script.script_name
                # Create error message for duplicate versions
                duplicate_error = (
                    f"Version {script.version} is used by both "
                    f"{existing_display} and {script_display}"
                )
                issues.append("Validation failed: Found migration scripts with duplicate versions")
                issues.append(duplicate_error)
                # Both sides of the collision are implicated, and both are on disk.
                result.add_failed_script(version_map[script.version].script_name)
                result.add_failed_script(script.script_name)
                result.success = False
                result.error_message = (
                    f"Version {script.version} is used by both "
                    f"{existing_display} and {script_display}"
                )
            else:
                version_map[script.version] = script
        if result.success:
            if callback_migration_count > 0:
                self.log.info(f"Found {callback_migration_count} callback migrations.")
        self.log.debug(
            f"[DEBUG] _validate_duplicate_versions END: success={result.success}, error='{result.error_message}'"
        )
        return result.success

    def _validate_duplicate_repeatable_names(
        self, scripts: List[Migration], result: ValidationResult, issues: List[str]
    ) -> bool:
        """Detect repeatable migrations that collide on script name across directories.

        ``script_name`` is always the bare filename now (PR #129), so a repeatable
        migration in the primary directory and one with the same filename in a
        secondary ``--scripts`` directory are indistinguishable by name alone.
        Two REPEATABLE scripts sharing a name but backed by different files is a
        genuine cross-directory naming collision — mirrors how
        ``_validate_duplicate_versions`` flags two versioned scripts sharing a
        version.
        """
        name_map: Dict[str, Migration] = {}
        for script in scripts:
            if script.type != MigrationType.REPEATABLE:
                continue
            existing = name_map.get(script.script_name)
            if existing is None:
                name_map[script.script_name] = script
                continue
            existing_path = getattr(existing, "path", None)
            script_path = getattr(script, "path", None)
            if (
                existing_path is not None
                and script_path is not None
                and existing_path == script_path
            ):
                # Same file resolved twice — not a cross-directory collision.
                continue
            if result.success:
                result.success = False
                result.error_message = (
                    f"Repeatable migration name {script.script_name} is used by scripts "
                    f"in more than one directory: {existing_path} and {script_path}"
                )
            issues.append(
                "Validation failed: Found repeatable migration scripts with duplicate names"
            )
            issues.append(
                f"Repeatable migration name {script.script_name} is used by scripts in "
                f"more than one directory: {existing_path} and {script_path}"
            )
        return result.success

    def _validate_checksums(
        self,
        scripts: List[Migration],
        applied_migrations: List[Migration],
        result: ValidationResult,
        issues: List[str],
        strict_mode: bool = False,
        all_scripts: Optional[List[Migration]] = None,
    ) -> None:
        """Delegate to :func:`dblift.core.sql_validator._checksum_validator.validate_checksums`.

        Kept as a method so test code that calls
        ``v._validate_checksums(...)`` directly continues to work.
        """
        from dblift.core.sql_validator._checksum_validator import validate_checksums as _impl

        _impl(self, scripts, applied_migrations, result, issues, strict_mode, all_scripts)

    def _check_repeatable_migrations(
        self,
        scripts: List[Migration],
        applied_migrations: List[Migration],
        result: ValidationResult,
        command: str = "migrate",
    ) -> None:
        """Delegate to
        :func:`dblift.core.sql_validator._checksum_validator.check_repeatable_migrations`.
        """
        from dblift.core.sql_validator._checksum_validator import (
            check_repeatable_migrations as _impl,
        )

        _impl(self, scripts, applied_migrations, result, command)

    def _validate_strict_mode_rules(
        self,
        scripts: List[Migration],
        applied_migrations: List[Migration],
        result: ValidationResult,
        issues: List[str],
    ) -> bool:
        """Delegate to
        :func:`dblift.core.sql_validator._strict_mode_validator.validate_strict_mode_rules`.
        """
        from dblift.core.sql_validator._strict_mode_validator import (
            validate_strict_mode_rules as _impl,
        )

        return _impl(self, scripts, applied_migrations, result, issues)

    def validate_out_of_order(
        self, migration: Migration, executed_migrations: List[Migration]
    ) -> bool:
        """Check if a migration was executed out of order.

        Args:
            migration: Migration to check
            executed_migrations: List of all executed migrations

        Returns:
            bool: True if executed out of order, False otherwise
        """
        # Get the applied migration record
        applied_migration = next(
            (
                m
                for m in executed_migrations
                if getattr(m, "script_name", None) == migration.script_name
                and getattr(m, "success", False)
            ),
            None,
        )
        if not applied_migration:
            return False

        # Check if this is a versioned migration (any format, not SQL only)
        if not is_versioned(migration.type) or not migration.version:
            return False

        # Get all migrations with higher version numbers
        higher_version_migrations = [
            m
            for m in executed_migrations
            if getattr(m, "success", False)
            and getattr(m, "version", None)
            and compare_versions(str(getattr(m, "version", "")), str(migration.version)) > 0
        ]

        # If any higher version migration has a lower installed_rank, this migration is out of order
        return any(
            getattr(m, "installed_rank", 0) < getattr(applied_migration, "installed_rank", 0)
            for m in higher_version_migrations
        )

    def _validate_reappeared_migrations(
        self,
        scripts: List[Migration],
        applied_migrations: List[Migration],
        result: ValidationResult,
        issues: List[str],
    ) -> None:
        deleted_migrations = [
            m for m in applied_migrations if getattr(m, "type", None) == MigrationType.DELETE
        ]
        if not deleted_migrations:
            return
        reappeared_scripts = []
        for deleted in deleted_migrations:
            script_name = getattr(deleted, "script_name", None)
            matching_scripts = [s for s in scripts if s.script_name == script_name]
            if matching_scripts:
                reappeared_scripts.append(
                    {
                        "script": script_name,
                        "version": getattr(deleted, "version", "unknown"),
                        "current_checksum": matching_scripts[0].checksum,
                        "history_checksum": getattr(deleted, "checksum", ""),
                    }
                )
        if reappeared_scripts:
            result.success = False
            script_list = ", ".join([f"{s['script']}" for s in reappeared_scripts])
            error_message = f"Found {len(reappeared_scripts)} previously deleted migration script(s) that have reappeared: {script_list}"
            repair_message = (
                "To resolve this issue, manually remove the DELETE entries from the history table:\n"
                f"DELETE FROM {self._history_schema}.{self._history_table} WHERE type = 'DELETE' AND script_name IN ({', '.join([repr(s['script']) for s in reappeared_scripts])});"
            )
            issues.append(error_message)
            issues.append(repair_message)
            result.error_message = f"{error_message}\n{repair_message}"
            for reappeared in reappeared_scripts:
                result.add_failed_script(str(reappeared["script"]))
            for script in reappeared_scripts:
                self.log.debug(
                    f"Reappeared migration: {script['script']} (version: {script['version']})"
                )

    def _validate_failed_migrations(
        self, applied_migrations: List[Migration], result: ValidationResult, issues: List[str]
    ) -> None:
        # Use is_migration_failure so integer 0 (DB2/SQL Server SMALLINT) and
        # string "false" are treated the same as bool False.  NULL/None means
        # the migration can be retried and is intentionally excluded.
        failed_migrations = [
            m for m in applied_migrations if is_migration_failure(getattr(m, "success", None))
        ]
        if not failed_migrations:
            return
        filtered_failed = []
        specific_repeatable_errors = []
        for m in failed_migrations:
            if is_migration_type(getattr(m, "type", None), "REPEATABLE"):
                # Keyed by script name alone: ``check_repeatable_migrations``
                # only schedules a repeatable it has already decided to reapply,
                # and refuses to schedule one that failed and has not changed.
                # A scheduled repeatable is therefore not a blocking failure.
                scheduled = any(
                    rep["script"] == getattr(m, "script_name", None)
                    for rep in getattr(result, "repeatable_migrations_to_reapply", [])
                )
                if scheduled:
                    continue
                specific_repeatable_errors.append(
                    f"Repeatable migration {getattr(m, 'script_name', None)} previously failed and has not changed. Please fix the script before retrying."
                )
            filtered_failed.append(m)
        if not filtered_failed:
            return
        if specific_repeatable_errors and len(filtered_failed) == len(specific_repeatable_errors):
            error_message = "\n".join(specific_repeatable_errors)
        else:
            script_list = ", ".join(
                [
                    f"{getattr(m, 'script_name', None)} (version: {getattr(m, 'version', 'unknown')})"
                    for m in filtered_failed
                ]
            )
            error_message = f"Found {len(filtered_failed)} failed migration(s): {script_list}"
        repair_message = "Run 'repair' command to update the status in the history table."
        issues.append(error_message)
        issues.append(repair_message)
        result.error_message = f"{error_message}\n{repair_message}"
        for m in filtered_failed:
            result.add_failed_script(getattr(m, "script_name", None))
            self.log.debug(
                f"Failed migration: {getattr(m, 'script_name', None)} (version: {getattr(m, 'version', 'unknown')})"
            )
        result.success = False
