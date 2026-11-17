"""
Migration data collection and preparation.

This module handles the complex logic for collecting, analyzing, and structuring
migration data from various sources (applied migrations, pending migrations,
filesystem) for display purposes.
"""

import functools
from typing import Any, Dict, List, Optional, Set

from dblift.core.logger import Log, NullLog
from dblift.core.logger.results import is_failed_migration_status
from dblift.core.migration._type_match import is_migration_type, migration_type_name
from dblift.core.migration.migration import VERSIONED_SCRIPT_TYPES, Migration
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.state.migration_display_state import MigrationDisplayState
from dblift.core.migration.state.migration_selector import passes_tag_filters
from dblift.core.migration.state.migration_state import MigrationEligibility, MigrationState
from dblift.core.migration.version_utils import compare_versions


class MigrationDataCollector:
    """Collects and structures migration data for display."""

    def __init__(self, log: Log, script_manager: MigrationScriptManager):
        """Initialize the data collector.

        Args:
            log: Logger instance
            script_manager: Script manager used to read tags from script names
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

    def _is_versioned_type(self, migration_type: Any) -> bool:
        """Return True for any versioned script type (SQL, PYTHON, etc.).

        Delegates to the shared VERSIONED_SCRIPT_TYPES constant so adding a new
        versioned type (e.g. SHELL) registers here automatically.
        """
        return any(is_migration_type(migration_type, t) for t in VERSIONED_SCRIPT_TYPES)

    def get_migration_data(
        self,
        migration_state: MigrationState,
        tags: Optional[List[str]] = None,
        exclude_tags: Optional[List[str]] = None,
        versions: Optional[List[str]] = None,
        exclude_versions: Optional[List[str]] = None,
    ) -> List[Dict[str, Any]]:
        """Get structured migration data suitable for any formatter (console, HTML, JSON).

        Uses the state's manager-computed statuses to show:
        1. All migrations from history in chronological order by installed_rank
        2. Undone migrations marked as "UNDONE" (not "SUCCESS")
        3. Pending migrations at the end

        Args:
            migration_state: MigrationState object (contains all state info)
            tags: Tags to include
            exclude_tags: Tags to exclude
            versions: Versions to include
            exclude_versions: Versions to exclude

        Returns:
            List of migration data dictionaries
        """
        filters = (tags or [], exclude_tags or [], versions or [], exclude_versions or [])

        # Use the same resolved undo catalogue that the undo command consumes.
        undo_versions = self._find_undo_versions(migration_state)

        # Sort all migrations by installed_rank to show complete sequential history
        sorted_applied_migrations = sorted(
            migration_state.all_applied_objects, key=lambda m: getattr(m, "installed_rank", 0) or 0
        )

        # Get pending migrations from state (already sorted by migration order)
        pending_migrations = migration_state.pending_objects

        # Applied rows come from the manager and unresolved display rows are
        # derived from the typed catalog. Reuse their existing display statuses.
        applied_status_by_id = {
            id(migration): entry.status
            for migration, entry in zip(
                migration_state.all_applied_objects, migration_state.applied
            )
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

            # Status is already computed by MigrationStateService (via build_state()).
            state = applied_status_by_id.get(id(migration), MigrationDisplayState.UNKNOWN.value)

            # Flyway removeUndos: completed undo scripts are not table rows. A
            # failed one is kept: it blocks validate, migrate and undo.
            if is_migration_type(migration_type, "UNDO_SQL") and not is_failed_migration_status(
                state
            ):
                continue

            # Skip if this version should be excluded based on filters
            if self._should_exclude_migration(version, script_name, *filters):
                continue

            row = self._display_row(
                migration, version, migration_type, script_name, state, undo_versions
            )
            row.update(
                installed_on=self._format_installed_on(installed_on),
                installed_by=installed_by or "",
                execution_time=execution_time or 0,
                installed_rank=installed_rank,
                checksum=checksum,
            )
            migrations_data.append(row)

        # Process pending migrations at the end (in execution order)
        # Execution order: versioned first (sorted by version), then repeatable (sorted by script
        # name)
        sorted_pending = sorted(
            pending_migrations,
            key=functools.cmp_to_key(self._compare_pending_migrations),
        )

        for migration in sorted_pending:
            script_name = migration.script_name
            version = getattr(migration, "version", None)
            migration_type = getattr(migration, "type", None)

            # Flyway removeUndos: undo scripts are not table rows.
            if is_migration_type(migration_type, "UNDO_SQL"):
                continue

            # Skip if should be excluded
            if self._should_exclude_migration(version, script_name, *filters):
                continue

            # Status is already computed by MigrationStateService (via build_state()).
            state = pending_status_by_id.get(id(migration), MigrationDisplayState.PENDING.value)

            migrations_data.append(
                self._display_row(
                    migration, version, migration_type, script_name, state, undo_versions
                )
            )

        return migrations_data

    def _display_row(
        self,
        migration: Migration,
        version: Optional[str],
        migration_type: Any,
        script_name: str,
        state: Optional[str],
        undo_versions: Set[str],
    ) -> Dict[str, Any]:
        """Build a row as for a pending migration; applied rows fill in their history columns."""
        return {
            "category": self._get_category_from_type(
                migration_type_name(migration_type), migration
            ),
            "version": version or "",
            "description": self._clean_delete_description(getattr(migration, "description", "")),
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

    def _find_undo_versions(self, migration_state: MigrationState) -> Set[str]:
        """Find versions that have undo capability available.

        A version is undoable if it has a separate undo companion script:
        ``U*.sql`` for SQL migrations or ``U*.py`` for Python migrations.
        Python undo companions use the same ``def migrate(context)`` contract
        as versioned scripts; they are not selected by an inline ``undo`` on ``V*``.
        """
        return {
            str(record.migration.version)
            for record in migration_state.catalog
            if record.eligibility == MigrationEligibility.UNDO_AVAILABLE
            and getattr(record.migration, "version", None) is not None
        }

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

        # Extract tags from the script name
        migration_tags = self.script_manager.extract_tags(script_name) or []

        return not passes_tag_filters(migration_tags, tags, exclude_tags)

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
        type_name = migration_type_name(migration_type)

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

    def _compare_pending_migrations(self, m1: Migration, m2: Migration) -> int:
        """Order pending migrations for display: versioned before repeatable,
        versioned entries in numeric version order, then by script name."""
        type1 = 0 if self._is_versioned_type(getattr(m1, "type", None)) else 1
        type2 = 0 if self._is_versioned_type(getattr(m2, "type", None)) else 1
        if type1 != type2:
            return type1 - type2

        if type1 == 0:
            version_cmp = compare_versions(
                getattr(m1, "version", "") or "", getattr(m2, "version", "") or ""
            )
            if version_cmp != 0:
                return version_cmp

        script1 = getattr(m1, "script_name", "")
        script2 = getattr(m2, "script_name", "")
        return -1 if script1 < script2 else (1 if script1 > script2 else 0)
