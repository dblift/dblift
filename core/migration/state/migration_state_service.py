"""
Migration state determination service.

This module provides services for determining the display state of migrations
based on their execution history and context.
"""

from pathlib import Path
from typing import Any, Dict, List, Union

from core.logger import Log
from core.migration.state.migration_display_state import MigrationDisplayState
from core.migration.version_utils import compare_versions as _compare_versions_shared
from core.migration.version_utils import (
    is_migration_failure,
    is_migration_success,
)


class MigrationStateService:
    """Service for determining migration display states."""

    def __init__(self, logger: Log):
        """Initialize the migration state service.

        Args:
            logger: Logger instance for debugging
        """
        self.logger = logger

    def _get_migration_type_string(self, migration_type: Any) -> str:
        """Safely get migration type as string, handling both enum and string types.

        Delegates to the shared helper in ``core.migration._type_match``;
        kept as a method for backwards compatibility with existing call sites.
        """
        from core.migration._type_match import migration_type_name

        return migration_type_name(migration_type)

    def determine_state(self, migration: Any, context: Dict[str, Any]) -> MigrationDisplayState:
        """Determine the display state of a migration based on its context.

        Args:
            migration: Migration object to analyze
            context: Context dictionary containing analysis results

        Returns:
            MigrationDisplayState: The appropriate display state
        """
        if not migration:
            return MigrationDisplayState.UNKNOWN

        # Get context data
        undone_versions = context.get("undone_versions", set())
        context.get("baseline_version")
        out_of_order_migrations = context.get("out_of_order_migrations", set())
        repeatable_checksums = context.get("repeatable_checksums", {})
        reapplied_versions = context.get("reapplied_versions", set())
        current_version = context.get("current_version")
        context.get("target_version")

        # Get migration properties
        version = getattr(migration, "version", None)
        migration_type_raw = getattr(migration, "type", None)
        migration_type = self._get_migration_type_string(migration_type_raw).upper()
        success = getattr(migration, "success", None)
        checksum = getattr(migration, "checksum", None)
        script_name = getattr(migration, "script_name", "")

        # Handle DELETE type migrations
        if migration_type == "DELETE":
            return MigrationDisplayState.DELETED

        # Handle BASELINE type migrations
        if migration_type == "BASELINE":
            return MigrationDisplayState.BASELINE

        # Handle failed migrations
        if is_migration_failure(success):
            # Check if this is a missing migration (no longer exists in filesystem)
            if hasattr(migration, "resolved") and not migration.resolved:
                # Check if version is in the future
                if version and current_version:
                    if self._compare_versions(version, current_version) > 0:
                        return MigrationDisplayState.FAILED_FUTURE
                    else:
                        return MigrationDisplayState.FAILED_MISSING
                else:
                    return MigrationDisplayState.FAILED_MISSING
            else:
                return MigrationDisplayState.FAILED

        # Handle successful migrations
        if is_migration_success(success):
            # Check for UNDO_SQL type
            if migration_type == "UNDO_SQL":
                return MigrationDisplayState.SUCCESS

            # Check if migration was undone
            if version in undone_versions:
                # Check if it was reapplied after being undone
                if version in reapplied_versions:
                    # If reapplied successfully, show as success
                    return MigrationDisplayState.SUCCESS
                else:
                    return MigrationDisplayState.UNDONE

            # Check for out-of-order migrations
            if version in out_of_order_migrations:
                return MigrationDisplayState.OUT_OF_ORDER

            # Check for repeatable migrations
            if migration_type == "REPEATABLE":
                stored_checksum = repeatable_checksums.get(script_name)
                if stored_checksum and checksum and stored_checksum != checksum:
                    # Repeatable migration is outdated
                    # Check if there's a newer version already applied
                    # For now, just mark as outdated
                    return MigrationDisplayState.OUTDATED

            # Check if migration is missing (success but not resolved)
            if hasattr(migration, "resolved") and not migration.resolved:
                # Check if version is in the future
                if version and current_version:
                    if self._compare_versions(version, current_version) > 0:
                        return MigrationDisplayState.FUTURE
                    else:
                        return MigrationDisplayState.MISSING
                else:
                    return MigrationDisplayState.MISSING

            # Default successful state
            return MigrationDisplayState.SUCCESS

        # Handle null success (needs repair)
        if success is None:
            return MigrationDisplayState.NEEDS_REPAIR

        # Default fallback
        return MigrationDisplayState.UNKNOWN

    def determine_pending_state(
        self, migration: Any, context: Dict[str, Any]
    ) -> MigrationDisplayState:
        """Determine the display state for a pending migration.

        Args:
            migration: Migration object to analyze
            context: Context dictionary containing analysis results

        Returns:
            MigrationDisplayState: The appropriate display state
        """
        # Get context data
        baseline_version = context.get("baseline_version")
        target_version = context.get("target_version")
        context.get("current_version")
        scripts_dir = context.get("scripts_dir")

        # Get migration properties
        version = getattr(migration, "version", None)
        # Migration type may be an enum; normalize to uppercase string safely
        migration_type = self._get_migration_type_string(getattr(migration, "type", None)).upper()

        # Handle different migration types
        if migration_type == "REPEATABLE":
            return MigrationDisplayState.PENDING

        if migration_type == "UNDO_SQL":
            # Check if the corresponding versioned migration was undone
            # For now, just show as available
            return MigrationDisplayState.AVAILABLE

        # Handle versioned migrations
        if version:
            # Check if below baseline
            if baseline_version and self._compare_versions(version, baseline_version) < 0:
                return MigrationDisplayState.BELOW_BASELINE

            # Check if above target
            if target_version and self._compare_versions(version, target_version) > 0:
                return MigrationDisplayState.ABOVE_TARGET

            # Check if this version has an undo script available
            if scripts_dir and self._version_has_undo_script(version, scripts_dir):
                return MigrationDisplayState.AVAILABLE

        # Default pending state
        return MigrationDisplayState.PENDING

    def _compare_versions(self, version1: str, version2: str) -> int:
        """Compare two version strings. Delegates to shared compare_versions utility."""
        return _compare_versions_shared(version1, version2)

    def _compare_version_parts(self, v1_parts: List[int], v2_parts: List[int]) -> int:
        """Compare version part lists.

        Args:
            v1_parts: First version parts
            v2_parts: Second version parts

        Returns:
            int: Comparison result
        """
        # Pad shorter version with zeros
        max_len = max(len(v1_parts), len(v2_parts))
        v1_parts.extend([0] * (max_len - len(v1_parts)))
        v2_parts.extend([0] * (max_len - len(v2_parts)))

        for i in range(max_len):
            if v1_parts[i] < v2_parts[i]:
                return -1
            elif v1_parts[i] > v2_parts[i]:
                return 1

        return 0

    def _version_has_undo_script(self, version: str, scripts_dir: Union[Path, str]) -> bool:
        """Check if a version has a corresponding undo script.

        Args:
            version: Version to check
            scripts_dir: Directory containing migration scripts

        Returns:
            bool: True if undo script exists
        """
        if not scripts_dir or not version:
            return False

        try:

            scripts_path = Path(scripts_dir)

            # Look for undo scripts with pattern U{version}*.sql
            undo_pattern = f"U{version}*.sql"
            undo_files = list(scripts_path.glob(undo_pattern))

            return len(undo_files) > 0

        except Exception as e:
            self.logger.debug(f"Could not check for undo scripts: {e}")
            return False
