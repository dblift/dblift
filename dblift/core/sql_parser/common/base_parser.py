"""Base parser implementations."""

import re
from typing import Any, Dict, List, Optional

from dblift.core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlObjectType,
    SqlStatement,
)
from dblift.core.sql_parser.parser_interface import SqlParserInterface

# SQL statement type constants
_SQL_TYPE_DDL = "DDL"
_SQL_TYPE_DML = "DML"
_SQL_TYPE_QUERY = "QUERY"


class RegexBasedParser(SqlParserInterface):
    """
    A parser implementation that uses regular expressions for parsing SQL statements.

    This is a fallback parser that doesn't depend on ANTLR or other external libraries.
    """

    def __init__(self, dialect: str):
        """Initialize RegexBasedParser.

        Args:
            dialect: SQL dialect to use
        """
        self._dialect: str = dialect
        self._last_statement: Optional[str] = None
        self._last_objects: List[Any] = []
        self._last_errors: List[Any] = []
        self._last_type: Optional[Any] = None

    @property
    def dialect_name(self) -> str:
        """Return the dialect name."""
        return self._dialect

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content into statements.

        Args:
            sql_content: SQL content to parse
            default_schema: Default schema name

        Returns:
            ParseResult with statements and any errors
        """
        statements = []
        errors = []

        try:
            # Split into individual statements
            sql_statements = self.split_statements(sql_content)

            # Parse each statement
            for sql in sql_statements:
                if not sql.strip():
                    continue

                try:
                    stmt_type = self._get_statement_type(sql)
                    objects = self.extract_objects(sql, default_schema)

                    statement = SqlStatement(
                        sql_text=sql,
                        statement_type=stmt_type,
                        objects=objects,
                        affected_objects=objects,
                        dialect=self._dialect,
                        schema=default_schema,
                    )
                    statements.append(statement)
                except Exception as e:
                    errors.append(f"Error parsing statement: {str(e)}")
        except Exception as e:
            errors.append(f"Error splitting SQL: {str(e)}")

        # Return a parse result
        return ParseResult(success=len(errors) == 0, statements=statements, errors=errors)

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into individual statements.

        Args:
            sql_content: SQL content to split

        Returns:
            List of SQL statements
        """
        # GO batch separators (SQL Server / MSSQL).
        from dblift.db.provider_registry import ProviderRegistry

        _quirks = ProviderRegistry.get_quirks(self._dialect.lower())
        if _quirks.supports_go_batch_separator:
            if re.search(r"(?i)^\s*GO\s*(?:--.*)?$", sql_content, flags=re.MULTILINE):
                return self._split_sqlserver_with_go(sql_content)

        # Handle normal semicolon-separated statements
        statements = self._split_by_semicolon(sql_content)
        return statements

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL syntax and return validation results.

        Args:
            sql_content: SQL content to validate

        Returns:
            Dictionary with validation results
        """
        # We don't do real validation without ANTLR, just assume SQL is valid
        return {"valid": True, "errors": []}

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract objects from SQL content.

        Args:
            sql_content: SQL content to extract objects from
            default_schema: Default schema name

        Returns:
            List of SqlObject instances
        """
        sql_objects: List[SqlObject] = []

        # Handle empty input
        if not sql_content or not sql_content.strip():
            return sql_objects

        sql = sql_content.strip()
        from dblift.db.provider_registry import ProviderRegistry

        _quirks = ProviderRegistry.get_quirks(self._dialect.lower())
        default_schema = (
            default_schema
            or _quirks.parser_default_schema
            or _quirks.default_schema_name
            or "default_schema"
        )

        # Extract tables from CREATE TABLE
        if sql.upper().startswith("CREATE TABLE"):
            match = re.search(r"CREATE\s+TABLE\s+(?:(\w+)\.)?(\w+)", sql, re.IGNORECASE)
            if match:
                schema = match.group(1) or default_schema
                table = match.group(2)
                sql_objects.append(
                    SqlObject(
                        name=table,
                        object_type=SqlObjectType.TABLE,
                        schema=schema,
                        dialect=self._dialect,
                    )
                )

        # Extract tables from ALTER TABLE
        elif sql.upper().startswith("ALTER TABLE"):
            match = re.search(r"ALTER\s+TABLE\s+(?:(\w+)\.)?(\w+)", sql, re.IGNORECASE)
            if match:
                schema = match.group(1) or default_schema
                table = match.group(2)
                sql_objects.append(
                    SqlObject(
                        name=table,
                        object_type=SqlObjectType.TABLE,
                        schema=schema,
                        dialect=self._dialect,
                    )
                )

        # Extract views from CREATE VIEW
        elif sql.upper().startswith("CREATE VIEW") or sql.upper().startswith(
            "CREATE OR REPLACE VIEW"
        ):
            match = re.search(
                r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:(\w+)\.)?(\w+)", sql, re.IGNORECASE
            )
            if match:
                schema = match.group(1) or default_schema
                view = match.group(2)
                sql_objects.append(
                    SqlObject(
                        name=view,
                        object_type=SqlObjectType.VIEW,
                        schema=schema,
                        dialect=self._dialect,
                    )
                )

        # Extract indexes from CREATE INDEX
        elif sql.upper().startswith("CREATE INDEX") or sql.upper().startswith(
            "CREATE UNIQUE INDEX"
        ):
            match = re.search(
                r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(\w+)\s+ON\s+(?:(\w+)\.)?(\w+)", sql, re.IGNORECASE
            )
            if match:
                index = match.group(1)
                schema = match.group(2) or default_schema
                table = match.group(3)
                sql_objects.append(
                    SqlObject(
                        name=index,
                        object_type=SqlObjectType.INDEX,
                        schema=schema,
                        dialect=self._dialect,
                    )
                )
                # Also add the table as an affected object
                sql_objects.append(
                    SqlObject(
                        name=table,
                        object_type=SqlObjectType.TABLE,
                        schema=schema,
                        dialect=self._dialect,
                    )
                )

        # Extract objects from DROP statements
        elif sql.upper().startswith("DROP"):
            match = re.search(r"DROP\s+(\w+)\s+(?:(\w+)\.)?(\w+)", sql, re.IGNORECASE)
            if match:
                object_type_str = match.group(1).upper()
                schema = match.group(2) or default_schema
                object_name = match.group(3)

                # Map the object type string to SqlObjectType
                object_type = SqlObjectType.UNKNOWN
                if object_type_str == "TABLE":
                    object_type = SqlObjectType.TABLE
                elif object_type_str == "VIEW":
                    object_type = SqlObjectType.VIEW
                elif object_type_str == "INDEX":
                    object_type = SqlObjectType.INDEX
                elif object_type_str == "SEQUENCE":
                    object_type = SqlObjectType.SEQUENCE
                elif object_type_str == "PROCEDURE":
                    object_type = SqlObjectType.PROCEDURE
                elif object_type_str == "FUNCTION":
                    object_type = SqlObjectType.FUNCTION
                elif object_type_str == "TRIGGER":
                    object_type = SqlObjectType.TRIGGER

                sql_objects.append(
                    SqlObject(
                        name=object_name,
                        object_type=object_type,
                        schema=schema,
                        dialect=self._dialect,
                    )
                )

        return sql_objects

    def get_affected_objects(
        self, sql: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Get objects affected by a SQL statement.

        Args:
            sql: SQL statement to analyze
            default_schema: Default schema name

        Returns:
            List of affected SqlObject instances
        """
        return self.extract_objects(sql, default_schema)

    def get_errors(self) -> List[str]:
        """Get any errors from the last parse operation.

        Returns:
            List of error messages
        """
        return self._last_errors

    @property
    def is_valid(self) -> bool:
        """Check if the last parse operation was valid.

        Returns:
            True if valid, False otherwise
        """
        return len(self._last_errors) == 0

    @property
    def is_dml(self) -> bool:
        """Check if the last parsed statement is DML.

        Returns:
            True if DML, False otherwise
        """
        return self._last_type == _SQL_TYPE_DML

    @property
    def is_query(self) -> bool:
        """Check if the last parsed statement is a query.

        Returns:
            True if query, False otherwise
        """
        return self._last_type == _SQL_TYPE_QUERY

    def _split_by_semicolon(self, sql_content: str) -> List[str]:
        """Split SQL content into individual statements.

        Args:
            sql_content: SQL content to split

        Returns:
            List of SQL statements
        """
        # Split by lines to handle line comments properly
        lines = sql_content.split("\n")

        statements = []
        current_statement = []
        in_string = False
        in_identifier = False
        in_line_comment = False
        in_block_comment = False

        for line in lines:
            # If we're in a line comment from the previous line, reset the flag
            if in_line_comment:
                in_line_comment = False

            # Skip empty lines
            if not line.strip():
                continue

            # Process line character by character
            i = 0
            while i < len(line):
                char = line[i]
                next_char = line[i + 1] if i < len(line) - 1 else ""

                # Handle string literals
                if char == "'" and not in_line_comment and not in_block_comment:
                    in_string = not in_string

                # Handle quoted identifiers (e.g., [name] in SQL Server, "name" in Oracle/PostgreSQL)
                elif (
                    (char == "[" or char == '"')
                    and not in_string
                    and not in_line_comment
                    and not in_block_comment
                ):
                    in_identifier = True
                elif (char == "]" or char == '"') and in_identifier:
                    in_identifier = False

                # Handle line comments (--) but only if not in string or block comment
                elif (
                    char == "-"
                    and next_char == "-"
                    and not in_string
                    and not in_identifier
                    and not in_block_comment
                ):
                    in_line_comment = True
                    i += 1  # Skip the next character

                # Handle block comments (/* */) but only if not in string
                elif char == "/" and next_char == "*" and not in_string and not in_line_comment:
                    in_block_comment = True
                    i += 1  # Skip the next character
                elif char == "*" and next_char == "/" and in_block_comment:
                    in_block_comment = False
                    i += 1  # Skip the next character

                # Handle semicolons (statement separators) but only if not in literals or comments
                elif (
                    char == ";"
                    and not in_string
                    and not in_identifier
                    and not in_line_comment
                    and not in_block_comment
                ):
                    # Add the current character to complete the statement
                    current_statement.append(char)

                    # Join the accumulated characters to form a statement
                    statement = "".join(current_statement).strip()
                    if statement and statement != ";":
                        statements.append(statement)

                    # Reset for the next statement
                    current_statement = []

                    # Skip to the next character
                    i += 1
                    continue

                # Add the current character to the statement
                if not in_line_comment and not in_block_comment:
                    current_statement.append(char)

                i += 1

            # Add a newline at the end of the line if we're collecting a statement
            if current_statement and not in_line_comment and not in_block_comment:
                current_statement.append("\n")

        # Add the last statement if there's any content left
        if current_statement:
            statement = "".join(current_statement).strip()
            if statement:
                statements.append(statement)

        return statements

    def _split_sqlserver_with_go(self, sql_content: str) -> List[str]:
        """Split SQL Server script with GO statements, following strict rules for batch cleaning."""
        # Split on GO statements - must be on a line by themselves, case-insensitive
        batches = re.split(r"(?im)^GO\s*$", sql_content)
        result = []

        for batch in batches:
            # Skip empty batches
            batch = batch.strip()
            if batch and batch.upper() != "GO":
                # Further split each batch on semicolons, but preserve DDL blocks
                batch_statements = self._split_batch_intelligently(batch)
                result.extend(batch_statements)

        return result

    def _split_batch_intelligently(self, batch_content: str) -> List[str]:
        """Split a SQL Server batch into individual statements, preserving DDL blocks."""
        statements = []
        current_statement = []
        in_string = False
        in_identifier = False
        in_line_comment = False
        in_block_comment = False
        # Track if we're inside a DDL block (CREATE PROCEDURE, FUNCTION, TRIGGER, etc.)
        in_ddl_block = False
        ddl_block_depth = 0

        i = 0
        while i < len(batch_content):
            char = batch_content[i]

            # Handle string literals
            if char == "'" and not in_line_comment and not in_block_comment:
                in_string = not in_string
                current_statement.append(char)
                i += 1
                continue

            # Handle SQL Server identifiers [...]
            elif char == "[" and not in_string and not in_line_comment and not in_block_comment:
                in_identifier = True
                current_statement.append(char)
                i += 1
                continue
            elif char == "]" and in_identifier:
                in_identifier = False
                current_statement.append(char)
                i += 1
                continue

            # Handle line comments --
            elif (
                char == "-"
                and i < len(batch_content) - 1
                and batch_content[i + 1] == "-"
                and not in_string
                and not in_identifier
                and not in_block_comment
            ):
                in_line_comment = True
                current_statement.append(char)
                current_statement.append(batch_content[i + 1])
                i += 2
                continue

            # Handle block comments /* ... */
            elif (
                char == "/"
                and i < len(batch_content) - 1
                and batch_content[i + 1] == "*"
                and not in_string
                and not in_identifier
                and not in_line_comment
            ):
                in_block_comment = True
                current_statement.append(char)
                current_statement.append(batch_content[i + 1])
                i += 2
                continue
            elif (
                char == "*"
                and i < len(batch_content) - 1
                and batch_content[i + 1] == "/"
                and in_block_comment
            ):
                in_block_comment = False
                current_statement.append(char)
                current_statement.append(batch_content[i + 1])
                i += 2
                continue

            # End line comments at newline
            elif char in ["\n", "\r"] and in_line_comment:
                in_line_comment = False
                current_statement.append(char)
                i += 1
                continue

            # Check for DDL block keywords (case-insensitive) when not in strings/comments
            if not in_string and not in_identifier and not in_line_comment and not in_block_comment:
                current_text = "".join(current_statement).upper()

                # Check for BEGIN keyword to increase block depth
                if re.search(r"\bBEGIN\s*$", current_text):
                    if in_ddl_block:
                        ddl_block_depth += 1

                # Check for END keyword to decrease block depth
                elif re.search(r"\bEND\s*$", current_text):
                    if in_ddl_block and ddl_block_depth > 0:
                        ddl_block_depth -= 1
                        if ddl_block_depth == 0:
                            in_ddl_block = False  # End of DDL block

                # Check for DDL statement start (CREATE PROCEDURE, FUNCTION, TRIGGER, etc.)
                elif re.search(
                    r"\bCREATE\s+(OR\s+REPLACE\s+)?(PROCEDURE|FUNCTION|TRIGGER)\b", current_text
                ):
                    in_ddl_block = True
                    ddl_block_depth = 0  # Will be incremented when we hit BEGIN

            # Handle statement termination on semicolons
            if (
                char == ";"
                and not in_string
                and not in_identifier
                and not in_line_comment
                and not in_block_comment
                and not in_ddl_block  # Don't split inside DDL blocks
            ):
                current_statement.append(char)
                if current_statement:
                    stmt = "".join(current_statement).strip()
                    if stmt:
                        statements.append(stmt)
                    current_statement = []
                i += 1
                continue

            current_statement.append(char)
            i += 1

        # Handle any remaining statement
        if current_statement:
            stmt = "".join(current_statement).strip()
            if stmt:
                statements.append(stmt)

        return statements

    def _get_statement_type(self, statement: str) -> str:
        """Get the type of SQL statement (DDL, DML, QUERY, UNKNOWN)."""
        statement = statement.strip().upper()

        # DDL statements
        if any(
            statement.startswith(keyword)
            for keyword in ["CREATE", "ALTER", "DROP", "TRUNCATE", "RENAME", "COMMENT"]
        ):
            return _SQL_TYPE_DDL

        # DML statements
        if any(
            statement.startswith(keyword)
            for keyword in ["INSERT", "UPDATE", "DELETE", "MERGE", "CALL", "EXPLAIN", "LOCK"]
        ):
            return _SQL_TYPE_DML

        # Query statements
        if any(
            statement.startswith(keyword)
            for keyword in ["SELECT", "WITH", "SHOW", "DESC", "DESCRIBE"]
        ):
            return _SQL_TYPE_QUERY

        # Default to UNKNOWN
        return "UNKNOWN"
