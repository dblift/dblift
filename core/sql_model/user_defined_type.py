"""User-Defined Type SQL model class."""

from typing import Any, Dict, List, Optional

from core.sql_model.base import SqlObject, SqlObjectType


class UserDefinedType(SqlObject):
    """Represents a user-defined type (UDT)."""

    def __init__(
        self,
        name: str,
        type_category: str,
        schema: Optional[str] = None,
        data_type: Optional[str] = None,
        definition: Optional[str] = None,
        attributes: Optional[List[Dict[str, Any]]] = None,
        enum_values: Optional[List[str]] = None,
        base_type: Optional[str] = None,
        comment: Optional[str] = None,
        dialect: Optional[str] = None,
    ):
        """Initialize a user-defined type.

        Args:
            name: Type name
            type_category: Category of type (COMPOSITE, ENUM, DOMAIN, OBJECT, DISTINCT, etc.)
            schema: Schema name (optional)
            data_type: SQL data type classification (optional)
            definition: Type definition/source code (optional)
            attributes: List of attributes for composite/structured types (optional)
            enum_values: List of values for enum types (optional)
            base_type: Base type for DISTINCT types (optional)
            comment: Type comment/description (optional)
            dialect: SQL dialect
        """
        super().__init__(name, SqlObjectType.TYPE, schema, dialect)
        self.type_category = type_category.upper()
        self.data_type = data_type
        self.definition = definition
        self.attributes = attributes or []
        self.enum_values = enum_values or []
        self.base_type = base_type
        self.comment = comment

    @property
    def is_composite(self) -> bool:
        """Check if this is a composite/structured type."""
        return self.type_category in ("COMPOSITE", "C", "STRUCT", "OBJECT")

    @property
    def is_enum(self) -> bool:
        """Check if this is an enum type."""
        return self.type_category in ("ENUM", "E")

    @property
    def is_domain(self) -> bool:
        """Check if this is a domain type."""
        return self.type_category in ("DOMAIN", "D")

    @property
    def is_distinct(self) -> bool:
        """Check if this is a distinct type."""
        return self.type_category == "DISTINCT"

    @property
    def create_statement(self) -> str:
        """Generate CREATE TYPE statement using database-specific generators.

        Returns:
            Dialect-specific CREATE TYPE statement
        """
        # Use the appropriate SQL generator for the dialect
        from core.sql_generator.generator_factory import SqlGeneratorFactory

        try:
            generator = SqlGeneratorFactory.create(
                self.dialect or "postgresql"  # lint: allow-dialect-string: factory default fallback
            )
            # Check if generator has the new method
            if hasattr(generator, "generate_create_statement"):
                result = generator.generate_create_statement(self)
                return str(result)
            else:
                # Fallback for old generators that don't have the method yet
                return self._generate_basic_create_statement()
        except (ValueError, ImportError, AttributeError):
            # Fallback to basic CREATE TYPE if generator not available
            return self._generate_basic_create_statement()

    def _generate_basic_create_statement(self) -> str:
        """Generate a basic CREATE TYPE statement as fallback."""
        schema_name = self.format_identifier(self.schema) if self.schema else ""
        type_name = self.format_identifier(self.name)
        schema_prefix = f"{schema_name}." if schema_name else ""

        # Story 26-5: dialect dispatch via plugin Quirks.
        from db.base_quirks import BaseQuirks
        from db.provider_registry import ProviderRegistry

        canonical = ProviderRegistry.canonical_dialect_name(self.dialect or "")
        quirks = ProviderRegistry.get_quirks(canonical) if canonical else BaseQuirks()

        # For PostgreSQL composite types
        if self.is_composite and self.attributes:
            attr_defs = []
            for attr in self.attributes:
                attr_name = self.format_identifier(attr.get("name", ""))
                attr_type = attr.get("type", "")
                attr_defs.append(f"    {attr_name} {attr_type}")
            body = ",\n".join(attr_defs)

            type_modifier = (
                quirks.udt_composite_object_modifier if self.type_category == "OBJECT" else ""
            )

            stmt = f"CREATE TYPE {schema_prefix}{type_name} AS{type_modifier} (\n{body}\n)"
            return stmt

        # For PostgreSQL enum types
        if self.is_enum and self.enum_values:
            stmt = f"CREATE TYPE {schema_prefix}{type_name} AS ENUM ("
            enum_vals = [f"'{val}'" for val in self.enum_values]
            stmt += ", ".join(enum_vals)
            stmt += ")"
            return stmt

        # For domains
        if self.is_domain and self.base_type:
            stmt = f"CREATE DOMAIN {schema_prefix}{type_name} AS {self.base_type}"
            if self.definition:
                stmt += f"\n{self.definition}"
            return stmt

        # For distinct types (SQL Server uses ``FROM``; DB2 / others
        # use ``CREATE DISTINCT TYPE x AS base``).
        if self.is_distinct and self.base_type:
            if quirks.udt_distinct_uses_from_syntax:
                stmt = f"CREATE TYPE {schema_prefix}{type_name} FROM {self.base_type}"
            else:
                stmt = f"CREATE DISTINCT TYPE {schema_prefix}{type_name} AS {self.base_type}"
            return stmt

        # Generic fallback
        if self.definition:
            return f"CREATE TYPE {schema_prefix}{type_name} AS {self.definition}"

        return f"CREATE TYPE {schema_prefix}{type_name}"

    @property
    def drop_statement(self) -> str:
        """
        Generate DROP TYPE statement.

        Returns:
            Dialect-specific DROP TYPE statement
        """
        schema_name = self.format_identifier(self.schema) if self.schema else ""
        type_name = self.format_identifier(self.name)
        schema_prefix = f"{schema_name}." if schema_name else ""

        if self.is_domain:
            return f"DROP DOMAIN {schema_prefix}{type_name}"
        else:
            return f"DROP TYPE {schema_prefix}{type_name}"

    def __str__(self) -> str:
        """Return string representation of the type."""
        type_info = f"{self.type_category}"
        if self.is_enum and self.enum_values:
            type_info += f" ({len(self.enum_values)} values)"
        elif self.is_composite and self.attributes:
            type_info += f" ({len(self.attributes)} attributes)"
        elif self.base_type:
            type_info += f" (base: {self.base_type})"

        return f"{self.object_type.value} {self.name}: {type_info}"

    def __eq__(self, other: Any) -> bool:
        """Check if two types are equal."""
        if not isinstance(other, UserDefinedType):
            return False
        return (
            super().__eq__(other)
            and self.type_category == other.type_category
            and (self.base_type or "").lower() == (other.base_type or "").lower()
        )

    def __hash__(self) -> int:
        """Return hash of the type."""
        return hash(
            (
                self.name.lower(),
                self.object_type,
                (self.schema or "").lower(),
                self.type_category,
            )
        )

    def to_dict(self) -> Dict[str, Any]:
        """Serialize user-defined type to dictionary form."""
        return {
            "name": self.name,
            "schema": self.schema,
            "dialect": self.dialect,
            "type_category": self.type_category,
            "data_type": self.data_type,
            "definition": self.definition,
            "attributes": self.attributes,
            "enum_values": self.enum_values,
            "base_type": self.base_type,
            "comment": self.comment,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "UserDefinedType":
        """Deserialize user-defined type from dictionary form."""
        return cls(
            name=data.get("name", ""),
            type_category=data.get("type_category", ""),
            schema=data.get("schema"),
            data_type=data.get("data_type"),
            definition=data.get("definition"),
            attributes=data.get("attributes"),
            enum_values=data.get("enum_values"),
            base_type=data.get("base_type"),
            comment=data.get("comment"),
            dialect=data.get("dialect"),
        )
