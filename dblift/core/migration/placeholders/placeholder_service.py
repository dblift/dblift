"""Placeholder service — substitutes ${name} tokens in migration SQL with configured values."""

import re
from typing import Any, Dict, Optional

from dblift.core.logger import Log, NullLog


class PlaceholderService:
    """Service for handling placeholder replacement in SQL scripts.

    This service centralizes placeholder replacement logic used in both
    MigrationExecutor and MigrationValidator.
    """

    def __init__(
        self, placeholders: Optional[Dict[str, Any]] = None, logger: Optional[Log] = None
    ) -> None:
        """Initialize the placeholder service.

        Args:
            placeholders: Dictionary of placeholder values
            logger: Optional logger instance
        """
        self.placeholders = placeholders or {}
        self.log = logger if logger is not None else NullLog()

    def add_placeholders(self, new_placeholders: Dict[str, Any]) -> None:
        """Add new placeholders to the existing ones.

        Args:
            new_placeholders: Dictionary of new placeholder values
        """
        if not new_placeholders:
            return

        for key, value in new_placeholders.items():
            self.placeholders[key] = value

    def replace_placeholders(self, sql_text: str) -> str:
        """Replace placeholders in SQL text with their values.

        Supports placeholders in the format ${placeholder_name} or
        ${placeholder_name:default_value}.

        Args:
            sql_text: The SQL text containing placeholders

        Returns:
            SQL text with placeholders replaced by actual values
        """
        if not sql_text or "${" not in sql_text:
            return sql_text

        # Look for placeholders in the format ${placeholder_name} or ${placeholder_name:default_value}
        pattern = r"\$\{([^}]+)\}"

        def replace_match(match: "re.Match[str]") -> str:
            placeholder_full = match.group(1)

            # Check if placeholder includes a default value (format: name:default)
            if ":" in placeholder_full:
                placeholder_name, default_value = placeholder_full.split(":", 1)
                placeholder_name = placeholder_name.strip()
                default_value = default_value.strip()
            else:
                placeholder_name = placeholder_full.strip()
                default_value = None

            # Use the placeholder value if it exists
            if placeholder_name in self.placeholders:
                return str(self.placeholders[placeholder_name])
            # Use default value if provided
            elif default_value is not None:
                return default_value
            # Otherwise, log warning and leave unchanged — the ${NAME} token may
            # belong to another templating system and should pass through as-is.
            else:
                placeholder_str = f"${{{placeholder_name}}}"
                self.log.warning(f"Placeholder '{placeholder_str}' not found, leaving as is")
                return match.group(0)

        # Replace all matches
        return re.sub(pattern, replace_match, sql_text)
