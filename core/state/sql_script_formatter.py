"""SQL Script Formatter for generating DBA-ready SQL scripts.

This module formats SQL statements into complete, readable scripts
that DBAs can review and execute.
"""

import logging
from typing import List, Optional

from core.state.sql_statement import SqlStatement

logger = logging.getLogger(__name__)


class SqlScriptFormatter:
    """Formats SQL statements into complete scripts."""

    def __init__(self, include_comments: bool = True, include_checks: bool = True):
        """Initialize the formatter.

        Args:
            include_comments: Whether to include comments in the script
            include_checks: Whether to include pre-execution checks
        """
        self.include_comments = include_comments
        self.include_checks = include_checks

    def format_script(
        self,
        statements: List[SqlStatement],
        title: Optional[str] = None,
        description: Optional[str] = None,
    ) -> str:
        """Format SQL statements into a complete script.

        Args:
            statements: List of SQL statements to format
            title: Optional title for the script
            description: Optional description

        Returns:
            Formatted SQL script as string
        """
        lines = []

        # Header
        if title:
            lines.append(f"-- {title}")
            lines.append("-- " + "=" * (len(title) + 2))
            lines.append("")

        if description:
            lines.append(f"-- {description}")
            lines.append("")

        # Add generation timestamp
        from datetime import datetime

        lines.append(f"-- Generated: {datetime.now().isoformat()}")
        lines.append(f"-- Total statements: {len(statements)}")
        lines.append("")

        # Group statements by type
        create_statements = [s for s in statements if s.statement_type == "CREATE"]
        alter_statements = [s for s in statements if s.statement_type == "ALTER"]
        drop_statements = [s for s in statements if s.statement_type == "DROP"]

        # Section: CREATE statements
        if create_statements:
            lines.append("-- ========================================")
            lines.append("-- CREATE OBJECTS")
            lines.append("-- ========================================")
            lines.append("")
            for stmt in create_statements:
                lines.extend(self._format_statement(stmt))
                lines.append("")

        # Section: ALTER statements
        if alter_statements:
            lines.append("-- ========================================")
            lines.append("-- ALTER OBJECTS")
            lines.append("-- ========================================")
            lines.append("")
            for stmt in alter_statements:
                lines.extend(self._format_statement(stmt))
                lines.append("")

        # Section: DROP statements (usually at the end)
        if drop_statements:
            lines.append("-- ========================================")
            lines.append("-- DROP OBJECTS")
            lines.append("-- WARNING: These statements will remove objects!")
            lines.append("-- ========================================")
            lines.append("")
            for stmt in drop_statements:
                lines.extend(self._format_statement(stmt))
                lines.append("")

        return "\n".join(lines)

    def _format_statement(self, statement: SqlStatement) -> List[str]:
        """Format a single SQL statement with comments and checks.

        Args:
            statement: SQL statement to format

        Returns:
            List of lines for the statement
        """
        lines = []

        # Comment with object info
        if self.include_comments:
            lines.append(
                f"-- {statement.statement_type} {statement.object_type}: {statement.object_name}"
            )

        # Pre-execution check
        if self.include_checks and statement.pre_check:
            lines.append("-- Pre-execution check:")
            lines.append(f"-- {statement.pre_check}")
            if statement.error_if_check_fails:
                lines.append(f"-- ERROR if check fails: {statement.error_message}")
            lines.append("")

        # SQL statement
        lines.append(statement.sql)

        # Post-statement comment
        if self.include_comments:
            lines.append("")

        return lines

    def format_statements_simple(self, statements: List[SqlStatement]) -> str:
        """Format statements as simple SQL (no comments).

        Args:
            statements: List of SQL statements

        Returns:
            Simple SQL script
        """
        return "\n\n".join(stmt.sql for stmt in statements)
