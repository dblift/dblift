"""
Data structures for reporting schema clean operations.

Providers return structured summaries so higher-level layers can avoid
parsing raw SQL to determine which objects were dropped.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional


@dataclass(frozen=True)
class CleanedObjectInfo:
    """Metadata describing a single database object removed during clean."""

    object_type: str
    name: str
    schema: Optional[str] = None
    details: Dict[str, str] = field(default_factory=dict)


@dataclass
class CleanExecutionSummary:
    """Structured result returned by provider clean operations."""

    statements: List[str] = field(default_factory=list)
    objects: List[CleanedObjectInfo] = field(default_factory=list)
    errors: List[str] = field(default_factory=list)  # Track errors during clean operations

    def add_statement(self, sql: str) -> None:
        """Record an executed SQL statement."""
        if sql:
            self.statements.append(sql)

    def add_object(
        self,
        object_type: str,
        name: str,
        schema: Optional[str] = None,
        details: Optional[Dict[str, str]] = None,
    ) -> None:
        """Record a dropped object."""
        self.objects.append(
            CleanedObjectInfo(
                object_type=object_type,
                name=name,
                schema=schema,
                details=details or {},
            )
        )

    def record_drop(
        self,
        sql: str,
        object_type: str,
        name: str,
        schema: Optional[str] = None,
        details: Optional[Dict[str, str]] = None,
    ) -> None:
        """Convenience helper to add both statement and object metadata."""
        self.add_statement(sql)
        self.add_object(object_type, name, schema=schema, details=details)

    def extend(self, other: "CleanExecutionSummary") -> None:
        """Merge another summary into this one."""
        if not other:
            return
        self.statements.extend(other.statements)
        self.objects.extend(other.objects)
        if hasattr(other, "errors"):
            self.errors.extend(other.errors)

    def add_error(self, error: str) -> None:
        """Record an error that occurred during clean operation."""
        if error:
            self.errors.append(error)
