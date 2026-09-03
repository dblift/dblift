"""Undo Script Generator models.

Data classes representing reversed SQL statements.
"""

from dataclasses import dataclass
from typing import Optional


@dataclass
class UndoStatement:
    """Represents a reversed SQL statement."""

    sql: str
    original_statement: str
    operation_type: str
    warning: Optional[str] = None
    requires_manual_review: bool = False
