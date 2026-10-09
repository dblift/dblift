"""
Undo command implementation.
"""

import time
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional

if TYPE_CHECKING:
    pass

from dblift.core.constants import SECONDS_TO_MILLISECONDS
from dblift.core.logger.results import MigrationInfo, MigrationSqlInfo, UndoResult
from dblift.core.migration.formats.migration_format import MigrationFormat
from dblift.core.migration.migration import MigrationType
from dblift.core.migration.rules.migration_rules import expand_undo_set_to_groups
from dblift.core.migration.state.migration_display_state import MigrationDisplayState
from dblift.core.migration.state.rank_wins import installed_rank, latest_successful_ranks
from dblift.core.migration.version_utils import compare_versions, is_migration_success

from ._script_events import emit_script_event as _emit_script_event
from .base_command import BaseCommand, PreflightConnectionError


class UndoCommand(BaseCommand):
    """Handles the 'undo' command execution."""

    @staticmethod
    def _normalize_filter_values(values: Optional[Any]) -> Optional[List[str]]:
        if values is None:
            return None
        if isinstance(values, str):
            return [part.strip().lower() for part in values.split(",") if part.strip()]
        return [str(value).strip().lower() for value in values if str(value).strip()]

    @staticmethod
    def _coerced_applied_list(value: Any) -> List[Any]:
        if value is None or not hasattr(value, "__iter__"):
            return []
        try:
            return list(value)
        except (TypeError, AttributeError):
            return []

    @staticmethod
    def _find_undo_script(migration: Any, state: Any) -> Optional[Any]:
        """Return the Available catalog undo script matching the applied version."""
        version = getattr(migration, "version", None)
        if version is None or state is None:
            return None
        version_s = str(version)
        pending_objects = getattr(state, "pending_objects", None) or []
        pending_entries = getattr(state, "pending", None) or []
        try:
            pairs = zip(pending_objects, pending_entries)
        except TypeError:
            return None
        for obj, entry in pairs:
            if getattr(entry, "status", None) != MigrationDisplayState.AVAILABLE.value:
                continue
            if str(getattr(entry, "version", None)) == version_s:
                return obj
        return None

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
        normalized_tags = self._normalize_filter_values(tags)
        normalized_exclude_tags = self._normalize_filter_values(exclude_tags)
        tag_filter_active = bool(normalized_tags or normalized_exclude_tags)

        result = UndoResult()
        result.show_sql = show_sql
        result.show_query_results = show_query_results
        result.target_schema = self.config.database.schema

        if not dry_run:
            self._prepare_required_analysis()

        try:
            # Connect before reading history; a missing history table means
            # there are no applied migrations and must not create anything.
            self._run_preflight(result)

            # Log command execution with connection info (after connection is established)
            self._log_command_header_update(
                "undo",
                target_version=target_version,
                dry_run=dry_run,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
                show_sql=show_sql,
            )

            # Setup parameters
            use_recursive, use_additional_dirs = self.migration_helpers.setup_migration_parameters(
                placeholders, recursive, additional_dirs, self.placeholder_service
            )

            # Catalog is unfiltered; undo selects applied Success then tags/versions.
            # target_version is rollback-to (undo versions > target), not an omit filter.
            migration_state = self.state_manager.build_state(
                scripts_dir,
                recursive=use_recursive,
                additional_dirs=use_additional_dirs,
                dir_recursive_map=dir_recursive_map,
                target_version=target_version,
            )

            applied_migrations = self._coerced_applied_list(
                getattr(migration_state, "all_applied_objects", None)
            )
            if not applied_migrations:
                applied_migrations = self._coerced_applied_list(
                    getattr(migration_state, "applied_objects", None)
                )

            # Store current schema version in result for HTML reports
            current_version = None
            current_source = applied_migrations
            applied_objects = self._coerced_applied_list(
                getattr(migration_state, "applied_objects", None)
            )
            if applied_objects:
                current_source = applied_objects
            if current_source:
                current_version = self.state_manager.get_current_version(current_source)
            if current_version:
                result.current_schema_version = current_version

            success_applied = [
                migration
                for migration in applied_migrations
                if getattr(migration, "type", None) in (MigrationType.SQL, MigrationType.PYTHON)
                and is_migration_success(getattr(migration, "success", False))
                and getattr(migration, "version", None)
            ]
            candidates = self.state_manager.apply_filters_to_migrations(
                success_applied,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )
            try:
                candidates = list(candidates)
            except (TypeError, AttributeError):
                candidates = success_applied
            version_ranks = latest_successful_ranks(applied_migrations)
            # A version undone and then re-applied has several successful rows;
            # only the latest one is currently applied, so plan that row alone.
            candidates = [
                migration
                for migration in candidates
                if installed_rank(migration) == version_ranks[str(migration.version)].versioned
            ]

            # Find migrations to undo using migration rules (based on state)
            migrations_to_undo = []

            if target_version is None:
                # No target version specified - find the latest migration that can be undone.
                # Walk applied migrations in reverse install-rank order (most recently
                # applied first) -- every provider's get_applied_migrations() query is
                # ORDER BY installed_rank, and the target-version branch below uses the
                # same reversed(applied_migrations) convention. Install rank, not version
                # number, determines what "most recent" means: migrations can be applied
                # out of version order.
                for migration in reversed(candidates):
                    version = str(migration.version)
                    # Auto-scan mode: silently skip candidates that are already
                    # undone instead of routing through should_undo_version(),
                    # which reports a refusal for an already-undone version.
                    if self.migration_rules._is_currently_undone(
                        version,
                        applied_migrations,
                        version_ranks=version_ranks,
                    ):
                        continue
                    migrations_to_undo.append(migration)
                    if not tag_filter_active:
                        break  # Only undo the most recent undoable migration

                if migrations_to_undo:
                    migrations_to_undo, added = expand_undo_set_to_groups(
                        self.migration_rules,
                        migrations_to_undo,
                        candidates,
                        applied_migrations,
                        version_ranks=version_ranks,
                    )
                    if added:
                        self.log.info(
                            "Undoing %d additional migration(s) written as one group with %s: %s"
                            % (
                                len(added),
                                migrations_to_undo[-1].script_name,
                                ", ".join(str(m.version) for m in added),
                            )
                        )
            else:
                # Target version specified - undo every installed version strictly
                # above the target, regardless of install rank. Out-of-order history
                # (e.g. V3 rank 1, V2 rank 2, --target-version 2) must still undo V3;
                # stopping at the first version ≤ target would skip a higher version
                # installed earlier.
                for migration in reversed(candidates):
                    if compare_versions(str(migration.version), str(target_version)) <= 0:
                        continue
                    version = str(migration.version)
                    if self.migration_rules._is_currently_undone(
                        version, applied_migrations, version_ranks=version_ranks
                    ):
                        continue
                    can_undo, message = self.migration_rules.should_undo_version(
                        version,
                        applied_migrations,
                        version_ranks=version_ranks,
                    )
                    if can_undo:
                        migrations_to_undo.append(migration)
                    elif message:
                        result.set_error(message)
                        self._log_command_completion("undo", result)
                        return result

                # --target-version undoes every version strictly above the
                # target; if that boundary lands in the middle of a group,
                # widen the plan to the whole group rather than leaving some
                # of its migrations applied and others undone (same rule the
                # no-target-version branch above applies).
                if migrations_to_undo:
                    migrations_to_undo, added = expand_undo_set_to_groups(
                        self.migration_rules,
                        migrations_to_undo,
                        candidates,
                        applied_migrations,
                        version_ranks=version_ranks,
                    )
                    if added:
                        self.log.info(
                            "--target-version %s falls inside a group of migrations written "
                            "as one unit; undoing %d additional migration(s) too: %s"
                            % (
                                target_version,
                                len(added),
                                ", ".join(str(m.version) for m in added),
                            )
                        )

            if not migrations_to_undo:
                self.log.info("No migrations to undo")
                result.complete()
                return result

            self.log.info(f"Found {len(migrations_to_undo)} migration(s) to undo")

            # Resolve every undo script before any write so a missing script
            # anywhere in the plan refuses the real run exactly like the dry run,
            # instead of failing midway and leaving a partial rollback.
            undo_plan = []
            for migration in migrations_to_undo:
                undo_migration = self._find_undo_script(migration, migration_state)
                if undo_migration is None:
                    error_msg = f"No undo script found for {migration.script_name}"
                    self.log.error(error_msg)
                    result.set_error(error_msg)
                    self._log_command_completion("undo", result)
                    return result
                undo_plan.append((migration, undo_migration))

            if not dry_run and not self._capture_objects:
                callback_snapshot = self.state_manager.new_callback_snapshot()
                callbacks = [
                    callback
                    for event in (
                        "beforeUndo",
                        "afterUndo",
                        "afterUndoError",
                        "beforeEach",
                        "afterEach",
                    )
                    for callback in self.state_manager.get_callbacks_by_event(
                        scripts_dir,
                        event,
                        read_snapshot=callback_snapshot,
                        recursive=use_recursive,
                        additional_dirs=use_additional_dirs,
                        dir_recursive_map=dir_recursive_map,
                    )
                ]
                self._preflight_execution_sql([undo for _, undo in undo_plan] + callbacks)

            if dry_run:
                for migration, undo_migration in undo_plan:
                    if show_sql:
                        if undo_migration.format == MigrationFormat.PYTHON:
                            self._add_empty_visible_sql(undo_migration, result)
                        else:
                            self._add_visible_sql(undo_migration, result)
                        if result.error_message:
                            self._log_command_completion("undo", result)
                            return result

                self.log.info("DRY RUN: Would undo the following migrations:")
                for migration in migrations_to_undo:
                    self.log.info(f"  - {migration.script_name}")
                # Note: Callbacks are NOT executed in dry-run mode
                self._log_command_completion("undo", result)
                return result

            # Execute beforeUndo callbacks
            try:
                self._execute_callbacks(
                    scripts_dir,
                    "beforeUndo",
                    use_recursive,
                    use_additional_dirs,
                    dir_recursive_map,
                    result=result,
                )
            except Exception as e:
                self.log.error(f"beforeUndo callback failed: {e}")
                result.set_error(f"beforeUndo callback failed: {e}")
                self._execute_callbacks(
                    scripts_dir,
                    "afterUndoError",
                    use_recursive,
                    use_additional_dirs,
                    dir_recursive_map,
                    result=result,
                )
                result.complete()
                return result

            # Execute undo for each migration
            for migration, undo_migration in undo_plan:
                # Initialize variables to avoid NameError in exception handler
                start_time = None
                journal_started = False

                try:
                    # Execute beforeEach callbacks
                    self._execute_callbacks(
                        scripts_dir,
                        "beforeEach",
                        use_recursive,
                        use_additional_dirs,
                        dir_recursive_map,
                        result=result,
                    )

                    start_time = time.time()

                    # Start journal tracking for undo migration (use undo script name for journal)
                    if self.journal:
                        self.journal.start_migration(
                            undo_migration.script_name,
                            details={
                                "version": undo_migration.version,
                                "description": undo_migration.description,
                                "type": undo_migration.type.value if undo_migration.type else "SQL",
                            },
                        )
                        journal_started = True

                    if show_sql:
                        self._add_visible_sql(undo_migration, result)
                        if result.error_message:
                            if self.journal and journal_started:
                                execution_time = int(
                                    (time.time() - start_time) * SECONDS_TO_MILLISECONDS
                                )
                                self.journal.end_migration(
                                    undo_migration.script_name,
                                    success=False,
                                    error_message=result.error_message,
                                    execution_time=execution_time,
                                )
                                journal_started = False
                            break

                    _undo_script_data = {
                        "script": undo_migration.script_name,
                        "version": migration.version,
                        "description": f"Undo: {migration.description}",
                        "type": "UNDO_SQL",
                    }
                    _emit_script_event("migration.script.started", _undo_script_data)
                    self.execution_engine.execute_migration(undo_migration, result)
                    execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)

                    if result.error_message:
                        if self.journal and journal_started:
                            self.journal.end_migration(
                                undo_migration.script_name,
                                success=False,
                                error_message=result.error_message,
                                execution_time=execution_time,
                            )
                            journal_started = False
                        _emit_script_event(
                            "migration.script.failed",
                            {
                                "script": undo_migration.script_name,
                                "version": migration.version,
                                "error": result.error_message,
                                "execution_time": execution_time,
                            },
                        )
                        self._execute_callbacks(
                            scripts_dir,
                            "afterUndoError",
                            use_recursive,
                            use_additional_dirs,
                            dir_recursive_map,
                            result=result,
                        )
                        break

                    # End journal tracking for undo migration (use undo script name for journal)
                    if self.journal:
                        self.journal.end_migration(
                            undo_migration.script_name, success=True, execution_time=execution_time
                        )
                        journal_started = False

                    # Create MigrationInfo for the undone migration (use undo script name)
                    migration_info = MigrationInfo(
                        script=undo_migration.script_name,
                        version=migration.version,
                        description=f"Undo: {migration.description}",
                        type="UNDO_SQL",
                        status="UNDONE",
                        execution_time=execution_time,
                        checksum=migration.checksum,
                    )
                    result.add_undone_migration(migration_info)

                    _emit_script_event(
                        "migration.script.completed",
                        {**_undo_script_data, "execution_time": execution_time},
                    )
                    _emit_script_event(
                        "undo.script.rolled_back",
                        {**_undo_script_data, "execution_time": execution_time},
                    )

                    self.log.info(f"Successfully undone migration {migration.script_name}")

                    # Execute afterEach callbacks after successful undo
                    self._execute_callbacks(
                        scripts_dir,
                        "afterEach",
                        use_recursive,
                        use_additional_dirs,
                        dir_recursive_map,
                        result=result,
                    )

                except Exception as e:
                    # Only log if error_message is not already set (execute_migration already logged it)
                    if not result.error_message:
                        self.log.error(f"Failed to undo migration {migration.script_name}: {e}")
                        error_message = str(e)
                    else:
                        # Error was already logged by execute_migration, just use the existing message
                        error_message = result.error_message

                    # End journal tracking for a failed undo migration. The journal
                    # entry was opened under ``undo_migration.script_name``; fall back
                    # to ``migration.script_name`` only for the rare case where the
                    # failure occurred before ``undo_migration`` was resolved, so the
                    # journal entry is always closed.
                    execution_time = 0
                    if start_time is not None:
                        execution_time = int((time.time() - start_time) * SECONDS_TO_MILLISECONDS)

                    if "_undo_script_data" in locals():
                        _emit_script_event(
                            "migration.script.failed",
                            {
                                "script": getattr(
                                    locals().get("undo_migration"),
                                    "script_name",
                                    migration.script_name,
                                ),
                                "version": migration.version,
                                "error": error_message,
                                "execution_time": execution_time,
                            },
                        )

                    if self.journal and journal_started:
                        journal_script_name = (
                            undo_migration.script_name
                            if undo_migration is not None
                            else migration.script_name
                        )
                        self.journal.end_migration(
                            journal_script_name,
                            success=False,
                            error_message=error_message,
                            execution_time=execution_time,
                        )

                    # Only set error if not already set (execute_migration already set it)
                    if not result.error_message:
                        result.set_error(f"Undo failed: {e}")
                    # Execute afterUndoError callbacks when undo fails
                    self._execute_callbacks(
                        scripts_dir,
                        "afterUndoError",
                        use_recursive,
                        use_additional_dirs,
                        dir_recursive_map,
                        result=result,
                    )
                    break

            # If we reach here, all undo migrations completed successfully
            # Execute afterUndo callbacks
            if not result.error_message:
                self._execute_callbacks(
                    scripts_dir,
                    "afterUndo",
                    use_recursive,
                    use_additional_dirs,
                    dir_recursive_map,
                    result=result,
                )

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
            applied_migrations_after = migration_state_after.applied_objects
            updated_version = self.state_manager.get_current_version(applied_migrations_after)
            if updated_version:
                result.current_schema_version = updated_version
            else:
                # No versioned migrations left, set to None
                result.current_schema_version = None

            self._log_command_completion("undo", result)
            return result

        except PreflightConnectionError:
            # Connection or schema-history setup failed before undo started;
            # propagate it as info does rather than as a failed undo.
            raise
        except Exception as e:
            self.log.error(f"Undo operation failed: {e}")
            result.set_error(f"Undo operation failed: {e}")
            # Execute afterUndoError callbacks on exception
            try:
                self._execute_callbacks(
                    scripts_dir,
                    "afterUndoError",
                    use_recursive,
                    use_additional_dirs,
                    dir_recursive_map,
                    result=result,
                )
            except Exception as e:
                self.log.debug(
                    f"afterUndoError callback failed (ignored during exception handling): {e}"
                )
            self._log_command_completion("undo", result)
            return result
