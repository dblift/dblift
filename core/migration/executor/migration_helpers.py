"""
Helper methods for migration execution.

This module contains utility methods used by the migration executor
for filtering, parameter setup, validation, and analysis.
"""

import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from config import DbliftConfig
from core.logger import Log, NullLog
from core.sql_validator.migration_validator import MigrationValidator


class MigrationHelpers:
    """Helper methods for migration operations."""

    def __init__(self, config: DbliftConfig, log: Log):
        """Initialize the migration helpers.

        Args:
            config: Application configuration
            log: Logger instance
        """
        self.config = config
        self.log = log if log is not None else NullLog()

    def setup_migration_parameters(
        self,
        placeholders: Optional[Dict[str, Any]],
        recursive: Optional[bool],
        additional_dirs: Optional[List[Path]],
        placeholder_service: Any,
    ) -> Tuple[bool, List[Path]]:
        """Setup and validate migration parameters.

        Args:
            placeholders: Custom placeholders for variable substitution
            recursive: Whether to recursively search for migrations
            additional_dirs: Additional directories to search for migrations
            placeholder_service: Placeholder service instance

        Returns:
            Tuple of (use_recursive, use_additional_dirs)
        """
        # Add any custom placeholders to the existing ones
        if placeholders:
            placeholder_service.add_placeholders(placeholders)

        # Set command type
        if hasattr(self.log, "set_command_type"):
            self.log.set_command_type("MIGRATE")

        # Use the recursive and additional_dirs parameters if provided, otherwise use config defaults
        use_recursive = (
            recursive
            if recursive is not None
            else getattr(self.config.migrations, "recursive", True)
        )
        use_additional_dirs = (
            additional_dirs
            if additional_dirs is not None
            else [Path(dir_path) for dir_path in getattr(self.config.migrations, "directories", [])]
        )

        return use_recursive, use_additional_dirs

    def validate_migrations_for_migrate(
        self,
        validator: MigrationValidator,
        scripts_dir: Path,
        use_recursive: bool,
        use_additional_dirs: List[Path],
        target_version: Optional[str] = None,
        tags: Optional[Sequence[str]] = None,
        exclude_tags: Optional[Sequence[str]] = None,
        versions: Optional[Sequence[str]] = None,
        exclude_versions: Optional[Sequence[str]] = None,
    ) -> Tuple[bool, Optional[str], float]:
        """Validate migrations for the migrate command.

        Args:
            validator: Migration validator instance
            scripts_dir: Directory containing migration scripts
            use_recursive: Whether to recursively search for migrations
            use_additional_dirs: Additional directories to search
            target_version: Optional target version filter
            tags: Optional tags to include
            exclude_tags: Optional tags to exclude
            versions: Optional versions to include
            exclude_versions: Optional versions to exclude

        Returns:
            Tuple of (validation_success, error_message, validation_time)
        """
        start_validation_time = time.time()
        validation_result = validator.validate_migrations(
            scripts_dir,
            "migrate",
            recursive=use_recursive,
            additional_dirs=use_additional_dirs,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
        )
        validation_time = time.time() - start_validation_time

        error_message_raw = getattr(validation_result, "error_message", "") or ""
        error_message_str = str(error_message_raw)
        lowered_error_message = error_message_str.lower()

        # Store validation errors but don't stop migration on validation failures
        # related to checksums for failed migrations
        if not validation_result.success:
            # Continue with migration instead of stopping, to show the actual migration errors
            # We'll display validation errors after migration fails
            self.log.debug(f"Migration validation found issues: {error_message_str}")
            # Only stop if it's not a checksum error (those will be shown in proper order after migration fails)
            if "modified migration scripts" not in lowered_error_message:
                # Log all validation issues
                issues = getattr(validation_result, "issues", None)
                if issues:
                    try:
                        for issue in issues:
                            self.log.error(issue)
                    except TypeError:
                        # issues is not iterable (likely a Mock); fall back to error message
                        self.log.error(f"Migration validation failed: {error_message_str}")
                else:
                    # Fallback to error_message if issues list is not available
                    self.log.error(f"Migration validation failed: {error_message_str}")
                return False, error_message_str, validation_time

        return validation_result.success, error_message_str, validation_time

    # NOTE: analyze_applied_migrations has been removed in favor of MigrationStateManager.
    # All migration state analysis should now go through MigrationStateManager.build_state()
    # which provides centralized, consistent state management across all operations.
