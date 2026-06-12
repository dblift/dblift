"""
Migration data preparation service.

This module provides services for preparing and analyzing migration data
for display and processing purposes.
"""

from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.logger import Log
from core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration
from core.migration.state.migration_display_state import MigrationDisplayState
from core.migration.state.migration_state_service import MigrationStateService
from core.migration.version_utils import compare_versions as _compare_versions_shared
from core.migration.version_utils import (
    is_migration_success,
)


class MigrationDataService:
    """Service for preparing migration data for display and analysis."""

    def __init__(
        self, logger: Log, scripts_dir: Optional[Path] = None, target_version: Optional[str] = None
    ):
        """Initialize the migration data service.

        Args:
            logger: Logger instance
            scripts_dir: Directory containing migration scripts
            target_version: Target version for migrations
        """
        self.logger = logger
        self.scripts_dir = scripts_dir
        self.target_version = target_version
        self.state_service = MigrationStateService(logger)

    def prepare_migration_data(
        self,
        applied_migrations: List[Migration],
        pending_migrations: Optional[List[Migration]] = None,
        failed_migrations: Optional[List[Migration]] = None,
    ) -> List[Dict[str, Any]]:
        """Prepare migration data for display by combining and analyzing all migrations.

        Args:
            applied_migrations: List of applied migrations from database
            pending_migrations: List of pending migrations from filesystem
            failed_migrations: List of failed migrations

        Returns:
            List of dictionaries containing migration data with display information
        """
        migration_data = []

        # Analyze applied migrations to get context
        context = self._build_analysis_context(applied_migrations)

        # Process applied migrations
        for migration in applied_migrations:
            try:
                state = self._determine_migration_state(migration, context)

                # Get category and clean description for DELETE entries
                category = self._get_migration_category(migration)
                description = str(getattr(migration, "description", ""))

                # Debug output for DELETE entries
                m_type = self._get_migration_type(migration)
                if m_type == "DELETE":
                    self.logger.debug(
                        f"[APPLIED] DELETE entry: script={getattr(migration, 'script_name', '')}, "
                        f"type={m_type}, category={category}, state={state.value}, desc={description}"
                    )

                # Clean description for DELETE entries - remove [DELETE:TYPE] prefix
                if description.startswith("[DELETE:") and "]" in description:
                    description = description[description.index("]") + 1 :].strip()

                migration_info = {
                    "category": category,
                    "version": self._format_version(getattr(migration, "version", None)),
                    "description": description,
                    "type": str(getattr(migration, "type", "")),
                    "installed_on": getattr(migration, "installed_on", None),
                    "state": state.value,
                    "execution_time": getattr(migration, "execution_time", 0),
                    "script": str(getattr(migration, "script_name", "")),
                    "checksum": str(getattr(migration, "checksum", "")),
                    "installed_by": str(getattr(migration, "installed_by", "")),
                    "installed_rank": getattr(migration, "installed_rank", 0),
                    "success": getattr(migration, "success", None),
                    "resolved": getattr(migration, "resolved", True),
                    "source": "applied",
                }

                migration_data.append(migration_info)

            except Exception as e:
                self.logger.warning(
                    f"Error processing applied migration {getattr(migration, 'script_name', 'unknown')}: {e}"
                )
                continue

        # Process pending migrations
        if pending_migrations:
            for migration in pending_migrations:
                try:
                    state = self.state_service.determine_pending_state(migration, context)

                    migration_info = {
                        "category": self._get_migration_category(migration),
                        "version": self._format_version(getattr(migration, "version", None)),
                        "description": str(getattr(migration, "description", "")),
                        "type": str(getattr(migration, "type", "")),
                        "installed_on": None,
                        "state": state.value,
                        "execution_time": None,
                        "script": str(getattr(migration, "script_name", "")),
                        "checksum": str(getattr(migration, "checksum", "")),
                        "installed_by": None,
                        "installed_rank": None,
                        "success": None,
                        "resolved": getattr(migration, "resolved", True),
                        "source": "pending",
                    }

                    migration_data.append(migration_info)

                except Exception as e:
                    self.logger.warning(
                        f"Error processing pending migration {getattr(migration, 'script_name', 'unknown')}: {e}"
                    )
                    continue

        # Ensure undone migrations are included in pending if they have undo scripts
        migration_data = self._ensure_undone_migrations_in_pending(migration_data, context)

        return migration_data

    def _build_analysis_context(self, applied_migrations: List[Migration]) -> Dict[str, Any]:
        """Build context for migration state analysis.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            Dictionary containing analysis context
        """
        # Sort migrations by installed rank for analysis
        sorted_migrations = self._sort_applied_migrations(applied_migrations)

        # Build analysis data
        undone_versions = self._get_undone_versions(sorted_migrations)
        reapplied_versions = self._get_reapplied_versions(sorted_migrations)
        baseline_version = self._get_baseline_version(sorted_migrations)
        out_of_order_migrations = self._detect_out_of_order_migrations(sorted_migrations)
        repeatable_checksums = self._build_repeatable_checksums(sorted_migrations)
        current_version = self._get_current_version(sorted_migrations)

        return {
            "undone_versions": undone_versions,
            "reapplied_versions": reapplied_versions,
            "baseline_version": baseline_version,
            "out_of_order_migrations": out_of_order_migrations,
            "repeatable_checksums": repeatable_checksums,
            "current_version": current_version,
            "target_version": self.target_version,
            "scripts_dir": self.scripts_dir,
        }

    def _determine_migration_state(
        self, migration: Any, context: Dict[str, Any]
    ) -> MigrationDisplayState:
        """Determine the display state for a migration.

        Args:
            migration: Migration to analyze
            context: Analysis context

        Returns:
            MigrationDisplayState: Appropriate display state
        """
        return self.state_service.determine_state(migration, context)

    def _ensure_undone_migrations_in_pending(
        self, migration_data: List[Dict[str, Any]], context: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """Ensure undone migrations with available undo scripts are shown in pending.

        Args:
            migration_data: Current migration data
            context: Analysis context

        Returns:
            Updated migration data with undone migrations as pending
        """
        undone_versions = context.get("undone_versions", set())
        scripts_dir = context.get("scripts_dir")

        if not undone_versions or not scripts_dir:
            return migration_data

        # Check each undone version for undo scripts
        for version in undone_versions:
            if self._version_has_undo_script(version, scripts_dir):
                # Check if we already have this as pending
                has_pending = any(
                    item["version"] == version and item["source"] == "pending"
                    for item in migration_data
                )

                if not has_pending:
                    # Find the original migration for description
                    original = next(
                        (
                            item
                            for item in migration_data
                            if item["version"] == version and item["type"] in VERSIONED_SCRIPT_TYPES
                        ),
                        None,
                    )

                    description = (
                        original["description"] if original else f"Undo migration {version}"
                    )

                    # Add as available undo migration
                    undo_migration = {
                        "category": "Undo",
                        "version": version,
                        "description": description,
                        "type": "UNDO_SQL",
                        "installed_on": None,
                        "state": MigrationDisplayState.AVAILABLE.value,
                        "execution_time": None,
                        "script": f"U{version}__.sql",
                        "checksum": "",
                        "installed_by": None,
                        "installed_rank": None,
                        "success": None,
                        "resolved": True,
                        "source": "pending",
                    }

                    migration_data.append(undo_migration)

        return migration_data

    def _get_undone_versions(self, migrations: List[Migration]) -> Set[str]:
        """Get set of versions that have been undone.

        Args:
            migrations: List of migrations to analyze

        Returns:
            Set of undone version strings
        """
        undone_versions = set()

        for migration in migrations:
            if self._get_migration_type(migration) == "UNDO_SQL":
                version = getattr(migration, "version", None)
                if version and self._is_migration_successful(migration):
                    undone_versions.add(str(version))

        return undone_versions

    def _get_reapplied_versions(self, migrations: List[Migration]) -> Set[str]:
        """Get set of versions that were reapplied after being undone.

        Args:
            migrations: List of migrations to analyze

        Returns:
            Set of reapplied version strings
        """
        reapplied_versions = set()
        undone_versions = self._get_undone_versions(migrations)

        # Find versioned migrations that were applied after their undo
        for migration in migrations:
            if self._get_migration_type(migration) in VERSIONED_SCRIPT_TYPES:
                version = getattr(migration, "version", None)
                if version and str(version) in undone_versions:
                    if self._is_migration_successful(migration):
                        # Check if this migration was applied after the undo
                        if self._is_version_reapplied(migrations, str(version)):
                            reapplied_versions.add(str(version))

        return reapplied_versions

    def _is_version_reapplied(self, migrations: List[Migration], version: str) -> bool:
        """Check if a version was reapplied after being undone.

        Args:
            migrations: List of migrations
            version: Version to check

        Returns:
            bool: True if version was reapplied
        """
        undo_rank = self._get_undo_rank(migrations, version)
        if undo_rank == -1:
            return False

        # Find the highest rank for this version after the undo
        max_rank_after_undo = -1
        for migration in migrations:
            if (
                self._get_migration_type(migration) in VERSIONED_SCRIPT_TYPES
                and str(getattr(migration, "version", "")) == version
            ):
                rank = getattr(migration, "installed_rank", 0)
                if rank > undo_rank:
                    max_rank_after_undo = max(max_rank_after_undo, rank)

        return max_rank_after_undo > undo_rank

    def _get_undo_rank(self, migrations: List[Migration], version: str) -> int:
        """Get the installed rank of the undo migration for a version.

        Args:
            migrations: List of migrations
            version: Version to find undo rank for

        Returns:
            int: Installed rank of undo migration, or -1 if not found
        """
        for migration in migrations:
            if (
                self._get_migration_type(migration) == "UNDO_SQL"
                and str(getattr(migration, "version", "")) == version
                and self._is_migration_successful(migration)
            ):
                return getattr(migration, "installed_rank", 0)
        return -1

    def _get_baseline_version(self, applied_migrations: List[Migration]) -> Optional[str]:
        """Get the baseline version from applied migrations.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            Optional[str]: Baseline version if found
        """
        for migration in applied_migrations:
            if self._get_migration_type(migration) == "BASELINE":
                return str(getattr(migration, "version", ""))
        return None

    def _detect_out_of_order_migrations(self, applied_migrations: List[Migration]) -> Set[str]:
        """Detect migrations that were applied out of order.

        Args:
            applied_migrations: List of applied migrations sorted by rank

        Returns:
            Set of version strings that were applied out of order
        """
        out_of_order = set()
        last_version_parts: list[int] = []

        for migration in applied_migrations:
            if self._get_migration_type(migration) not in VERSIONED_SCRIPT_TYPES:
                continue

            version = str(getattr(migration, "version", ""))
            if not version:
                continue

            try:
                # Parse version into parts for comparison
                version_parts = []
                for part in version.replace("_", ".").split("."):
                    try:
                        version_parts.append(int(part))
                    except ValueError:
                        version_parts.append(0)

                # Check if this version is lower than the previous one
                if (
                    last_version_parts
                    and self._compare_version_parts(version_parts, last_version_parts) < 0
                ):
                    out_of_order.add(version)

                last_version_parts = version_parts

            except Exception as e:
                self.logger.debug(f"Could not parse version for out-of-order detection: {e}")
                continue

        return out_of_order

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
        v1_parts_padded = v1_parts + [0] * (max_len - len(v1_parts))
        v2_parts_padded = v2_parts + [0] * (max_len - len(v2_parts))

        for i in range(max_len):
            if v1_parts_padded[i] < v2_parts_padded[i]:
                return -1
            elif v1_parts_padded[i] > v2_parts_padded[i]:
                return 1

        return 0

    def _build_repeatable_checksums(self, applied_migrations: List[Migration]) -> Dict[str, str]:
        """Build a map of repeatable migration checksums.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            Dict mapping script names to their latest checksums
        """
        repeatable_checksums = {}

        for migration in applied_migrations:
            if self._get_migration_type(migration) == "REPEATABLE":
                script_name = str(getattr(migration, "script_name", ""))
                checksum = str(getattr(migration, "checksum", ""))
                if script_name and checksum:
                    repeatable_checksums[script_name] = checksum

        return repeatable_checksums

    def _sort_applied_migrations(self, applied_migrations: List[Migration]) -> List[Migration]:
        """Sort applied migrations by installed rank.

        Args:
            applied_migrations: List of migrations to sort

        Returns:
            List of migrations sorted by installed rank
        """
        return sorted(applied_migrations, key=lambda m: getattr(m, "installed_rank", 0))

    def _version_has_undo_script(self, version: str, scripts_dir: Optional[Path]) -> bool:
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
            # Look for undo scripts with pattern U{version}*.sql
            undo_pattern = f"U{version}*.sql"
            undo_files = list(scripts_dir.glob(undo_pattern))
            return len(undo_files) > 0
        except Exception as e:
            self.logger.debug(f"Could not check for undo scripts: {e}")
            return False

    def _format_version(self, version: Optional[str]) -> str:
        """Format version string for display.

        Args:
            version: Version string to format

        Returns:
            Formatted version string
        """
        if not version:
            return ""
        return str(version).replace("_", ".")

    def _get_migration_category(self, migration: Any) -> str:
        """Get the display category for a migration.

        Args:
            migration: Migration object

        Returns:
            str: Display category
        """
        m_type = self._get_migration_type(migration)

        if m_type in VERSIONED_SCRIPT_TYPES:
            return "Versioned"
        elif m_type == "REPEATABLE":
            return "Repeatable"
        elif m_type == "UNDO_SQL":
            return "Undo"
        elif m_type == "BASELINE":
            return "Baseline"
        elif m_type == "DELETE":
            # For DELETE entries, extract original type from description
            # Description format: [DELETE:ORIGINAL_TYPE] reason
            description = getattr(migration, "description", "")
            if description and "[DELETE:" in description:
                try:
                    # Extract original type
                    start = description.index("[DELETE:") + 8
                    end = description.index("]", start)
                    original_type = description[start:end].strip()
                    self.logger.debug(f"Extracted original type: {original_type}")

                    # Map to display category
                    if original_type in VERSIONED_SCRIPT_TYPES:
                        return "Versioned"
                    elif original_type == "REPEATABLE":
                        return "Repeatable"
                    elif original_type == "UNDO_SQL":
                        return "Undo"
                    else:
                        return original_type.capitalize()
                except (ValueError, IndexError):
                    pass

            # Fallback: try to infer from script name
            script_name = getattr(migration, "script_name", "")
            if script_name.startswith("V"):
                return "Versioned"
            elif script_name.startswith("R"):
                return "Repeatable"
            elif script_name.startswith("U"):
                return "Undo"

            return "Deleted"
        else:
            return m_type.capitalize() if m_type else "Unknown"

    def _get_migration_type(self, migration: Any) -> str:
        """Get the migration type as uppercase string.

        Args:
            migration: Migration object

        Returns:
            str: Migration type in uppercase
        """
        from core.migration._type_match import migration_type_name

        return migration_type_name(getattr(migration, "type", None)).upper()

    def _is_migration_successful(self, migration: Any) -> bool:
        """Check if a migration was successful.

        Args:
            migration: Migration object

        Returns:
            bool: True if migration was successful
        """
        success = getattr(migration, "success", None)
        return is_migration_success(success)

    def _get_current_version(self, applied_migrations: List[Migration]) -> Optional[str]:
        """Get the current version from successfully applied versioned migrations.

        Args:
            applied_migrations: List of applied migrations

        Returns:
            Optional[str]: Current version if found
        """
        current_version = None

        for migration in applied_migrations:
            if self._get_migration_type(
                migration
            ) in VERSIONED_SCRIPT_TYPES and self._is_migration_successful(migration):
                version = str(getattr(migration, "version", ""))
                if version:
                    # Keep track of the highest version
                    if not current_version:
                        current_version = version
                    else:
                        try:
                            if _compare_versions_shared(version, current_version) > 0:
                                current_version = version
                        except Exception as e:
                            self.logger.debug(
                                f"Version comparison failed, using string fallback: {e}"
                            )
                            if version > current_version:
                                current_version = version

        return current_version
