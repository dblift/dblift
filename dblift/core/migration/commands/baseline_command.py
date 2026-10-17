"""
Baseline command implementation.
"""

from contextlib import ExitStack
from typing import TYPE_CHECKING, Any, Dict, cast

if TYPE_CHECKING:
    pass
from dblift.core.logger.results import BaselineResult
from dblift.core.migration.history.history_transaction import history_transaction
from dblift.core.migration.migration import Migration, MigrationType

from .base_command import MIGRATION_LOCK_REFUSAL, BaseCommand


def _existing_history_message(schema: str, count: int) -> str:
    """Error for a baseline attempted on a schema whose history already has rows."""
    return (
        f"Schema {schema} already contains a migration history table with {count} "
        "migration(s). Baseline cannot be applied to a schema with existing migrations."
    )


class BaselineCommand(BaseCommand):
    """Handles the 'baseline' command execution."""

    def execute(
        self, baseline_version: str, baseline_description: str = "", dry_run: bool = False
    ) -> BaselineResult:
        """Create a baseline for existing database."""
        result = BaselineResult()
        result.target_schema = self.config.database.schema

        def body() -> None:
            if dry_run:
                # Don't create the schema/history table as a side effect of dry-run.
                # If it already exists, run the same "history already has rows"
                # precondition the real run would hit, so dry-run can't report
                # false success for a baseline that would actually fail.
                if self.history_manager.has_history_table:
                    existing = self.state_manager.get_applied_migration_records()
                    if existing:
                        raise RuntimeError(
                            _existing_history_message(result.target_schema, len(existing))
                        )
                result.baseline_version = baseline_version
                result.message = f"Dry run: baseline {baseline_version} would be created"
                self.log.info(f"DRY RUN: Would create baseline {baseline_version}")
                return

            with ExitStack() as lock:
                if not lock.enter_context(self._migration_lock()):
                    self.log.error(MIGRATION_LOCK_REFUSAL)
                    result.set_error(MIGRATION_LOCK_REFUSAL)
                    return

                # Another run may have written history since preflight looked.
                if self.history_manager.has_history_table:
                    existing = self.state_manager.get_applied_migration_records()
                    if existing:
                        raise RuntimeError(
                            _existing_history_message(result.target_schema, len(existing))
                        )

                # Create baseline migration record without script_path since baseline doesn't have a file
                script_name = f"B{baseline_version}__{baseline_description}.sql"
                baseline_migration = Migration(
                    script_name=script_name,
                    content=f"-- Baseline migration for version {baseline_version}",
                    version=baseline_version,
                    description=baseline_description,
                    type=MigrationType.BASELINE,
                    logger=self.log,
                    _filename_metadata=self.script_manager.parse_filename(script_name),
                )

                # Record the baseline in one transaction so the row is committed
                # (autoCommit off) or rolled back if writing it fails.
                with history_transaction(self.provider, self.log, "baseline"):
                    self.history_manager.record_migration(
                        baseline_migration, success=True, execution_time=0
                    )

            result.baseline_version = baseline_version

            self.log.debug(f"Baseline {baseline_version} created successfully")

        header_kwargs: Dict[str, Any] = {"baseline_version": baseline_version}
        if dry_run:
            header_kwargs["dry_run"] = True

        # Canonical preflight (ADR-0011): connect → ensure schema/history
        # table (skipped in dry-run so baseline never creates it as a
        # side effect of a dry-run) → populate connection info.
        # baseline() has no prior migrate()/info() call to rely on, so
        # it must run this itself -- some providers (e.g. CosmosDB)
        # have no lazy-reconnect hook and raise instead of connecting
        # on demand (mirrors the same fix applied to undo()). A failure
        # propagates as info does rather than as a failed baseline.
        return cast(
            BaselineResult,
            self._run_command_lifecycle(
                "baseline",
                result,
                body,
                preflight=lambda: self._run_preflight(
                    result, ensure_history=True, dry_run=dry_run, create_schema=True
                ),
                error_message_prefix="Baseline operation failed",
                header_kwargs=header_kwargs,
            ),
        )
