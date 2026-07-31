"""PostgreSQL dialect configuration for regex-based parsing.

This module provides PostgreSQL-specific patterns and configurations for the
unified regex parser framework, extracted from PostgreSQLParser.g4 grammar.
"""

import re
from typing import Any, Dict, List, Pattern, Set

from core.sql_parser.dialects.base_config import DialectConfig


class PostgreSqlConfig(DialectConfig):
    """PostgreSQL dialect configuration with comprehensive pattern support."""

    def __init__(self) -> None:
        """Initialize PostgreSQL dialect configuration."""
        super().__init__()  # type: ignore[no-untyped-call]

        # PostgreSQL uses double quotes for identifiers, single quotes for strings
        self.identifier_quote_char = '"'
        self.string_quote_char = "'"

        # PostgreSQL supports dollar quoting for strings/functions
        self.supports_dollar_quoting = True

        # PostgreSQL uses semicolon as statement separator
        self.statement_separator = ";"

        # PostgreSQL supports block comments /* */ and line comments --
        self.line_comment_prefix = "--"
        self.block_comment_start = "/*"
        self.block_comment_end = "*/"

        # PostgreSQL-specific features
        self.supports_copy_statements = True
        self.supports_plpgsql_blocks = True
        self.supports_cte_with_recursive = True
        self.supports_on_conflict = True
        self.supports_returning = True

        # Compile regex patterns for performance
        self._compile_patterns()

    def _compile_patterns(self) -> None:
        """Compile regex patterns for performance."""
        # DDL patterns
        self._ddl_patterns = {
            "create_table": re.compile(
                r"\s*CREATE\s+(?:(?:GLOBAL|LOCAL)\s+)?(?:TEMPORARY|TEMP)?\s+TABLE\s+", re.IGNORECASE
            ),
            "create_view": re.compile(r"\s*CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+", re.IGNORECASE),
            "create_materialized_view": re.compile(
                r"\s*CREATE\s+MATERIALIZED\s+VIEW\s+", re.IGNORECASE
            ),
            "create_index": re.compile(
                r"\s*CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?", re.IGNORECASE
            ),
            "create_schema": re.compile(r"\s*CREATE\s+SCHEMA\s+", re.IGNORECASE),
            "create_sequence": re.compile(r"\s*CREATE\s+SEQUENCE\s+", re.IGNORECASE),
            "create_type": re.compile(r"\s*CREATE\s+TYPE\s+", re.IGNORECASE),
            "create_domain": re.compile(r"\s*CREATE\s+DOMAIN\s+", re.IGNORECASE),
            "create_function": re.compile(
                r"\s*CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+", re.IGNORECASE
            ),
            "create_procedure": re.compile(
                r"\s*CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+", re.IGNORECASE
            ),
            "create_trigger": re.compile(r"\s*CREATE\s+TRIGGER\s+", re.IGNORECASE),
            "create_extension": re.compile(r"\s*CREATE\s+EXTENSION\s+", re.IGNORECASE),
            "create_foreign_data_wrapper": re.compile(
                r"\s*CREATE\s+FOREIGN\s+DATA\s+WRAPPER\s+", re.IGNORECASE
            ),
            "create_server": re.compile(r"\s*CREATE\s+SERVER\s+", re.IGNORECASE),
            "drop_foreign_data_wrapper": re.compile(
                r"\s*DROP\s+FOREIGN\s+DATA\s+WRAPPER\s+", re.IGNORECASE
            ),
            "drop_server": re.compile(r"\s*DROP\s+SERVER\s+", re.IGNORECASE),
            "create_role": re.compile(r"\s*CREATE\s+(?:ROLE|USER|GROUP)\s+", re.IGNORECASE),
            "create_database": re.compile(r"\s*CREATE\s+DATABASE\s+", re.IGNORECASE),
            "create_tablespace": re.compile(r"\s*CREATE\s+TABLESPACE\s+", re.IGNORECASE),
            "create_cast": re.compile(r"\s*CREATE\s+CAST\s+", re.IGNORECASE),
            "create_transform": re.compile(r"\s*CREATE\s+TRANSFORM\s+", re.IGNORECASE),
            # Grammar-based: CREATE FOREIGN TABLE supports IF NOT EXISTS
            "create_foreign_table": re.compile(
                r"\s*CREATE\s+FOREIGN\s+TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?", re.IGNORECASE
            ),
            "create_publication": re.compile(r"\s*CREATE\s+PUBLICATION\s+", re.IGNORECASE),
            "create_subscription": re.compile(r"\s*CREATE\s+SUBSCRIPTION\s+", re.IGNORECASE),
            "create_policy": re.compile(r"\s*CREATE\s+POLICY\s+", re.IGNORECASE),
            "create_statistics": re.compile(r"\s*CREATE\s+STATISTICS\s+", re.IGNORECASE),
            "alter_table": re.compile(r"\s*ALTER\s+TABLE\s+", re.IGNORECASE),
            "alter_index": re.compile(r"\s*ALTER\s+INDEX\s+", re.IGNORECASE),
            "alter_sequence": re.compile(r"\s*ALTER\s+SEQUENCE\s+", re.IGNORECASE),
            "alter_view": re.compile(r"\s*ALTER\s+VIEW\s+", re.IGNORECASE),
            "alter_schema": re.compile(r"\s*ALTER\s+SCHEMA\s+", re.IGNORECASE),
            "alter_type": re.compile(r"\s*ALTER\s+TYPE\s+", re.IGNORECASE),
            "alter_domain": re.compile(r"\s*ALTER\s+DOMAIN\s+", re.IGNORECASE),
            "alter_function": re.compile(r"\s*ALTER\s+FUNCTION\s+", re.IGNORECASE),
            "alter_procedure": re.compile(r"\s*ALTER\s+PROCEDURE\s+", re.IGNORECASE),
            "alter_trigger": re.compile(r"\s*ALTER\s+TRIGGER\s+", re.IGNORECASE),
            "alter_extension": re.compile(r"\s*ALTER\s+EXTENSION\s+", re.IGNORECASE),
            "alter_role": re.compile(r"\s*ALTER\s+(?:ROLE|USER|GROUP)\s+", re.IGNORECASE),
            "alter_database": re.compile(r"\s*ALTER\s+DATABASE\s+", re.IGNORECASE),
            "alter_tablespace": re.compile(r"\s*ALTER\s+TABLESPACE\s+", re.IGNORECASE),
            "alter_foreign_table": re.compile(r"\s*ALTER\s+FOREIGN\s+TABLE\s+", re.IGNORECASE),
            "alter_publication": re.compile(r"\s*ALTER\s+PUBLICATION\s+", re.IGNORECASE),
            "alter_subscription": re.compile(r"\s*ALTER\s+SUBSCRIPTION\s+", re.IGNORECASE),
            "alter_policy": re.compile(r"\s*ALTER\s+POLICY\s+", re.IGNORECASE),
            "alter_system": re.compile(r"\s*ALTER\s+SYSTEM\s+", re.IGNORECASE),
            "drop_table": re.compile(r"\s*DROP\s+TABLE\s+", re.IGNORECASE),
            "drop_view": re.compile(r"\s*DROP\s+VIEW\s+", re.IGNORECASE),
            "drop_materialized_view": re.compile(
                r"\s*DROP\s+MATERIALIZED\s+VIEW\s+", re.IGNORECASE
            ),
            "drop_index": re.compile(r"\s*DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?", re.IGNORECASE),
            "drop_schema": re.compile(r"\s*DROP\s+SCHEMA\s+", re.IGNORECASE),
            "drop_sequence": re.compile(r"\s*DROP\s+SEQUENCE\s+", re.IGNORECASE),
            "drop_type": re.compile(r"\s*DROP\s+TYPE\s+", re.IGNORECASE),
            "drop_domain": re.compile(r"\s*DROP\s+DOMAIN\s+", re.IGNORECASE),
            "drop_function": re.compile(r"\s*DROP\s+FUNCTION\s+", re.IGNORECASE),
            "drop_procedure": re.compile(r"\s*DROP\s+PROCEDURE\s+", re.IGNORECASE),
            "drop_trigger": re.compile(r"\s*DROP\s+TRIGGER\s+", re.IGNORECASE),
            "drop_extension": re.compile(r"\s*DROP\s+EXTENSION\s+", re.IGNORECASE),
            "drop_role": re.compile(r"\s*DROP\s+(?:ROLE|USER|GROUP)\s+", re.IGNORECASE),
            "drop_database": re.compile(r"\s*DROP\s+DATABASE\s+", re.IGNORECASE),
            "drop_tablespace": re.compile(r"\s*DROP\s+TABLESPACE\s+", re.IGNORECASE),
            "drop_cast": re.compile(r"\s*DROP\s+CAST\s+", re.IGNORECASE),
            "drop_transform": re.compile(r"\s*DROP\s+TRANSFORM\s+", re.IGNORECASE),
            "drop_foreign_table": re.compile(r"\s*DROP\s+FOREIGN\s+TABLE\s+", re.IGNORECASE),
            "drop_publication": re.compile(r"\s*DROP\s+PUBLICATION\s+", re.IGNORECASE),
            "drop_subscription": re.compile(r"\s*DROP\s+SUBSCRIPTION\s+", re.IGNORECASE),
            "drop_policy": re.compile(r"\s*DROP\s+POLICY\s+", re.IGNORECASE),
            "drop_owned": re.compile(r"\s*DROP\s+OWNED\s+", re.IGNORECASE),
            "drop_statistics": re.compile(r"\s*DROP\s+STATISTICS\s+", re.IGNORECASE),
            "truncate": re.compile(r"\s*TRUNCATE\s+(?:TABLE\s+)?", re.IGNORECASE),
            "grant": re.compile(r"\s*GRANT\s+", re.IGNORECASE),
            "revoke": re.compile(r"\s*REVOKE\s+", re.IGNORECASE),
            "comment": re.compile(r"\s*COMMENT\s+ON\s+", re.IGNORECASE),
            "vacuum": re.compile(r"\s*VACUUM\s+", re.IGNORECASE),
            "analyze": re.compile(r"\s*ANALYZE\s+", re.IGNORECASE),
            "cluster": re.compile(r"\s*CLUSTER\s+", re.IGNORECASE),
            "reindex": re.compile(r"\s*REINDEX\s+", re.IGNORECASE),
        }

        # DML patterns
        self._dml_patterns = {
            "insert": re.compile(r"\s*INSERT\s+INTO\s+", re.IGNORECASE),
            "update": re.compile(r"\s*UPDATE\s+", re.IGNORECASE),
            "delete": re.compile(r"\s*DELETE\s+FROM\s+", re.IGNORECASE),
            "merge": re.compile(r"\s*MERGE\s+INTO\s+", re.IGNORECASE),
            "copy": re.compile(r"\s*COPY\s+", re.IGNORECASE),
            "call": re.compile(r"\s*CALL\s+", re.IGNORECASE),
            "execute": re.compile(r"\s*EXECUTE\s+", re.IGNORECASE),
            "prepare": re.compile(r"\s*PREPARE\s+", re.IGNORECASE),
            "deallocate": re.compile(r"\s*DEALLOCATE\s+", re.IGNORECASE),
            "lock": re.compile(r"\s*LOCK\s+(?:TABLE\s+)?", re.IGNORECASE),
        }

        # Query patterns
        self._query_patterns = {
            "select": re.compile(r"\s*SELECT\s+", re.IGNORECASE),
            "with": re.compile(r"\s*WITH\s+(?:RECURSIVE\s+)?", re.IGNORECASE),
            "values": re.compile(r"\s*VALUES\s+", re.IGNORECASE),
            "table": re.compile(r"\s*TABLE\s+", re.IGNORECASE),
            "explain": re.compile(r"\s*EXPLAIN\s+", re.IGNORECASE),
            "show": re.compile(r"\s*SHOW\s+", re.IGNORECASE),
        }

        # Dollar quoting pattern
        self.dollar_quote_pattern = re.compile(r"\$([a-zA-Z_][a-zA-Z0-9_]*)?\$", re.IGNORECASE)

        # Function/procedure pattern with dollar quoting
        self.function_with_dollar_pattern = re.compile(
            r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:FUNCTION|PROCEDURE)\s+.*?\$([a-zA-Z_][a-zA-Z0-9_]*)?\$",
            re.IGNORECASE | re.DOTALL,
        )

        # PL/pgSQL block pattern
        self.plpgsql_block_pattern = re.compile(
            r"DO\s+\$\$\s*BEGIN\s+.*?\s+END\s*\$\$", re.IGNORECASE | re.DOTALL
        )

        # COPY statement pattern
        self.copy_statement_pattern = re.compile(
            r"COPY\s+(?:\([^)]+\)|[^(]+?)\s+(?:FROM|TO)\s+", re.IGNORECASE
        )

        # Block keywords for PL/pgSQL
        self._block_keywords = {
            "BEGIN",
            "END",
            "DECLARE",
            "EXCEPTION",
            "WHEN",
            "THEN",
            "ELSE",
            "ELSIF",
            "IF",
            "LOOP",
            "WHILE",
            "FOR",
            "FOREACH",
            "CASE",
            "RETURN",
            "RAISE",
            "PERFORM",
            "EXECUTE",
            "OPEN",
            "CLOSE",
            "FETCH",
            "MOVE",
            "EXIT",
            "CONTINUE",
            "GOTO",
            "COMMIT",
            "ROLLBACK",
        }

    def get_ddl_keywords(self) -> Set[str]:
        """Get DDL keywords for PostgreSQL."""
        return {
            "CREATE",
            "ALTER",
            "DROP",
            "TRUNCATE",
            "GRANT",
            "REVOKE",
            "COMMENT",
            "VACUUM",
            "ANALYZE",
            "CLUSTER",
            "REINDEX",
            "REFRESH",
            "SECURITY",
            "LABEL",
            "IMPORT",
            "REASSIGN",
        }

    def get_dml_keywords(self) -> Set[str]:
        """Get DML keywords for PostgreSQL."""
        return {
            "INSERT",
            "UPDATE",
            "DELETE",
            "MERGE",
            "COPY",
            "CALL",
            "EXECUTE",
            "PREPARE",
            "DEALLOCATE",
            "LOCK",
            "LISTEN",
            "NOTIFY",
            "UNLISTEN",
            "LOAD",
            "DISCARD",
            "CHECKPOINT",
            "FETCH",
            "MOVE",
            "CLOSE",
        }

    def get_query_keywords(self) -> Set[str]:
        """Get query keywords for PostgreSQL."""
        return {"SELECT", "WITH", "VALUES", "TABLE", "EXPLAIN", "SHOW", "DESCRIBE", "DESC"}

    def get_transaction_keywords(self) -> Set[str]:
        """Get transaction control keywords for PostgreSQL."""
        return {
            "BEGIN",
            "START",
            "COMMIT",
            "END",
            "ROLLBACK",
            "ABORT",
            "SAVEPOINT",
            "RELEASE",
            "PREPARE",
            "TRANSACTION",
            "WORK",
        }

    def get_identifier_pattern(self) -> "re.Pattern[str]":
        """Get regex pattern for PostgreSQL identifiers.

        Based on PostgreSQL grammar: IdentifierChar: StrictIdentifierChar | '$'
        This allows $ in unquoted identifiers, which is PostgreSQL-specific.
        """
        # PostgreSQL identifiers: unquoted (alphanumeric + underscore + $, starting with letter)
        # or quoted with double quotes (with "" escaping)
        return re.compile(r'(?:"[^"]*"|[a-zA-Z_][a-zA-Z0-9_$]*)', re.IGNORECASE)

    def get_qualified_identifier_pattern(self) -> "re.Pattern[str]":
        """Get regex pattern for qualified identifiers (schema.table).

        Based on PostgreSQL grammar: qualified_name supports $ in identifiers.
        """
        # Grammar-based: Support $ in identifiers (PostgreSQL allows $ in unquoted identifiers)
        identifier = r'(?:"[^"]*"|[a-zA-Z_][a-zA-Z0-9_$]*)'
        return re.compile(rf"(?:{identifier}\.)?{identifier}", re.IGNORECASE)

    def get_string_literal_pattern(self) -> "re.Pattern[str]":
        """Get regex pattern for PostgreSQL string literals."""
        # PostgreSQL supports:
        # - Single quotes: 'string'
        # - Escaped strings: E'string'
        # - Dollar quotes: $tag$string$tag$
        return re.compile(
            r"(?:E?'(?:[^'\\]|\\.)*'|\$([a-zA-Z_][a-zA-Z0-9_]*)?\$.*?\$\1\$)",
            re.IGNORECASE | re.DOTALL,
        )

    def get_comment_pattern(self) -> "re.Pattern[str]":
        """Get regex pattern for PostgreSQL comments."""
        return re.compile(r"(?:--[^\r\n]*|/\*.*?\*/)", re.DOTALL)

    def get_statement_separator_pattern(self) -> "re.Pattern[str]":
        """Get regex pattern for PostgreSQL statement separators."""
        return re.compile(r";")

    def is_ddl_statement(self, statement: str) -> bool:
        """Check if statement is a DDL statement."""
        statement = statement.strip()
        if not statement:
            return False

        # Check against compiled DDL patterns
        for pattern in self._ddl_patterns.values():
            if pattern.match(statement):
                return True

        return False

    def is_dml_statement(self, statement: str) -> bool:
        """Check if statement is a DML statement."""
        statement = statement.strip()
        if not statement:
            return False

        # Check against compiled DML patterns
        for pattern in self._dml_patterns.values():
            if pattern.match(statement):
                return True

        return False

    def is_query_statement(self, statement: str) -> bool:
        """Check if statement is a query statement."""
        statement = statement.strip()
        if not statement:
            return False

        # Check against compiled query patterns
        for pattern in self._query_patterns.values():
            if pattern.match(statement):
                return True

        return False

    def get_batch_separator(self) -> str:
        """Get PostgreSQL batch separator (semicolon)."""
        return ";"

    def supports_block_comments(self) -> bool:
        """Check if PostgreSQL supports block comments."""
        return True

    def supports_line_comments(self) -> bool:
        """Check if PostgreSQL supports line comments."""
        return True

    def get_block_keywords_for_splitting(self) -> Set[str]:
        """Get block keywords that require special handling during splitting."""
        return self._block_keywords

    def extract_dollar_quoted_blocks(self, sql: str) -> List[Dict[str, Any]]:
        """Extract dollar-quoted blocks from SQL content."""
        blocks = []
        pos = 0

        while pos < len(sql):
            # Find start of dollar quote
            match = self.dollar_quote_pattern.search(sql, pos)
            if not match:
                break

            start_pos = match.start()
            tag = match.group(1) or ""
            start_quote = f"${tag}$"

            # Find matching end quote
            end_pos = sql.find(start_quote, match.end())
            if end_pos == -1:
                # No matching end quote found
                pos = match.end()
                continue

            # Extract the block
            block_content = sql[match.end() : end_pos]
            blocks.append(
                {
                    "start": start_pos,
                    "end": end_pos + len(start_quote),
                    "tag": tag,
                    "content": block_content,
                    "full_block": sql[start_pos : end_pos + len(start_quote)],
                }
            )

            pos = end_pos + len(start_quote)

        return blocks

    def normalize_identifier(self, identifier: str, is_quoted: bool = False) -> str:
        """Normalize identifier according to PostgreSQL rules.

        PostgreSQL rules:
        - Unquoted identifiers are case-insensitive (folded to lowercase)
        - Quoted identifiers preserve case exactly
        - Double quotes are used for identifiers

        Args:
            identifier: Raw identifier string
            is_quoted: Whether the identifier was quoted (double quotes)

        Returns:
            Normalized identifier
        """
        if not identifier:
            return identifier

        # Remove double quotes if present
        if identifier.startswith('"') and identifier.endswith('"'):
            identifier = identifier[1:-1]
            is_quoted = True

        if is_quoted:
            return identifier  # Preserve exact case for quoted identifiers
        else:
            # PostgreSQL folds unquoted identifiers to lowercase
            return identifier.lower()

    # Required abstract properties from unified_regex_parser.py DialectConfig
    @property
    def name(self) -> str:
        """Dialect name."""
        return "postgresql"  # lint: allow-dialect-string: dialect dispatch

    @property
    def batch_separators(self) -> List[Pattern[str]]:
        """Regex patterns for batch separators (PostgreSQL uses semicolon)."""
        return [re.compile(r";")]

    @property
    def quoted_identifiers(self) -> List[Pattern[str]]:
        """Regex patterns for quoted identifiers."""
        return [re.compile(r'"[^"]*"')]

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
        return ["CREATE", "ALTER", "DROP", "DO", "DECLARE", "BEGIN"]

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
            # CREATE patterns - Grammar-based improvements
            # CREATE TABLE: supports TEMP, IF NOT EXISTS, $ in identifiers
            "create_table": re.compile(
                r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?TABLE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # CREATE VIEW: supports OR REPLACE, IF NOT EXISTS, $ in identifiers
            "create_view": re.compile(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # CREATE MATERIALIZED VIEW: supports UNLOGGED, IF NOT EXISTS, $ in identifiers
            # Grammar-based: CREATE optnolog? MATERIALIZED VIEW (IF_P NOT EXISTS)?
            "create_materialized_view": re.compile(
                r"CREATE\s+(?:UNLOGGED\s+)?MATERIALIZED\s+VIEW\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # CREATE INDEX: supports IF NOT EXISTS, CONCURRENTLY, $ in identifiers
            "create_index": re.compile(
                r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE SEQUENCE supports IF NOT EXISTS and $ in identifiers
            "create_sequence": re.compile(
                r"CREATE\s+(?:TEMP(?:ORARY)?\s+)?SEQUENCE\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: Support $ in identifiers and quoted identifiers
            "create_function": re.compile(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "create_procedure": re.compile(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE TRIGGER supports CONSTRAINT TRIGGER and $ in identifiers
            "create_trigger": re.compile(
                r"CREATE\s+(?:CONSTRAINT\s+)?TRIGGER\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: Support $ in identifiers and quoted identifiers
            # Grammar-based: Support $ in identifiers and quoted identifiers
            "create_type": re.compile(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:DISTINCT\s+)?TYPE\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "create_domain": re.compile(
                r"CREATE\s+DOMAIN\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE COLLATION supports IF NOT EXISTS and FROM clause
            "create_collation": re.compile(
                r"CREATE\s+COLLATION\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE STATISTICS supports IF NOT EXISTS
            "create_statistics": re.compile(
                r"CREATE\s+STATISTICS\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE CAST syntax (special syntax with parentheses)
            "create_cast": re.compile(
                r"CREATE\s+CAST\s*\(.*?\)",
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE OPERATOR
            "create_operator": re.compile(
                r"CREATE\s+OPERATOR\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE OPERATOR CLASS
            "create_operator_class": re.compile(
                r"CREATE\s+OPERATOR\s+CLASS\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE OPERATOR FAMILY
            "create_operator_family": re.compile(
                r"CREATE\s+OPERATOR\s+FAMILY\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE SCHEMA supports IF NOT EXISTS
            "create_schema": re.compile(
                r"CREATE\s+SCHEMA\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE EXTENSION supports IF NOT EXISTS and $ in identifiers
            "create_extension": re.compile(
                r"CREATE\s+EXTENSION\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: Support $ in identifiers and quoted identifiers
            "create_foreign_data_wrapper": re.compile(
                r"CREATE\s+FOREIGN\s+DATA\s+WRAPPER\s+" r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "create_foreign_server": re.compile(
                r"CREATE\s+SERVER\s+(?:IF\s+NOT\s+EXISTS\s+)?"
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # ALTER patterns
            # Grammar-based: ALTER statements support IF EXISTS (not IF NOT EXISTS)
            # Support $ in identifiers and quoted identifiers
            "alter_table": re.compile(
                r"ALTER\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "alter_view": re.compile(
                r"ALTER\s+VIEW\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "alter_index": re.compile(
                r"ALTER\s+INDEX\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "alter_sequence": re.compile(
                r"ALTER\s+SEQUENCE\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: Support $ in identifiers and quoted identifiers for ALTER statements
            "alter_function": re.compile(
                r"ALTER\s+FUNCTION\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "alter_procedure": re.compile(
                r"ALTER\s+PROCEDURE\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "alter_trigger": re.compile(
                r"ALTER\s+TRIGGER\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "alter_type": re.compile(
                r"ALTER\s+TYPE\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "alter_domain": re.compile(
                r"ALTER\s+DOMAIN\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: Support $ in identifiers and quoted identifiers
            "alter_schema": re.compile(
                r"ALTER\s+SCHEMA\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: ALTER STATISTICS supports IF EXISTS
            "alter_statistics": re.compile(
                r"ALTER\s+STATISTICS\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # DROP patterns - Grammar-based: Support IF EXISTS, $ in identifiers
            "drop_table": re.compile(
                r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: Support $ in identifiers and quoted identifiers for DROP statements
            "drop_view": re.compile(
                r"DROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_materialized_view": re.compile(
                r"DROP\s+MATERIALIZED\s+VIEW\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_index": re.compile(
                r"DROP\s+INDEX\s+(?:CONCURRENTLY\s+)?(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_sequence": re.compile(
                r"DROP\s+SEQUENCE\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_function": re.compile(
                r"DROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_procedure": re.compile(
                r"DROP\s+PROCEDURE\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_trigger": re.compile(
                r"DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))'
                r'(?:\s+ON\s+(?:(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_$]*)\.)?'
                r'(?:"[^"]+"|[a-zA-Z_][a-zA-Z0-9_$]*))?',
                re.IGNORECASE,
            ),
            "drop_type": re.compile(
                r"DROP\s+TYPE\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_domain": re.compile(
                r"DROP\s+DOMAIN\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_schema": re.compile(
                r"DROP\s+SCHEMA\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_extension": re.compile(
                r"DROP\s+EXTENSION\s+(?:IF\s+EXISTS\s+)?"
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: Support $ in identifiers and quoted identifiers
            "drop_foreign_data_wrapper": re.compile(
                r"DROP\s+FOREIGN\s+DATA\s+WRAPPER\s+(?:IF\s+EXISTS\s+)?"
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "drop_foreign_server": re.compile(
                r"DROP\s+SERVER\s+(?:IF\s+EXISTS\s+)?" r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: DROP OPERATOR supports IF EXISTS
            "drop_operator": re.compile(
                r"DROP\s+OPERATOR\s+(?:IF\s+EXISTS\s+)?",
                re.IGNORECASE,
            ),
            # Grammar-based: DROP OPERATOR CLASS supports IF EXISTS
            "drop_operator_class": re.compile(
                r"DROP\s+OPERATOR\s+CLASS\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: DROP OPERATOR FAMILY supports IF EXISTS
            "drop_operator_family": re.compile(
                r"DROP\s+OPERATOR\s+FAMILY\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: DROP CAST supports IF EXISTS
            "drop_cast": re.compile(
                r"DROP\s+CAST\s+(?:IF\s+EXISTS\s+)?",
                re.IGNORECASE,
            ),
            # Grammar-based: DROP COLLATION supports IF EXISTS
            "drop_collation": re.compile(
                r"DROP\s+COLLATION\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # Grammar-based: DROP STATISTICS supports IF EXISTS
            "drop_statistics": re.compile(
                r"DROP\s+STATISTICS\s+(?:IF\s+EXISTS\s+)?"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            # COMMENT patterns (also DDL operations that affect objects)
            # Grammar-based: Support $ in identifiers and quoted identifiers
            "comment_table": re.compile(
                r"COMMENT\s+ON\s+TABLE\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "comment_column": re.compile(
                r"COMMENT\s+ON\s+COLUMN\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "comment_view": re.compile(
                r"COMMENT\s+ON\s+VIEW\s+"
                r'(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?'
                r'(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "comment_index": re.compile(r"COMMENT\s+ON\s+INDEX\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE),
            "comment_sequence": re.compile(
                r"COMMENT\s+ON\s+SEQUENCE\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE
            ),
            "comment_function": re.compile(
                r'COMMENT\s+ON\s+FUNCTION\s+(?:(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))\.)?(?:"([^"]+)"|([a-zA-Z_][a-zA-Z0-9_$]*))',
                re.IGNORECASE,
            ),
            "comment_procedure": re.compile(
                r"COMMENT\s+ON\s+PROCEDURE\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE
            ),
            "comment_trigger": re.compile(
                r"COMMENT\s+ON\s+TRIGGER\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE
            ),
            "comment_type": re.compile(r"COMMENT\s+ON\s+TYPE\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE),
            "comment_domain": re.compile(
                r"COMMENT\s+ON\s+DOMAIN\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE
            ),
            "comment_schema": re.compile(
                r"COMMENT\s+ON\s+SCHEMA\s+(?:(\w+)\.)?(\w+)", re.IGNORECASE
            ),
        }
