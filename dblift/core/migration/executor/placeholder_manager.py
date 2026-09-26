"""
Placeholder management for migration executor.

This module handles initialization and replacement of placeholders in SQL scripts.
"""

from datetime import datetime
from typing import TYPE_CHECKING, Any, Dict, Optional

if TYPE_CHECKING:
    from dblift.core.migration.placeholders.placeholder_service import PlaceholderService

from dblift.config import DbliftConfig
from dblift.config.database_config import BaseDatabaseConfig
from dblift.core.logger import Log, NullLog
from dblift.db.object_naming import configured_identifier_text, dictionary_identifier


def _dblift_schema_placeholder(database: BaseDatabaseConfig) -> Optional[str]:
    """Value of ``${dblift_schema}``.

    Oracle expands to the catalog spelling with the quotes removed: unquoted
    ``myschema`` becomes ``MYSCHEMA``, and ``"myschema"`` stays ``myschema``.
    Other dialects keep the configured text. A null schema stays ``None``.
    """
    schema = database.schema
    if not isinstance(schema, str):
        return None
    # Unquoted Oracle names are uppercased everywhere else dblift uses them.
    if database.type == "oracle":  # lint: allow-dialect-string: catalog spelling
        return dictionary_identifier(schema, database.type)
    return configured_identifier_text(schema)


class PlaceholderManager:
    """Manages placeholders for SQL migration scripts."""

    def __init__(self, config: DbliftConfig, log: Log, executor: Optional[Any] = None):
        """Initialize the placeholder manager.

        Args:
            config: Application configuration
            log: Logger instance
            executor: The migration executor (for getting installed_by)
        """
        self.config = config
        self.log = log if log is not None else NullLog()
        self.executor = executor
        self.placeholder_service: Optional["PlaceholderService"] = None  # Will be set by executor

    def init_placeholders(self) -> Dict[str, Any]:
        """Initialize placeholders dictionary with both default and user-defined placeholders.

        Returns:
            Dictionary of placeholders and their values
        """
        placeholders = {
            # Default system placeholders with dblift_ prefix.
            "dblift_database": getattr(
                self.config.database,
                "database",
                getattr(
                    self.config.database,
                    "database_name",
                    getattr(self.config.database, "host", None),
                ),
            ),
            "dblift_timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "dblift_date": datetime.now().strftime("%Y-%m-%d"),
            "dblift_time": datetime.now().strftime("%H:%M:%S"),
            "dblift_username": (
                self.executor.get_installed_by() if self.executor else self.config.database.username
            ),
        }
        schema = _dblift_schema_placeholder(self.config.database)
        if schema is not None:
            placeholders["dblift_schema"] = schema
        # Add user-defined placeholders if present
        if hasattr(self.config, "placeholders") and self.config.placeholders:
            placeholders.update(self.config.placeholders)
        return placeholders

    def replace_placeholders(self, sql_text: str) -> str:
        """Replace placeholders in SQL text with their values.

        Uses the PlaceholderService for consistent placeholder handling.

        Args:
            sql_text: The SQL text containing placeholders

        Returns:
            SQL text with placeholders replaced by actual values
        """
        # The placeholder_service was initialized in __init__
        if self.placeholder_service is None:
            return sql_text  # Return unchanged if service not available
        return self.placeholder_service.replace_placeholders(sql_text)
