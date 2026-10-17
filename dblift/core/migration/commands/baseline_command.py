"""
Baseline command implementation.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
from dblift.core.logger.results import BaselineResult
from dblift.core.migration.history.history_transaction import history_transaction
from dblift.core.migration.migration import Migration, MigrationType

from .base_command import BaseCommand, PreflightConnectionError


class BaselineCommand(BaseCommand):
    """Handles the 'baseline' command execution."""

    def execute(
        self, baseline_version: str, baseline_description: str = "", dry_run: bool = False
    ) -> BaselineResult:
        """Create a baseline for existing database."""
        result = BaselineResult()
        result.target_schema = self.config.database.schema

        try:
            # Canonical preflight (ADR-0011): connect → ensure schema/history
            # table (skipped in dry-run so baseline never creates it as a
            # side effect of a dry-run) → populate connection info.
            # baseline() has no prior migrate()/info() call to rely on, so
            # it must run this itself -- some providers (e.g. CosmosDB)
            # have no lazy-reconnect hook and raise instead of connecting
            # on demand (mirrors the same fix applied to undo()).
            self._run_preflight(result, ensure_history=True, dry_run=dry_run, create_schema=True)

            if dry_run:
                # Don't create the schema/history table as a side effect of dry-run.
                # If it already exists, run the same "history already has rows"
                # precondition the real run would hit, so dry-run can't report
                # false success for a baseline that would actually fail.
                if self.history_manager.has_history_table:
                    existing = self.state_manager.get_applied_migration_records()
                    if existing:
                        raise RuntimeError(
                            f"Schema {result.target_schema} already contains a migration "
                            f"history table with {len(existing)} migration(s). Baseline "
                            "cannot be applied to a schema with existing migrations."
                        )
                result.baseline_version = baseline_version
                result.message = f"Dry run: baseline {baseline_version} would be created"
                self.log.info(f"DRY RUN: Would create baseline {baseline_version}")
                self._log_command_header_update(
                    "baseline", baseline_version=baseline_version, dry_run=True
                )
                self._log_command_completion("baseline", result)
                return result

            # Log command execution with connection info (after connection is established)
            self._log_command_header_update("baseline", baseline_version=baseline_version)

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
            self._log_command_completion("baseline", result)
            return result

        except PreflightConnectionError:
            # Connection or schema-history setup failed before baseline
            # started; propagate it as info does rather than as a failed baseline.
            raise
        except Exception as e:
            self.log.error(f"Baseline operation failed: {e}")
            result.set_error(f"Baseline operation failed: {e}")
            self._log_command_completion("baseline", result)
            return result
