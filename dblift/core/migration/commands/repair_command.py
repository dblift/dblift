"""
Repair command implementation.
"""

from contextlib import ExitStack
from pathlib import Path
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, cast

if TYPE_CHECKING:
    pass

from dblift.core.exceptions import ExecutionError
from dblift.core.logger.results import RepairResult
from dblift.core.migration.history.history_transaction import history_transaction
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.state.migration_state import MigrationState
from dblift.core.migration.state.repair_plan import (  # noqa: F401  re-exports
    RepairAction,
    RepairSafetyError,
    _count_candidate_missing,
)
from dblift.db.provider_capabilities import ensure_provider_connection
from dblift.db.provider_interfaces import TransactionalProvider

from ._repair_records import record_repair
from .base_command import MIGRATION_LOCK_REFUSAL, BaseCommand


class RepairCommand(BaseCommand):
    """Handles the 'repair' command execution."""

    def execute(
        self,
        scripts_dir: Path,
        dry_run: bool = False,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
    ) -> RepairResult:
        """Repair migration history by fixing checksums and removing invalid entries."""
        result = RepairResult()
        result.target_schema = self.config.database.schema

        def detect_and_repair() -> None:
            try:
                plan = self.state_manager.plan_repairs(
                    scripts_dir,
                    recursive=recursive,
                    additional_dirs=additional_dirs,
                    dir_recursive_map=dir_recursive_map,
                )
                migration_state = plan.state

                if not plan.actions:
                    self.log.info(
                        "Repair check completed: no checksum, failed migration, or history issues detected."
                    )
                    return

                if dry_run:
                    self.log.info("DRY RUN: the following repairs would be executed:")
                    for action in plan.actions:
                        self.log.info(f"  - {action.details['type']}: {action.details['script']}")
                        record_repair(result, action.kind, dict(action.details), migration_state)
                    return

                # Execute repairs
                repairs_executed, error = self._execute_repair_loop(
                    plan.actions, result, migration_state
                )
                if error:
                    return

                # Post-repair validation
                if repairs_executed:
                    validation_error = self._validate_post_repair_state(
                        migration_state=migration_state,
                        actions=plan.actions,
                        scripts_dir=scripts_dir,
                        recursive=recursive,
                        additional_dirs=additional_dirs,
                        dir_recursive_map=dir_recursive_map,
                        result=result,
                    )
                    if validation_error:
                        return

                # Log summary
                self._build_repair_summary(result)
            except RepairSafetyError as e:
                # Operator-facing safety abort — not a crash. Log the exact
                # message (already actionable) without stack-trace noise.
                self.log.error(str(e))
                result.set_error(str(e))

        def body() -> None:
            # A real run writes the schema history, so it must not overlap a
            # migration: hold the lock from detection through verification.
            with ExitStack() as lock:
                if not dry_run and not lock.enter_context(self._migration_lock()):
                    self.log.error(MIGRATION_LOCK_REFUSAL)
                    result.set_error(MIGRATION_LOCK_REFUSAL)
                    return
                detect_and_repair()

        # Connect, ensure the schema-history table exists and read connection
        # metadata. Failures raise PreflightConnectionError, as for every
        # other command.
        return cast(
            RepairResult,
            self._run_command_lifecycle(
                "repair",
                result,
                body,
                preflight=lambda: self._run_preflight(result, ensure_history=True),
                error_message_prefix="Repair operation failed",
                header_kwargs={"dry_run": dry_run},
            ),
        )

    def _delete_failed_migration_entry(
        self, repair: Dict[str, Any], result: RepairResult, migration_state: Any = None
    ) -> bool:
        """Delete a failed migration row from history so it can be retried.

        Shared by the FAILED_MIGRATION branch and the CHECKSUM_MISMATCH-on-failed-row branch
        of the repair loop. Returns True when a row was actually deleted.
        """
        script_name = repair.get("script", "")
        version = repair.get("version")

        try:
            # ADR-0015: must use the normalized name — passing the
            # raw lowercase "dblift_schema_history" through
            # ``get_schema_qualified_name`` produces ``"DBLIFT_TEST"."dblift_schema_history"``
            # on Oracle, and Oracle reads that as a literally-named
            # lowercase table → ORA-00942. ``normalized_history_table``
            # returns ``"DBLIFT_SCHEMA_HISTORY"`` for UPPERCASE dialects.
            self.log.debug(f"Removing failed migration entry: {script_name} (version: {version})")

            # Ensure connection is ready
            ensure_provider_connection(self.provider)

            # The backend owns the delete: relational dialects emit a
            # parameterised DELETE, document stores remove the history
            # document through their SDK. The command stays dialect-free and
            # composes no SQL of its own.
            row_removed = self.history_manager.delete_failed_migration_entry(script_name)

            if row_removed:
                record_repair(result, "FAILED_MIGRATION", repair, migration_state)
                # Warn about non-transactional DDL databases
                if (
                    isinstance(self.provider, TransactionalProvider)
                    and not self.provider.supports_transactional_ddl()
                ):
                    self.log.warning(
                        "Failed migration may have committed DDL objects before failure. "
                        'Retry may fail with "object already exists". Inspect schema state '
                        "before retrying, manually drop objects created before the failure, "
                        "or use `clean --clean-enabled` for a full reset."
                    )
                return True

            self.log.warning(f"No failed migration entry found for: {script_name}")
            return False
        except Exception as delete_err:
            self.log.error(f"Failed to reset failed migration entry {script_name}: {delete_err}")
            raise

    def _execute_repair_loop(
        self,
        actions: Sequence[RepairAction],
        result: RepairResult,
        migration_state: Any = None,
    ) -> "tuple[int, bool]":
        """Execute all repair actions in a transaction, rolling back on any failure.

        Args:
            actions: Planned repairs to execute; a checksum repair on a failed row
                arrives already routed as a FAILED_MIGRATION.
            result: RepairResult to update with counters and errors
            migration_state: Migration state the actions were planned from; describes the
                history row each repair targets on the result.

        Returns:
            Tuple of (repairs_executed: int, had_error: bool)
        """
        # Ensure the provider connection is ready before manipulating history
        try:
            ensure_provider_connection(self.provider)
        except Exception as ensure_err:
            self.log.debug(f"Unable to eagerly ensure connection before repair: {ensure_err}")

        # Perform repairs
        repairs_executed = 0
        step_error: Optional[Exception] = None

        if actions:
            self.log.info(f"Repairing {len(actions)} migration history issue(s).")

        try:
            with history_transaction(self.provider, self.log, "repair"):
                for action in actions:
                    repair = dict(action.details)
                    try:
                        if action.kind == "CHECKSUM_MISMATCH":
                            new_checksum = repair.get("new_checksum")
                            # The checksum column is INT; pass int for CRC32, not str
                            if new_checksum is not None and not isinstance(new_checksum, int):
                                try:
                                    new_checksum = int(new_checksum)
                                except (TypeError, ValueError):
                                    pass
                            if new_checksum is None:
                                raise ExecutionError(
                                    f"CHECKSUM_MISMATCH repair for {repair.get('script', '')} "
                                    "requires new_checksum"
                                )
                            updated = self.history_manager.repair_checksum(
                                str(repair.get("script", "")), new_checksum
                            )
                            if not updated:
                                raise ExecutionError(
                                    f"No history entry updated for {repair['script']}. "
                                    "Repair may require manual intervention."
                                )
                            repairs_executed += 1
                            record_repair(result, "CHECKSUM_MISMATCH", repair, migration_state)
                            self.log.info(f"Updated checksum for {repair['script']}")

                        elif action.kind == "MISSING_SCRIPT":
                            # For missing scripts, create a DELETE entry in the history table
                            # This marks the migration as intentionally deleted
                            script_name = repair.get("script", "")
                            version = repair.get("version")
                            description = repair.get("description", "")
                            original_type_obj = repair.get(
                                "original_type"
                            )  # Get original type from repair dict

                            try:
                                # Convert original type to string for storing in description
                                if original_type_obj:
                                    if hasattr(original_type_obj, "name"):
                                        original_type_name = original_type_obj.name
                                    else:
                                        original_type_name = str(original_type_obj).upper()
                                else:
                                    # Infer from script name
                                    if script_name.startswith("V"):
                                        original_type_name = MigrationType.SQL.name
                                    elif script_name.startswith("R"):
                                        original_type_name = MigrationType.REPEATABLE.name
                                    elif script_name.startswith("U"):
                                        original_type_name = MigrationType.UNDO_SQL.name
                                    else:
                                        original_type_name = MigrationType.SQL.name

                                # Create DELETE entry with original type embedded in description
                                delete_reason = (
                                    description or "Marked as deleted via repair command"
                                )
                                # Store original type in description: [DELETE:ORIGINAL_TYPE] description
                                enriched_description = (
                                    f"[DELETE:{original_type_name}] {delete_reason}"
                                )

                                delete_migration = Migration(
                                    script_name=script_name,
                                    content=f"-- Delete operation: {enriched_description}",
                                    version=version,
                                    description=enriched_description,
                                    type=MigrationType.DELETE,
                                    tags=[],
                                    _filename_metadata=self.script_manager.parse_filename(
                                        script_name
                                    ),
                                )

                                self.log.debug(
                                    f"Creating DELETE entry for missing migration: {script_name} (version: {version})"
                                )

                                # Record the DELETE entry in the history table
                                self.history_manager.record_migration(
                                    delete_migration, success=True, execution_time=0
                                )

                                repairs_executed += 1
                                record_repair(result, "MISSING_SCRIPT", repair, migration_state)
                                self.log.info(
                                    f"Marked migration as deleted: {script_name} - "
                                    f"DELETE entry created in history"
                                )
                            except Exception as delete_err:
                                self.log.error(
                                    f"Failed to mark migration as deleted {script_name}: {delete_err}"
                                )
                                raise

                        elif action.kind == "FAILED_MIGRATION":
                            # Remove failed migration entry from history to allow retry
                            # (same approach as Flyway: repair deletes FAILED entries).
                            if self._delete_failed_migration_entry(repair, result, migration_state):
                                repairs_executed += 1
                                self.log.info(
                                    f"Removed failed migration entry: {repair.get('script', '')} - "
                                    "migration can now be retried"
                                )
                    except Exception as e:
                        self.log.error(f"Failed to repair {repair['script']}: {e}")
                        result.set_error(f"Repair failed: {e}")
                        step_error = e
                        raise
        except Exception as e:
            if e is not step_error:
                result.set_error(f"Repair operation failed: {e}")
            return repairs_executed, True

        return repairs_executed, False

    def _validate_post_repair_state(
        self,
        migration_state: MigrationState,
        actions: Sequence[RepairAction],
        scripts_dir: Path,
        recursive: bool,
        additional_dirs: Optional[List[Path]],
        dir_recursive_map: Optional[Dict[Path, bool]],
        result: RepairResult,
    ) -> bool:
        """Re-compute state after repairs to verify they applied successfully.

        Args:
            migration_state: The pre-repair migration state (unused; kept for symmetry)
            actions: The repairs that were attempted
            scripts_dir: Directory containing migration scripts
            recursive: Whether to scan directories recursively
            additional_dirs: Additional directories to scan
            dir_recursive_map: Per-directory recursive override map
            result: RepairResult to set error on if validation fails

        Returns:
            True if a validation error was detected (caller should return early), False otherwise
        """
        try:
            post_state = self.state_manager.build_state(
                scripts_dir,
                recursive=recursive,
                additional_dirs=additional_dirs,
                dir_recursive_map=dir_recursive_map,
            )
            repaired_scripts = {action.script for action in actions}
            remaining_issues = [
                change.script_name
                for change in post_state.checksum_changes
                if change.script_name in repaired_scripts
            ]
            if remaining_issues:
                issue_list = ", ".join(remaining_issues)
                message = (
                    f"Checksum repair incomplete for: {issue_list}. "
                    "Please inspect history table manually."
                )
                self.log.error(message)
                result.set_error(message)
                return True
        except Exception as e:
            self.log.debug(f"Could not rebuild state after repair: {e}")

        return False

    def _build_repair_summary(self, result: RepairResult) -> None:
        """Log a summary of completed repairs.

        Args:
            result: RepairResult containing counters for fixed/reset/marked items
        """
        summary_parts = []
        if result.checksums_fixed > 0:
            summary_parts.append(f"{result.checksums_fixed} checksum(s) fixed")
        if result.failed_migrations_removed > 0:
            summary_parts.append(f"{result.failed_migrations_removed} failed migration(s) reset")
        if result.deleted_migrations_marked > 0:
            summary_parts.append(
                f"{result.deleted_migrations_marked} missing migration(s) marked as deleted"
            )

        if summary_parts:
            self.log.info(f"Repair operation completed successfully: {', '.join(summary_parts)}")
        else:
            self.log.info("Repair operation completed successfully")
