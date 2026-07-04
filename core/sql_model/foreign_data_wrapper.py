"""Foreign Data Wrapper SQL model class (PostgreSQL-specific)."""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


class ForeignDataWrapper(SqlObject):
    """
    Represents a foreign data wrapper (PostgreSQL-specific).

    Foreign Data Wrappers (FDW) enable PostgreSQL to access external data sources
    including other databases (postgres_fdw, oracle_fdw), files (file_fdw), and
    custom data sources.
    """

    def __init__(
        self,
        name: str,
        handler: Optional[str] = None,
        validator: Optional[str] = None,
        options: Optional[Dict[str, str]] = None,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
    ):
        """Initialize a foreign data wrapper.

        Args:
            name: FDW name (e.g., 'postgres_fdw', 'oracle_fdw')
            handler: Handler function name (optional)
            validator: Validator function name (optional)
            options: FDW-specific options as key-value pairs (optional)
            schema: Schema (typically 'public' or system schemas)
            dialect: SQL dialect (typically 'postgresql')
        """
        super().__init__(name, SqlObjectType.FOREIGN_DATA_WRAPPER, schema, dialect)
        self.handler = handler
        self.validator = validator
        # Create a copy of options to avoid mutating caller's dictionary
        self.options = dict(options) if options else {}

    @property
    def create_statement(self) -> str:
        """Generate CREATE FOREIGN DATA WRAPPER statement using database-specific generators.

        Returns:
            Dialect-specific CREATE FOREIGN DATA WRAPPER statement
        """
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        try:
            generator = SqlGeneratorFactory.create(self.dialect or "")
            return str(generator.generate_create_statement(self))
        except (ValueError, ImportError, AttributeError):
            return ""

    @property
    def drop_statement(self) -> str:
        """
        Generate DROP FOREIGN DATA WRAPPER statement.

        Returns:
            PostgreSQL DROP FOREIGN DATA WRAPPER statement
        """
        fdw_name = self.format_identifier(self.name)
        return f"DROP FOREIGN DATA WRAPPER IF EXISTS {fdw_name} CASCADE;"

    def __str__(self) -> str:
        """Return string representation of the FDW."""
        info = f"FOREIGN DATA WRAPPER {self.name}"
        if self.handler:
            info += f" (handler: {self.handler})"
        return info

    def __eq__(self, other: Any) -> bool:
        """Check if two FDWs are equal."""
        if not isinstance(other, ForeignDataWrapper):
            return False
        return (
            super().__eq__(other)
            and (self.handler or "").lower() == (other.handler or "").lower()
            and (self.validator or "").lower() == (other.validator or "").lower()
            and self.options == other.options
        )

    def __hash__(self) -> int:
        """Return hash of the FDW."""
        return hash(
            (
                self.name.lower(),
                self.object_type,
                (self.schema or "").lower(),
                (self.handler or "").lower(),
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize foreign data wrapper to dictionary."""
        return {
            "name": self.name,
            "schema": self.schema,
            "dialect": self.dialect,
            "handler": self.handler,
            "validator": self.validator,
            "options": self.options,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "ForeignDataWrapper":
        """Deserialize foreign data wrapper from dictionary."""
        return cls(
            name=data.get("name", ""),
            handler=data.get("handler"),
            validator=data.get("validator"),
            options=data.get("options"),
            schema=data.get("schema"),
            dialect=data.get("dialect"),
        )
