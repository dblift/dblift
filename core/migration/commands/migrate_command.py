"""
Migrate command implementation.
"""

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union

from config import DbliftConfig

if TYPE_CHECKING:
    from core.migration.journals.migration_journal import MigrationJournal
    from core.migration.placeholders.placeholder_service import PlaceholderService

from core.constants import SECONDS_TO_MILLISECONDS
from core.logger import Log
from core.logger.results import MigrateResult, MigrationInfo, MigrationSqlInfo
from core.migration._type_match import migration_type_name
from core.migration.executor.execution_engine import ExecutionEngine
from core.migration.executor.migration_helpers import MigrationHelpers
from core.migration.history.migration_history_manager import MigrationHistoryManager
from core.migration.migration import (
    VERSIONED_SCRIPT_TYPES,
    AppliedMigration,
    Migration,
    MigrationType,
)
from core.migration.rules.migration_rules import MigrationRules
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.state.migration_state_manager import (
    MigrationStateManager,
    StrictModeError,
)
from core.migration.ui.migration_ui import MigrationUI
from core.sql_validator.migration_validator import MigrationValidator
from db.base_provider import BaseProvider

from ._script_events import emit_script_event as _emit_script_event
from .base_command import BaseCommand, BaseCommandContext


class MigrateCommand(BaseCommand):
    """Handles the 'migrate' command execution."""

    def __init__(
        self,
        ctx_or_config: Optional[Union[BaseCommandContext, DbliftConfig]] = None,
        log: Optional[Log] = None,
        provider: Optional[BaseProvider] = None,
        script_manager: Optional[MigrationScriptManager] = None,
        history_manager: Optional[MigrationHistoryManager] = None,
        validator: Optional[MigrationValidator] = None,
        execution_engine: Optional[ExecutionEngine] = None,
        migration_helpers: Optional[MigrationHelpers] = None,
        state_manager: Optional[MigrationStateManager] = None,
        migration_ui: Optional[MigrationUI] = None,
        migration_rules: Optional[MigrationRules] = None,
        journal: Optional["MigrationJournal"] = None,
        placeholder_service: Optional["PlaceholderService"] = None,
        config: Optional[DbliftConfig] = None,
    ):
        """Initialize migrate command.

        Args:
            ctx_or_config: A :class:`~.base_command.BaseCommandContext` (preferred)
                or the application config (legacy).
            (remaining args are legacy; ignored when ctx provided)
        """
        super().__init__(
            ctx_or_config,
            log=log,
            provider=provider,
            script_manager=script_manager,
            history_manager=history_manager,
            validator=validator,
            execution_engine=execution_engine,
            migration_helpers=migration_helpers,
            state_manager=state_manager,
            migration_ui=migration_ui,
            migration_rules=migration_rules,
            journal=journal,
            placeholder_service=placeholder_service,
            config=config,
        )

    def _initialize_migration_execution(
        self,
        result: MigrateResult,
        scripts_dir: Path,
        target_version: Optional[str],
        dry_run: bool,
        tags: Optional[str],
        exclude_tags: Optional[str],
        versions: Optional[str],
        exclude_versions: Optional[str],
        mark_as_executed: bool,
        show_sql: bool,
        placeholders: Optional[Dict[str, Any]],
        recursive: Optional[bool],
        additional_dirs: Optional[List[Path]],
    ) -> tuple[bool, bool, Optional[List[Path]]]:
        """Initialize migration execution and resolve migration parameters.

        Returns:
            Tuple of (validation_success, use_recursive, use_additional_dirs)
        """
        # Canonical preflight (ADR-0011): connect → ensure history (skipped
        # in dry-run to preserve byte-identical DB) → populate.
        self._run_preflight(result, ensure_history=True, dry_run=dry_run)

        # Log command execution with filters and connection info
        self._log_command_header_update(
            "migrate",
            target_version=target_version,
            dry_run=dry_run,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
            mark_as_executed=mark_as_executed,
            show_sql=show_sql,
        )

        # Display current schema version (for debug logs)
        self._log_current_schema_version()

        # Setup migration parameters
        use_recursive, use_additional_dirs = self.migration_helpers.setup_migration_parameters(
            placeholders, recursive, additional_dirs, self.placeholder_service
        )

        return True, use_recursive, use_additional_dirs

    def _collect_visible_sql(self, migrations: List[Migration], result: MigrateResult) -> None:
        """Populate SQL visibility data for migration scripts."""
        for migration in migrations:
            statements = self.execution_engine.get_executable_sql_statements(migration, result)
            if result.error_message:
                return
            result.add_sql_migration(
                MigrationSqlInfo(
                    script=migration.script_name,
                    version=migration.version,
                    description=migration.description,
                    statements=statements,
                )
            )

    def _handle_dry_run(
        self,
        pending_migrations: List[Migration],
        result: MigrateResult,
        show_sql: bool = False,
    ) -> MigrateResult:
        """Handle dry run mode - log migrations without executing them."""
        result.show_sql = show_sql
        if show_sql:
            self._collect_visible_sql(pending_migrations, result)
            if result.error_message:
                self._log_command_completion("migrate", result)
                return result

        self.log.info("DRY RUN: Would execute the following migrations:")
        for migration in pending_migrations:
            self.log.info(f"  - {migration.script_name}")
        result.dry_run_count = len(pending_migrations)
        # Note: Callbacks are NOT executed in dry-run mode
        self._log_command_completion("migrate", result)
        return result

    def _filter_already_applied(
        self,
        pending: List[Migration],
        applied: List[AppliedMigration],
    ) -> List[Migration]:
        """Drop versioned migrations already present in successful history rows.

        Versioned migrations are uniquely keyed on ``(version, type)``; that
        pair must be unique across history rows for installed_rank ordering
        to work. Repeatables are content-checksum based and re-evaluated each
        run, so they are never filtered here.
        """
        latest_undo_rank_by_version: Dict[str, int] = {}
        for rec in applied:
            if not rec.success or rec.version is None:
                continue
            if migration_type_name(rec.type) == MigrationType.UNDO_SQL.value:
                version = str(rec.version)
                latest_undo_rank_by_version[version] = max(
                    latest_undo_rank_by_version.get(version, 0),
                    int(rec.installed_rank or 0),
                )

        successful_keys = set()
        for rec in applied:
            if not rec.success or rec.version is None:
                continue
            rec_type = migration_type_name(rec.type)
            if rec_type not in VERSIONED_SCRIPT_TYPES:
                continue
            if int(rec.installed_rank or 0) <= latest_undo_rank_by_version.get(str(rec.version), 0):
                continue
            successful_keys.add((str(rec.version), rec_type))

        filtered: List[Migration] = []
        for migration in pending:
            type_value = migration_type_name(migration.type)
            if (
                type_value in VERSIONED_SCRIPT_TYPES
                and (str(migration.version), type_value) in successful_keys
            ):
                self.log.info(
                    f"Skipping {migration.script_name} (version: "
                    f"{migration.version}) — applied by concurrent process"
                )
                continue
            filtered.append(migration)
        return filtered

    def _mark_migrations_as_executed(
        self, pending_migrations: List[Migration], result: MigrateResult
    ) -> bool:
        """Mark migrations as executed without running them.

        Returns:
            True if all migrations were marked successfully, False otherwise
        """
        for migration in pending_migrations:
            try:
                self.history_manager.record_migration(migration, success=True, execution_time=0)

                # Add migration info to result
                migration_info = MigrationInfo(
                    script=migration.script_name,
                    version=migration.version,
                    description=migration.description,
                    type=migration.type.value if migration.type else "SQL",
                    status="SUCCESS",
                    execution_time=0,
                    checksum=migration.checksum,
                )
                result.add_migration(migration_info)

                self.log.info(f"Marked {migration.script_name} as executed")
            except Exception as e:
                self.log.error(f"Failed to mark {migration.script_name} as executed: {e}")
                result.set_error(f"Failed to mark migration as executed: {e}")
                return False
        return True

    def _execute_before_callbacks(
        self,
        scripts_dir: Path,
        versioned_migrations: List[Migration],
        repeatable_migrations: List[Migration],
        use_recursive: bool,
        use_additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
    ) -> None:
        """Execute all before-migration callbacks."""
        # Execute beforeMigrate callbacks
        self._execute_callbacks(
            scripts_dir,
            "beforeMigrate",
            use_recursive,
            use_additional_dirs,
            dir_recursive_map,
        )

        # Execute beforeVersioned callbacks if there are versioned migrations
        if versioned_migrations:
            self._execute_callbacks(
                scripts_dir, "beforeVersioned", use_recursive, use_additional_dirs
            )

        # Execute beforeRepeatable callbacks if there are repeatable migrations
        if repeatable_migrations:
            self._execute_callbacks(
                scripts_dir,
                "beforeRepeatable",
                use_recursive,
                use_additional_dirs,
                dir_recursive_map,
            )

    def _execute_after_callbacks(
        self,
        scripts_dir: Path,
        versioned_migrations: List[Migration],
        repeatable_migrations: List[Migration],
        use_recursive: bool,
        use_additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
        result: MigrateResult,
    ) -> None:
        """Execute all after-migration callbacks if migrations completed successfully."""
        if result.error_message:
            return

        # Execute afterVersioned callbacks if there were versioned migrations
        if versioned_migrations:
            self._execute_callbacks(
                scripts_dir, "afterVersioned", use_recursive, use_additional_dirs
            )

        # Execute afterRepeatable callbacks if there were repeatable migrations
        if repeatable_migrations:
            self._execute_callbacks(
                scripts_dir,
                "afterRepeatable",
                use_recursive,
                use_additional_dirs,
                dir_recursive_map,
            )

        # Execute afterMigrate callbacks after all migrations complete successfully
        self._execute_callbacks(
            scripts_dir,
            "afterMigrate",
            use_recursive,
            use_additional_dirs,
            dir_recursive_map,
        )

    def _handle_failed_migration(
        self,
        migration: Migration,
        start_time: float,
        exception: Exception,
        result: MigrateResult,
        scripts_dir: Path,
        use_recursive: bool,
        use_additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
    ) -> None:
        """Handle a failed migration - record error, journal, and history."""
        # Only log if error_message is not already set (execute_migration already logged it)
        if not result.error_message:
            self.log.error(f"Migration {migration.script_name} failed: {exception}")
            error_message = str(exception)
        else:
            # Error was already logged by execute_migration, just use the existing message
            error_message = result.error_message

        # End journal tracking for failed migration
        execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)
        if self.journal:
            self.journal.end_migration(
                migration.script_name,
                success=False,
                error_message=error_message,
                execution_time=execution_time,
            )

        # Note: ExecutionEngine already records the failed migration in history
        # (with its own transaction), so we do NOT record it again here.

        # Only set error if not already set (execute_migration already set it)
        if not result.error_message:
            result.set_error(f"Migration failed: {error_message}")

        # Execute afterMigrateError callbacks when migration fails
        self._execute_callbacks(
            scripts_dir,
            "afterMigrateError",
            use_recursive,
            use_additional_dirs,
            dir_recursive_map,
        )

    def _execute_single_migration(
        self,
        migration: Migration,
        scripts_dir: Path,
        use_recursive: bool,
        use_additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
        result: MigrateResult,
    ) -> bool:
        """Execute a single migration.

        Returns:
            True if migration succeeded, False if it failed
        """
        try:
            # Execute beforeEach callbacks
            self._execute_callbacks(
                scripts_dir,
                "beforeEach",
                use_recursive,
                use_additional_dirs,
                dir_recursive_map,
            )
            self._execute_callbacks(
                scripts_dir,
                "beforeEachMigrate",
                use_recursive,
                use_additional_dirs,
                dir_recursive_map,
            )

            # Start journal tracking for this migration
            if self.journal:
                self.journal.start_migration(
                    migration.script_name,
                    details={
                        "version": migration.version,
                        "description": migration.description,
                        "type": migration.type.value if migration.type else "SQL",
                    },
                )

            start_time = time.time()
            _script_event_data = {
                "script": migration.script_name,
                "version": migration.version,
                "description": migration.description,
                "type": migration.type.value if migration.type else "SQL",
            }
            _emit_script_event("migration.script.started", _script_event_data)
            self.execution_engine.execute_migration(migration, result)
            execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)

            # Check if migration failed during execution
            if result.error_message:
                # Migration failed - ExecutionEngine.execute_migration() already:
                # 1. Set the error in result
                # 2. Added failed migration info to result
                # 3. Rolled back the transaction (transaction management is handled by ExecutionEngine)
                # We just need to end journal tracking and break
                if self.journal:
                    self.journal.end_migration(
                        migration.script_name,
                        success=False,
                        error_message=result.error_message,
                        execution_time=execution_time,
                    )
                _emit_script_event(
                    "migration.script.failed",
                    {
                        **_script_event_data,
                        "error": result.error_message,
                        "execution_time": execution_time,
                    },
                )
                # Execute afterMigrateError callbacks before breaking
                self._execute_callbacks(
                    scripts_dir,
                    "afterMigrateError",
                    use_recursive,
                    use_additional_dirs,
                )
                return False

            # End journal tracking for successful migration
            if self.journal:
                self.journal.end_migration(
                    migration.script_name,
                    success=True,
                    execution_time=execution_time,
                )

            # Migration history is recorded within the transaction by ExecutionEngine.execute_migration()
            # Transaction management (begin/commit/rollback) is handled by ExecutionEngine

            # Add migration info to result
            migration_info = MigrationInfo(
                script=migration.script_name,
                version=migration.version,
                description=migration.description,
                type=migration.type.value if migration.type else "SQL",
                status="SUCCESS",
                execution_time=execution_time,
                checksum=migration.checksum,
            )
            result.add_migration(migration_info)

            _emit_script_event(
                "migration.script.completed",
                {**_script_event_data, "execution_time": execution_time},
            )
            self.log.info(f"Successfully applied migration {migration.script_name}")

            # Execute afterEach callbacks after successful migration
            self._execute_callbacks(
                scripts_dir,
                "afterEachMigrate",
                use_recursive,
                use_additional_dirs,
                dir_recursive_map,
            )
            self._execute_callbacks(
                scripts_dir,
                "afterEach",
                use_recursive,
                use_additional_dirs,
                dir_recursive_map,
            )

            return True

        except Exception as e:
            self._handle_failed_migration(
                migration,
                start_time,
                e,
                result,
                scripts_dir,
                use_recursive,
                use_additional_dirs,
                dir_recursive_map,
            )
            return False

    def _execute_migration_loop(
        self,
        pending_migrations: List[Migration],
        scripts_dir: Path,
        use_recursive: bool,
        use_additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
        result: MigrateResult,
    ) -> None:
        """Execute the main migration loop."""
        from rich.progress import (
            BarColumn,
            MofNCompleteColumn,
            Progress,
            SpinnerColumn,
            TextColumn,
            TimeElapsedColumn,
        )

        from core.logger.console import get_stderr_console, is_progress_disabled

        self.log.debug(
            f"Starting execution loop for {len(pending_migrations)} pending migration(s)"
        )
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            MofNCompleteColumn(),
            TimeElapsedColumn(),
            console=get_stderr_console(),
            transient=True,
            disable=is_progress_disabled(),
        ) as progress:
            task = progress.add_task("Migrating", total=len(pending_migrations))
            for migration in pending_migrations:
                progress.update(task, description=f"{migration.script_name}")
                self.log.debug(
                    f"About to execute migration: {migration.script_name} (version: {migration.version})"
                )
                if result.show_sql:
                    self._collect_visible_sql([migration], result)
                    if result.error_message:
                        break
                success = self._execute_single_migration(
                    migration,
                    scripts_dir,
                    use_recursive,
                    use_additional_dirs,
                    dir_recursive_map,
                    result,
                )
                if not success:
                    # Failed migration must not bump MofNCompleteColumn —
                    # the bar would read "3/5 done" while only 2 actually
                    # completed. Stop without advancing.
                    break
                progress.advance(task)

    def _update_final_state(
        self,
        result: MigrateResult,
        scripts_dir: Path,
        use_recursive: bool,
        use_additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
    ) -> None:
        """Update final schema version after migrations are applied."""
        # Rebuild state to get accurate applied migrations after migration
        migration_state_after = self.state_manager.build_state(
            scripts_dir,
            recursive=use_recursive,
            additional_dirs=use_additional_dirs,
            dir_recursive_map=dir_recursive_map,
            target_version=None,
            tags=None,
            exclude_tags=None,
            versions=None,
            exclude_versions=None,
        )
        applied_migrations_after = migration_state_after.applied_objects
        updated_version = self.state_manager.get_current_version(applied_migrations_after)
        if updated_version:
            result.current_schema_version = updated_version

    def execute(
        self,
        scripts_dir: Path,
        dry_run: bool = False,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        mark_as_executed: bool = False,
        placeholders: Optional[Dict[str, Any]] = None,
        recursive: Optional[bool] = None,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        show_sql: bool = False,
    ) -> MigrateResult:
        """Execute database migrations.

        This will automatically create the schema history table if it doesn't exist,
        without requiring a separate baseline command.
        """
        from core.seams.runtime_checks import run_checks

        run_checks("command.pre_migrate")
        result = MigrateResult()
        result.show_sql = show_sql
        result.target_schema = self.config.database.schema
        result.journal = self.journal
        if not getattr(self, "migration_helpers", None):
            self.migration_helpers = MigrationHelpers(self.config, self.log)

        try:
            # Initialize and validate migrations
            validation_success, use_recursive, use_additional_dirs = (
                self._initialize_migration_execution(
                    result,
                    scripts_dir,
                    target_version,
                    dry_run,
                    tags,
                    exclude_tags,
                    versions,
                    exclude_versions,
                    mark_as_executed,
                    show_sql,
                    placeholders,
                    recursive,
                    additional_dirs,
                )
            )
            if not validation_success:
                return result

            # Use MigrationStateManager to get centralized migration state.
            # Pass strict_mode so _is_versioned_pending raises immediately on
            # out-of-order migrations instead of emitting a misleading
            # "Applying anyway; use --strict" warning.
            strict_mode = bool(getattr(self.config, "strict_mode", False))
            migration_state = self.state_manager.build_state(
                scripts_dir,
                recursive=use_recursive,
                additional_dirs=use_additional_dirs,
                dir_recursive_map=dir_recursive_map,
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                strict_mode=strict_mode,
            )

            # Store current schema version in result for HTML reports
            applied_migrations = migration_state.applied_objects
            current_version = self.state_manager.get_current_version(applied_migrations)
            if current_version:
                result.current_schema_version = current_version

            pending_migrations = migration_state.pending_objects

            if getattr(self, "validator", None) is None:
                validation_success, validation_errors, validation_time = True, None, 0.0
            else:
                validation_success, validation_errors, validation_time = (
                    self.migration_helpers.validate_migrations_for_migrate(
                        self.validator,
                        scripts_dir,
                        use_recursive,
                        use_additional_dirs or [],
                        target_version=target_version,
                        tags=tags,
                        exclude_tags=exclude_tags,
                        versions=versions,
                        exclude_versions=exclude_versions,
                    )
                )
            if not validation_success:
                result.set_error(f"Validation failed: {validation_errors}")
                result.complete()
                return result

            if not pending_migrations:
                self.log.info("No pending migrations found")
                self._log_command_completion("migrate", result)
                return result

            self.log.info(f"Found {len(pending_migrations)} pending migration(s)")
            for pending_migration in pending_migrations:
                self.log.debug(
                    f"  - Pending migration: {pending_migration.script_name} (version: {pending_migration.version}, type: {pending_migration.type})"
                )

            if dry_run:
                return self._handle_dry_run(pending_migrations, result, show_sql=show_sql)

            if mark_as_executed:
                if not self._mark_migrations_as_executed(pending_migrations, result):
                    self._log_command_completion("migrate", result)
                    return result
                try:
                    self.provider.commit_transaction()
                except Exception as commit_error:
                    self.log.error(
                        f"Failed to commit mark-as-executed history records: {commit_error}"
                    )
                    result.set_error(
                        f"Failed to commit mark-as-executed history records: {commit_error}"
                    )
                    result.complete()
                    self._log_command_completion("migrate", result)
                    return result
            else:
                # Acquire migration lock before executing migrations
                lock_acquired = False
                try:
                    if not self.provider.acquire_migration_lock(
                        self.config.database.schema, wait_timeout_seconds=60
                    ):
                        result.set_error(
                            "Could not acquire migration lock - another migration may be running"
                        )
                        result.complete()
                        return result

                    lock_acquired = True
                    self.log.info("Migration lock acquired successfully")

                    # BUG-01: re-read history after lock acquisition. Another
                    # process may have applied versioned migrations while we
                    # were waiting; running them again would fail and write
                    # duplicate failure rows into the history table.
                    applied_after_lock = self.history_manager.get_applied_migration_records()
                    filtered_pending = self._filter_already_applied(
                        pending_migrations, applied_after_lock
                    )
                    skipped_after_lock = len(pending_migrations) - len(filtered_pending)
                    if skipped_after_lock > 0:
                        self.log.info(
                            f"{skipped_after_lock} pending migration(s) "
                            "applied by another process while waiting for the "
                            "lock; skipping"
                        )
                    pending_migrations = filtered_pending

                    if not pending_migrations:
                        self.log.info(
                            "All pending migrations were applied by another "
                            "process while waiting for the lock"
                        )
                    else:
                        # Separate versioned and repeatable migrations for targeted callbacks
                        versioned_migrations = [
                            m
                            for m in pending_migrations
                            if getattr(m.type, "value", m.type) in VERSIONED_SCRIPT_TYPES
                        ]
                        repeatable_migrations = [
                            m for m in pending_migrations if m.type == MigrationType.REPEATABLE
                        ]

                        # Execute before-migration callbacks
                        self._execute_before_callbacks(
                            scripts_dir,
                            versioned_migrations,
                            repeatable_migrations,
                            use_recursive,
                            use_additional_dirs,
                            dir_recursive_map,
                        )

                        # Execute migrations normally
                        self._execute_migration_loop(
                            pending_migrations,
                            scripts_dir,
                            use_recursive,
                            use_additional_dirs,
                            dir_recursive_map,
                            result,
                        )

                        # Execute after-migration callbacks if all migrations succeeded
                        self._execute_after_callbacks(
                            scripts_dir,
                            versioned_migrations,
                            repeatable_migrations,
                            use_recursive,
                            use_additional_dirs,
                            dir_recursive_map,
                            result,
                        )

                except Exception as e:
                    # Handle any exception during lock acquisition or migration execution
                    # Only log if error_message is not already set (migration execution already logged it)
                    if not result.error_message:
                        self.log.error(f"Exception during migration execution: {e}")
                        result.set_error(f"Migration execution failed: {e}")
                    # Execute afterMigrateError callbacks on exception
                    self._execute_callbacks(
                        scripts_dir,
                        "afterMigrateError",
                        use_recursive,
                        use_additional_dirs,
                        dir_recursive_map,
                    )
                finally:
                    # Always release the migration lock if it was acquired
                    if lock_acquired:
                        try:
                            self.provider.release_migration_lock(self.config.database.schema)
                            self.log.debug("Migration lock released successfully")
                        except Exception as release_e:
                            self.log.warning(f"Could not release migration lock: {release_e}")

            # Update final schema version
            self._update_final_state(
                result, scripts_dir, use_recursive, use_additional_dirs, dir_recursive_map
            )

            self._log_command_completion("migrate", result)
            return result

        except StrictModeError as e:
            # Strict-mode out-of-order violations raised by
            # ``_is_versioned_pending``. Specific subclass of
            # ``ValueError`` so unrelated ``ValueError``s elsewhere in
            # the try block (validation, lock acquisition, state
            # updates) still fall through to the broader handler with
            # the "Migration operation failed:" prefix (PR #241 Bugbot).
            self.log.error(str(e))
            result.set_error(str(e))
            self._log_command_completion("migrate", result)
            return result
        except Exception as e:
            self.log.error(f"Migration operation failed: {e}")
            result.set_error(f"Migration operation failed: {e}")
            self._log_command_completion("migrate", result)
            return result
