"""MySQL Event SQL Model."""

import re
from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType

_NS_MYSQL = "mysql"  # lint: allow-dialect-string: plugin namespace key for dialect_options


class Event(SqlObject):
    """Represents a MySQL scheduled event."""

    def __init__(
        self,
        name: str,
        schema: Optional[str] = None,
        definition: Optional[str] = None,
        schedule: Optional[str] = None,
        enabled: bool = True,
        comment: Optional[str] = None,
        definer: Optional[str] = None,
        event_type: str = "ONE TIME",  # ONE TIME or RECURRING
        dialect: Optional[
            str
        ] = "mysql",  # lint: allow-dialect-string: events are MySQL-only domain object
    ):
        """Initialize a MySQL event.

        Args:
            name: Event name
            schema: Schema/database name (optional)
            definition: Event body (DO clause)
            schedule: Schedule expression (AT or EVERY clause)
            enabled: Whether the event is enabled
            comment: Event comment/description
            definer: User who defined the event
            event_type: Event type (ONE TIME or RECURRING)
            dialect: SQL dialect (defaults to mysql)
        """
        super().__init__(name, SqlObjectType.EVENT, schema, dialect)
        self.definition = definition
        self.schedule = schedule
        self.enabled = enabled
        self.comment = comment
        # ``dialect_options`` is initialized by ``SqlObject.__init__``; the
        # property setter below routes into it under its plugin namespace.
        self.definer = definer
        self.event_type = event_type

    @property
    def definer(self) -> Optional[str]:
        """MySQL ``DEFINER = user@host`` (Events are MySQL/MariaDB-only)."""
        value = self.get_dialect_option(_NS_MYSQL, "definer")
        return value if value is None or isinstance(value, str) else str(value)

    @definer.setter
    def definer(self, value: Optional[str]) -> None:
        """Set MySQL ``DEFINER = user@host`` (Events are MySQL/MariaDB-only)."""
        self._set_plugin_option(_NS_MYSQL, "definer", value)

    @property
    def create_statement(self) -> str:
        """Generate CREATE EVENT statement using database-specific generators.

        Returns:
            Dialect-specific CREATE EVENT statement
        """
        # Use the appropriate SQL generator for the dialect
        from core.sql_generator.generator_factory import (
            SqlGeneratorFactory,
        )

        try:
            generator = SqlGeneratorFactory.create(
                self.dialect or "mysql"  # lint: allow-dialect-string: events are MySQL-only
            )
            # Check if generator has the new method
            if hasattr(generator, "generate_create_statement"):
                result = generator.generate_create_statement(self)
                return str(result)
            else:
                # Fallback for old generators that don't have the method yet
                return self._generate_basic_create_statement()
        except (ValueError, ImportError, AttributeError):
            # Fallback to basic CREATE EVENT if generator not available
            return self._generate_basic_create_statement()

    def _generate_basic_create_statement(self) -> str:
        """Generate a basic CREATE EVENT statement as fallback."""
        # Format identifiers
        schema_name = self.format_identifier(self.schema) if self.schema else ""
        event_name = self.format_identifier(self.name)
        schema_prefix = f"{schema_name}." if schema_name else ""

        stmt = f"CREATE EVENT {schema_prefix}{event_name}\n"

        # Add schedule
        normalized_schedule = self._normalize_schedule(self.schedule)
        if normalized_schedule:
            stmt += f"  ON SCHEDULE {normalized_schedule}\n"

        # Add status
        status = "ENABLE" if self.enabled else "DISABLE"
        stmt += f"  {status}\n"

        # Add comment
        if self.comment:
            stmt += f"  COMMENT '{self.comment}'\n"

        # Add definition
        if self.definition:
            body = self.definition.rstrip()
            body_stripped = body.strip()
            upper_body = body_stripped.upper()
            if not upper_body.endswith("END") and not upper_body.endswith("END;"):
                body += "\nEND"
                upper_body = "END"
            if not upper_body.endswith("END;"):
                body += ";"
            stmt += f"  DO\n{body}\n"

        return stmt

    def _normalize_schedule(self, schedule: Optional[str]) -> Optional[str]:
        """Ensure MySQL/MariaDB schedule clauses quote literal timestamps.

        Story 26-5: dialect dispatch via plugin Quirks
        (``event_supports_mysql_schedule``).
        """
        if not schedule or not self.dialect:
            return schedule
        from db.provider_registry import ProviderRegistry

        canonical = ProviderRegistry.canonical_dialect_name(self.dialect)
        if not canonical:
            return schedule
        if not ProviderRegistry.get_quirks(canonical).event_supports_mysql_schedule:
            return schedule

        normalized = schedule
        for keyword in ("STARTS", "ENDS", "AT"):
            pattern = re.compile(
                rf"({keyword}\s+)(\d{{4}}-\d{{2}}-\d{{2}}\s+\d{{2}}:\d{{2}}:\d{{2}})",
                re.IGNORECASE,
            )

            def _repl(match: re.Match[str]) -> str:
                prefix, timestamp = match.groups()
                return f"{prefix}'{timestamp}'"

            normalized = pattern.sub(_repl, normalized)

        return normalized

    def __str__(self) -> str:
        """Return string representation of the event."""
        qualified = f"{self.schema}.{self.name}" if self.schema else self.name
        status = "enabled" if self.enabled else "disabled"
        return f"Event {qualified} ({self.event_type}, {status})"

    def __eq__(self, other: Any) -> bool:
        """Check if two events are equal."""
        if not isinstance(other, Event):
            return False
        return (
            super().__eq__(other)
            and self.definition == other.definition
            and self.schedule == other.schedule
            and self.enabled == other.enabled
            and self.event_type == other.event_type
        )

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Event":
        """Create event from dictionary representation.

        Args:
            data: Dictionary with event attributes

        Returns:
            Event object
        """
        return cls(
            name=data["name"],
            schema=data.get("schema"),
            definition=data.get("definition"),
            schedule=data.get("schedule"),
            enabled=data.get("enabled", True),
            comment=data.get("comment"),
            definer=data.get("definer"),
            event_type=data.get("event_type", "ONE TIME"),
            dialect=data.get("dialect", "mysql"),  # lint: allow-dialect-string: events MySQL-only
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert event to dictionary representation.

        Returns:
            Dictionary with event attributes
        """
        return {
            "name": self.name,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "definition": self.definition,
            "schedule": self.schedule,
            "enabled": self.enabled,
            "comment": self.comment,
            "definer": self.definer,
            "event_type": self.event_type,
        }
