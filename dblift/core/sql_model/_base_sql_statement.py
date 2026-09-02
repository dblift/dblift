"""``SqlStatement`` representation plus the ``SqlStatementType`` enum.

This module is part of the ``dblift.core.sql_model.base`` split (PR-H13). Public
import paths should continue to use ``from core.sql_model.base import ...``;
this module is re-exported by the ``base`` façade.
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional, Union

from dblift.core.sql_model._base_sql_object import SqlObject


class SqlStatementType(Enum):
    """SQL statement types."""

    CREATE = "CREATE"
    ALTER = "ALTER"
    DROP = "DROP"
    INSERT = "INSERT"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    SELECT = "SELECT"
    MERGE = "MERGE"
    TRUNCATE = "TRUNCATE"
    GRANT = "GRANT"
    REVOKE = "REVOKE"
    COMMENT = "COMMENT"
    DECLARE = "DECLARE"
    BEGIN = "BEGIN"
    CALL = "CALL"
    EXECUTE = "EXECUTE"
    DDL = "DDL"
    DML = "DML"
    QUERY = "QUERY"
    UNKNOWN = "UNKNOWN"


class SqlStatement:
    """Represents a parsed SQL statement."""

    sql_text: str
    statement_type: SqlStatementType
    objects: List[SqlObject]
    affected_objects: List[SqlObject]
    dialect: Optional[str]
    schema: Optional[str]

    def __init__(
        self,
        sql_text: str,
        statement_type: Union[SqlStatementType, str],
        objects: Optional[List[SqlObject]] = None,
        affected_objects: Optional[List[SqlObject]] = None,
        dialect: Optional[str] = None,
        schema: Optional[str] = None,
    ) -> None:
        """Initialize a SQL statement.

        Args:
            sql_text: Raw SQL text
            statement_type: Type of statement
            objects: SQL objects in the statement
            affected_objects: Objects affected by the statement
            dialect: SQL dialect used
            schema: Default schema
        """
        self.sql_text = sql_text

        # Handle both enum and string statement types
        if isinstance(statement_type, str):
            try:
                self.statement_type = SqlStatementType[statement_type.upper()]
            except KeyError:
                self.statement_type = SqlStatementType.UNKNOWN
        else:
            self.statement_type = statement_type

        self.objects = objects or []
        self.affected_objects = affected_objects or []
        self.dialect = dialect.lower() if dialect else None
        self.schema = schema

    def get_primary_object(self) -> Optional[SqlObject]:
        """Get the primary object in the statement.

        Returns:
            The primary object or None if no objects are found.
        """
        if self.objects:
            return self.objects[0]
        return None

    def __str__(self) -> str:
        """Return string representation of the statement."""
        return (
            f"{self.statement_type.value} statement affecting {len(self.affected_objects)} objects"
        )
