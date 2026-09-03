"""
Migration state determination service.

This module provides services for determining the display state of migrations
based on their execution history and context.
"""

from pathlib import Path
from typing import Any, Dict

from dblift.core.logger import Log
from dblift.core.migration.migration import normalize_migration_checksum
from dblift.core.migration.state.migration_display_state import MigrationDisplayState
from dblift.core.migration.version_utils import compare_versions as _compare_versions_shared
from dblift.core.migration.version_utils import is_migration_failure, is_migration_success


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

        Delegates to the shared helper in ``dblift.core.migration._type_match``;
        kept as a method for backwards compatibility with existing call sites.
        """
        from dblift.core.migration._type_match import migration_type_name

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
                if (
                    stored_checksum
                    and checksum
                    and self._checksums_differ(stored_checksum, checksum)
                ):
                    # Latest successful checksum is on a newer history row.
                    return MigrationDisplayState.SUPERSEDED
                pending_repeatables = context.get("pending_repeatable_scripts") or set()
                script_basename = Path(script_name).name if script_name else ""
                if script_name in pending_repeatables or script_basename in pending_repeatables:
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
            # Check if at or below baseline (baselined versions must not be Pending)
            if baseline_version and self._compare_versions(version, baseline_version) <= 0:
                return MigrationDisplayState.BELOW_BASELINE

            # Check if above target
            if target_version and self._compare_versions(version, target_version) > 0:
                return MigrationDisplayState.ABOVE_TARGET

        # Default pending state
        return MigrationDisplayState.PENDING

    def _compare_versions(self, version1: str, version2: str) -> int:
        """Compare two version strings. Delegates to shared compare_versions utility."""
        return _compare_versions_shared(version1, version2)

    @staticmethod
    def _checksums_differ(stored: Any, current: Any) -> bool:
        """True when stored and current checksums are not the same CRC32.

        History rows and the analysis index may disagree on type (int vs
        ``str(int)``) or signedness (unsigned driver CRC32 vs Python signed).
        Non-numeric legacy values fall back to identity comparison.
        """
        normalized_stored = normalize_migration_checksum(stored)
        normalized_current = normalize_migration_checksum(current)
        if normalized_stored is not None and normalized_current is not None:
            return normalized_stored != normalized_current
        return bool(stored != current)
