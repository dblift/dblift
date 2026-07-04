"""Synonym SQL model class."""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


class Synonym(SqlObject):
    """Represents a database synonym (alias for another object)."""

    def __init__(
        self,
        name: str,
        target_object: str,
        schema: Optional[str] = None,
        target_schema: Optional[str] = None,
        target_database: Optional[str] = None,
        db_link: Optional[str] = None,
        dialect: Optional[str] = None,
    ):
        """Initialize a synonym.

        Args:
            name: Synonym name
            target_object: Name of the target object this synonym points to
            schema: Schema where the synonym is defined (optional)
            target_schema: Schema of the target object (optional)
            target_database: Database of the target object (optional, SQL Server)
            db_link: Database link for remote objects (optional, Oracle)
            dialect: SQL dialect
        """
        super().__init__(name, SqlObjectType.SYNONYM, schema, dialect)
        self.target_object = target_object
        self.target_schema = target_schema
        self.target_database = target_database
        self.db_link = db_link

    @property
    def target_full_name(self) -> str:
        """
        Get the fully qualified name of the target object.

        Returns:
            Fully qualified target name including schema/database/link
        """
        parts = []

        # Add target database if present (SQL Server)
        if self.target_database:
            parts.append(self.format_identifier(self.target_database))

        # Add target schema if present
        if self.target_schema:
            parts.append(self.format_identifier(self.target_schema))

        # Add target object name
        parts.append(self.format_identifier(self.target_object))

        result = ".".join(parts)

        # Add database link if present (Oracle)
        if self.db_link:
            result += f"@{self.format_identifier(self.db_link)}"

        return result

    @property
    def create_statement(self) -> str:
        """Generate CREATE SYNONYM statement using database-specific generators.

        Returns:
            Dialect-specific CREATE SYNONYM statement
        """
        from core.sql_generator.generator_factory import (
            SqlGeneratorFactory,
        )

        try:
            generator = SqlGeneratorFactory.create(self.dialect)
            return str(generator.generate_create_statement(self))
        except (ValueError, ImportError, AttributeError):
            return ""

    @property
    def drop_statement(self) -> str:
        """
        Generate DROP SYNONYM statement.

        Returns:
            Dialect-specific DROP SYNONYM statement
        """
        from db.base_quirks import BaseQuirks
        from db.provider_registry import ProviderRegistry

        canonical = ProviderRegistry.canonical_dialect_name(self.dialect or "")
        quirks = ProviderRegistry.get_quirks(canonical) if canonical else BaseQuirks()

        schema_name = self.format_identifier(self.schema) if self.schema else ""
        synonym_name = self.format_identifier(self.name)
        schema_prefix = f"{schema_name}." if schema_name else ""

        return f"DROP {quirks.synonym_keyword} {schema_prefix}{synonym_name}"

    def __str__(self) -> str:
        """Return string representation of the synonym."""
        return f"{self.object_type.value} {self.name} -> {self.target_full_name}"

    def __eq__(self, other: Any) -> bool:
        """Check if two synonyms are equal."""
        if not isinstance(other, Synonym):
            return False
        return (
            super().__eq__(other)
            and self.target_object.lower() == other.target_object.lower()
            and (self.target_schema or "").lower() == (other.target_schema or "").lower()
            and (self.target_database or "").lower() == (other.target_database or "").lower()
            and (self.db_link or "").lower() == (other.db_link or "").lower()
        )

    def __hash__(self) -> int:
        """Return hash of the synonym."""
        return hash(
            (
                self.name.lower(),
                self.object_type,
                (self.schema or "").lower(),
                self.target_object.lower(),
                (self.target_schema or "").lower(),
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize synonym to dictionary form."""
        return {
            "name": self.name,
            "schema": self.schema,
            "dialect": self.dialect,
            "target_object": self.target_object,
            "target_schema": self.target_schema,
            "target_database": self.target_database,
            "db_link": self.db_link,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Synonym":
        """Deserialize synonym from dictionary."""
        return cls(
            name=data.get("name", ""),
            target_object=data.get("target_object", ""),
            schema=data.get("schema"),
            target_schema=data.get("target_schema"),
            target_database=data.get("target_database"),
            db_link=data.get("db_link"),
            dialect=data.get("dialect"),
        )
