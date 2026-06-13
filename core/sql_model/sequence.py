"""Dialect-agnostic ``Sequence`` SQL object — CREATE/ALTER DDL for numeric sequences."""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType

_NS_POSTGRES = "postgresql"  # lint: allow-dialect-string: plugin namespace key for dialect_options


def _quirks_for(dialect: Optional[str]) -> Any:
    """Story 26-5: resolve quirks for *dialect* via the registry."""
    from db.base_quirks import BaseQuirks
    from db.provider_registry import ProviderRegistry

    canonical = ProviderRegistry.canonical_dialect_name(dialect or "")
    if canonical:
        return ProviderRegistry.get_quirks(canonical)
    return BaseQuirks()


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
        # ``dialect_options`` is initialized by ``SqlObject.__init__``; the
        # property setters below route into it under their plugin namespace.
        self.temp = temp
        self.owned_by_table = owned_by_table
        self.owned_by_column = owned_by_column

    @property
    def temp(self) -> bool:
        """PostgreSQL ``CREATE TEMPORARY SEQUENCE`` flag."""
        return bool(self.get_dialect_option(_NS_POSTGRES, "temp", default=False))

    @temp.setter
    def temp(self, value: bool) -> None:
        """Set PostgreSQL ``CREATE TEMPORARY SEQUENCE`` flag."""
        self._set_plugin_option(_NS_POSTGRES, "temp", value, default=False)

    @property
    def owned_by_table(self) -> Optional[str]:
        """PostgreSQL ``OWNED BY <table>.<column>`` — owning table portion."""
        value = self.get_dialect_option(_NS_POSTGRES, "owned_by_table")
        return value if value is None or isinstance(value, str) else str(value)

    @owned_by_table.setter
    def owned_by_table(self, value: Optional[str]) -> None:
        """Set PostgreSQL ``OWNED BY <table>.<column>`` — owning table portion."""
        self._set_plugin_option(_NS_POSTGRES, "owned_by_table", value)

    @property
    def owned_by_column(self) -> Optional[str]:
        """PostgreSQL ``OWNED BY <table>.<column>`` — owning column portion."""
        value = self.get_dialect_option(_NS_POSTGRES, "owned_by_column")
        return value if value is None or isinstance(value, str) else str(value)

    @owned_by_column.setter
    def owned_by_column(self, value: Optional[str]) -> None:
        """Set PostgreSQL ``OWNED BY <table>.<column>`` — owning column portion."""
        self._set_plugin_option(_NS_POSTGRES, "owned_by_column", value)

    @property
    def create_statement(self) -> str:
        """Generate CREATE SEQUENCE statement using database-specific generators.

        Returns:
            Dialect-specific CREATE SEQUENCE statement
        """
        # If no dialect specified, use basic generator to ensure all attributes are included
        if not self.dialect:
            return self._generate_basic_create_statement()

        # Use the appropriate SQL generator for the dialect
        from core.sql_generator.generator_factory import (
            SqlGeneratorFactory,
        )

        try:
            generator = SqlGeneratorFactory.create(self.dialect)
            # Check if generator has the new method
            if hasattr(generator, "generate_create_statement"):
                result = generator.generate_create_statement(self)
                return str(result)
            else:
                # Fallback for old generators that don't have the method yet
                return self._generate_basic_create_statement()
        except (ValueError, ImportError, AttributeError):
            # Fallback to basic CREATE SEQUENCE if generator not available
            return self._generate_basic_create_statement()

    def _generate_basic_create_statement(self) -> str:
        """Generate a basic CREATE SEQUENCE statement as fallback.

        Story 26-5: dialect dispatch routed through plugin Quirks.
        """
        quirks = _quirks_for(self.dialect)

        schema_name = self.format_identifier(self.schema) if self.schema else ""
        seq_name = self.format_identifier(self.name)
        schema_prefix = f"{schema_name}." if schema_name else ""

        temp_prefix = "TEMPORARY " if self.temp and quirks.seq_supports_temp else ""

        stmt = f"CREATE {temp_prefix}SEQUENCE {schema_prefix}{seq_name}"

        if self.start_with is not None:
            stmt += f" START WITH {self.start_with}"

        if self.increment_by is not None and self.increment_by != 1:
            stmt += f" INCREMENT BY {self.increment_by}"

        if self.min_value is not None:
            stmt += f" MINVALUE {self.min_value}"

        if self.max_value is not None:
            stmt += f" MAXVALUE {self.max_value}"

        stmt += " CYCLE" if self.cycle else f" {quirks.seq_nocycle_keyword}"

        cache_clause = ""
        if self.cache is None:
            if quirks.seq_default_nocache_when_unset:
                cache_clause = " NOCACHE"
        else:
            if quirks.seq_cache_one_means_nocache and self.cache <= 1:
                cache_clause = " NOCACHE"
            else:
                cache_clause = f" CACHE {self.cache}"

        stmt += cache_clause

        return stmt

    @property
    def drop_statement(self) -> str:
        """Generate DROP SEQUENCE statement.

        Returns:
            SQL DROP SEQUENCE statement for this sequence
        """
        schema_prefix = self.format_identifier(self.schema) + "." if self.schema else ""
        seq_name = self.format_identifier(self.name)

        # Story 26-5: ``IF EXISTS`` support comes from plugin Quirks.
        if _quirks_for(self.dialect).seq_drop_supports_if_exists:
            return f"DROP SEQUENCE IF EXISTS {schema_prefix}{seq_name}"
        return f"DROP SEQUENCE {schema_prefix}{seq_name}"

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Sequence":
        """Create sequence from dictionary representation.

        Args:
            data: Dictionary with sequence attributes

        Returns:
            Sequence object
        """
        return cls(
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
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert sequence to dictionary representation.

        Returns:
            Dictionary with sequence attributes
        """
        return {
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
        }
