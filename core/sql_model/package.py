"""Oracle Package SQL Model."""

import re
from typing import Any, Dict, List, Optional

from core.sql_model.base import SqlObject, SqlObjectType


class Package(SqlObject):
    """Represents an Oracle package (specification and body)."""

    def __init__(
        self,
        name: str,
        schema: Optional[str] = None,
        spec: Optional[str] = None,
        body: Optional[str] = None,
        dialect: Optional[str] = None,
    ):
        """Initialize an Oracle package.

        Args:
            name: Package name
            schema: Schema name (optional)
            spec: Package specification (header/interface)
            body: Package body (implementation)
            dialect: SQL dialect, supplied by the creating introspector
        """
        super().__init__(name, SqlObjectType.PACKAGE, schema, dialect)
        self.spec = spec
        self.body = body
        # Track procedures and functions declared in this package
        self.procedures: List[str] = []
        self.functions: List[str] = []

    @property
    def create_statement(self) -> str:
        """OSS builds do not ship SQL generation for this object."""
        return ""

    def __str__(self) -> str:
        """Return string representation of the package."""
        qualified = f"{self.schema}.{self.name}" if self.schema else self.name
        if self.spec and self.body:
            return f"Package {qualified} (spec + body)"
        elif self.spec:
            return f"Package {qualified} (spec only)"
        elif self.body:
            return f"Package {qualified} (body only)"
        return f"Package {qualified}"

    def __eq__(self, other: Any) -> bool:
        """Check if two packages are equal."""
        if not isinstance(other, Package):
            return False
        return super().__eq__(other) and self.spec == other.spec and self.body == other.body

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "Package":
        """Create package from dictionary representation.

        Args:
            data: Dictionary with package attributes

        Returns:
            Package object
        """
        return cls(
            name=data["name"],
            schema=data.get("schema"),
            spec=data.get("spec"),
            body=data.get("body"),
            dialect=data.get("dialect"),
        )

    def to_dict(self) -> Dict[str, Any]:
        """Convert package to dictionary representation.

        Returns:
            Dictionary with package attributes
        """
        return {
            "name": self.name,
            "schema": self.schema,
            "object_type": self.object_type.value,
            "dialect": self.dialect,
            "spec": self.spec,
            "body": self.body,
            "procedures": self.procedures,
            "functions": self.functions,
        }

    def _build_package_section(self, section: str, qualified_name: str, is_body: bool) -> str:
        """Normalize package spec/body text into a full CREATE statement."""
        text = (section or "").strip()
        if not text:
            return ""

        # Remove trailing SQL*Plus terminator if present
        if text.endswith("/"):
            text = text[:-1].rstrip()

        # Strip leading CREATE [OR REPLACE] if already present
        text = re.sub(
            r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?",
            "",
            text,
            flags=re.IGNORECASE,
        )

        header = "PACKAGE BODY" if is_body else "PACKAGE"
        prefix = f"CREATE OR REPLACE {header} {qualified_name}"
        unquoted_name = self.name.strip('"')

        # Allow definitions that already include CREATE [OR REPLACE]
        pattern = rf"""^(?:CREATE\s+(?:OR\s+REPLACE\s+)?)?\s*PACKAGE(?:\s+BODY)?\s+{re.escape(unquoted_name)}\s+(IS|AS)\b"""
        match = re.match(pattern, text, re.IGNORECASE)
        if match:
            clause = match.group(1).upper()
            remainder = text[match.end() :].lstrip()
            return f"{prefix} {clause}\n{remainder}"

        return f"{prefix}\n{text}"

    def _append_block_terminator(self, statement: str) -> str:
        """Append a SQL*Plus-style block terminator if the dialect uses one."""
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect or "")
        text = statement.rstrip()
        if not text.endswith(";"):
            text = f"{text};"
        terminator = quirks.trigger_terminator  # OracleQuirks = "\n/"
        return f"{text}{terminator}" if terminator else text
