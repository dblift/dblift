"""Migration-validator entry point — verifies migration scripts against applied history."""

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple, Union

from core.constants import TEST_PLACEHOLDER_TIME_MS
from core.logger import Log, NullLog
from core.migration._type_match import is_migration_type
from core.migration.history.migration_history_manager import MigrationHistoryManager
from core.migration.migration import (
    Migration,
    MigrationType,
)
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.sql.sql_analyzer import SqlAnalyzer
from core.migration.version_utils import is_migration_failure, is_migration_success


class ValidationResult:
    """Result of a migration validation.

    Attributes:
        success: Whether the validation was successful
        error_message: Error message if validation failed
        repeatable_migrations_to_reapply: List of repeatable migrations that need to be reapplied
        migrations: List of migration objects (populated by validator)
        execution_time: Time taken for validation (ms)
        issues: List of issues found during validation
    """

    def __init__(self) -> None:
        """Initialize a fresh, successful result with empty migration/issue lists."""
        self.success = True
        self.error_message = ""
        self.repeatable_migrations_to_reapply: List[Dict[str, Union[str, int]]] = []
        self.migrations: List[Migration] = []
        self.execution_time = 0
        self.issues: List[str] = []

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


def _last_successful_non_delete_record(
    applied_migrations: List[Migration], script_name: str
) -> Optional[Migration]:
    """Match :meth:`MigrationScriptManager.has_script_changed` — latest successful row only."""
    for migration in reversed(applied_migrations):
        if getattr(migration, "script_name", None) != script_name:
            continue
        migration_type = getattr(migration, "type", None)
        if is_migration_type(migration_type, "DELETE") or is_migration_type(
            migration_type, "UNDO_SQL"
        ):
            continue
        if not is_migration_success(getattr(migration, "success", False)):
            continue
        return migration
    return None


