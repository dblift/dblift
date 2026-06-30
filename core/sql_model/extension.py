"""Extension SQL model class (PostgreSQL-specific)."""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


class Extension(SqlObject):
    """
    Represents a database extension (PostgreSQL-specific).

    Extensions are add-on modules that provide additional functionality
    to the database, such as PostGIS for geographic data, pgcrypto for
    cryptographic functions, or pg_trgm for trigram text search.
    """

    def __init__(
        self,
        name: str,
        version: Optional[str] = None,
        schema: Optional[str] = None,
        description: Optional[str] = None,
        relocatable: bool = False,
        dialect: Optional[str] = None,
    ):
        """Initialize an extension.

        Args:
            name: Extension name
            version: Extension version (optional)
            schema: Schema where the extension is installed (optional)
            description: Extension description (optional)
            relocatable: Whether the extension can be relocated to another schema
            dialect: SQL dialect (typically 'postgresql')
        """
        # Extensions are a PostgreSQL-specific feature
        super().__init__(name, SqlObjectType.EXTENSION, schema, dialect)
        self.version = version
        self.description = description
        self.relocatable = relocatable

    @property
    def create_statement(self) -> str:
        """OSS builds do not ship SQL generation for this object."""
        return ""

    @property
    def drop_statement(self) -> str:
        """
        Generate DROP EXTENSION statement.

        Returns:
            PostgreSQL DROP EXTENSION statement
        """
        return f"DROP EXTENSION IF EXISTS {self.format_identifier(self.name)}"

    def __str__(self) -> str:
        """Return string representation of the extension."""
        info = f"EXTENSION {self.name}"
        if self.version:
            info += f" (v{self.version})"
        if self.description:
            info += f" - {self.description}"
        return info

    def __eq__(self, other: Any) -> bool:
        """Check if two extensions are equal."""
        if not isinstance(other, Extension):
            return False
        return super().__eq__(other) and (self.version or "") == (other.version or "")

    def __hash__(self) -> int:
        """Return hash of the extension."""
        return hash(
            (
                self.name.lower(),
                self.object_type,
                (self.schema or "").lower(),
                (self.version or ""),
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize extension to dictionary."""
        return {
            "name": self.name,
            "schema": self.schema,
            "dialect": self.dialect,
            "version": self.version,
            "description": self.description,
            "relocatable": self.relocatable,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Extension":
        """Deserialize extension from dictionary."""
        return cls(
            name=data.get("name", ""),
            version=data.get("version"),
            schema=data.get("schema"),
            description=data.get("description"),
            relocatable=data.get("relocatable", False),
            dialect=data.get("dialect"),
        )
