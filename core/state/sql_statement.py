"""SQL Statement models for diff-to-SQL generation."""

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class SqlStatement:
    """Represents a SQL statement with metadata."""

    sql: str
    statement_type: str  # "CREATE", "ALTER", "DROP", etc.
    object_type: str  # "TABLE", "COLUMN", "CONSTRAINT", etc.
    object_name: str
    dialect: str
    pre_check: Optional[str] = None  # SQL to check before execution
    error_if_check_fails: bool = False
    error_message: Optional[str] = None
    depends_on: Optional[List[str]] = None  # List of object names this depends on
    sdk_operation: Optional[Dict[str, Any]] = None  # For CosmosDB: SDK operation details
    requires_sdk: bool = False  # Whether this statement requires SDK execution

    def __post_init__(self):
        """Initialize default values."""
        if self.depends_on is None:
            self.depends_on = []

    def __str__(self) -> str:
        """String representation."""
        return f"{self.statement_type} {self.object_type} {self.object_name}"


@dataclass
class GenerationOptions:
    """Options for SQL generation."""

    # ``dialect`` is required (no default) and is therefore declared
    # keyword-only so it can keep its position while every existing caller —
    # all of which pass ``dialect=`` — continues to work unchanged (ADR-26 E).
    dialect: str = field(kw_only=True)
    include_comments: bool = True
    dry_run: bool = False
    validate_before_execute: bool = True
    combine_statements: bool = True