class MigrationValidator:
    """Validates migration scripts and their execution history."""

    def __init__(
        self,
        script_manager: MigrationScriptManager,
        history_manager: MigrationHistoryManager,
        log: Log,
        placeholders: Optional[Dict[str, Any]] = None,
    ):
        """Initialize the validator.

        Args:
            script_manager: Script manager instance
            history_manager: History manager instance
            log: Logger instance
            placeholders: Optional placeholders for SQL replacement
        """
        self.script_manager = script_manager
        self.history_manager = history_manager
        self.log = log if log is not None else NullLog()
        self.placeholders = placeholders or {}

        # Initialize the SQL analyzer with ANTLR support and database type from provider config
        dblift_config = getattr(self.history_manager.provider, "config", None)
        if dblift_config:
            dialect = dblift_config.database.type
            self.sql_analyzer = SqlAnalyzer(dialect=dialect, logger=self.log)
        else:
            dialect = ""
            self.sql_analyzer = SqlAnalyzer(dialect=dialect, logger=self.log)

        from db.provider_registry import ProviderRegistry

        self._quirks = ProviderRegistry.get_quirks(dialect)

        # Cache for Flyway compatibility check results
        self._flyway_compatibility_cache: Optional[Dict[str, object]] = None

    def _replace_placeholders(self, sql_text: str) -> str:
        """Replace placeholders in SQL text with their values.

        This method uses the PlaceholderService to handle replacements.

        Args:
            sql_text: The SQL text containing placeholders

        Returns:
            SQL text with placeholders replaced by actual values
        """
        from core.migration.placeholders.placeholder_service import PlaceholderService

        # Create a placeholder service instance with our placeholders
        placeholder_service = PlaceholderService(self.placeholders, self.log)

        # Use the service to replace placeholders
        return str(placeholder_service.replace_placeholders(sql_text))

    def validate_flyway_compatibility(self) -> Dict[str, object]:
        """Delegate to :func:`core.sql_validator._flyway_compatibility.validate_flyway_compatibility`."""
        from core.sql_validator._flyway_compatibility import validate_flyway_compatibility as _impl

        return _impl(self)

    def check_flyway_history_table(self) -> ValidationResult:
        """Delegate to :func:`core.sql_validator._flyway_compatibility.check_flyway_history_table`."""
        from core.sql_validator._flyway_compatibility import check_flyway_history_table as _impl

        return _impl(self)

    def _check_table_compatibility(self, issues: List[str]) -> None:
        """Delegate to :func:`core.sql_validator._flyway_compatibility.check_table_compatibility`."""
        from core.sql_validator._flyway_compatibility import check_table_compatibility as _impl

        _impl(self, issues)

    # ------------------------------------------------------------------
    # Filtering / scoping — delegated to ``_migration_filter`` (SRP).
    # ------------------------------------------------------------------

    def _load_and_filter_migrations(
        self, scripts_dir: Path, recursive: bool, additional_dirs: List[Path], issues: List[str]
    ) -> List[Migration]:
        """Delegate to :func:`core.sql_validator._migration_filter.load_and_filter_migrations`."""
        from core.sql_validator._migration_filter import load_and_filter_migrations as _impl

        return _impl(self, scripts_dir, recursive, additional_dirs, issues)

    def _handle_baseline_filtering(self, valid_scripts: List[Migration]) -> List[Migration]:
        """Delegate to :func:`core.sql_validator._migration_filter.handle_baseline_filtering`."""
        from core.sql_validator._migration_filter import handle_baseline_filtering as _impl

        return _impl(self, valid_scripts)

    @staticmethod
    def _normalize_filter(value: Optional[Sequence[str]]) -> Optional[List[str]]:
        """Delegate to :func:`core.sql_validator._migration_filter.normalize_filter`."""
        from core.sql_validator._migration_filter import normalize_filter as _impl

        return _impl(value)

    def _passes_filters(
        self,
        migration: Migration,
        target_version: Optional[str],
        tags: Optional[List[str]],
        exclude_tags: Optional[List[str]],
        versions: Optional[List[str]],
        exclude_versions: Optional[List[str]],
    ) -> bool:
        """Delegate to :func:`core.sql_validator._migration_filter.passes_filters`."""
        from core.sql_validator._migration_filter import passes_filters as _impl

        return _impl(
            self, migration, target_version, tags, exclude_tags, versions, exclude_versions
        )

    def _apply_filters(
        self,
        migrations: List[Migration],
        target_version: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        exclude_tags: Optional[Sequence[str]] = None,
        versions: Optional[Sequence[str]] = None,
        exclude_versions: Optional[Sequence[str]] = None,
    ) -> List[Migration]:
        """Delegate to :func:`core.sql_validator._migration_filter.apply_filters`."""
        from core.sql_validator._migration_filter import apply_filters as _impl

        return _impl(
            self, migrations, target_version, tags, exclude_tags, versions, exclude_versions
        )

    def _scope_applied_migrations_for_validation(
        self,
        applied_migrations: List[Migration],
        target_version: Optional[str] = None,
        versions: Optional[Sequence[str]] = None,
        exclude_versions: Optional[Sequence[str]] = None,
    ) -> List[Migration]:
        """Delegate to :func:`core.sql_validator._migration_filter.scope_applied_migrations_for_validation`."""
        from core.sql_validator._migration_filter import (
            scope_applied_migrations_for_validation as _impl,
        )

        return _impl(self, applied_migrations, target_version, versions, exclude_versions)

    def _validate_no_scripts_case(
        self, valid_scripts: List[Migration], issues: List[str]
    ) -> Tuple[bool, bool]:
        """Delegate to :func:`core.sql_validator._migration_filter.validate_no_scripts_case`."""
        from core.sql_validator._migration_filter import validate_no_scripts_case as _impl

        return _impl(self, valid_scripts, issues)

    def validate_resolved_migrations(
        self, migrations: List[Migration], command: str = "migrate"
    ) -> ValidationResult:
        """Validate an already resolved migration list.

        This mirrors Flyway's resolve-then-validate flow for migrate pre-flight:
        callers pass the same migrations they intend to execute, so validation
        cannot inspect out-of-scope files.
        """
        validation_result = ValidationResult()
        validation_result.success = True
        validation_result.error_message = ""
        validation_result.migrations = []
        validation_result.execution_time = 0
        issues: List[str] = []

        try:
            valid_scripts = [
                script
                for script in migrations
                if script.type
                in (
                    MigrationType.SQL,
                    MigrationType.REPEATABLE,
                    MigrationType.CALLBACK,
                    MigrationType.BASELINE,
                    MigrationType.UNDO_SQL,
                    MigrationType.PYTHON,
                )
            ]

            self.log.debug(
                f"[DEBUG] resolved valid_scripts: {[s.script_name for s in valid_scripts]}"
            )

            should_return_early, validation_success = self._validate_no_scripts_case(
                valid_scripts, issues
            )
            if should_return_early:
                validation_result.success = validation_success
                if not validation_success and issues:
                    validation_result.error_message = issues[0]
                validation_result.execution_time = TEST_PLACEHOLDER_TIME_MS
                validation_result.issues = issues
                return validation_result

            history_table_exists = self.history_manager.has_history_table
            applied_migrations = []
            if history_table_exists:
                try:
                    applied_migrations = self.history_manager.get_applied_migrations()
                except Exception as e:
                    self.log.error(f"Error getting applied migrations: {e}")
                    applied_migrations = []

            self._check_repeatable_migrations(
                valid_scripts, applied_migrations, validation_result, command
            )

            if all(
                s.type in (MigrationType.REPEATABLE, MigrationType.CALLBACK) for s in valid_scripts
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

            # Flyway-compatible validate semantics: validate migration metadata/history,
            # not SQL syntax. SQL parsing belongs to the explicit static SQL lint command.
            validation_result.migrations = valid_scripts

            if history_table_exists:
                callback_in_history = [m for m in applied_migrations if m.type == "CALLBACK"]
                if callback_in_history:
                    validation_result.success = False
                    validation_result.error_message = (
                        " " f"{', '.join(m.script_name for m in callback_in_history)}. " "."
                    )
                    validation_result.issues = issues
                    return validation_result

                config = getattr(self.history_manager.provider, "config", None)
                strict_mode = bool(getattr(config, "strict_mode", False))
                if strict_mode and command in ("migrate", "validate"):
                    self.log.info("Strict mode is enabled. Validating with strict migration rules.")
                    if not self._validate_strict_mode_rules(
                        valid_scripts, applied_migrations, validation_result, issues
                    ):
                        validation_result.issues = issues
                        return validation_result

                self._validate_failed_migrations(applied_migrations, validation_result, issues)
                self._validate_checksums(
                    valid_scripts, applied_migrations, validation_result, issues, strict_mode
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

        except Exception as e:
            error_msg = f"Validation failed: {str(e)}"
            try:
                self.log.error(error_msg)
            except Exception as log_e:
                logging.getLogger(__name__).error(f"{error_msg} (log unavailable: {log_e})")

            validation_result.success = False
            validation_result.error_message = error_msg
            validation_result.issues = issues
            return validation_result

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
    ) -> ValidationResult:
        """Validate migrations against the database.

        This checks for duplicate version numbers, missing migrations, and modified scripts.

        Args:
            scripts_dir: Directory containing migration scripts
            command: The command being executed (migrate, undo, etc.)
            recursive: Whether to scan subdirectories for migration scripts
            additional_dirs: Additional directories to scan for migration scripts
            target_version: Optional target version filter
            tags: Optional tags to include
            exclude_tags: Optional tags to exclude
            versions: Optional versions to include
            exclude_versions: Optional versions to exclude

        Returns:
            ValidationResult: Result of the validation
        """
        validation_result = ValidationResult()
        self.log.debug(
            f"[DEBUG] validate_migrations: initial state: success={validation_result.success}, error='{validation_result.error_message}', issues={[]} "
        )
        validation_result.success = True
        validation_result.error_message = ""
        validation_result.migrations = []
        validation_result.execution_time = 0
        issues: List[str] = []  # Shared issues list for the entire function

        if not scripts_dir.exists():
            validation_result.success = False
            self.log.debug(
                f"[DEBUG] validate_migrations: setting success=False because scripts_dir does not exist. issues={issues}"
            )
            validation_result.error_message = (
                f"Migration scripts directory not found: {scripts_dir}"
            )
            self.log.debug(
                f"[DEBUG] RETURN (not exists): success={validation_result.success}, error='{validation_result.error_message}'"
            )
            validation_result.issues = issues
            return validation_result

        try:

            # Load and filter migration scripts
            valid_scripts = self._load_and_filter_migrations(
                scripts_dir, recursive, additional_dirs or [], issues
            )

            # Handle baseline filtering
            valid_scripts = self._handle_baseline_filtering(valid_scripts)

            valid_scripts = self._apply_filters(
                valid_scripts,
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )

            self.log.debug(f"[DEBUG] valid_scripts: {[s.script_name for s in valid_scripts]}")

            # Validate no scripts case
            should_return_early, validation_success = self._validate_no_scripts_case(
                valid_scripts, issues
            )
            if should_return_early:
                validation_result.success = validation_success
                if not validation_success and issues:
                    validation_result.error_message = issues[0]
                validation_result.execution_time = TEST_PLACEHOLDER_TIME_MS
                validation_result.issues = issues
                return validation_result

            # Check if history table exists
            history_table_exists = self.history_manager.has_history_table
            applied_migrations = []
            if history_table_exists:
                try:
                    applied_migrations = self.history_manager.get_applied_migrations()
                except Exception as e:
                    self.log.error(f"Error getting applied migrations: {e}")
                    applied_migrations = []
            scoped_applied_migrations = self._scope_applied_migrations_for_validation(
                applied_migrations,
                target_version=target_version,
                versions=versions,
                exclude_versions=exclude_versions,
            )

            # Always check repeatable migrations for reapply, even if all scripts are repeatable/callback
            self._check_repeatable_migrations(
                valid_scripts, applied_migrations, validation_result, command
            )
            self.log.debug(
                f"[DEBUG] validate_migrations: after _check_repeatable_migrations: success={validation_result.success}, "
                f"error='{validation_result.error_message}', issues={issues}"
            )

            # If there are no valid scripts, validation should succeed (never fail for empty/ignored input)
            if not valid_scripts:
                config = getattr(self.history_manager.provider, "config", None)
                strict_mode = bool(getattr(config, "strict_mode", False))
                # If there are applied migrations and strict mode is on, fail validation
                if history_table_exists and scoped_applied_migrations and strict_mode:
                    self._validate_checksums(
                        valid_scripts,
                        scoped_applied_migrations,
                        validation_result,
                        issues,
                        strict_mode,
                    )
                    if issues:
                        validation_result.success = False
                        self.log.debug(
                            f"[DEBUG] validate_migrations: setting success=False because issues after strict_mode check. issues={issues}"
                        )
                        if not validation_result.error_message and issues:
                            validation_result.error_message = issues[0]
                        validation_result.execution_time = TEST_PLACEHOLDER_TIME_MS
                        self.log.debug(
                            f"[DEBUG] RETURN (no valid scripts, but missing in history): success={validation_result.success}, error='{validation_result.error_message}'"
                        )
                        validation_result.issues = issues
                        return validation_result
                # Otherwise, succeed
                validation_result.success = True
                validation_result.error_message = ""
                validation_result.execution_time = TEST_PLACEHOLDER_TIME_MS
                self.log.debug(
                    f"[DEBUG] RETURN (no valid scripts): success={validation_result.success}, error='{validation_result.error_message}'"
                )
                validation_result.issues = issues
                return validation_result

            # If all valid scripts are repeatable or callback, validation should succeed
            if all(
                s.type in (MigrationType.REPEATABLE, MigrationType.CALLBACK) for s in valid_scripts
            ):
                # _check_repeatable_migrations already called above
                if validation_result.success and not issues:
                    validation_result.success = True
                    validation_result.error_message = ""
                validation_result.migrations = valid_scripts
                validation_result.execution_time = TEST_PLACEHOLDER_TIME_MS
                self.log.debug(
                    f"[DEBUG] RETURN (all repeatable/callback): success={validation_result.success}, error='{validation_result.error_message}'"
                )
                validation_result.issues = issues
                return validation_result

            # Validate that there are no duplicate version numbers
            if not self._validate_duplicate_versions(valid_scripts, validation_result, issues):
                self.log.debug(
                    f"[DEBUG] validate_migrations: after _validate_duplicate_versions: success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
                )
                self.log.debug(
                    f"[DEBUG] RETURN (duplicate versions): success={validation_result.success}, error='{validation_result.error_message}'"
                )
                validation_result.issues = issues
                return validation_result

            # Set migrations list for report generation
            validation_result.migrations = valid_scripts

            # Flyway-compatible validate semantics: validate migration metadata/history,
            # not SQL syntax. SQL parsing belongs to the explicit static SQL lint command.
            self.log.debug(
                f"[DEBUG] validate_migrations: skipping SQL syntax parsing; success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
            )

            # If history table exists, validate checksums and other constraints
            if history_table_exists:
                callback_in_history = [m for m in applied_migrations if m.type == "CALLBACK"]
                if callback_in_history:
                    validation_result.success = False
                    validation_result.error_message = (
                        " " f"{', '.join(m.script_name for m in callback_in_history)}. " "."
                    )
                    self.log.debug(
                        f"[DEBUG] validate_migrations: after callback_in_history check: success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
                    )
                    self.log.debug(
                        f"[DEBUG] RETURN (callback in history): success={validation_result.success}, error='{validation_result.error_message}'"
                    )
                    validation_result.issues = issues
                    return validation_result

                # Check if strict mode is enabled and validate accordingly
                config = getattr(self.history_manager.provider, "config", None)
                strict_mode = bool(getattr(config, "strict_mode", False))
                if strict_mode and command in ("migrate", "validate"):
                    self.log.info("Strict mode is enabled. Validating with strict migration rules.")
                    if not self._validate_strict_mode_rules(
                        valid_scripts, scoped_applied_migrations, validation_result, issues
                    ):
                        self.log.debug(
                            f"[DEBUG] validate_migrations: after _validate_strict_mode_rules: success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
                        )
                        self.log.debug(
                            f"[DEBUG] RETURN (strict mode validation failed): success={validation_result.success}, error='{validation_result.error_message}'"
                        )
                        validation_result.issues = issues
                        return validation_result

                # Patch: Only treat missing script for applied migration as error if strict_mode is enabled
                # Otherwise, log a warning but do not set success=False
                self._validate_failed_migrations(
                    scoped_applied_migrations, validation_result, issues
                )
                self.log.debug(
                    f"[DEBUG] validate_migrations: after _validate_failed_migrations: success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
                )
                self._validate_checksums(
                    valid_scripts,
                    scoped_applied_migrations,
                    validation_result,
                    issues,
                    strict_mode,
                )
                self.log.debug(
                    f"[DEBUG] validate_migrations: after _validate_checksums: success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
                )
                self._validate_reappeared_migrations(
                    valid_scripts, scoped_applied_migrations, validation_result, issues
                )
                self.log.debug(
                    f"[DEBUG] validate_migrations: after _validate_reappeared_migrations: success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
                )

            self.log.debug(
                f"[DEBUG] validate_migrations: FINAL state before return: success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
            )

            # DEBUG: Log the issues and result before returning
            self.log.debug(f"[DEBUG] FINAL issues: {issues}")
            self.log.debug(f"[DEBUG] FINAL result.success: {validation_result.success}")

            # If there are issues, validation fails
            if issues:
                validation_result.success = False
                self.log.debug(
                    f"[DEBUG] validate_migrations: setting success=False because issues at final check. issues={issues}"
                )
                if not validation_result.error_message and issues:
                    validation_result.error_message = issues[0]
                validation_result.execution_time = (
                    TEST_PLACEHOLDER_TIME_MS  # Placeholder time in ms
                )
                self.log.debug(
                    f"[DEBUG] RETURN (issues): success={validation_result.success}, error='{validation_result.error_message}'"
                )
                validation_result.issues = issues
                return validation_result

            # At the end, if there are no issues, ensure success is True and error_message is empty
            validation_result.issues = issues
            self.log.debug(f"[DEBUG] FINAL issues at return: {issues}")
            self.log.debug(
                f"[DEBUG] FINAL error_message at return: {validation_result.error_message}"
            )
            if not issues:
                validation_result.success = True
                validation_result.error_message = ""
                for issue in issues:
                    self.log.debug(f"[DEBUG] Issue: {issue}")
            else:
                for issue in issues:
                    self.log.warning(f"[WARNING] Issue: {issue}")
            self.log.debug(
                f"FINAL RETURN: success={validation_result.success}, error='{validation_result.error_message}', issues={issues}"
            )
            validation_result.issues = issues
            return validation_result

        except Exception as e:
            # Try to use a standard log if DbliftLogger instantiation failed
            error_msg = f"Validation failed: {str(e)}"
            try:
                # Log using self.log which should be available
                self.log.error(error_msg)
            except Exception as log_e:
                # Fallback to standard logging if self.log is unavailable
                logging.getLogger(__name__).error(f"{error_msg} (log unavailable: {log_e})")

            validation_result.success = False
            validation_result.error_message = error_msg
            self.log.debug(
                f"[DEBUG] RETURN (exception): success={validation_result.success}, error='{validation_result.error_message}'"
            )
            validation_result.issues = issues
            return validation_result

    def _get_undone_versions(self, applied_migrations: List[Migration]) -> set:
        """Get versions that have been undone."""
        undone_versions = set()
        for m in applied_migrations:
            if getattr(m, "type", None) == "UNDO_SQL" and getattr(m, "success", False):
                undone_versions.add(getattr(m, "version", None))
        return undone_versions

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
                # Create error message for duplicate versions
                duplicate_error = (
                    f"Version {script.version} is used by both "
                    f"{version_map[script.version].script_name} and {script.script_name}"
                )
                issues.append("Validation failed: Found migration scripts with duplicate versions")
                issues.append(duplicate_error)
                result.success = False
                result.error_message = (
                    f"Version {script.version} is used by both "
                    f"{version_map[script.version].script_name} and {script.script_name}"
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

    def _validate_checksums(
        self,
        scripts: List[Migration],
        applied_migrations: List[Migration],
        result: ValidationResult,
        issues: List[str],
        strict_mode: bool = False,
    ) -> None:
        """Delegate to :func:`core.sql_validator._checksum_validator.validate_checksums`.

        Kept as a method so test code that calls
        ``v._validate_checksums(...)`` directly continues to work.
        """
        from core.sql_validator._checksum_validator import validate_checksums as _impl

        _impl(self, scripts, applied_migrations, result, issues, strict_mode)

    def _check_repeatable_migrations(
        self,
        scripts: List[Migration],
        applied_migrations: List[Migration],
        result: ValidationResult,
        command: str = "migrate",
    ) -> None:
        """Delegate to :func:`core.sql_validator._checksum_validator.check_repeatable_migrations`."""
        from core.sql_validator._checksum_validator import check_repeatable_migrations as _impl

        _impl(self, scripts, applied_migrations, result, command)

    def _validate_sql_syntax(
        self, scripts: List[Migration], result: ValidationResult, issues: List[str]
    ) -> None:
        """Delegate to :func:`core.sql_validator._sql_syntax_validator.validate_sql_syntax`."""
        from core.sql_validator._sql_syntax_validator import validate_sql_syntax as _impl

        _impl(self, scripts, result, issues)

    def _validate_strict_mode_rules(
        self,
        scripts: List[Migration],
        applied_migrations: List[Migration],
        result: ValidationResult,
        issues: List[str],
    ) -> bool:
        """Delegate to :func:`core.sql_validator._strict_mode_validator.validate_strict_mode_rules`."""
        from core.sql_validator._strict_mode_validator import validate_strict_mode_rules as _impl

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

        # Check if this is a versioned migration
        if migration.type != MigrationType.SQL or not migration.version:
            return False

        # Get all migrations with higher version numbers
        higher_version_migrations = [
            m
            for m in executed_migrations
            if getattr(m, "success", False)
            and getattr(m, "version", None)
            and self.script_manager.compare_versions(
                str(getattr(m, "version", "")), str(migration.version)
            )
            > 0
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
                f"DELETE FROM {self.history_manager.schema}.{self.history_manager.history_table} WHERE type = 'DELETE' AND script_name IN ({', '.join([repr(s['script']) for s in reappeared_scripts])});"
            )
            issues.append(error_message)
            issues.append(repair_message)
            result.error_message = f"{error_message}\n{repair_message}"
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
            if getattr(m, "type", None) == "REPEATABLE":
                scheduled = any(
                    rep["script"] == getattr(m, "script_name", None)
                    and rep["old_checksum"] == getattr(m, "checksum", None)
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
            self.log.debug(
                f"Failed migration: {getattr(m, 'script_name', None)} (version: {getattr(m, 'version', 'unknown')})"
            )
        result.success = False
