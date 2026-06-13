"""
Display formatting utilities for migration UI.

This module contains utilities for formatting different aspects of migration
display, including states, categories, versions, and other display elements.
"""

from typing import Any, Optional, Tuple, cast

from core.logger import Log, NullLog
from core.migration.migration import VERSIONED_SCRIPT_TYPES
from core.migration.version_utils import compare_versions as _compare_versions_shared


class DisplayFormatters:
    """Utility class for formatting display elements."""

    def __init__(self, log: Log):
        """Initialize the display formatters.

        Args:
            log: Logger instance
        """
        self.log = log if log is not None else NullLog()

    def format_state(self, state: str) -> str:
        """Format migration state for display.

        Args:
            state: Raw migration state

        Returns:
            str: Formatted state string
        """
        state_mappings = {
            "SUCCESS": "✓ Applied",
            "APPLIED": "✓ Applied",
            "FAILED": "✗ Failed",
            "PENDING": "⋯ Pending",
            "UNDONE": "↶ Undone",
            "OUT OF ORDER": "⚠ Out of Order",
            "DELETED": "✗ Deleted",
            "UNKNOWN": "? Unknown",
        }

        return state_mappings.get(state.upper(), state)

    def format_category(self, category: str) -> str:
        """Format migration category for display.

        Args:
            category: Raw migration category

        Returns:
            str: Formatted category string
        """
        category_mappings = {
            "versioned": "📄 Versioned",
            "repeatable": "🔄 Repeatable",
            "callback": "⚡ Callback",
            "baseline": "📏 Baseline",
            "undo": "↶ Undo",
            "deleted": "🗑 Deleted",
            "delete": "🗑 Deleted",
        }

        return category_mappings.get(category.lower(), category)

    def format_version(self, version: Optional[str]) -> str:
        """Format version string for display.

        Args:
            version: Version string or None

        Returns:
            str: Formatted version string
        """
        return version if version else ""

    def get_category_and_display_type(self, m_type: str) -> Tuple[str, str]:
        """Get the category and display type for a migration type.

        Args:
            m_type: Migration type string

        Returns:
            tuple: (category, display_type)
        """
        type_mappings = {
            "SQL": ("Versioned", "versioned"),
            "PYTHON": ("Versioned", "python"),
            "REPEATABLE": ("Repeatable", "repeatable"),
            "CALLBACK": ("Callback", "callback"),
            "BASELINE": ("Baseline", "baseline"),
            "UNDO_SQL": ("Undo", "undo"),
            "DELETE": ("Deleted", "deleted"),
        }

        return type_mappings.get(m_type, ("Unknown", "unknown"))

    def determine_pending_migration_status(
        self,
        migration: Any,
        target_version: Optional[str] = None,
        current_version: Optional[str] = None,
        baseline_version: Optional[str] = None,
    ) -> str:
        """Determine the status of a pending migration.

        Args:
            migration: Migration object
            target_version: Target version for migration
            current_version: Current applied version
            baseline_version: Baseline version if any

        Returns:
            str: Status string for the pending migration
        """
        version = getattr(migration, "version", None)
        migration_type = getattr(migration, "type", None)
        # Normalize enum to its string value so comparisons work for both
        # MigrationType enum members and plain strings (e.g. from history records).
        if migration_type is not None and hasattr(migration_type, "value"):
            migration_type = migration_type.value

        # For repeatable and callback migrations, they're always "Pending"
        if migration_type in ("REPEATABLE", "CALLBACK"):
            return "Pending"

        # For versioned migrations, check version relationships
        if migration_type in VERSIONED_SCRIPT_TYPES and version:
            # Check if version is above target (if specified)
            if target_version:
                if self._compare_versions(version, target_version) > 0:
                    return "Above Target"

            # Check if version is below baseline (if specified)
            if baseline_version:
                if self._compare_versions(version, baseline_version) <= 0:
                    return "Below Baseline"

            return "Pending"

        return "Pending"

    def format_execution_time(self, execution_time: Optional[int]) -> str:
        """Format execution time for display.

        Args:
            execution_time: Execution time in milliseconds

        Returns:
            str: Formatted execution time string
        """
        if execution_time is None or execution_time == 0:
            return ""

        if execution_time < 1000:
            return f"{execution_time}ms"
        elif execution_time < 60000:
            seconds = execution_time / 1000
            return f"{seconds:.1f}s"
        else:
            minutes = execution_time / 60000
            return f"{minutes:.1f}min"

    def format_installed_on(self, installed_on: Any) -> str:
        """Format installation timestamp for display.

        Args:
            installed_on: Timestamp object

        Returns:
            str: Formatted timestamp string
        """
        if not installed_on:
            return ""

        try:
            if hasattr(installed_on, "strftime"):
                return cast(str, installed_on.strftime("%Y-%m-%d %H:%M:%S"))
            else:
                return str(installed_on)
        except (AttributeError, ValueError):
            return str(installed_on)

    def truncate_description(self, description: str, max_length: int = 50) -> str:
        """Truncate description for display in tables.

        Args:
            description: Description string
            max_length: Maximum length before truncation

        Returns:
            str: Truncated description with ellipsis if needed
        """
        if not description:
            return ""

        if len(description) <= max_length:
            return description

        return description[: max_length - 3] + "..."

    def format_file_path(self, filepath: str, max_length: int = 30) -> str:
        """Format file path for display, truncating if necessary.

        Args:
            filepath: Full file path
            max_length: Maximum display length

        Returns:
            str: Formatted file path
        """
        if not filepath:
            return ""

        if len(filepath) <= max_length:
            return filepath

        # Try to show just the filename if path is too long
        parts = filepath.split("/")
        filename = parts[-1] if parts else filepath

        if len(filename) <= max_length:
            return f".../{filename}"
        else:
            return filename[: max_length - 3] + "..."

    def get_status_indicator(self, success: bool) -> str:
        """Get a visual indicator for success/failure status.

        Args:
            success: Boolean success status

        Returns:
            str: Visual indicator
        """
        return "✓" if success else "✗"

    def _compare_versions(self, version1: str, version2: str) -> int:
        """Compare two version strings.

        Args:
            version1: First version
            version2: Second version

        Returns:
            int: -1 if v1 < v2, 0 if equal, 1 if v1 > v2
        """
        return _compare_versions_shared(version1, version2)
