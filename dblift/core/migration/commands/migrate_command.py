"""
Migrate command implementation.
"""

from contextlib import ExitStack, nullcontext
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Tuple, Union, cast

from dblift.config import DbliftConfig
from dblift.db.provider_interfaces import TransactionalProvider

if TYPE_CHECKING:
    from dblift.core.migration.journals.migration_journal import MigrationJournal
    from dblift.core.migration.placeholders.placeholder_service import PlaceholderService

from dblift.core.constants import DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
from dblift.core.logger import Log
from dblift.core.logger.results import MigrateResult, MigrationInfo, MigrationSqlInfo
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.executor.migration_helpers import MigrationHelpers
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration, MigrationType
from dblift.core.migration.presentation import presentation_for
from dblift.core.migration.rules.migration_rules import MigrationRules
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.sql.lint import SAFE, lint_pending_scripts
from dblift.core.migration.sql.script_analysis import dialect_of
from dblift.core.migration.state.migrate_plan import StrictModeError
from dblift.core.migration.state.migration_state import MigrationReadSnapshot, MigrationState
from dblift.core.migration.state.migration_state_manager import MigrationStateManager
from dblift.core.migration.ui.migration_ui import MigrationUI
from dblift.core.migration.ui.progress import NullProgress
from dblift.core.migration.version_utils import compare_versions
from dblift.core.sql_validator.migration_validator import MigrationValidator
from dblift.db.base_provider import BaseProvider
from dblift.db.error import redact_driver_error_text

from ._script_runner import ScriptRunner, ScriptRunPolicy
from .base_command import MIGRATION_LOCK_REFUSAL, BaseCommand, BaseCommandContext

