"""
Migrate command implementation.
"""

from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Union, cast

from dblift.config import DbliftConfig
from dblift.db.provider_interfaces import TransactionalProvider

if TYPE_CHECKING:
    from dblift.core.migration.journals.migration_journal import MigrationJournal
    from dblift.core.migration.placeholders.placeholder_service import PlaceholderService

from dblift.core.constants import DEFAULT_MIGRATION_LOCK_TIMEOUT_SECONDS
from dblift.core.logger import Log
from dblift.core.logger.results import MigrateResult, MigrationInfo, MigrationSqlInfo
from dblift.core.migration._type_match import migration_type_name
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.executor.migration_helpers import MigrationHelpers
from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
from dblift.core.migration.migration import (
    VERSIONED_SCRIPT_TYPES,
    AppliedMigration,
    Migration,
    MigrationType,
)
from dblift.core.migration.rules.migration_rules import MigrationRules
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.sql.lint import SAFE, lint_pending_scripts
from dblift.core.migration.sql.script_analysis import dialect_of
from dblift.core.migration.state.migration_state_manager import (
    MigrationStateManager,
    StrictModeError,
)
from dblift.core.migration.state.rank_wins import installed_rank, latest_successful_ranks
from dblift.core.migration.ui.migration_ui import MigrationUI
from dblift.core.migration.ui.progress import migration_progress
from dblift.core.migration.version_utils import compare_versions, is_migration_success
from dblift.core.sql_validator.migration_validator import MigrationValidator
from dblift.db.base_provider import BaseProvider

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
                return result

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
        return result

    def _filter_already_applied(
        self,
        pending: List[Migration],
        applied: List[AppliedMigration],
    ) -> List[Migration]:
        """Drop migrations already present in successful history rows.

        Versioned migrations are uniquely keyed on ``(version, type)``; that
        pair must be unique across history rows for installed_rank ordering
        to work. Repeatables are content-checksum based, keyed on
        script_name: a repeatable is only dropped if a successful history
        row for the same script now has a matching checksum, since a
        concurrent process may have applied it (with unchanged content)
        while this process was waiting for the lock.
        """
        ranks = latest_successful_ranks(applied)

        successful_keys = set()
        for rec in applied:
            if rec.version is None or not is_migration_success(rec.success):
                continue
            rec_type = migration_type_name(rec.type)
            if rec_type not in VERSIONED_SCRIPT_TYPES:
                continue
            state = ranks.get(str(rec.version))
            undo_rank = state.undo if state is not None else 0
            if installed_rank(rec) <= undo_rank:
                continue
            successful_keys.add((str(rec.version), rec_type))

        latest_repeatable_by_script: Dict[str, AppliedMigration] = {}
        for rec in applied:
            if not rec.success or migration_type_name(rec.type) != MigrationType.REPEATABLE.value:
                continue
            script = str(rec.script_name)
            current = latest_repeatable_by_script.get(script)
            if current is None or int(rec.installed_rank or 0) > int(current.installed_rank or 0):
                latest_repeatable_by_script[script] = rec

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
            if type_value == MigrationType.REPEATABLE.value:
                applied_rec = latest_repeatable_by_script.get(migration.script_name)
                current_checksum = getattr(migration, "checksum", None)
                # Only skip when both sides have a known, matching checksum —
                # a missing checksum on either side (None) must never count as
                # a match, or a repeatable that was never actually verified
                # against this content would be silently skipped.
                if (
                    applied_rec is not None
                    and applied_rec.checksum is not None
                    and applied_rec.checksum == current_checksum
                ):
                    self.log.info(
                        f"Skipping {migration.script_name} — applied by " "concurrent process"
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
        with migration_progress(self.log, len(pending_migrations)) as progress:
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
                progress.describe(f"{migration.script_name}")
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
                progress.advance()

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
        applied_migrations_after = migration_state_after.applied_objects
        updated_version = self.state_manager.get_current_version(applied_migrations_after)
        if updated_version:
            result.current_schema_version = updated_version

    def _enforce_strict_ordering(
        self,
        migrations: List[Migration],
        current_version: Optional[str],
        strict_mode: bool,
    ) -> None:
        """Raise or warn when executable pending is out of version order."""
        if not current_version:
            return
        for migration in migrations:
            version = getattr(migration, "version", None)
            if not version:
                continue
            if compare_versions(str(version), str(current_version)) <= 0:
                script_name = getattr(migration, "script_name", "")
                if strict_mode:
                    raise StrictModeError(
                        f"Strict mode: out-of-order migration {script_name} "
                        f"(version {version} <= current version {current_version}). "
                        f"Renumber the script above {current_version} or run "
                        f"without --strict to apply it anyway."
                    )
                self.log.warning(
                    f"Out-of-order migration {script_name} "
                    f"(version {version} <= current version {current_version}). "
                    f"Applying anyway; use --strict to enforce strict ordering."
                )

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
            migration_state = self.state_manager.build_state(
                scripts_dir,
                recursive=use_recursive,
                additional_dirs=use_additional_dirs,
                dir_recursive_map=dir_recursive_map,
                target_version=target_version,
                read_snapshot=read_snapshot,
            )

            # Store current schema version in result for HTML reports
            applied_migrations = migration_state.applied_objects
            current_version = self.state_manager.get_current_version(applied_migrations)
            if current_version:
                result.current_schema_version = current_version

            pending_migrations = migration_state.executable_pending_objects()
            pending_migrations = self.state_manager.apply_filters_to_migrations(
                pending_migrations,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )
            try:
                self._enforce_strict_ordering(pending_migrations, current_version, strict_mode)
            except StrictModeError as e:
                # A specific subclass of ``ValueError``: it keeps its bare
                # message, while any other error in the body gets the
                # "Migration operation failed:" prefix (PR #241 Bugbot).
                self.log.error(str(e))
                result.set_error(str(e))
                return

            if not dry_run and not mark_as_executed and not self._capture_objects:
                if pending_migrations:
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
                        getattr(m.type, "value", m.type) in VERSIONED_SCRIPT_TYPES
                        for m in pending_migrations
                    ):
                        events.extend(("beforeVersioned", "afterVersioned"))
                    if any(m.type == MigrationType.REPEATABLE for m in pending_migrations):
                        events.extend(("beforeRepeatable", "afterRepeatable"))
                    callbacks = self._callbacks_for(events)
                    self._preflight_execution_sql(pending_migrations + callbacks)
                self._run_preflight(result, ensure_history=True, ensure_schema=True)

            if getattr(self, "validator", None) is None:
                validation_success, validation_errors, validation_time = True, None, 0.0
            else:
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
                    resolved_migrations=migration_state.resolved_objects,
                    applied_migrations=migration_state.all_applied_objects,
                    read_snapshot=read_snapshot,
                )
                validation_success, validation_errors, validation_time = (
                    self.migration_helpers.validate_migrations_for_migrate(
                        self.validator,
                        validation_snapshot,
                    )
                )
            if not validation_success:
                result.set_error(f"Validation failed: {validation_errors}")
                result.complete()
                return

            if not pending_migrations:
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

            if mark_as_executed:
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
                # Acquire migration lock before executing migrations
                lock = ExitStack()
                try:
                    if not lock.enter_context(self._migration_lock()):
                        self.log.error(MIGRATION_LOCK_REFUSAL)
                        result.set_error(MIGRATION_LOCK_REFUSAL)
                        result.complete()
                        return

                    # Re-read history after lock acquisition. Another
                    # process may have applied versioned migrations while we
                    # were waiting; running them again would fail and write
                    # duplicate failure rows into the history table.
                    applied_after_lock = self.state_manager.get_applied_migration_records()
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
                        self.log.error(f"Exception during migration execution: {e}")
                        result.set_error(f"Migration execution failed: {e}")
                    # Execute afterMigrateError callbacks on exception
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
