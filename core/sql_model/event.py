"""MySQL Event SQL Model."""

import re
from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


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
        dialect: Optional[str] = None,
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
            dialect: SQL dialect, supplied by the creating introspector
        """
        super().__init__(name, SqlObjectType.EVENT, schema, dialect)
        self.definition = definition
        self.schedule = schedule
        self.enabled = enabled
        self.comment = comment
        # MySQL ``DEFINER = user@host`` (Events are MySQL/MariaDB-only).
        self.definer = definer
        self.event_type = event_type

    @property
    def create_statement(self) -> str:
        """OSS builds do not ship SQL generation for this object."""
        return ""

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
            dialect=data.get("dialect"),
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