MIGRATE_POLICY = ScriptRunPolicy(
    before_events=("beforeEach", "beforeEachMigrate"),
    after_events=("afterEachMigrate", "afterEach"),
    error_event="afterMigrateError",
    failure_prefix="Migration failed",
)


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

    def _collect_visible_sql(
        self, migrations: List[Migration], result: MigrateResult, record: bool = True
    ) -> None:
        """Populate SQL visibility data for migration scripts.

        With ``record=False`` the statements are only prepared, so a script the real run
        refuses sets the error without its SQL being added to the result.
        """
        for migration in migrations:
            statements = self.execution_engine.get_executable_sql_statements(migration, result)
            if result.error_message:
                return
            if not record:
                continue
            result.add_sql_migration(
                MigrationSqlInfo(
                    script=migration.script_name,
                    version=migration.version,
                    description=migration.description,
                    statements=statements,
                    annotations=self.execution_engine.annotate_sql_statements(statements),
                )
            )

    def _handle_dry_run(
        self,
        pending_migrations: List[Migration],
        result: MigrateResult,
        show_sql: bool = False,
    ) -> None:
        """Handle dry run mode - log migrations without executing them."""
        result.show_sql = show_sql
        # Prepared even without --show-sql: the real run refuses a script at this step.
        self._collect_visible_sql(pending_migrations, result, record=show_sql)
        if result.error_message:
            return

        dialect = dialect_of(self.config)
        analysed = (
            lint_pending_scripts(
                pending_migrations,
                dialect,
                self.log,
                enabled=self._capture_objects,
            )
            if dialect
            else {}
        )

        self.log.info("DRY RUN: Would execute the following migrations:")
        for migration in pending_migrations:
            analysis = analysed.get(migration.script_name)
            verdict = f" [{analysis['verdict']}]" if analysis and "verdict" in analysis else ""
            self.log.info(f"  - {migration.script_name}{verdict}")
            for finding in (analysis or {}).get("findings", []):
                if not finding["allowed"]:
                    # dedupe=False: the same finding can recur in another script.
                    self.log.warning(
                        f"      {finding['severity']} {finding['code']}, "
                        f"statement {finding['statement'] + 1}: {finding['message']}",
                        dedupe=False,
                    )
            # Appended directly (not via `result.add_migration`): that method
            # flips `result.success` to False for any non-SUCCESS status,
            # which would wrongly mark a clean dry run as failed.
            result.migrations.append(
                MigrationInfo(
                    script=migration.script_name,
                    version=migration.version,
                    description=migration.description,
                    type=migration.type.value if migration.type else "SQL",
                    status="PENDING",
                    checksum=migration.checksum,
                    analysis=analysis,
                )
            )
        if any(a.get("verdict", SAFE) != SAFE for a in analysed.values()):
            self.log.info("Run `dblift validate-sql` to see the statement behind each finding.")
        result.dry_run_count = len(pending_migrations)
        # Note: Callbacks are NOT executed in dry-run mode

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
        versioned_migrations: List[Migration],
        repeatable_migrations: List[Migration],
    ) -> None:
        """Execute all before-migration callbacks."""
        # Execute beforeMigrate callbacks
        self._fire("beforeMigrate")

        # Execute beforeVersioned callbacks if there are versioned migrations
        if versioned_migrations:
            self._fire("beforeVersioned")

        # Execute beforeRepeatable callbacks if there are repeatable migrations
        if repeatable_migrations:
            self._fire("beforeRepeatable")

    def _execute_after_callbacks(
        self,
        versioned_migrations: List[Migration],
        repeatable_migrations: List[Migration],
        result: MigrateResult,
    ) -> None:
        """Execute all after-migration callbacks if migrations completed successfully."""
        if result.error_message:
            return

        # Execute afterVersioned callbacks if there were versioned migrations
        if versioned_migrations:
            self._fire("afterVersioned")

        # Execute afterRepeatable callbacks if there were repeatable migrations
        if repeatable_migrations:
            self._fire("afterRepeatable")

        # Execute afterMigrate callbacks after all migrations complete successfully
        self._fire("afterMigrate")

    def _record_applied(
        self, migration: Migration, result: MigrateResult, execution_time: int
    ) -> None:
        """Add the applied migration to the result and log it."""
        result.add_migration(
            MigrationInfo(
                script=migration.script_name,
                version=migration.version,
                description=migration.description,
                type=migration.type.value if migration.type else "SQL",
                status="SUCCESS",
                execution_time=execution_time,
                checksum=migration.checksum,
            )
        )
        self.log.info(f"Successfully applied migration {migration.script_name}")

    def _execute_migration_loop(
        self, pending_migrations: List[Migration], result: MigrateResult
    ) -> None:
        """Execute the main migration loop."""
        self.log.debug(
            f"Starting execution loop for {len(pending_migrations)} pending migration(s)"
        )
        runner = ScriptRunner(self, MIGRATE_POLICY)
        presenter = presentation_for(self.execution_engine, self.log)
        progress = (
            presenter.migration_loop(self.log, len(pending_migrations))
            if presenter is not None
            else nullcontext(NullProgress())
        )
        with progress as sink:
            for migration in pending_migrations:
                if self._migration_lock_lost():
                    # Another migrate may already be running; the migration in
                    # flight could not be interrupted safely, the next must not start.
                    message = (
                        "The migration lock was lost (taken over by another process or "
                        f"not renewable); stopping before {migration.script_name}"
                    )
                    self.log.error(message)
                    result.set_error(message)
                    break
                sink.describe(migration.script_name)
                self.log.debug(
                    f"About to execute migration: {migration.script_name} (version: {migration.version})"
                )
                if result.show_sql:
                    self._collect_visible_sql([migration], result)
                    if result.error_message:
                        break
                success = runner.run(
                    migration,
                    result,
                    event_data={
                        "script": migration.script_name,
                        "version": migration.version,
                        "description": migration.description,
                        "type": migration.type.value if migration.type else "SQL",
                    },
                    on_success=partial(self._record_applied, migration, result),
                )
                if not success:
                    # Failed migration must not bump MofNCompleteColumn —
                    # the bar would read "3/5 done" while only 2 actually
                    # completed. Stop without advancing.
                    break
                sink.advance()

    def _update_final_state(self, result: MigrateResult) -> None:
        """Update final schema version after migrations are applied."""
        # Rebuild state to get accurate applied migrations after migration.
        # scripts_dir=None so build_state skips pending-migration computation
        # (only applied_objects is needed here) — this run's tag/version
        # exclusion filters aren't available at this point, so recomputing
        # pending here would misreport excluded, never-applied scripts as
        # out-of-order.
        binding = self._bound_callbacks()
        migration_state_after = self.state_manager.build_state(
            None,
            recursive=binding.recursive,
            additional_dirs=binding.additional_dirs,
            dir_recursive_map=binding.dir_recursive_map,
            target_version=None,
            tags=None,
            exclude_tags=None,
            versions=None,
            exclude_versions=None,
        )
        result.current_schema_version = migration_state_after.current_version

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
        show_query_results: bool = False,
    ) -> MigrateResult:
        """Execute database migrations.

        This will automatically create the schema history table if it doesn't exist,
        without requiring a separate baseline command.
        """
        from dblift.core.seams.runtime_checks import run_checks

        if not dry_run and not mark_as_executed:
            self._prepare_required_analysis()

        # A dry run applies nothing, so the pre-migrate checks that gate
        # applying a migration do not run for it — the same reason the
        # per-statement migration.pre_execution checks never fire in dry-run.
        # Dry-run has its own point, so an add-on can register a check that
        # runs only before a preview.
        if not dry_run:
            run_checks("command.pre_migrate")
        else:
            run_checks("command.pre_migrate_dry_run")
        self._reset_callback_catalog()
        result = MigrateResult()
        result.show_sql = show_sql
        result.show_query_results = show_query_results
        result.target_schema = self.config.database.schema
        result.journal = self.journal
        if not getattr(self, "migration_helpers", None):
            self.migration_helpers = MigrationHelpers(self.config, self.log)

        read_snapshot = self.state_manager.new_read_snapshot()

        # Connect before reading state. Execution mode delays history creation
        # until selected SQL is classified; dry-run leaves the database untouched.
        defer_history = not dry_run and not mark_as_executed and not self._capture_objects
        restore_busy_timeout = None

        def preflight() -> None:
            nonlocal restore_busy_timeout
            # SQLite only: widen busy_timeout for this command; the provider
            # returns what undoes it (None when nothing was changed). This
            # opens the connection, so connect through the preflight first:
            # a database that cannot be opened then fails as a preflight
            # connection error rather than a raw driver error.
            widen_busy_timeout = getattr(self.provider, "widen_busy_timeout", None)
            if callable(widen_busy_timeout):
                self._preflight_connect(result)
                restore_busy_timeout = widen_busy_timeout(DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS)
            self._run_preflight(
                result, ensure_history=not defer_history, dry_run=dry_run, ensure_schema=True
            )

        def body() -> None:
            use_recursive, use_additional_dirs = self.migration_helpers.setup_migration_parameters(
                placeholders, recursive, additional_dirs, self.placeholder_service
            )
            self._bind_callbacks(
                scripts_dir, use_recursive, use_additional_dirs, dir_recursive_map, result
            )

            # Catalog is unfiltered; migrate selects Pending then tags/versions.
            # target_version is label context only (Above target), not an omit filter.
            strict_mode = bool(getattr(self.config, "strict_mode", False))

            plan_migrate = partial(
                self.state_manager.plan_migrate,
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

            try:
                plan = plan_migrate(read_snapshot=read_snapshot)
            except StrictModeError as e:
                # A specific subclass of ``ValueError``: it keeps its bare
                # message, while any other error in the body gets the
                # "Migration operation failed:" prefix (PR #241 Bugbot).
                if e.current_version:
                    result.current_schema_version = e.current_version
                self.log.error(str(e))
                result.set_error(str(e))
                return
            migration_state = plan.state
            current_version = plan.current_version
            pending_migrations = list(plan.pending)

            # Store current schema version in result for HTML reports
            if current_version:
                result.current_schema_version = current_version

            def preflight_sql(migrations: List[Migration]) -> None:
                """Classify the SQL of ``migrations`` and of the callbacks they would fire."""
                events = [
                    "beforeMigrate",
                    "afterMigrate",
                    "afterMigrateError",
                    "beforeEach",
                    "afterEach",
                    "beforeEachMigrate",
                    "afterEachMigrate",
                ]
                if any(
                    getattr(m.type, "value", m.type) in VERSIONED_SCRIPT_TYPES for m in migrations
                ):
                    events.extend(("beforeVersioned", "afterVersioned"))
                if any(m.type == MigrationType.REPEATABLE for m in migrations):
                    events.extend(("beforeRepeatable", "afterRepeatable"))
                self._preflight_execution_sql(migrations + self._callbacks_for(events))

            if not dry_run and not mark_as_executed and not self._capture_objects:
                if pending_migrations:
                    preflight_sql(pending_migrations)
                self._run_preflight(result, ensure_history=True, ensure_schema=True)

            def validate(
                state: MigrationState, snapshot: MigrationReadSnapshot
            ) -> Tuple[bool, object]:
                """Validate ``state`` read through ``snapshot``; return (valid, errors)."""
                validation_snapshot = self.state_manager.build_validation_snapshot(
                    scripts_dir,
                    "migrate",
                    recursive=use_recursive,
                    additional_dirs=use_additional_dirs or [],
                    dir_recursive_map=dir_recursive_map,
                    target_version=target_version,
                    tags=tags,
                    exclude_tags=exclude_tags,
                    versions=versions,
                    exclude_versions=exclude_versions,
                    strict_mode=strict_mode,
                    resolved_migrations=state.resolved_objects,
                    applied_migrations=state.all_applied_objects,
                    read_snapshot=snapshot,
                )
                valid, errors, _ = self.migration_helpers.validate_migrations_for_migrate(
                    self.validator,
                    validation_snapshot,
                )
                return valid, errors

            validation_success, validation_errors = validate(migration_state, read_snapshot)
            if not validation_success:
                result.set_error(f"Validation failed: {validation_errors}")
                result.complete()
                return

            if not pending_migrations:
                if (
                    target_version is not None
                    and current_version
                    and compare_versions(current_version, target_version) >= 0
                ):
                    self.log.info(
                        f"No pending migrations found: the current version {current_version} "
                        f"is at or above the target version {target_version}, nothing to apply"
                    )
                else:
                    self.log.info("No pending migrations found")
                return

            self.log.info(f"Found {len(pending_migrations)} pending migration(s)")
            for pending_migration in pending_migrations:
                self.log.debug(
                    f"  - Pending migration: {pending_migration.script_name} (version: {pending_migration.version}, type: {pending_migration.type})"
                )

            if dry_run:
                self._handle_dry_run(pending_migrations, result, show_sql=show_sql)
                return

            # Acquire the migration lock before changing anything
            lock = ExitStack()
            try:
                if not lock.enter_context(self._migration_lock()):
                    self.log.error(MIGRATION_LOCK_REFUSAL)
                    result.set_error(MIGRATION_LOCK_REFUSAL)
                    result.complete()
                    return

                # Plan again now that the lock is held: another process may have
                # applied (or undone) migrations while we were waiting, and
                # running a stale plan would fail and write duplicate failure
                # rows into the history table.
                locked_snapshot = self.state_manager.new_read_snapshot()
                try:
                    locked_plan = plan_migrate(read_snapshot=locked_snapshot)
                except StrictModeError as e:
                    # Nothing ran, so no error callbacks fire.
                    self.log.error(str(e))
                    result.set_error(str(e))
                    return
                locked_state = locked_plan.state
                locked_pending = list(locked_plan.pending)

                locked_success, locked_errors = validate(locked_state, locked_snapshot)
                if not locked_success:
                    # Nothing ran, so no error callbacks fire.
                    result.set_error(f"Validation failed: {locked_errors}")
                    result.complete()
                    return

                planned = {m.script_name for m in pending_migrations}
                newly_pending = [m for m in locked_pending if m.script_name not in planned]
                if newly_pending and not mark_as_executed and not self._capture_objects:
                    preflight_sql(newly_pending)

                still_pending = {m.script_name for m in locked_pending}
                skipped = [m for m in pending_migrations if m.script_name not in still_pending]
                for migration in skipped:
                    version = f" (version: {migration.version})" if migration.version else ""
                    self.log.info(
                        f"Skipping {migration.script_name}{version} — applied by concurrent process"
                    )
                if skipped:
                    self.log.info(
                        f"{len(skipped)} pending migration(s) "
                        "applied by another process while waiting for the "
                        "lock; skipping"
                    )
                pending_migrations = locked_pending

                if not pending_migrations:
                    self.log.info(
                        "All pending migrations were applied by another "
                        "process while waiting for the lock"
                    )
                elif mark_as_executed:
                    if not self._mark_migrations_as_executed(pending_migrations, result):
                        return
                    try:
                        if isinstance(self.provider, TransactionalProvider):
                            self.provider.commit_transaction()
                    except Exception as commit_error:
                        self.log.error(
                            f"Failed to commit mark-as-executed history records: {commit_error}"
                        )
                        result.set_error(
                            f"Failed to commit mark-as-executed history records: {commit_error}"
                        )
                        result.complete()
                        return
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
                    self._execute_before_callbacks(versioned_migrations, repeatable_migrations)

                    # Execute migrations normally
                    self._execute_migration_loop(pending_migrations, result)

                    # Execute after-migration callbacks if all migrations succeeded
                    self._execute_after_callbacks(
                        versioned_migrations, repeatable_migrations, result
                    )

            except Exception as e:
                # Handle any exception during lock acquisition or migration execution
                # Only log if error_message is not already set (migration execution already logged it)
                if not result.error_message:
                    reason = redact_driver_error_text(str(e))
                    self.log.error(f"Exception during migration execution: {reason}")
                    result.set_error(f"Migration execution failed: {reason}")
                # Execute afterMigrateError callbacks on exception
                if not mark_as_executed:
                    self._fire("afterMigrateError")
            finally:
                # Always release the migration lock if it was acquired
                lock.close()

            # Update final schema version
            self._update_final_state(result)

        try:
            return cast(
                MigrateResult,
                self._run_command_lifecycle(
                    "migrate",
                    result,
                    body,
                    preflight=preflight,
                    error_message_prefix="Migration operation failed",
                    header_kwargs={
                        "target_version": target_version,
                        "dry_run": dry_run,
                        "tags": tags,
                        "exclude_tags": exclude_tags,
                        "versions": versions,
                        "exclude_versions": exclude_versions,
                        "mark_as_executed": mark_as_executed,
                        "show_sql": show_sql,
                        "read_snapshot": read_snapshot,
                    },
                ),
            )
        finally:
            if callable(restore_busy_timeout):
                restore_busy_timeout()
