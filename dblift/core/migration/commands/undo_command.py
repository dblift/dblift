"""
Undo command implementation.
"""

from contextlib import ExitStack
from functools import partial
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, cast

if TYPE_CHECKING:
    pass

from dblift.core.logger.results import MigrationInfo, MigrationSqlInfo, UndoResult
from dblift.core.migration.formats.migration_format import MigrationFormat
from dblift.core.migration.migration import Migration

from ._script_runner import ScriptRunner, ScriptRunPolicy
from .base_command import MIGRATION_LOCK_REFUSAL, BaseCommand, PreflightConnectionError

UNDO_POLICY = ScriptRunPolicy(
    before_events=("beforeEach",),
    after_events=("afterEach",),
    error_event="afterUndoError",
    failure_prefix="Undo failed",
    completed_events=("migration.script.completed", "undo.script.rolled_back"),
)


class UndoCommand(BaseCommand):
    """Handles the 'undo' command execution."""

    def _add_visible_sql(self, undo_migration: Any, result: UndoResult) -> None:
        """Populate SQL visibility data for an undo migration script."""
        statements = self.execution_engine.get_executable_sql_statements(undo_migration, result)
        if result.error_message:
            return
        result.add_sql_migration(
            MigrationSqlInfo(
                script=undo_migration.script_name,
                version=undo_migration.version,
                description=undo_migration.description,
                statements=statements,
                annotations=self.execution_engine.annotate_sql_statements(statements),
            )
        )

    @staticmethod
    def _add_empty_visible_sql(migration: Any, result: UndoResult) -> None:
        """Record a non-SQL undo migration with no SQL statements."""
        result.add_sql_migration(
            MigrationSqlInfo(
                script=migration.script_name,
                version=migration.version,
                description=migration.description,
                statements=[],
            )
        )

    def _record_undone(
        self,
        migration: Migration,
        undo_migration: Migration,
        result: UndoResult,
        execution_time: int,
    ) -> None:
        """Add the undone migration to the result (under the undo script name) and log it."""
        result.add_undone_migration(
            MigrationInfo(
                script=undo_migration.script_name,
                version=migration.version,
                description=f"Undo: {migration.description}",
                type="UNDO_SQL",
                status="UNDONE",
                execution_time=execution_time,
                checksum=migration.checksum,
            )
        )
        self.log.info(f"Successfully undone migration {migration.script_name}")

    def _fire_error_callback_while_locked(
        self,
        exc_type: Optional[type],
        exc: Optional[BaseException],
        _traceback: object,
    ) -> bool:
        """Fire ``afterUndoError`` when the locked block raised; never swallow the error.

        Pushed on the lock's ``ExitStack`` after the lock, so it runs before the
        lock is released: error callbacks can run SQL, which must not overlap a
        migrate. A connection failure is not an undo failure and fires nothing.
        """
        if isinstance(exc, Exception) and not isinstance(exc, PreflightConnectionError):
            self._run_error_handler("undo", lambda: self._fire("afterUndoError"))
        return False

    def execute(
        self,
        scripts_dir: Path,
        target_version: Optional[str] = None,
        dry_run: bool = False,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
        show_sql: bool = False,
        show_query_results: bool = False,
        placeholders: Optional[Dict[str, Any]] = None,
        recursive: Optional[bool] = None,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> UndoResult:
        """Undo migrations to a target version."""
        self._reset_callback_catalog()

        result = UndoResult()
        result.show_sql = show_sql
        result.show_query_results = show_query_results
        result.target_schema = self.config.database.schema

        if not dry_run:
            self._prepare_required_analysis()

        def body() -> None:
            # Held from before the plan is read until the state is rebuilt, so a
            # migration cannot run on the schema in between. Dry run never locks.
            # Released here, before the lifecycle logs the footer.
            with ExitStack() as lock:
                # Without a history table there is nothing to undo; the lock would
                # create objects in a schema that was never migrated.
                if not dry_run and not self.history_manager.has_history_table:
                    self.log.info("No migrations to undo")
                    result.complete()
                    return

                if not dry_run and not lock.enter_context(self._migration_lock()):
                    self.log.error(MIGRATION_LOCK_REFUSAL)
                    result.set_error(MIGRATION_LOCK_REFUSAL)
                    return

                lock.push(self._fire_error_callback_while_locked)

                # Setup parameters
                use_recursive, use_additional_dirs = (
                    self.migration_helpers.setup_migration_parameters(
                        placeholders, recursive, additional_dirs, self.placeholder_service
                    )
                )
                self._bind_callbacks(
                    scripts_dir, use_recursive, use_additional_dirs, dir_recursive_map, result
                )

                plan = self.state_manager.plan_undo(
                    scripts_dir,
                    recursive=use_recursive,
                    additional_dirs=use_additional_dirs,
                    dir_recursive_map=dir_recursive_map,
                    target_version=target_version,
                    tags=tags,
                    exclude_tags=exclude_tags,
                    versions=versions,
                    exclude_versions=exclude_versions,
                    migration_rules=self.migration_rules,
                )

                # Store current schema version in result for HTML reports
                if plan.current_version:
                    result.current_schema_version = plan.current_version

                if plan.refusal and plan.missing_undo_script is None:
                    result.set_error(plan.refusal)
                    return

                if plan.group_additions:
                    if plan.target_boundary_in_group:
                        self.log.info(
                            "--target-version %s falls inside a group of migrations written "
                            "as one unit; undoing %d additional migration(s) too: %s"
                            % (
                                target_version,
                                len(plan.group_additions),
                                ", ".join(str(m.version) for m in plan.group_additions),
                            )
                        )
                    else:
                        self.log.info(
                            "Undoing %d additional migration(s) written as one group with %s: %s"
                            % (
                                len(plan.group_additions),
                                plan.selected[-1].script_name,
                                ", ".join(str(m.version) for m in plan.group_additions),
                            )
                        )

                if not plan.selected:
                    self.log.info("No migrations to undo")
                    result.complete()
                    return

                self.log.info(f"Found {len(plan.selected)} migration(s) to undo")

                if plan.refusal:
                    self.log.error(plan.refusal)
                    result.set_error(plan.refusal)
                    return

                undo_plan = [(step.migration, step.undo_script) for step in plan.steps]

                if not dry_run and not self._capture_objects:
                    callbacks = self._callbacks_for(
                        ("beforeUndo", "afterUndo", "afterUndoError", "beforeEach", "afterEach")
                    )
                    self._preflight_execution_sql([undo for _, undo in undo_plan] + callbacks)

                if dry_run:
                    for migration, undo_migration in undo_plan:
                        if show_sql:
                            if undo_migration.format == MigrationFormat.PYTHON:
                                self._add_empty_visible_sql(undo_migration, result)
                            else:
                                self._add_visible_sql(undo_migration, result)
                            if result.error_message:
                                return

                    self.log.info("DRY RUN: Would undo the following migrations:")
                    for migration, _ in undo_plan:
                        self.log.info(f"  - {migration.script_name}")
                    # Note: Callbacks are NOT executed in dry-run mode
                    return

                # Execute beforeUndo callbacks
                try:
                    self._fire("beforeUndo")
                except Exception as e:
                    self.log.error(f"beforeUndo callback failed: {e}")
                    result.set_error(f"beforeUndo callback failed: {e}")
                    self._fire("afterUndoError")
                    result.complete()
                    return

                # Execute undo for each migration
                runner = ScriptRunner(self, UNDO_POLICY)
                for migration, undo_migration in undo_plan:
                    if self._migration_lock_lost():
                        # Another process may have taken the lock over; the undo in
                        # flight could not be interrupted safely, the next must not start.
                        message = (
                            "The migration lock was lost (taken over by another process or "
                            f"not renewable); stopping before {undo_migration.script_name}"
                        )
                        self.log.error(message)
                        result.set_error(message)
                        break
                    if show_sql:
                        self._add_visible_sql(undo_migration, result)
                        if result.error_message:
                            break

                    success = runner.run(
                        undo_migration,
                        result,
                        event_data={
                            "script": undo_migration.script_name,
                            "version": migration.version,
                            "description": f"Undo: {migration.description}",
                            "type": "UNDO_SQL",
                        },
                        on_success=partial(self._record_undone, migration, undo_migration, result),
                    )
                    if not success:
                        break

                # If we reach here, all undo migrations completed successfully
                # Execute afterUndo callbacks
                if not result.error_message:
                    self._fire("afterUndo")

                # Set journal on result for HTML formatter access
                result.journal = self.journal

                # Update schema version after migrations are undone
                # Rebuild state to get accurate applied migrations after undo
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
                result.current_schema_version = migration_state_after.current_version

                return

        # Connect before reading history; a missing history table means there
        # are no applied migrations and must not create anything. A connection
        # or schema-history failure propagates as it does for info.
        return cast(
            UndoResult,
            self._run_command_lifecycle(
                "undo",
                result,
                body,
                preflight=lambda: self._run_preflight(result),
                error_message_prefix="Undo operation failed",
                header_kwargs={
                    "target_version": target_version,
                    "dry_run": dry_run,
                    "tags": tags,
                    "exclude_tags": exclude_tags,
                    "versions": versions,
                    "exclude_versions": exclude_versions,
                    "show_sql": show_sql,
                },
            ),
        )
