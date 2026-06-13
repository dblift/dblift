"""SQLite dialect configuration for regex-based parsing.

This module provides SQLite-specific patterns and configurations for the
unified regex parser framework.

SQLite has simpler SQL syntax compared to enterprise databases:
- No stored procedures
- No schemas (database file IS the schema)
- Limited ALTER TABLE support
- Simple trigger syntax
"""

import re
from typing import Dict, List, Pattern, Set

from core.sql_parser.dialects.base_config import DialectConfig


class SQLiteConfig(DialectConfig):
    """SQLite dialect configuration with comprehensive pattern support."""

    def __init__(self) -> None:
        """Initialize SQLite dialect configuration."""
        super().__init__()  # type: ignore[no-untyped-call]

        # SQLite uses double quotes for identifiers, single quotes for strings
        self.identifier_quote_char = '"'
        self.string_quote_char = "'"

        # SQLite also supports square brackets for identifiers (SQL Server compatibility)
        self.supports_bracket_identifiers = True

        # SQLite uses semicolon as statement separator
        self.statement_separator = ";"

        # SQLite supports block comments /* */ and line comments --
        self.line_comment_prefix = "--"
        self.block_comment_start = "/*"
        self.block_comment_end = "*/"

        # SQLite-specific features
        self.supports_dollar_quoting = False  # No dollar quoting
        self.supports_copy_statements = False  # No COPY statement
        self.supports_plpgsql_blocks = False  # No PL/SQL blocks
        self.supports_cte_with_recursive = True  # Supports WITH RECURSIVE
        self.supports_on_conflict = True  # Supports ON CONFLICT clause
        self.supports_returning = True  # SQLite 3.35+ supports RETURNING

        # Compile regex patterns for performance
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for performance."""
        # DDL patterns for SQLite
        self._ddl_patterns = {
            "create_table": re.compile(
                r"\s*CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                re.IGNORECASE,
            ),
            "create_view": re.compile(
                r"\s*CREATE\s+(?:TEMP(?:ORARY)?\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                re.IGNORECASE,
            ),
            "create_index": re.compile(
                r"\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                re.IGNORECASE,
            ),
            "create_trigger": re.compile(
                r"\s*CREATE\s+(?:TEMP(?:ORARY)?\s+)?TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                re.IGNORECASE,
            ),
            "create_virtual_table": re.compile(
                r"\s*CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?",
                re.IGNORECASE,
            ),
            "alter_table": re.compile(r"\s*ALTER\s+TABLE\s+", re.IGNORECASE),
            "drop_table": re.compile(r"\s*DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?", re.IGNORECASE),
            "drop_view": re.compile(r"\s*DROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?", re.IGNORECASE),
            "drop_index": re.compile(r"\s*DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?", re.IGNORECASE),
            "drop_trigger": re.compile(r"\s*DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?", re.IGNORECASE),
            "vacuum": re.compile(r"\s*VACUUM\s*", re.IGNORECASE),
            "analyze": re.compile(r"\s*ANALYZE\s*", re.IGNORECASE),
            "reindex": re.compile(r"\s*REINDEX\s*", re.IGNORECASE),
            "pragma": re.compile(r"\s*PRAGMA\s+", re.IGNORECASE),
            "attach": re.compile(r"\s*ATTACH\s+", re.IGNORECASE),
            "detach": re.compile(r"\s*DETACH\s+", re.IGNORECASE),
        }

        # DML patterns
        self._dml_patterns = {
            "insert": re.compile(
                r"\s*(?:INSERT|REPLACE)\s+(?:OR\s+(?:ROLLBACK|ABORT|FAIL|IGNORE|REPLACE)\s+)?INTO\s+",
                re.IGNORECASE,
            ),
            "update": re.compile(
                r"\s*UPDATE\s+(?:OR\s+(?:ROLLBACK|ABORT|FAIL|IGNORE|REPLACE)\s+)?",
                re.IGNORECASE,
            ),
            "delete": re.compile(r"\s*DELETE\s+FROM\s+", re.IGNORECASE),
            "replace": re.compile(r"\s*REPLACE\s+INTO\s+", re.IGNORECASE),
        }

        # Query patterns
        self._query_patterns = {
            "select": re.compile(r"\s*SELECT\s+", re.IGNORECASE),
            "with": re.compile(r"\s*WITH\s+(?:RECURSIVE\s+)?", re.IGNORECASE),
            "values": re.compile(r"\s*VALUES\s+", re.IGNORECASE),
            "explain": re.compile(r"\s*EXPLAIN\s+", re.IGNORECASE),
        }

    def get_ddl_keywords(self) -> Set[str]:
        """Get DDL keywords for SQLite."""
        return {
            "CREATE",
            "ALTER",
            "DROP",
            "VACUUM",
            "ANALYZE",
            "REINDEX",
            "PRAGMA",
            "ATTACH",
            "DETACH",
        }

    def get_dml_keywords(self) -> Set[str]:
        """Get DML keywords for SQLite."""
        return {
            "INSERT",
            "UPDATE",
            "DELETE",
            "REPLACE",
        }

    def get_query_keywords(self) -> Set[str]:
        """Get query keywords for SQLite."""
        return {"SELECT", "WITH", "VALUES", "EXPLAIN"}

    def get_transaction_keywords(self) -> Set[str]:
        """Get transaction control keywords for SQLite."""
        return {
            "BEGIN",
            "COMMIT",
            "END",
            "ROLLBACK",
            "SAVEPOINT",
            "RELEASE",
            "TRANSACTION",
            "DEFERRED",
            "IMMEDIATE",
            "EXCLUSIVE",
        }

    def get_identifier_pattern(self) -> re.Pattern[str]:
        """Get regex pattern for SQLite identifiers."""
        # SQLite identifiers: unquoted, double-quoted, or bracket-quoted
        return re.compile(r'(?:"[^"]*"|\[[^\]]*\]|[a-zA-Z_][a-zA-Z0-9_]*)', re.IGNORECASE)

    def get_qualified_identifier_pattern(self) -> re.Pattern[str]:
        """Get regex pattern for qualified identifiers (database.table)."""
        identifier = r'(?:"[^"]*"|\[[^\]]*\]|[a-zA-Z_][a-zA-Z0-9_]*)'
        return re.compile(rf"(?:{identifier}\.)?{identifier}", re.IGNORECASE)

    def get_string_literal_pattern(self) -> re.Pattern[str]:
        """Get regex pattern for SQLite string literals."""
        # SQLite uses single quotes for strings with '' for escaping
        return re.compile(r"'(?:[^']|'')*'", re.IGNORECASE)

    def get_comment_pattern(self) -> re.Pattern[str]:
        """Get regex pattern for SQLite comments."""
        return re.compile(r"(?:--[^\r\n]*|/\*.*?\*/)", re.DOTALL)

    def get_statement_separator_pattern(self) -> re.Pattern[str]:
        """Get regex pattern for SQLite statement separators."""
        return re.compile(r";")

    def is_ddl_statement(self, statement: str) -> bool:
        """Check if statement is a DDL statement."""
        statement = statement.strip()
        if not statement:
            return False

        for pattern in self._ddl_patterns.values():
            if pattern.match(statement):
                return True

        return False

    def is_dml_statement(self, statement: str) -> bool:
        """Check if statement is a DML statement."""
        statement = statement.strip()
        if not statement:
            return False

        for pattern in self._dml_patterns.values():
            if pattern.match(statement):
                return True

        return False

    def is_query_statement(self, statement: str) -> bool:
        """Check if statement is a query statement."""
        statement = statement.strip()
        if not statement:
            return False

        for pattern in self._query_patterns.values():
            if pattern.match(statement):
                return True

        return False

    def get_batch_separator(self) -> str:
        """Get SQLite batch separator (semicolon)."""
        return ";"

    def supports_block_comments(self) -> bool:
        """Check if SQLite supports block comments."""
        return True

    def supports_line_comments(self) -> bool:
        """Check if SQLite supports line comments."""
        return True

    def get_block_keywords_for_splitting(self) -> Set[str]:
        """Get block keywords that require special handling during splitting."""
        # SQLite triggers use BEGIN/END blocks
        return {"BEGIN", "END", "CASE", "WHEN", "THEN", "ELSE"}

    def normalize_identifier(self, identifier: str, is_quoted: bool = False) -> str:
        """Normalize identifier according to SQLite rules.

        SQLite rules:
        - Unquoted identifiers are case-insensitive
        - Quoted identifiers (double quotes or brackets) preserve case

        Args:
            identifier: Raw identifier string
            is_quoted: Whether the identifier was quoted

        Returns:
            Normalized identifier
        """
        if not identifier:
            return identifier

        # Remove double quotes if present
        if identifier.startswith('"') and identifier.endswith('"'):
            identifier = identifier[1:-1]
            is_quoted = True

        # Remove brackets if present (SQL Server compatibility)
        if identifier.startswith("[") and identifier.endswith("]"):
            identifier = identifier[1:-1]
            is_quoted = True

        if is_quoted:
            return identifier  # Preserve exact case for quoted identifiers
        else:
            # SQLite is case-insensitive for unquoted identifiers
            # but doesn't fold case like PostgreSQL
            return identifier

    # Required abstract properties from DialectConfig
    @property
    def name(self) -> str:
        """Dialect name."""
        return "sqlite"  # lint: allow-dialect-string: dialect dispatch

    @property
    def batch_separators(self) -> List[Pattern[str]]:
        """Regex patterns for batch separators."""
        return [re.compile(r";")]

    @property
    def quoted_identifiers(self) -> List[Pattern[str]]:
        """Regex patterns for quoted identifiers."""
        return [
            re.compile(r'"[^"]*"'),  # Double quotes
            re.compile(r"\[[^\]]*\]"),  # Square brackets
        ]

    @property
    def comment_patterns(self) -> List[Pattern[str]]:
        """Regex patterns for comments."""
        return [
            re.compile(r"--[^\r\n]*"),  # Line comments
            re.compile(r"/\*.*?\*/", re.DOTALL),  # Block comments
        ]

    @property
    def block_keywords(self) -> List[str]:
        """Keywords that start block statements."""
        return ["CREATE", "ALTER", "DROP", "BEGIN"]

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
        return {
            # CREATE patterns
            "create_table": re.compile(
                r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            "create_view": re.compile(
                r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            "create_index": re.compile(
                r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            "create_trigger": re.compile(
                r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TRIGGER\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            "create_virtual_table": re.compile(
                r"CREATE\s+VIRTUAL\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            # ALTER patterns (limited in SQLite)
            "alter_table": re.compile(
                r"ALTER\s+TABLE\s+"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            # DROP patterns
            "drop_table": re.compile(
                r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            "drop_view": re.compile(
                r"DROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            "drop_index": re.compile(
                r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
            "drop_trigger": re.compile(
                r"DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))\.)?'
                r'(?:"([^"]+)"|\[([^\]]+)\]|([a-zA-Z_][a-zA-Z0-9_]*))',
                re.IGNORECASE,
            ),
        }
