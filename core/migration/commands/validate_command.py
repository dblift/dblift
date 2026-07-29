"""
Validate command implementation.
"""

from pathlib import Path
from typing import TYPE_CHECKING, Dict, List, Optional

if TYPE_CHECKING:
    pass
from core.logger.results import ValidateResult

from .base_command import BaseCommand


class ValidateCommand(BaseCommand):
    """Handles the 'validate' command execution."""

    def execute(
        self,
        scripts_dir: Path,
        recursive: bool = True,
        additional_dirs: Optional[List[Path]] = None,
        dir_recursive_map: Optional[Dict[Path, bool]] = None,
        target_version: Optional[str] = None,
        tags: Optional[str] = None,
        exclude_tags: Optional[str] = None,
        versions: Optional[str] = None,
        exclude_versions: Optional[str] = None,
    ) -> ValidateResult:
        """Validate migration scripts."""
        result = ValidateResult()
        result.target_schema = self.config.database.schema

        # Log command execution with filters
        # Populate database connection information
        self._populate_database_info(result)

        try:
            # Ensure the schema history table exists before validating. A
            # failure here (e.g. missing DB privileges) is a real command
            # failure, not something to swallow: validating scripts against
            # a history table that couldn't be created would report success
            # while the schema was left in an unusable state.
            try:
                self.history_manager.create_schema_and_history_table(create_schema=False)
            except Exception as e:
                from core.migration.sql.sql_execution_service import _format_execution_error

                try:
                    formatted = _format_execution_error(e)
                except Exception:
                    formatted = ""
                error_msg = f"Could not create schema history table: {formatted or str(e)}"
                self.log.error(error_msg)
                result.set_error(error_msg)
                self._log_command_completion("validate", result)
                return result

            # Log command execution with connection info (after connection is established)
            self._log_command_header_update(
                "validate",
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )

            validation_result = self.validator.validate_migrations(
                scripts_dir,
                "validate",
                recursive=recursive,
                additional_dirs=additional_dirs,
                target_version=target_version,
                tags=tags,
                exclude_tags=exclude_tags,
                versions=versions,
                exclude_versions=exclude_versions,
            )

            result.success = validation_result.success
            result.error_message = validation_result.error_message or ""
            # execution_time is calculated automatically by the base class

            if validation_result.success:
                self.log.info("Migration validation passed")
            else:
                # Log all validation issues
                if hasattr(validation_result, "issues") and validation_result.issues:
                    for issue in validation_result.issues:
                        self.log.error(issue)
                else:
                    # Fallback to error_message if issues list is not available
                    self.log.error(f"Migration validation failed: {result.error_message}")

            self._log_command_completion("validate", result)
            return result

        except Exception as e:
            self.log.error(f"Validation operation failed: {e}")
            result.set_error(f"Validation operation failed: {e}")
            self._log_command_completion("validate", result)
            return result
