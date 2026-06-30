"""Module SQL model class (DB2-specific)."""

from typing import Any, Dict, Optional

from core.sql_model.base import SqlObject, SqlObjectType


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

    @property
    def create_statement(self) -> str:
        """
        Generate CREATE MODULE statement.

        Returns:
            DB2 CREATE MODULE statement
        """
        # DB2 modules are typically defined in full
        # Format: CREATE OR REPLACE MODULE schema.module_name
        #         <module_body>
        #         END MODULE
        if not self.definition:
            # Minimal module template
            module_name = f'"{self.schema}"."{self.name}"' if self.schema else f'"{self.name}"'
            return f"CREATE OR REPLACE MODULE {module_name}\n  -- Module body here\nEND MODULE;"

        return self.definition

    @property
    def drop_statement(self) -> str:
        """
        Generate DROP MODULE statement.

        Returns:
            DB2 DROP MODULE statement
        """
        module_name = f'"{self.schema}"."{self.name}"' if self.schema else f'"{self.name}"'
        return f"DROP MODULE {module_name};"

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
