"""Base ``SqlObject`` class and related ``SqlObjectType`` enum.

This module is part of the ``core.sql_model.base`` split (PR-H13). Public
import paths should continue to use ``from core.sql_model.base import ...``;
this module is re-exported by the ``base`` façade.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, Optional, Union


class SqlObjectType(Enum):
    """SQL object types that can be created, modified, or dropped."""

    TABLE = "TABLE"
    VIRTUAL_TABLE = "VIRTUAL_TABLE"  # SQLite CREATE VIRTUAL TABLE
    VIEW = "VIEW"
    INDEX = "INDEX"
    SEQUENCE = "SEQUENCE"
    PROCEDURE = "PROCEDURE"
    FUNCTION = "FUNCTION"
    TRIGGER = "TRIGGER"
    CONSTRAINT = "CONSTRAINT"
    SCHEMA = "SCHEMA"
    DATABASE = "DATABASE"
    TYPE = "TYPE"
    ROLE = "ROLE"
    USER = "USER"
    MATERIALIZED_VIEW = "MATERIALIZED_VIEW"
    PACKAGE = "PACKAGE"
    PACKAGE_BODY = "PACKAGE_BODY"
    SYNONYM = "SYNONYM"
    EVENT = "EVENT"  # MySQL scheduled events
    PARTITION = "PARTITION"  # Table partitions
    DATABASE_LINK = "DATABASE_LINK"  # Oracle database links
    EXTENSION = "EXTENSION"  # PostgreSQL extensions
    FOREIGN_DATA_WRAPPER = "FOREIGN_DATA_WRAPPER"  # PostgreSQL foreign data wrappers
    FOREIGN_SERVER = "FOREIGN_SERVER"  # PostgreSQL foreign servers
    UNKNOWN = "UNKNOWN"


class SqlObject:
    """Base class for SQL objects."""

    name: str
    object_type: SqlObjectType
    schema: Optional[str]
    dialect: Optional[str]
    explicit_properties: Optional[Dict[str, bool]]
    dialect_options: Dict[str, Dict[str, Any]]

    def __init__(
        self,
        name: str,
        object_type: Union[SqlObjectType, str],
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
    ) -> None:
        """Initialize a SQL object.

        Args:
            name: Object name
            object_type: Object type
            schema: Schema name (optional)
            dialect: SQL dialect (optional)
        """
        self.name = name

        # Handle both enum and string object types
        if isinstance(object_type, str):
            try:
                self.object_type = SqlObjectType[object_type.upper()]
            except KeyError:
                self.object_type = SqlObjectType.UNKNOWN
        else:
            self.object_type = object_type

        self.schema = schema
        self.dialect = dialect.lower() if dialect else None
        self.explicit_properties = {}
        self.dialect_options = {}

    def __str__(self) -> str:
        """Return string representation of the object."""
        if self.schema:
            return f"{self.object_type.value} {self.schema}.{self.name}"
        return f"{self.object_type.value} {self.name}"

    def __eq__(self, other: Any) -> bool:
        """Check if two SQL objects are equal."""
        if not isinstance(other, SqlObject):
            return False
        return (
            self.name.lower() == other.name.lower()
            and self.object_type == other.object_type
            and (self.schema or "").lower() == (other.schema or "").lower()
        )

    def __hash__(self) -> int:
        """Return hash of the object."""
        return hash((self.name.lower(), self.object_type, (self.schema or "").lower()))

    def format_identifier(self, identifier: str) -> str:
        """Format an identifier according to the SQL dialect.

        Args:
            identifier: The identifier to format

        Returns:
            Formatted identifier
        """
        if not identifier:
            return identifier

        # Story 26-5: identifier quote characters come from plugin Quirks
        # via the central registry. ``BaseQuirks`` defaults to double
        # quotes, plugins (MySQL/MariaDB → backticks, SQL Server →
        # brackets) override. Unknown dialects fall back to no quoting.
        if not self.dialect:
            return identifier
        from db.provider_registry import ProviderRegistry

        canonical = ProviderRegistry.canonical_dialect_name(self.dialect)
        if not canonical:
            return identifier
        quirks = ProviderRegistry.get_quirks(canonical)
        escaped = identifier.replace(quirks.quote_close, quirks.quote_close * 2)
        return f"{quirks.quote_open}{escaped}{quirks.quote_close}"

    def get_dialect_option(
        self, plugin: str, key: str, default: Optional[Any] = None
    ) -> Optional[Any]:
        """Return ``dialect_options[plugin][key]`` or *default* when absent."""
        return self.dialect_options.get(plugin, {}).get(key, default)

    def set_dialect_option(self, plugin: str, key: str, value: Any) -> None:
        """Store *value* under ``dialect_options[plugin][key]``.

        Creates the per-plugin sub-dict on first write. ``None`` values are
        accepted (callers occasionally need to record "explicitly unset").
        """
        self.dialect_options.setdefault(plugin, {})[key] = value

    def _set_plugin_option(self, plugin: str, key: str, value: Any, *, default: Any = None) -> None:
        """Setter helper for legacy property aliases.

        When *value* equals *default* the entry is deleted so ``__eq__``
        does not differentiate "explicitly default" from "never set". Each
        flat-alias setter passes the historical attribute default
        (``None`` / ``False`` / ``[]``) so equality remains stable.
        """
        if value == default:
            self.dialect_options.get(plugin, {}).pop(key, None)
            if plugin in self.dialect_options and not self.dialect_options[plugin]:
                del self.dialect_options[plugin]
        else:
            self.set_dialect_option(plugin, key, value)

    def mark_property_explicit(self, property_name: str) -> None:
        """Mark a property as explicitly defined (not using a schema default).

        Args:
            property_name: The name of the property
        """
        if self.explicit_properties is None:
            self.explicit_properties = {}
        self.explicit_properties[property_name] = True

    def is_property_explicit(self, property_name: str) -> bool:
        """Check if a property was explicitly defined.

        Args:
            property_name: The name of the property

        Returns:
            True if the property was explicitly defined, False otherwise
        """
        if self.explicit_properties is None:
            return False
        return self.explicit_properties.get(property_name, False)

    def compare_with_defaults(
        self, other: "SqlObject", schema_defaults: Optional[Dict[str, Any]] = None
    ) -> Dict[str, Any]:
        """Compare two SQL objects, taking into account schema defaults.

        Args:
            other: The other SQL object to compare with
            schema_defaults: Dictionary of schema default values

        Returns:
            Dictionary of differences between the objects
        """
        if not isinstance(other, SqlObject) or self.object_type != other.object_type:
            return {"error": "Cannot compare objects of different types"}

        schema_defaults = schema_defaults or {}
        differences = {}

        # Basic properties comparison
        # Convert to Python strings to handle driver-returned objects
        self_name = str(self.name) if self.name else ""
        other_name = str(other.name) if other.name else ""
        if self_name.lower() != other_name.lower():
            differences["name"] = {"self": self.name, "other": other.name}

        # Convert to Python strings to handle driver-returned objects
        self_schema = str(self.schema) if self.schema else ""
        other_schema = str(other.schema) if other.schema else ""
        if self_schema.lower() != other_schema.lower():
            # Use empty string if schema is None to satisfy type checker
            differences["schema"] = {"self": self.schema or "", "other": other.schema or ""}

        # Subclasses should override this method to compare specific properties
        return differences


def get_object_type_name(obj: "SqlObject") -> str:
    """Return the string name of an SQL object's type.

    Replaces the recurring pattern:
        obj.object_type.value if hasattr(obj.object_type, "value") else str(obj.object_type)

    Args:
        obj: Any object with an object_type attribute (SqlObject subclass)

    Returns:
        Object type string (e.g., "TABLE", "VIEW", "INDEX")
    """
    if isinstance(obj.object_type, SqlObjectType):
        return obj.object_type.value
    return str(obj.object_type)
