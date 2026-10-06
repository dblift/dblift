"""Dialect-agnostic ``Sequence`` SQL object — numeric sequence attributes."""

from typing import Any, Dict, Optional

from dblift.core.sql_model.base import SqlObject, SqlObjectType


class Sequence(SqlObject):
    """Represents a database sequence."""

    def __init__(
        self,
        name: str,
        schema: Optional[str] = None,
        start_with: Optional[int] = None,
        increment_by: Optional[int] = None,
        min_value: Optional[int] = None,
        max_value: Optional[int] = None,
        cycle: bool = False,
        cache: Optional[int] = None,
        dialect: Optional[str] = None,
        # Grammar-based: PostgreSQL-specific sequence properties
        temp: bool = False,  # TEMP or TEMPORARY keyword (PostgreSQL)
        owned_by_table: Optional[str] = None,
        owned_by_column: Optional[str] = None,
        data_type: Optional[str] = None,
    ):
        """Initialize a sequence.

        Args:
            name: Sequence name
            schema: Schema name
            start_with: Starting value
            increment_by: Increment value
            min_value: Minimum value
            max_value: Maximum value
            cycle: Whether to cycle when reaching max_value
            cache: Cache size
            data_type: Declared sequence data type, if captured
            dialect: SQL dialect
            temp: Whether sequence is TEMPORARY (PostgreSQL grammar-based)
        """
        super().__init__(name, SqlObjectType.SEQUENCE, schema, dialect)
        self.start_with = start_with
        self.increment_by = increment_by or 1
        self.min_value = min_value
        self.max_value = max_value
        self.cycle = cycle
        self.cache = cache
        self.data_type = data_type
        # PostgreSQL grammar-based sequence properties.
        self.temp = temp  # ``CREATE TEMPORARY SEQUENCE`` flag
        self.owned_by_table = owned_by_table  # ``OWNED BY <table>.<column>`` table
        self.owned_by_column = owned_by_column  # ``OWNED BY <table>.<column>`` column

    def __eq__(self, other: object) -> bool:
        """Compare sequence identity and its captured data type."""
        return (
            isinstance(other, Sequence)
            and super().__eq__(other)
            and self.data_type == other.data_type
        )

    def __hash__(self) -> int:
        """Hash sequence identity and its captured data type."""
        return hash((super().__hash__(), self.data_type))

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Sequence":
        """Create sequence from dictionary representation.

        Args:
            data: Dictionary with sequence attributes

        Returns:
            Sequence object
        """
        sequence = cls(
            name=data["name"],
            schema=data.get("schema"),
            start_with=data.get("start_with"),
            increment_by=data.get("increment_by", 1),
            min_value=data.get("min_value"),
            max_value=data.get("max_value"),
            cycle=data.get("cycle", False),
            cache=data.get("cache"),
            dialect=data.get("dialect"),
            temp=data.get("temp", False),
            owned_by_table=data.get("owned_by_table"),
            owned_by_column=data.get("owned_by_column"),
            data_type=data.get("data_type"),
        )
        for plugin, options in (data.get("dialect_options") or {}).items():
            for key, value in options.items():
                sequence.set_dialect_option(plugin, key, value)
        return sequence

    def to_dict(self) -> Dict[str, Any]:
        """Convert sequence to dictionary representation.

        Returns:
            Dictionary with sequence attributes
        """
        result: Dict[str, Any] = {
            "name": self.name,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "start_with": self.start_with,
            "increment_by": self.increment_by,
            "min_value": self.min_value,
            "max_value": self.max_value,
            "cycle": self.cycle,
            "cache": self.cache,
            "temp": self.temp,
            "owned_by_table": self.owned_by_table,
            "owned_by_column": self.owned_by_column,
            "data_type": self.data_type,
        }
        if self.dialect_options:
            result["dialect_options"] = self.dialect_options
        return result
