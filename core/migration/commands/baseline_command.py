"""
Baseline command implementation.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass
from core.logger.results import BaselineResult
from core.migration.migration import Migration, MigrationType

from .base_command import BaseCommand


class BaselineCommand(BaseCommand):
    """Handles the 'baseline' command execution."""

    def execute(
        self, baseline_version: str, baseline_description: str = "", dry_run: bool = False
    ) -> BaselineResult:
        """Create a baseline for existing database."""
        result = BaselineResult()
        result.target_schema = self.config.database.schema

        # Populate database connection information
        self._populate_database_info(result)

        try:
            # Ensure schema and history table exist before baselining (this establishes the
            # connection). Runs for dry-run too: when the history table already exists with
            # rows, this raises the same "cannot baseline a schema with existing migrations"
            # error the real run would hit, instead of letting dry-run report false success.
            self.history_manager.create_schema_and_history_table(create_schema=True)

            if dry_run:
                result.baseline_version = baseline_version
                result.message = f"Dry run: baseline {baseline_version} would be created"
                self._log_command_header_update(
                    "baseline", baseline_version=baseline_version, dry_run=True
                )
                self._log_command_completion("baseline", result)
                return result

            # Log command execution with connection info (after connection is established)
            self._log_command_header_update("baseline", baseline_version=baseline_version)

            # CRITICAL: Start a transaction before recording baseline
            # This ensures all operations (history recording, commit) use the same connection
            transaction_started = False
            try:
                self.provider.begin_transaction()
                transaction_started = True
                self.log.debug("Started transaction for baseline recording")
            except Exception as e:
                self.log.warning(f"Could not begin transaction for baseline: {e}")
                # Continue - some databases might use autoCommit mode

            # Create baseline migration record without script_path since baseline doesn't have a file
            baseline_migration = Migration(
                script_name=f"B{baseline_version}__{baseline_description}.sql",
                content=f"-- Baseline migration for version {baseline_version}",
                version=baseline_version,
                description=baseline_description,
                type=MigrationType.BASELINE,
                logger=self.log,
            )

            # Record the baseline
            self.history_manager.record_migration(
                baseline_migration, success=True, execution_time=0
            )

            # CRITICAL: Commit the baseline record when autoCommit is disabled
            # Without this, the baseline record will be rolled back when connection closes
            if transaction_started:
                try:
                    self.provider.commit_transaction()
                    self.log.debug("Committed baseline transaction")
                except Exception as commit_err:
                    self.log.error(f"Failed to commit baseline transaction: {commit_err}")
                    # Rollback on error
                    try:
                        self.provider.rollback_transaction()
                        self.log.debug("Rolled back baseline transaction after commit failure")
                    except Exception as rb_e:
                        self.log.debug(f"Could not rollback baseline transaction: {rb_e}")
                    raise

            result.baseline_version = baseline_version

            self.log.debug(f"Baseline {baseline_version} created successfully")
            self._log_command_completion("baseline", result)
            return result

        except Exception as e:
            self.log.error(f"Baseline operation failed: {e}")
            result.set_error(f"Baseline operation failed: {e}")
            self._log_command_completion("baseline", result)
            return result
