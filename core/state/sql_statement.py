"""SQL statement models used by runtime formatting and SDK translation."""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class SqlStatement:
    """Represents a SQL statement with runtime metadata."""

    sql: str
    statement_type: str
    object_type: str
    object_name: str
    dialect: str
    pre_check: Optional[str] = None
    error_if_check_fails: bool = False
    error_message: Optional[str] = None
    depends_on: Optional[List[str]] = None
    sdk_operation: Optional[Dict[str, Any]] = None
    requires_sdk: bool = False

    def __post_init__(self) -> None:
        """Initialize default values."""
        if self.depends_on is None:
            self.depends_on = []

    def __str__(self) -> str:
        """Return a concise display label."""
        return f"{self.statement_type} {self.object_type} {self.object_name}"
