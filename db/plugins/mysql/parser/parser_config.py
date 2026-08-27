"""MySQL dialect configuration for regex-based SQL parsing.

This module provides MySQL-specific patterns and configuration for the regex parser,
extracted from MySQL grammar files and existing parser implementation.
"""

import re
from typing import Dict, List, Optional, Pattern, Set

from core.sql_parser.dialects.base_config import DialectConfig


class MySqlConfig(DialectConfig):
    """MySQL dialect configuration with comprehensive regex patterns."""

    dialect_name = "mysql"  # lint: allow-dialect-string: dialect dispatch

    def __init__(self) -> None:
        """Initialize MySQL dialect configuration."""
        super().__init__()  # type: ignore[no-untyped-call]
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile all MySQL-specific regex patterns."""
        self._ddl_patterns = self._compile_ddl_patterns()
        self._dml_patterns = self._compile_dml_patterns()
        self._query_patterns = self._compile_query_patterns()
        self._object_patterns = self._compile_object_patterns()
        self._comment_patterns = self._compile_comment_patterns()
        self._batch_separators = self._compile_batch_separators()

    def _compile_ddl_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile MySQL DDL patterns."""
        return {
            # CREATE statements
            # Grammar-based: CREATE TEMPORARY? TABLE ifNotExists? tableName
            "create_table": re.compile(
                r"\b(?:CREATE)\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r"(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)"
                r"(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?",
                re.IGNORECASE,
            ),
            "create_view": re.compile(
                r"\b(?:CREATE)\s+(?:OR\s+REPLACE\s+)?(?:ALGORITHM\s*=\s*(?:MERGE|TEMPTABLE|UNDEFINED)\s+)?(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?(?:SQL\s+SECURITY\s+(?:DEFINER|INVOKER)\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE intimeAction? indexCategory? INDEX uid ... ON tableName
            # Supports ONLINE/OFFLINE, UNIQUE/FULLTEXT/SPATIAL
            "create_index": re.compile(
                r"\b(?:CREATE)\s+(?:ONLINE|OFFLINE\s+)?"
                r"(?:UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?"
                r"INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r"(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)"
                r"\s+ON\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "create_database": re.compile(
                r"\b(?:CREATE)\s+(?:DATABASE|SCHEMA)\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)",
                re.IGNORECASE,
            ),
            "create_procedure": re.compile(
                r"\b(?:CREATE)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?PROCEDURE\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "create_function": re.compile(
                r"\b(?:CREATE)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?FUNCTION\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE ownerStatement? TRIGGER ifNotExists? fullId triggerTime triggerEvent ON tableName
            # Supports DEFINER, IF NOT EXISTS, FOLLOWS/PRECEDES
            "create_trigger": re.compile(
                r"\b(?:CREATE)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?"
                r"TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r"(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)"
                r"(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?",
                re.IGNORECASE,
            ),
            "create_user": re.compile(
                r"\b(?:CREATE)\s+USER\s+(?:IF\s+NOT\s+EXISTS\s+)?", re.IGNORECASE
            ),
            "create_event": re.compile(
                r"\b(?:CREATE)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?EVENT\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            # ALTER statements
            # Grammar-based: ALTER intimeAction? IGNORE? TABLE tableName
            # Supports ONLINE/OFFLINE, IGNORE
            "alter_table": re.compile(
                r"\b(?:ALTER)\s+(?:ONLINE|OFFLINE\s+)?(?:IGNORE\s+)?"
                r"TABLE\s+"
                r"(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)"
                r"(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?",
                re.IGNORECASE,
            ),
            "alter_view": re.compile(
                r"\b(?:ALTER)\s+(?:ALGORITHM\s*=\s*(?:MERGE|TEMPTABLE|UNDEFINED)\s+)?(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?(?:SQL\s+SECURITY\s+(?:DEFINER|INVOKER)\s+)?VIEW\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "alter_database": re.compile(
                r"\b(?:ALTER)\s+(?:DATABASE|SCHEMA)\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)",
                re.IGNORECASE,
            ),
            "alter_procedure": re.compile(
                r"\b(?:ALTER)\s+PROCEDURE\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "alter_function": re.compile(
                r"\b(?:ALTER)\s+FUNCTION\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "alter_user": re.compile(r"\b(?:ALTER)\s+USER\s+(?:IF\s+EXISTS\s+)?", re.IGNORECASE),
            "alter_event": re.compile(
                r"\b(?:ALTER)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?EVENT\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            # DROP statements
            # Grammar-based: DROP TEMPORARY? TABLE ifExists? tables (RESTRICT | CASCADE)?
            "drop_table": re.compile(
                r"\b(?:DROP)\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+EXISTS\s+)?"
                r"(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)"
                r"(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?",
                re.IGNORECASE,
            ),
            "drop_view": re.compile(
                r"\b(?:DROP)\s+VIEW\s+(?:IF\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            # Grammar-based: DROP INDEX intimeAction? uid ON tableName
            # Supports ONLINE/OFFLINE, ALGORITHM, LOCK options
            "drop_index": re.compile(
                r"\b(?:DROP)\s+INDEX\s+(?:ONLINE|OFFLINE\s+)?"
                r"(?:IF\s+EXISTS\s+)?"
                r"(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)"
                r"\s+ON\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "drop_database": re.compile(
                r"\b(?:DROP)\s+(?:DATABASE|SCHEMA)\s+(?:IF\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)",
                re.IGNORECASE,
            ),
            "drop_procedure": re.compile(
                r"\b(?:DROP)\s+PROCEDURE\s+(?:IF\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "drop_function": re.compile(
                r"\b(?:DROP)\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "drop_trigger": re.compile(
                r"\b(?:DROP)\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "drop_user": re.compile(r"\b(?:DROP)\s+USER\s+(?:IF\s+EXISTS\s+)?", re.IGNORECASE),
            "drop_event": re.compile(
                r"\b(?:DROP)\s+EVENT\s+(?:IF\s+EXISTS\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            # Other DDL statements
            "truncate_table": re.compile(
                r"\b(?:TRUNCATE)\s+(?:TABLE\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "rename_table": re.compile(
                r"\b(?:RENAME)\s+TABLE\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "grant": re.compile(r"\b(?:GRANT)\s+", re.IGNORECASE),
            "revoke": re.compile(r"\b(?:REVOKE)\s+", re.IGNORECASE),
        }

    def _compile_dml_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile MySQL DML patterns."""
        return {
            "insert": re.compile(
                r"\b(?:INSERT)\s+(?:LOW_PRIORITY\s+|DELAYED\s+|HIGH_PRIORITY\s+)?(?:IGNORE\s+)?(?:INTO\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "update": re.compile(
                r"\b(?:UPDATE)\s+(?:LOW_PRIORITY\s+|IGNORE\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "delete": re.compile(
                r"\b(?:DELETE)\s+(?:LOW_PRIORITY\s+|QUICK\s+|IGNORE\s+)?(?:FROM\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "replace": re.compile(
                r"\b(?:REPLACE)\s+(?:LOW_PRIORITY\s+|DELAYED\s+)?(?:INTO\s+)?(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "load_data": re.compile(
                r"\b(?:LOAD)\s+DATA\s+(?:LOW_PRIORITY\s+|CONCURRENT\s+)?(?:LOCAL\s+)?INFILE\s+",
                re.IGNORECASE,
            ),
            "call": re.compile(
                r"\b(?:CALL)\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "do": re.compile(r"\b(?:DO)\s+", re.IGNORECASE),
        }

    def _compile_query_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile MySQL query patterns."""
        return {
            "select": re.compile(
                r"\b(?:SELECT)\s+(?:ALL\s+|DISTINCT\s+|DISTINCTROW\s+)?(?:HIGH_PRIORITY\s+|STRAIGHT_JOIN\s+|SQL_SMALL_RESULT\s+|SQL_BIG_RESULT\s+|SQL_BUFFER_RESULT\s+|SQL_NO_CACHE\s+|SQL_CALC_FOUND_ROWS\s+)?",
                re.IGNORECASE,
            ),
            "with": re.compile(r"\b(?:WITH)\s+(?:RECURSIVE\s+)?", re.IGNORECASE),
            "show": re.compile(r"\b(?:SHOW)\s+", re.IGNORECASE),
            "describe": re.compile(
                r"\b(?:DESCRIBE|DESC)\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "explain": re.compile(
                r"\b(?:EXPLAIN)\s+(?:(?:EXTENDED\s+|PARTITIONS\s+|FORMAT\s*=\s*(?:TRADITIONAL|JSON)\s+)*)",
                re.IGNORECASE,
            ),
            "analyze": re.compile(
                r"\b(?:ANALYZE)\s+(?:NO_WRITE_TO_BINLOG\s+|LOCAL\s+)?TABLE\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "check": re.compile(
                r"\b(?:CHECK)\s+TABLE\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "optimize": re.compile(
                r"\b(?:OPTIMIZE)\s+(?:NO_WRITE_TO_BINLOG\s+|LOCAL\s+)?TABLE\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
            "repair": re.compile(
                r"\b(?:REPAIR)\s+(?:NO_WRITE_TO_BINLOG\s+|LOCAL\s+)?TABLE\s+(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*(?:\.[a-zA-Z_][a-zA-Z0-9_]*)?)",
                re.IGNORECASE,
            ),
        }

    def _compile_object_patterns(self) -> Dict[str, Pattern[str]]:
        """Compile MySQL object extraction patterns.

        Grammar-based improvements based on MySQL grammar analysis:
        - IF NOT EXISTS support for CREATE statements
        - IF EXISTS support for DROP statements
        - Backtick identifier support (MySQL uses backticks, not double quotes)
        - TEMPORARY table support
        - ONLINE/OFFLINE for indexes
        """
        return {
            # Grammar-based: CREATE TEMPORARY? TABLE ifNotExists? tableName
            # Supports backticks and TEMPORARY
            "table": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:TEMPORARY\s+)?TABLE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
                r"(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))"
                r"(?:\.(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))?",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE orReplace? (ALGORITHM '=' algType)? ownerStatement? ... VIEW fullId
            # Supports OR REPLACE, ALGORITHM, DEFINER, SQL SECURITY
            "view": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:OR\s+REPLACE\s+)?"
                r"(?:ALGORITHM\s*=\s*(?:MERGE|TEMPTABLE|UNDEFINED)\s+)?"
                r"(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?"
                r"(?:SQL\s+SECURITY\s+(?:DEFINER|INVOKER)\s+)?"
                r"VIEW\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
                r"(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))"
                r"(?:\.(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))?",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE intimeAction? indexCategory? INDEX uid ... ON tableName
            # Supports ONLINE/OFFLINE, UNIQUE/FULLTEXT/SPATIAL
            "index": re.compile(
                r"\b(?:CREATE|DROP)\s+(?:ONLINE|OFFLINE\s+)?"
                r"(?:UNIQUE\s+|FULLTEXT\s+|SPATIAL\s+)?"
                r"INDEX\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
                r"(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))"
                r"(?:\s+ON\s+(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))"
                r"(?:\.(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))?)?",
                re.IGNORECASE,
            ),
            "database": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:DATABASE|SCHEMA)\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE ownerStatement? PROCEDURE ifNotExists? fullId
            # Supports DEFINER, IF NOT EXISTS, backticks
            "procedure": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?"
                r"PROCEDURE\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
                r"(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))"
                r"(?:\.(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))?",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE ownerStatement? AGGREGATE? FUNCTION ifNotExists? fullId
            # Supports DEFINER, AGGREGATE, IF NOT EXISTS, backticks
            "function": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?"
                r"(?:AGGREGATE\s+)?FUNCTION\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
                r"(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))"
                r"(?:\.(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))?",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE ownerStatement? TRIGGER ifNotExists? fullId
            # Supports DEFINER, IF NOT EXISTS, backticks
            "trigger": re.compile(
                r"\b(?:CREATE|DROP)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?"
                r"TRIGGER\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
                r"(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))"
                r"(?:\.(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))?",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE ownerStatement? EVENT ifNotExists? fullId
            # Supports DEFINER, IF NOT EXISTS, backticks
            "event": re.compile(
                r"\b(?:CREATE|DROP|ALTER)\s+(?:DEFINER\s*=\s*[^@]+@[^\s]+\s+)?"
                r"EVENT\s+(?:IF\s+(?:NOT\s+)?EXISTS\s+)?"
                r"(?:(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))"
                r"(?:\.(?:`([^`]+)`)|([a-zA-Z_][a-zA-Z0-9_]*))?",
                re.IGNORECASE,
            ),
        }

    def _compile_comment_patterns(self) -> List[Pattern[str]]:
        """Compile MySQL comment patterns."""
        return [
            # Single-line comments with --
            re.compile(r"--.*$", re.MULTILINE),
            # Single-line comments with #
            re.compile(r"#.*$", re.MULTILINE),
            # Multi-line comments /* ... */
            re.compile(r"/\*.*?\*/", re.DOTALL),
            # MySQL-specific comments /*! ... */
            re.compile(r"/\*!.*?\*/", re.DOTALL),
        ]

    def _compile_batch_separators(self) -> List[Pattern[str]]:
        """Compile MySQL batch separator patterns."""
        return [
            # DELIMITER statements
            re.compile(r"^\s*DELIMITER\s+", re.IGNORECASE | re.MULTILINE),
        ]

    @property
    def name(self) -> str:
        """Dialect name."""
        return self.dialect_name

    @property
    def ddl_patterns(self) -> Dict[str, Pattern[str]]:
        """DDL statement regex patterns."""
        return self._ddl_patterns

    @property
    def dml_patterns(self) -> Dict[str, Pattern[str]]:
        """DML statement regex patterns."""
        return self._dml_patterns

    @property
    def query_patterns(self) -> Dict[str, Pattern[str]]:
        """Query statement regex patterns."""
        return self._query_patterns

    @property
    def object_patterns(self) -> Dict[str, Pattern[str]]:
        """Object extraction regex patterns."""
        return self._object_patterns

    @property
    def comment_patterns(self) -> List[Pattern[str]]:
        """Regex patterns for comments."""
        return self._comment_patterns

    @property
    def batch_separators(self) -> List[Pattern[str]]:
        """Regex patterns for batch separators."""
        return self._batch_separators

    @property
    def quoted_identifiers(self) -> List[Pattern[str]]:
        """Regex patterns for quoted identifiers."""
        return [re.compile(r"`([^`]+)`")]

    @property
    def block_keywords(self) -> List[str]:
        """Get MySQL block keywords."""
        return [
            "BEGIN",
            "END",
            "DECLARE",
            "IF",
            "THEN",
            "ELSE",
            "ELSEIF",
            "ENDIF",
            "WHILE",
            "LOOP",
            "REPEAT",
            "UNTIL",
            "CASE",
            "WHEN",
            "DELIMITER",
        ]

    def get_default_schema(self) -> Optional[str]:
        """Get default schema name for MySQL.

        MySQL has no server-wide default schema the way SQL Server has
        ``dbo`` — the effective schema is whatever database the connection
        is using, which varies per deployment. Returning ``None`` avoids
        fabricating a schema qualifier (previously the literal ``"mysql"``
        system schema) when no schema was explicitly supplied.
        """
        return None

    def normalize_identifier(self, identifier: str, is_quoted: bool = False) -> str:
        """Normalize MySQL identifier according to dialect rules.

        Args:
            identifier: Raw identifier string

        Returns:
            Normalized identifier
        """
        if not identifier:
            return identifier

        # Remove backticks if present
        if identifier.startswith("`") and identifier.endswith("`"):
            identifier = identifier[1:-1]

        # MySQL identifiers are case-insensitive by default on Windows/Mac
        # but case-sensitive on Linux - we'll normalize to lowercase
        return identifier.lower()

    def extract_delimiter_blocks(self, sql: str) -> List[Dict[str, str]]:
        """Extract MySQL DELIMITER blocks for stored procedures.

        Args:
            sql: SQL content to parse

        Returns:
            List of delimiter blocks with their custom delimiters
        """
        blocks = []
        current_delimiter = ";"
        lines = sql.split("\n")
        current_block: List[str] = []

        # Track whether we're inside a block comment to ignore DELIMITER inside comments
        in_block_comment = False

        for line in lines:
            line_stripped = line.strip()

            # Check for DELIMITER statement
            # Handle entering/exiting block comments
            if not in_block_comment and re.match(r"^\s*/\*", line_stripped):
                # Ignore /*! ... */ MySQL special comments for simplicity here
                if not line_stripped.startswith("/*!"):
                    in_block_comment = True
            if in_block_comment:
                if re.search(r"\*/\s*$", line_stripped):
                    in_block_comment = False
                current_block.append(line)
                continue

            delimiter_match = re.match(r"^\s*DELIMITER\s+(.+)\s*$", line_stripped, re.IGNORECASE)
            if delimiter_match:
                # Save current block if exists
                if current_block:
                    blocks.append(
                        {
                            "delimiter": current_delimiter,
                            "content": "\n".join(current_block),
                        }
                    )
                    current_block = []

                # Update delimiter
                current_delimiter = delimiter_match.group(1).strip()
                continue

            # Check if line ends with current delimiter
            if line_stripped.endswith(current_delimiter):
                # Remove the delimiter from the line before adding to block
                delimiter_len = len(current_delimiter)
                line_without_delimiter = line.rstrip()
                if line_without_delimiter.endswith(current_delimiter):
                    line_without_delimiter = line_without_delimiter[:-delimiter_len].rstrip()
                current_block.append(line_without_delimiter)
                # Save block
                blocks.append(
                    {
                        "delimiter": current_delimiter,
                        "content": "\n".join(current_block),
                    }
                )
                current_block = []
            else:
                current_block.append(line)

        # Add any remaining block
        if current_block:
            blocks.append(
                {
                    "delimiter": current_delimiter,
                    "content": "\n".join(current_block),
                }
            )

        return blocks

    def get_identifier_pattern(self) -> "re.Pattern[str]":
        """Get regex pattern for MySQL identifiers.

        Based on MySQL grammar: uid = simpleId | CHARSET_REVERSE_QOUTE_STRING | STRING_LITERAL
        MySQL uses backticks (`) for quoted identifiers, not double quotes.
        Unquoted identifiers follow standard SQL identifier rules.

        Returns:
            Compiled regex pattern for MySQL identifiers
        """
        # MySQL identifiers: backtick-quoted or unquoted (alphanumeric + underscore, starting with letter)
        return re.compile(r"(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)", re.IGNORECASE)

    def get_qualified_identifier_pattern(self) -> "re.Pattern[str]":
        """Get regex pattern for qualified identifiers (schema.table).

        Based on MySQL grammar: fullId = uid (DOT_ID | '.' uid)?
        MySQL uses backticks for quoted identifiers.

        Returns:
            Compiled regex pattern for qualified MySQL identifiers
        """
        # Grammar-based: Support backticks for MySQL identifiers
        identifier = r"(?:`[^`]+`|[a-zA-Z_][a-zA-Z0-9_]*)"
        return re.compile(rf"(?:{identifier}\.)?{identifier}", re.IGNORECASE)

    def extract_backtick_identifiers(self, sql: str) -> List[str]:
        """Extract backtick-quoted identifiers from SQL.

        Args:
            sql: SQL content to parse

        Returns:
            List of backtick-quoted identifiers
        """
        # Pattern to match backtick-quoted identifiers
        pattern = re.compile(r"`([^`]+)`")
        matches = pattern.findall(sql)
        return matches

    def is_hash_comment(self, line: str) -> bool:
        """Check if line is a MySQL hash comment.

        Args:
            line: Line to check

        Returns:
            True if line is a hash comment
        """
        return line.strip().startswith("#")

    def extract_stored_procedure_body(self, sql: str) -> str:
        """Extract stored procedure body from CREATE PROCEDURE statement.

        Args:
            sql: CREATE PROCEDURE statement

        Returns:
            Procedure body content
        """
        # Find the BEGIN keyword and extract until matching END
        begin_match = re.search(r"\bBEGIN\b", sql, re.IGNORECASE)
        if not begin_match:
            return sql

        # Extract from BEGIN to matching END
        start_pos = begin_match.start()
        depth = 0
        pos = start_pos

        while pos < len(sql):
            # Check for BEGIN
            if re.match(r"\bBEGIN\b", sql[pos:], re.IGNORECASE):
                depth += 1
                pos += 5
                continue

            # Check for END
            if re.match(r"\bEND\b", sql[pos:], re.IGNORECASE):
                depth -= 1
                if depth == 0:
                    return sql[start_pos : pos + 3]
                pos += 3
                continue

            pos += 1

        return sql[start_pos:]

    # Abstract method implementations
    def get_ddl_keywords(self) -> Set[str]:
        """Get DDL keywords for MySQL."""
        return {
            "CREATE",
            "ALTER",
            "DROP",
            "TRUNCATE",
            "COMMENT",
            "GRANT",
            "REVOKE",
            "TABLE",
            "VIEW",
            "INDEX",
            "SEQUENCE",
            "PROCEDURE",
            "FUNCTION",
            "TRIGGER",
            "DATABASE",
            "SCHEMA",
            "EVENT",
            "USER",
            "ROLE",
        }

    def get_dml_keywords(self) -> Set[str]:
        """Get DML keywords for MySQL."""
        return {"INSERT", "UPDATE", "DELETE", "REPLACE", "LOAD", "CALL", "SET", "VALUES"}

    def get_query_keywords(self) -> Set[str]:
        """Get query keywords for MySQL."""
        return {"SELECT", "WITH", "EXPLAIN", "DESCRIBE", "SHOW"}

    def get_string_literal_pattern(self) -> Pattern[str]:
        """Get regex pattern for string literals."""
        return re.compile(r"'([^']|'')*'", re.IGNORECASE)

    def get_comment_pattern(self) -> Pattern[str]:
        """Get regex pattern for comments."""
        return re.compile(r"(?:--.*$|#.*$|/\*.*?\*/)", re.MULTILINE | re.DOTALL)

    def get_statement_separator_pattern(self) -> Pattern[str]:
        """Get regex pattern for statement separators."""
        return re.compile(r";\s*$", re.MULTILINE)

    def is_ddl_statement(self, statement: str) -> bool:
        """Check if statement is a DDL statement."""
        statement_upper = statement.strip().upper()
        ddl_keywords = self.get_ddl_keywords()
        first_words = statement_upper.split()[:2]
        return any(word in ddl_keywords for word in first_words if word)

    def is_dml_statement(self, statement: str) -> bool:
        """Check if statement is a DML statement."""
        statement_upper = statement.strip().upper()
        dml_keywords = self.get_dml_keywords()
        words = statement_upper.split()
        first_word = words[0] if words else ""
        return first_word in dml_keywords

    def is_query_statement(self, statement: str) -> bool:
        """Check if statement is a query statement."""
        statement_upper = statement.strip().upper()
        query_keywords = self.get_query_keywords()
        words = statement_upper.split()
        first_word = words[0] if words else ""
        return first_word in query_keywords

    def get_batch_separator(self) -> str:
        """Get batch separator for MySQL."""
        return ";"

    def supports_block_comments(self) -> bool:
        """Check if MySQL supports block comments."""
        return True

    def supports_line_comments(self) -> bool:
        """Check if MySQL supports line comments."""
        return True
