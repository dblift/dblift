"""Module SQL model class (DB2-specific)."""

from typing import Any, Dict, Optional

from dblift.core.sql_model.base import SqlObject, SqlObjectType


class Module(SqlObject):
    """
    Represents a DB2 Module - a collection of SQL procedures, functions, and types.

    DB2 Modules are similar to Oracle Packages - they group related SQL routines
    and user-defined types together. Modules support SQL routine encapsulation
    and can contain both published (public) and internal (private) routines.
    """

    def __init__(
        self,
        name: str,
        definition: str,
        schema: Optional[str] = None,
        dialect: Optional[str] = None,
    ):
        """Initialize a DB2 module.

        Args:
            name: Module name
            definition: Complete module definition (CREATE MODULE ... END MODULE)
            schema: Schema name (typically the module owner)
            dialect: SQL dialect (typically 'db2')
        """
        super().__init__(name, SqlObjectType.PACKAGE, schema, dialect)
        self.definition = definition

    def __str__(self) -> str:
        """Return string representation of the module."""
        schema_part = f"{self.schema}." if self.schema else ""
        lines = len(self.definition.split("\n")) if self.definition else 0
        return f"MODULE {schema_part}{self.name} ({lines} lines)"

    def __eq__(self, other: Any) -> bool:
        """Check if two modules are equal.

        Note: Case-sensitive in DB2 for delimited identifiers.
        """
        if not isinstance(other, Module):
            return False
        return super().__eq__(other) and self.definition == other.definition

    def __hash__(self) -> int:
        """Return hash of the module."""
        return hash(
            (
                self.name,
                self.object_type,
                (self.schema or ""),
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize module to dictionary."""
        return {
            "name": self.name,
            "schema": self.schema,
            "dialect": self.dialect,
            "definition": self.definition,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Module":
        """Deserialize module from dictionary."""
        return cls(
            name=data.get("name", ""),
            definition=data.get("definition", ""),
            schema=data.get("schema"),
            dialect=data.get("dialect"),
        )
