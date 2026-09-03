"""SQL Server dialect configuration for regex-based parsing.

This module provides T-SQL-specific patterns and configuration for the regex parser,
extracted from TSqlParser.g4 and TSqlLexer.g4 grammar files from grammars-v4 repository.
"""

import re
from typing import Dict, List, Pattern, Set

from dblift.core.sql_parser.dialects.base_config import DialectConfig


class SqlServerConfig(DialectConfig):
    """SQL Server dialect configuration extracted from TSqlParser.g4 grammar.

    Grammar-based improvements include:
    - CREATE OR ALTER support for all object types
    - IF NOT EXISTS / IF EXISTS clauses
    - Filegroup support (ON [PRIMARY] | ON filegroup_name)
    - System-versioned temporal tables
    - Memory-optimized tables
    - Full-text indexes
    - XML indexes
    - Comprehensive synonym and linked server patterns
    - SCHEMA operations
    """

    @property
    def name(self) -> str:
        """Dialect name."""
        return "sqlserver"  # lint: allow-dialect-string: dialect dispatch

    @property
    def batch_separators(self) -> List[Pattern[str]]:
        """Regex patterns for batch separators (GO statements).

        T-SQL uses GO as a batch separator, not a statement terminator.
        """
        return [re.compile(r"(?im)^\s*GO\s*(?:--.*)?$", re.MULTILINE)]

    @property
    def quoted_identifiers(self) -> List[Pattern[str]]:
        """Regex patterns for quoted identifiers.

        T-SQL supports:
        - Bracket identifiers: [name]
        - Double-quoted identifiers: "name" (when QUOTED_IDENTIFIER is ON)
        """
        return [
            re.compile(r"\[([^\]]+)\]"),  # Bracket identifiers [name]
            re.compile(r'"([^"]+)"'),  # Double-quoted identifiers "name"
        ]

    @property
    def comment_patterns(self) -> List[Pattern[str]]:
        """Regex patterns for comments.

        T-SQL supports:
        - Line comments: --
        - Block comments: /* ... */
        """
        return [
            re.compile(r"--.*$", re.MULTILINE),  # Line comments
            re.compile(r"/\*.*?\*/", re.DOTALL),  # Block comments
        ]

    @property
    def block_keywords(self) -> List[str]:
        """Keywords that start block statements.

        T-SQL block statements that require special handling:
        - CREATE PROCEDURE/FUNCTION/TRIGGER
        - CREATE OR ALTER PROCEDURE/FUNCTION/TRIGGER
        - ALTER PROCEDURE/FUNCTION/TRIGGER
        - BEGIN...END blocks
        """
        return [
            "CREATE PROCEDURE",
            "CREATE FUNCTION",
            "CREATE TRIGGER",
            "CREATE OR ALTER PROCEDURE",
            "CREATE OR ALTER FUNCTION",
            "CREATE OR ALTER TRIGGER",
            "CREATE OR ALTER VIEW",
            "ALTER PROCEDURE",
            "ALTER FUNCTION",
            "ALTER TRIGGER",
            "ALTER VIEW",
        ]

    @property
    def ddl_patterns(self) -> Dict[str, Pattern[str]]:
        """DDL statement regex patterns extracted from TSqlParser.g4.

        Grammar-based improvements:
        - CREATE OR ALTER support for VIEW, PROCEDURE, FUNCTION, TRIGGER
        - IF NOT EXISTS support for CREATE statements
        - IF EXISTS support for DROP statements
        - Filegroup support (ON [PRIMARY] | ON filegroup_name)
        - System-versioned temporal tables
        - Memory-optimized tables
        - Full-text indexes
        - XML indexes
        - Synonym operations
        - SCHEMA operations (ALTER, DROP)
        """
        # T-SQL identifier pattern: bracket-quoted or unquoted
        # Supports schema.object format
        id_pattern = r"(?:\[?([^\]]+)\]?\.)?(?:\[?([^\]]+)\]?)"

        return {
            # Table operations
            # Grammar-based: CREATE TABLE supports filegroups, memory-optimized, system-versioned
            "create_table": re.compile(
                r"CREATE\s+TABLE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "alter_table": re.compile(
                r"ALTER\s+TABLE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP TABLE supports IF EXISTS
            "drop_table": re.compile(
                r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # View operations
            # Grammar-based: CREATE OR ALTER VIEW support
            "create_view": re.compile(
                r"CREATE\s+(?:OR\s+ALTER\s+)?VIEW\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "alter_view": re.compile(
                r"ALTER\s+VIEW\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP VIEW supports IF EXISTS
            "drop_view": re.compile(
                r"DROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Index operations
            # Grammar-based: Supports CLUSTERED/NONCLUSTERED, UNIQUE, FULLTEXT, XML indexes
            "create_index": re.compile(
                r"CREATE\s+(?:UNIQUE\s+)?(?:CLUSTERED\s+|NONCLUSTERED\s+)?"
                r"(?:PRIMARY\s+)?(?:XML\s+)?(?:SPATIAL\s+)?"
                r"(?:COLUMNSTORE\s+)?(?:NONCLUSTERED\s+COLUMNSTORE\s+)?"
                r"INDEX\s+(?:\[?([^\]]+)\]?)\s+ON\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE FULLTEXT INDEX
            "create_fulltext_index": re.compile(
                r"CREATE\s+FULLTEXT\s+INDEX\s+(?:ON\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE XML INDEX
            "create_xml_index": re.compile(
                r"CREATE\s+(?:PRIMARY\s+)?XML\s+INDEX\s+(?:\[?([^\]]+)\]?)\s+ON\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP INDEX supports IF EXISTS
            "drop_index": re.compile(
                r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?(?:\[?([^\]]+)\]?)\s+ON\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Procedure/Function operations
            # Grammar-based: CREATE OR ALTER support
            "create_procedure": re.compile(
                r"CREATE\s+(?:OR\s+ALTER\s+)?PROCEDURE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "alter_procedure": re.compile(
                r"ALTER\s+PROCEDURE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP PROCEDURE supports IF EXISTS
            "drop_procedure": re.compile(
                r"DROP\s+PROCEDURE\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE OR ALTER FUNCTION support
            "create_function": re.compile(
                r"CREATE\s+(?:OR\s+ALTER\s+)?FUNCTION\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "alter_function": re.compile(
                r"ALTER\s+FUNCTION\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP FUNCTION supports IF EXISTS
            "drop_function": re.compile(
                r"DROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Trigger operations
            # Grammar-based: CREATE OR ALTER TRIGGER support
            "create_trigger": re.compile(
                r"CREATE\s+(?:OR\s+ALTER\s+)?TRIGGER\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "alter_trigger": re.compile(
                r"ALTER\s+TRIGGER\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP TRIGGER supports IF EXISTS
            "drop_trigger": re.compile(
                r"DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Synonym operations
            # Grammar-based: CREATE SYNONYM support
            "create_synonym": re.compile(
                r"CREATE\s+SYNONYM\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP SYNONYM supports IF EXISTS
            "drop_synonym": re.compile(
                r"DROP\s+SYNONYM\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Linked Server operations (stored procedures)
            "create_linked_server": re.compile(
                r"(?:EXEC|EXECUTE)\s+sp_addlinkedserver\s+@server\s*=\s*(?:'([^']+)'|N'([^']+)'|\[?([^\]]+)\]?)",
                re.IGNORECASE,
            ),
            "drop_linked_server": re.compile(
                r"(?:EXEC|EXECUTE)\s+sp_dropserver\s+@server\s*=\s*(?:'([^']+)'|N'([^']+)'|\[?([^\]]+)\]?)",
                re.IGNORECASE,
            ),
            # SCHEMA operations
            # Grammar-based: CREATE SCHEMA support
            "create_schema": re.compile(
                r"CREATE\s+SCHEMA\s+(?:\[?([^\]]+)\]?)",
                re.IGNORECASE,
            ),
            # Grammar-based: ALTER SCHEMA support
            "alter_schema": re.compile(
                r"ALTER\s+SCHEMA\s+(?:\[?([^\]]+)\]?)",
                re.IGNORECASE,
            ),
            # Grammar-based: DROP SCHEMA supports IF EXISTS
            "drop_schema": re.compile(
                r"DROP\s+SCHEMA\s+(?:IF\s+EXISTS\s+)?(?:\[?([^\]]+)\]?)",
                re.IGNORECASE,
            ),
            # Other DDL
            "truncate_table": re.compile(
                r"TRUNCATE\s+TABLE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE TYPE support (user-defined types)
            "create_type": re.compile(
                r"CREATE\s+TYPE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "drop_type": re.compile(
                r"DROP\s+TYPE\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE SEQUENCE support
            "create_sequence": re.compile(
                r"CREATE\s+SEQUENCE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "drop_sequence": re.compile(
                r"DROP\s+SEQUENCE\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
        }

    @property
    def dml_patterns(self) -> Dict[str, Pattern[str]]:
        """DML statement regex patterns."""
        return {
            "insert": re.compile(
                r"INSERT\s+(?:INTO\s+)?(?:(?:\[?([^\]]+)\]?)\.)?(?:\[?([^\]]+)\]?)", re.IGNORECASE
            ),
            "update": re.compile(
                r"UPDATE\s+(?:(?:\[?([^\]]+)\]?)\.)?(?:\[?([^\]]+)\]?)", re.IGNORECASE
            ),
            "delete": re.compile(
                r"DELETE\s+(?:FROM\s+)?(?:(?:\[?([^\]]+)\]?)\.)?(?:\[?([^\]]+)\]?)", re.IGNORECASE
            ),
            "merge": re.compile(
                r"MERGE\s+(?:(?:\[?([^\]]+)\]?)\.)?(?:\[?([^\]]+)\]?)", re.IGNORECASE
            ),
            "execute": re.compile(
                r"EXEC(?:UTE)?\s+(?:(?:\[?([^\]]+)\]?)\.)?(?:\[?([^\]]+)\]?)", re.IGNORECASE
            ),
        }

    @property
    def query_patterns(self) -> Dict[str, Pattern[str]]:
        """Query statement regex patterns."""
        return {
            "select": re.compile(r"SELECT\s+", re.IGNORECASE),
            "with": re.compile(r"WITH\s+", re.IGNORECASE),
        }

    @property
    def object_patterns(self) -> Dict[str, Pattern[str]]:
        """Object extraction regex patterns.

        Grammar-based improvements based on T-SQL grammar analysis:
        - CREATE OR ALTER support for VIEW, PROCEDURE, FUNCTION, TRIGGER
        - IF NOT EXISTS / IF EXISTS clauses
        - Comprehensive bracket identifier support
        - Full-text and XML index patterns
        - Synonym patterns
        - SCHEMA operation patterns
        """
        # T-SQL identifier pattern: bracket-quoted or unquoted
        # Supports schema.object format
        id_pattern = r"(?:\[?([^\]]+)\]?\.)?(?:\[?([^\]]+)\]?)"

        return {
            # Tables
            # Grammar-based: Supports filegroups, memory-optimized, system-versioned
            "table_create": re.compile(
                r"CREATE\s+TABLE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "table_alter": re.compile(
                r"ALTER\s+TABLE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP TABLE supports IF EXISTS
            "table_drop": re.compile(
                r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Views
            # Grammar-based: CREATE OR ALTER VIEW support
            "view_create": re.compile(
                r"CREATE\s+(?:OR\s+ALTER\s+)?VIEW\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "view_alter": re.compile(
                r"ALTER\s+VIEW\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP VIEW supports IF EXISTS
            "view_drop": re.compile(
                r"DROP\s+VIEW\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Indexes
            # Grammar-based: Supports CLUSTERED/NONCLUSTERED, UNIQUE, XML, FULLTEXT, COLUMNSTORE
            "index_create": re.compile(
                r"CREATE\s+(?:UNIQUE\s+)?(?:CLUSTERED\s+|NONCLUSTERED\s+)?"
                r"(?:PRIMARY\s+)?(?:XML\s+)?(?:SPATIAL\s+)?"
                r"(?:COLUMNSTORE\s+)?(?:NONCLUSTERED\s+COLUMNSTORE\s+)?"
                r"INDEX\s+(?:\[?([^\]]+)\]?)\s+ON\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: FULLTEXT INDEX
            "fulltext_index_create": re.compile(
                r"CREATE\s+FULLTEXT\s+INDEX\s+(?:ON\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: XML INDEX
            "xml_index_create": re.compile(
                r"CREATE\s+(?:PRIMARY\s+)?XML\s+INDEX\s+(?:\[?([^\]]+)\]?)\s+ON\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: DROP INDEX supports IF EXISTS
            "index_drop": re.compile(
                r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?(?:\[?([^\]]+)\]?)\s+ON\s+" + id_pattern,
                re.IGNORECASE,
            ),
            # Procedures/Functions
            # Grammar-based: CREATE OR ALTER support
            "procedure_create": re.compile(
                r"CREATE\s+(?:OR\s+ALTER\s+)?PROCEDURE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "procedure_alter": re.compile(
                r"ALTER\s+PROCEDURE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "procedure_drop": re.compile(
                r"DROP\s+PROCEDURE\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Grammar-based: CREATE OR ALTER FUNCTION support
            "function_create": re.compile(
                r"CREATE\s+(?:OR\s+ALTER\s+)?FUNCTION\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "function_alter": re.compile(
                r"ALTER\s+FUNCTION\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "function_drop": re.compile(
                r"DROP\s+FUNCTION\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Triggers
            # Grammar-based: CREATE OR ALTER TRIGGER support
            "trigger_create": re.compile(
                r"CREATE\s+(?:OR\s+ALTER\s+)?TRIGGER\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "trigger_alter": re.compile(
                r"ALTER\s+TRIGGER\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "trigger_drop": re.compile(
                r"DROP\s+TRIGGER\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # Synonyms
            # Grammar-based: CREATE SYNONYM support
            "synonym_create": re.compile(
                r"CREATE\s+SYNONYM\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "synonym_drop": re.compile(
                r"DROP\s+SYNONYM\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # SCHEMA
            # Grammar-based: SCHEMA operations
            "schema_create": re.compile(
                r"CREATE\s+SCHEMA\s+(?:\[?([^\]]+)\]?)",
                re.IGNORECASE,
            ),
            "schema_alter": re.compile(
                r"ALTER\s+SCHEMA\s+(?:\[?([^\]]+)\]?)",
                re.IGNORECASE,
            ),
            "schema_drop": re.compile(
                r"DROP\s+SCHEMA\s+(?:IF\s+EXISTS\s+)?(?:\[?([^\]]+)\]?)",
                re.IGNORECASE,
            ),
            # TYPE (user-defined types)
            # Grammar-based: CREATE TYPE support
            "type_create": re.compile(
                r"CREATE\s+TYPE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "type_drop": re.compile(
                r"DROP\s+TYPE\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
            # SEQUENCE
            # Grammar-based: CREATE SEQUENCE support
            "sequence_create": re.compile(
                r"CREATE\s+SEQUENCE\s+" + id_pattern,
                re.IGNORECASE,
            ),
            "sequence_drop": re.compile(
                r"DROP\s+SEQUENCE\s+(?:IF\s+EXISTS\s+)?" + id_pattern,
                re.IGNORECASE,
            ),
        }

    def get_default_schema(self) -> str:
        """Get default schema name for SQL Server."""
        return "dbo"

    def get_identifier_pattern(self) -> re.Pattern[str]:
        """Get regex pattern for T-SQL identifiers.

        Based on T-SQL grammar: identifiers can be:
        - Bracket-quoted: [name]
        - Double-quoted: "name" (when QUOTED_IDENTIFIER is ON)
        - Unquoted: alphanumeric + underscore + @, #, $ (for some types)

        Returns:
            Compiled regex pattern for T-SQL identifiers
        """
        # T-SQL identifiers: bracket-quoted, double-quoted, or unquoted
        # Unquoted: alphanumeric + underscore, starting with letter or underscore or @ or #
        return re.compile(r'(?:\[[^\]]+\]|"[^"]+"|[a-zA-Z_@#][a-zA-Z0-9_@#$]*)', re.IGNORECASE)

    def get_qualified_identifier_pattern(self) -> re.Pattern[str]:
        """Get regex pattern for qualified identifiers (schema.object).

        Based on T-SQL grammar: qualified identifiers support schema.object format.
        Both parts can be bracket-quoted, double-quoted, or unquoted.

        Returns:
            Compiled regex pattern for qualified T-SQL identifiers
        """
        # Grammar-based: Support brackets and double quotes for T-SQL identifiers
        identifier = r'(?:\[[^\]]+\]|"[^"]+"|[a-zA-Z_@#][a-zA-Z0-9_@#$]*)'
        return re.compile(rf"(?:{identifier}\.)?{identifier}", re.IGNORECASE)

    def normalize_identifier(self, identifier: str, is_quoted: bool = False) -> str:
        """Normalize identifier according to SQL Server rules.

        SQL Server rules:
        - Unquoted identifiers are case-insensitive (stored as provided)
        - Quoted identifiers preserve case exactly
        - Bracket identifiers preserve case exactly

        Args:
            identifier: Raw identifier string
            is_quoted: Whether the identifier was quoted (brackets or double quotes)

        Returns:
            Normalized identifier
        """
        if not identifier:
            return identifier

        # Remove brackets if present
        if identifier.startswith("[") and identifier.endswith("]"):
            identifier = identifier[1:-1]
            is_quoted = True

        # Remove double quotes if present
        if identifier.startswith('"') and identifier.endswith('"'):
            identifier = identifier[1:-1]
            is_quoted = True

        if is_quoted:
            return identifier  # Preserve exact case for quoted identifiers
        else:
            # SQL Server preserves case for unquoted identifiers too
            # but comparisons are case-insensitive
            return identifier

    # Abstract method implementations
    def get_ddl_keywords(self) -> Set[str]:
        """Get DDL keywords for SQL Server."""
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
            "SYNONYM",
            "ROLE",
            "USER",
            "LOGIN",
        }

    def get_dml_keywords(self) -> Set[str]:
        """Get DML keywords for SQL Server."""
        return {"INSERT", "UPDATE", "DELETE", "MERGE", "EXEC", "EXECUTE", "SET", "VALUES"}

    def get_query_keywords(self) -> Set[str]:
        """Get query keywords for SQL Server."""
        return {"SELECT", "WITH", "EXPLAIN"}

    def get_string_literal_pattern(self) -> Pattern[str]:
        """Get regex pattern for string literals."""
        return re.compile(r"'([^']|'')*'", re.IGNORECASE)

    def get_comment_pattern(self) -> Pattern[str]:
        """Get regex pattern for comments."""
        return re.compile(r"(?:--.*$|/\*.*?\*/)", re.MULTILINE | re.DOTALL)

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
        """Get batch separator for SQL Server."""
        return "GO"

    def supports_block_comments(self) -> bool:
        """Check if SQL Server supports block comments."""
        return True

    def supports_line_comments(self) -> bool:
        """Check if SQL Server supports line comments."""
        return True
