"""
Migration data collection and preparation.

This module handles the complex logic for collecting, analyzing, and structuring
migration data from various sources (applied migrations, pending migrations,
filesystem) for display purposes.
"""

import functools
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from core.logger import Log, NullLog
from core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration
from core.migration.scripting.migration_script_manager import MigrationScriptManager
from core.migration.state.migration_display_state import MigrationDisplayState
from core.migration.state.migration_state import MigrationState
from core.migration.version_utils import compare_versions as _compare_versions_shared


class MigrationDataCollector:
    """Collects and structures migration data for display."""

    def __init__(self, log: Log, script_manager: Optional[MigrationScriptManager] = None):
        """Initialize the data collector.

        Args:
            log: Logger instance
            script_manager: Script manager instance (optional)
        """
        self.log = log if log is not None else NullLog()
        self.script_manager = script_manager

    def _format_installed_on(self, installed_on: Any) -> str:
        """Format installed_on timestamp for display.

        Handles both datetime objects and ISO string formats (e.g., from CosmosDB).

        Args:
            installed_on: Timestamp as datetime object or ISO string

        Returns:
            Formatted timestamp string or empty string
        """
        if not installed_on:
            return ""

        try:
            if hasattr(installed_on, "strftime"):
                # It's a datetime object
                return str(installed_on.strftime("%Y-%m-%d %H:%M:%S"))
            elif isinstance(installed_on, str):
                # It's an ISO string (e.g., from CosmosDB)
                from datetime import datetime

                try:
                    # Try to parse ISO format and reformat
                    # Handle both with and without timezone
                    if installed_on.endswith("Z"):
                        dt = datetime.fromisoformat(installed_on.replace("Z", "+00:00"))
                    else:
                        dt = datetime.fromisoformat(installed_on)
                    return dt.strftime("%Y-%m-%d %H:%M:%S")
                except (ValueError, AttributeError):
                    # If parsing fails, use the string as-is (truncate if too long)
                    return installed_on[:19] if len(installed_on) > 19 else installed_on
            else:
                return str(installed_on)
        except Exception as e:
            self.log.debug(f"Could not format installed_on timestamp: {e}")
            return str(installed_on) if installed_on else ""

    def _get_migration_type_string(self, migration_type: Any) -> str:
        """Safely get migration type as string, handling both enum and string types.

        Delegates to the shared helper in ``core.migration._type_match``;
        kept as a method for backwards compatibility with existing call sites.
        """
        from core.migration._type_match import migration_type_name

        return migration_type_name(migration_type)

    def _is_migration_type_equal(self, migration_type: Any, target_type: str) -> bool:
        """Check if migration type matches target type, handling both enum and string types.

        Delegates to the shared helper in ``core.migration._type_match``;
        kept as a method for backwards compatibility with existing call sites.
        """
        from core.migration._type_match import is_migration_type

        return is_migration_type(migration_type, target_type)

    def _is_versioned_type(self, migration_type: Any) -> bool:
        """Return True for any versioned script type (SQL, PYTHON, etc.).

        Delegates to the shared VERSIONED_SCRIPT_TYPES constant so adding a new
        versioned type (e.g. SHELL) registers here automatically.
        """
        return any(self._is_migration_type_equal(migration_type, t) for t in VERSIONED_SCRIPT_TYPES)

    def get_migration_data(
        self,
        migration_state: MigrationState,
        all_applied_migrations: List[Migration],
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get structured migration data suitable for any formatter (console, HTML, JSON).

        Args:
            migration_state: MigrationState object (contains all state info)
            all_applied_migrations: All migrations from history in chronological order
            scripts_dir: Directory containing migration scripts
            target_version: Target version for filtering
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude
        """
        return self._get_migration_data_from_state(
            migration_state=migration_state,
            all_applied_migrations=all_applied_migrations,
            scripts_dir=scripts_dir,
            target_version=target_version,
            tags=tags,
            exclude_tags=exclude_tags,
            versions=versions,
            exclude_versions=exclude_versions,
        )

    def _get_migration_data_from_state(
        self,
        migration_state: MigrationState,
        all_applied_migrations: List[Migration],
        scripts_dir: Optional[Path] = None,
        target_version: Optional[str] = None,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get migration data from MigrationState (new implementation).

        This method uses the StateManager's state to show:
        1. All migrations in chronological order by installed_rank
        2. Undone migrations marked as "UNDONE" (not "SUCCESS")
        3. Pending migrations at the end

        Args:
            migration_state: MigrationState object containing all state information
            all_applied_migrations: All migrations from history table (not filtered)
            scripts_dir: Directory containing migration scripts
            target_version: Target version for filtering
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude

        Returns:
            List of migration data dictionaries
        """
        if self.script_manager is None:
            logger = self.log
            self.script_manager = MigrationScriptManager(logger, "utf-8")

        # Get undo script versions from filesystem
        undo_versions = self._find_undo_versions(scripts_dir)

        # Sort all migrations by installed_rank to show complete sequential history
        sorted_applied_migrations = sorted(
            all_applied_migrations, key=lambda m: getattr(m, "installed_rank", 0) or 0
        )

        # Get pending migrations from state (already sorted by migration order)
        pending_migrations = migration_state.pending_objects

        # Build repeatable checksums map to filter out old repeatable executions
        repeatable_checksums = migration_state.repeatable_checksums

        # migration_state.applied/pending were built 1:1 (same order, same objects)
        # from migration_state.all_applied_objects/pending_objects by MigrationStateManager,
        # using MigrationStateService as the single source of truth for status. Reuse those
        # already-computed statuses instead of re-deriving them here.
        applied_status_by_id = {
            id(migration): entry.status
            for migration, entry in zip(migration_state.all_applied_objects, migration_state.applied)
        }
        pending_status_by_id = {
            id(migration): entry.status
            for migration, entry in zip(migration_state.pending_objects, migration_state.pending)
        }

        migrations_data = []

        # Process all applied migrations in chronological order
        for migration in sorted_applied_migrations:
            migration_type = getattr(migration, "type", None)
            version = getattr(migration, "version", None)
            script_name = migration.script_name
            installed_on = getattr(migration, "installed_on", None)
            execution_time = getattr(migration, "execution_time", 0)
            installed_rank = getattr(migration, "installed_rank", None)
            checksum = getattr(migration, "checksum", None)
            installed_by = getattr(migration, "installed_by", None)

            # Skip if this version should be excluded based on filters
            if self._should_exclude_migration(
                version,
                script_name,
                tags or [],
                exclude_tags or [],
                versions or [],
                exclude_versions or [],
            ):
                continue

            # For repeatable migrations, only show the latest execution (by checksum)
            if self._is_migration_type_equal(migration_type, "REPEATABLE"):
                if script_name in repeatable_checksums:
                    latest_checksum = repeatable_checksums[script_name]
                    if checksum and checksum != latest_checksum:
                        # This is an older execution of the repeatable migration, skip it
                        continue

            # Status is already computed by MigrationStateService (via build_state()).
            state = applied_status_by_id.get(id(migration), MigrationDisplayState.UNKNOWN.value)

            migrations_data.append(
                {
                    "category": self._get_category_from_type(
                        self._get_migration_type_string(migration_type), migration
                    ),
                    "version": self._format_version(version),
                    "description": self._clean_delete_description(
                        getattr(migration, "description", "")
                    ),
                    "type": self._get_type_from_migration_type(migration_type, script_name),
                    "installed_on": self._format_installed_on(installed_on),
                    "installed_by": installed_by or "",
                    "state": state,
                    "undoable": version in undo_versions if version else False,
                    "filepath": getattr(migration, "filepath", ""),
                    "script": script_name,
                    "execution_time": execution_time or 0,
                    "installed_rank": installed_rank,
                    "checksum": checksum,
                }
            )

        # Process pending migrations at the end (in execution order)
        # Execution order: versioned first (sorted by version), then repeatable (sorted by script name)
        sorted_pending = sorted(
            pending_migrations,
            key=functools.cmp_to_key(self._compare_pending_migrations),
        )

        for migration in sorted_pending:
            script_name = migration.script_name
            version = getattr(migration, "version", None)
            migration_type = getattr(migration, "type", None)

            # Skip if should be excluded
            if self._should_exclude_migration(
                version,
                script_name,
                tags or [],
                exclude_tags or [],
                versions or [],
                exclude_versions or [],
            ):
                continue

            # Status is already computed by MigrationStateService (via build_state()).
            state = pending_status_by_id.get(id(migration), MigrationDisplayState.PENDING.value)

            migrations_data.append(
                {
                    "category": self._get_category_from_type(
                        self._get_migration_type_string(migration_type), migration
                    ),
                    "version": self._format_version(version),
                    "description": self._clean_delete_description(
                        getattr(migration, "description", "")
                    ),
                    "type": self._get_type_from_migration_type(migration_type, script_name),
                    "installed_on": "",
                    "installed_by": "",
                    "state": state,
                    "undoable": version in undo_versions if version else False,
                    "filepath": getattr(migration, "filepath", ""),
                    "script": script_name,
                    "execution_time": 0,
                    "installed_rank": None,
                }
            )

        return migrations_data

    def _find_undo_versions(self, scripts_dir: Optional[Path]) -> Set[str]:
        """Find versions that have undo capability available.

        A version is undoable if it has a separate undo companion script:
        ``U*.sql`` for SQL migrations or ``U*.py`` for Python migrations.
        Python undo companions use the same ``def migrate(context)`` contract
        as versioned scripts; they are not selected by an inline ``undo`` on ``V*``.
        """
        undo_versions = set()
        if scripts_dir and scripts_dir.exists() and self.script_manager is not None:
            for pattern in ("U*.sql", "U*.py"):
                for file_path in scripts_dir.rglob(pattern):
                    version = self.script_manager.extract_version(file_path.name)
                    if version:
                        undo_versions.add(version)
        return undo_versions

    def _should_exclude_migration(
        self,
        version: Optional[str],
        script_name: str,
        tags: List[str],
        exclude_tags: List[str],
        versions: List[str],
        exclude_versions: List[str],
    ) -> bool:
        """Check if migration should be excluded based on filters."""
        # Versions inclusion filter
        if versions and version and version not in versions:
            return True

        # Versions exclusion filter
        if exclude_versions and version in exclude_versions:
            return True

        # Extract tags from script name if script_manager is available
        migration_tags = []
        if self.script_manager is not None:
            migration_tags = self.script_manager.extract_tags(script_name) or []

        # Tags inclusion filter: migration must have at least one matching tag
        if tags:
            if not migration_tags or not any(tag in migration_tags for tag in tags):
                return True

        # Tags exclusion filter: migration must not have any excluded tags
        if exclude_tags:
            if migration_tags and any(tag in migration_tags for tag in exclude_tags):
                return True

        return False

    def _clean_delete_description(self, description: str) -> str:
        """Remove [DELETE:TYPE] prefix from description.

        Args:
            description: Original description

        Returns:
            Cleaned description
        """
        if description and description.startswith("[DELETE:") and "]" in description:
            try:
                return description[description.index("]") + 1 :].strip()
            except (ValueError, IndexError):
                return description
        return description

    def _get_category_from_type(self, migration_type: str, migration: Any = None) -> str:
        """Get display category from migration type.

        For DELETE entries, extracts the original type from the description.

        Args:
            migration_type: Migration type string
            migration: Optional migration object (needed for DELETE entries)

        Returns:
            Display category string
        """
        type_to_category = {
            "SQL": "Versioned",
            "PYTHON": "Versioned",
            "REPEATABLE": "Repeatable",
            "CALLBACK": "Callback",
            "BASELINE": "Baseline",
            "UNDO_SQL": "Undo",
        }

        # For DELETE entries, extract original type from description
        if migration_type == "DELETE" and migration:
            description = getattr(migration, "description", "")
            if description and "[DELETE:" in description:
                try:
                    # Extract original type from [DELETE:TYPE] prefix
                    start = description.index("[DELETE:") + 8
                    end = description.index("]", start)
                    original_type = description[start:end].strip()
                    # Return category for original type
                    return type_to_category.get(original_type, original_type.capitalize())
                except (ValueError, IndexError):
                    pass

            # Fallback: infer from script name
            script_name = getattr(migration, "script_name", "")
            if script_name.startswith("V"):
                return "Versioned"
            elif script_name.startswith("R"):
                return "Repeatable"
            elif script_name.startswith("U"):
                return "Undo"

            # Last fallback
            return "Deleted"

        return type_to_category.get(migration_type, "Unknown")

    def _get_type_from_migration_type(self, migration_type: Any, script_name: str = "") -> str:
        """Get display type from migration type enum.

        Args:
            migration_type: MigrationType enum or string
            script_name: Script file name — used to distinguish Python from SQL
                repeatable migrations (history stores type=REPEATABLE for both).
        """
        if not migration_type:
            return "UNKNOWN"

        # Get the enum name or string value using helper function
        type_name = self._get_migration_type_string(migration_type)

        # REPEATABLE covers both .sql and .py scripts; the history table stores
        # type=REPEATABLE regardless of the script's extension.  Infer the real
        # format from the filename so Python repeatables show "Python", not "SQL".
        if type_name == "REPEATABLE" and (script_name or "").lower().endswith(".py"):
            return "Python"

        # Map migration types to display types
        type_mapping = {
            "SQL": "SQL",
            "PYTHON": "Python",
            "REPEATABLE": "SQL",
            "CALLBACK": "SQL",
            "BASELINE": "SQL",
            "UNDO_SQL": "UNDO_SQL",
            "DELETE": "SQL",
        }

        return type_mapping.get(type_name, "UNKNOWN")

    def _format_version(self, version: Optional[str]) -> str:
        """Format version for display."""
        return version if version else ""

    def _compare_versions(self, version1: Optional[str], version2: Optional[str]) -> int:
        """Compare two version strings. Delegates to shared compare_versions utility."""
        return _compare_versions_shared(version1, version2)

    def _compare_pending_migrations(self, m1: Migration, m2: Migration) -> int:
        """Order pending migrations for display: versioned before repeatable,
        versioned entries in numeric version order, then by script name."""
        type1 = 0 if self._is_versioned_type(getattr(m1, "type", None)) else 1
        type2 = 0 if self._is_versioned_type(getattr(m2, "type", None)) else 1
        if type1 != type2:
            return type1 - type2

        if type1 == 0:
            version_cmp = self._compare_versions(
                getattr(m1, "version", "") or "", getattr(m2, "version", "") or ""
            )
            if version_cmp != 0:
                return version_cmp

        script1 = getattr(m1, "script_name", "")
        script2 = getattr(m2, "script_name", "")
        return -1 if script1 < script2 else (1 if script1 > script2 else 0)
