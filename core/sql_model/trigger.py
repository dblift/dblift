"""
Trigger SQL Model.

Represents a database trigger with its definition, timing, and events.
"""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


def _quirks_for(dialect: Optional[str]) -> Any:
    """Resolve quirks for *dialect* via the registry.

    Story 26-5: replaces inline ``if dialect in {...}`` dispatch in
    the trigger DDL paths.
    """
    from db.base_quirks import BaseQuirks
    from db.provider_registry import ProviderRegistry

    canonical = ProviderRegistry.canonical_dialect_name(dialect or "")
    if canonical:
        return ProviderRegistry.get_quirks(canonical)
    return BaseQuirks()


class Trigger(SqlObject):
    """Represents a database trigger."""

    def __init__(
        self,
        name: str,
        table_name: str,
        schema: Optional[str] = None,
        timing: Optional[str] = None,
        events: Optional[list[str]] = None,
        orientation: Optional[str] = None,
        definition: Optional[str] = None,
        enabled: bool = True,
        dialect: Optional[str] = None,
        function_schema: Optional[str] = None,
        function_name: Optional[str] = None,
        function_arguments: Optional[str] = None,
        when_clause: Optional[str] = None,
        is_constraint_trigger: Optional[bool] = None,
        constraint_deferrable: Optional[bool] = None,
        constraint_initially_deferred: Optional[bool] = None,
        # Grammar-based: MySQL-specific trigger properties
        definer: Optional[str] = None,  # user@host (MySQL)
        # Trigger execution order - SQL-generation-only
        execution_order: Optional[int] = None,  # Execution order/priority - SQL-generation-only
        follows_trigger: Optional[
            str
        ] = None,  # Name of trigger this follows (MySQL/Oracle) - SQL-generation-only
        precedes_trigger: Optional[
            str
        ] = None,  # Name of trigger this precedes (MySQL/Oracle) - SQL-generation-only
    ):
        """Initialize a trigger.

        Args:
            name: Trigger name
            table_name: Name of the table the trigger is on
            schema: Schema name (optional)
            timing: When trigger fires (BEFORE, AFTER, INSTEAD OF)
            events: List of events that fire the trigger (INSERT, UPDATE, DELETE, TRUNCATE)
            orientation: Trigger level (ROW, STATEMENT)
            definition: Trigger body/definition
            enabled: Whether trigger is enabled
            dialect: SQL dialect
            definer: Definer user - user@host (MySQL grammar-based)
            execution_order: Execution order/priority - SQL-generation-only (implementation detail)
            follows_trigger: Name of trigger this follows (MySQL/Oracle) - SQL-generation-only
            precedes_trigger: Name of trigger this precedes (MySQL/Oracle) - SQL-generation-only
        """
        super().__init__(name, SqlObjectType.TRIGGER, schema, dialect)
        self.table_name = table_name
        self.timing = timing  # BEFORE, AFTER, INSTEAD OF
        self.events = events or []  # INSERT, UPDATE, DELETE, TRUNCATE (grammar-based)
        self.orientation = orientation  # ROW, STATEMENT
        self.definition = definition
        self.enabled = enabled
        self.function_schema = function_schema
        self.function_name = function_name
        self.function_arguments = function_arguments
        self.when_clause = when_clause
        # Post-introspection: explicit CONSTRAINT TRIGGER metadata (fallback to definition sniffing)
        if is_constraint_trigger is None:
            inferred_constraint = "CONSTRAINT TRIGGER" in (definition or "").upper()
            self.is_constraint_trigger = inferred_constraint
        else:
            self.is_constraint_trigger = is_constraint_trigger
        self.constraint_deferrable = constraint_deferrable
        self.constraint_initially_deferred = constraint_initially_deferred
        # MySQL grammar-based trigger properties.
        self.definer = definer  # ``DEFINER = user@host``
        self.execution_order = execution_order  # execution priority (integer)
        self.follows_trigger = follows_trigger  # trigger this one FOLLOWs
        self.precedes_trigger = precedes_trigger  # trigger this one PRECEDEs

    @property
    def qualified_table_name(self) -> str:
        """Get the qualified table name (schema.table).

        Returns:
            Qualified table name
        """
        if self.schema:
            return (
                f"{self.format_identifier(self.schema)}.{self.format_identifier(self.table_name)}"
            )
        return self.format_identifier(self.table_name)

    @property
    def event_str(self) -> str:
        """Get events as a formatted string.

        Returns:
            Events joined by ' OR ' (e.g., 'INSERT OR UPDATE')
        """
        return " OR ".join(self.events) if self.events else ""

    @property
    def create_statement(self) -> str:
        """OSS builds do not ship SQL generation for this object."""
        return ""

    @staticmethod
    def _format_mysql_definer(definer: str) -> str:
        """Return a properly quoted MySQL DEFINER clause."""
        if not definer:
            return definer

        trimmed = definer.strip()
        if "`" in trimmed or trimmed.upper() == "CURRENT_USER":
            return trimmed

        if "@" in trimmed:
            user_part, host_part = trimmed.split("@", 1)
        else:
            user_part, host_part = trimmed, "%"

        user_part = user_part.strip("`\"'")
        host_part = host_part.strip("`\"'") or "%"

        return f"`{user_part}`@`{host_part}`"

    def __str__(self) -> str:
        """Return string representation of the trigger."""
        return f"Trigger {self.name} on {self.table_name}"

    def __eq__(self, other: Any) -> bool:
        """Check if two triggers are equal.

        Args:
            other: Other object to compare

        Returns:
            True if triggers are equal
        """
        if not isinstance(other, Trigger):
            return False
        return (
            super().__eq__(other)
            and self.table_name == other.table_name
            and self.timing == other.timing
            and self.events == other.events
            and self.orientation == other.orientation
            and self.definition == other.definition
            and self.function_schema == other.function_schema
            and self.function_name == other.function_name
            and self.function_arguments == other.function_arguments
            and self.when_clause == other.when_clause
            and self.is_constraint_trigger == other.is_constraint_trigger
            and self.constraint_deferrable == other.constraint_deferrable
            and self.constraint_initially_deferred == other.constraint_initially_deferred
            # Grammar-based: MySQL-specific properties
            and self.definer == other.definer
        )

    def __repr__(self) -> str:
        """Return detailed representation of the trigger."""
        return (
            f"Trigger(name={self.name!r}, table={self.table_name!r}, "
            f"timing={self.timing!r}, events={self.events!r}, "
            f"orientation={self.orientation!r})"
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Trigger":
        """Create trigger from dictionary representation.

        Args:
            data: Dictionary with trigger attributes

        Returns:
            Trigger object
        """
        return cls(
            name=data["name"],
            table_name=data["table_name"],
            schema=data.get("schema"),
            timing=data.get("timing"),
            events=data.get("events", []),
            orientation=data.get("orientation"),
            definition=data.get("definition"),
            enabled=data.get("enabled", True),
            dialect=data.get("dialect"),
            function_schema=data.get("function_schema"),
            function_name=data.get("function_name"),
            function_arguments=data.get("function_arguments"),
            when_clause=data.get("when_clause"),
            is_constraint_trigger=data.get("is_constraint_trigger"),
            constraint_deferrable=data.get("constraint_deferrable"),
            constraint_initially_deferred=data.get("constraint_initially_deferred"),
            definer=data.get("definer"),
            execution_order=data.get("execution_order"),
            follows_trigger=data.get("follows_trigger"),
            precedes_trigger=data.get("precedes_trigger"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert trigger to dictionary representation.

        Returns:
            Dictionary with trigger attributes
        """
        return {
            "name": self.name,
            "table_name": self.table_name,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "timing": self.timing,
            "events": self.events,
            "orientation": self.orientation,
            "definition": self.definition,
            "enabled": self.enabled,
            "function_schema": self.function_schema,
            "function_name": self.function_name,
            "function_arguments": self.function_arguments,
            "when_clause": self.when_clause,
            "is_constraint_trigger": self.is_constraint_trigger,
            "constraint_deferrable": self.constraint_deferrable,
            "constraint_initially_deferred": self.constraint_initially_deferred,
            "definer": self.definer,
            "execution_order": self.execution_order,
            "follows_trigger": self.follows_trigger,
            "precedes_trigger": self.precedes_trigger,
        }

    def _format_body(self, body: str) -> str:
        """Normalize trigger body text.

        Story 26-5: BEGIN/END / DECLARE wrapping is handled by the
        per-dialect ``ModelQuirks.wrap_trigger_body`` hook. Default
        passes the body through unchanged; Oracle wraps it in a
        valid PL/SQL block.
        """
        wrapped: str = _quirks_for(self.dialect).wrap_trigger_body(body or "")
        return wrapped
