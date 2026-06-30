"""SQL analyzer — parses migration scripts to extract tables, views, indexes, and other objects."""

import logging
import re
from typing import Any, Dict, List, Optional, Tuple, cast

from core.logger import Log
from core.migration.sql.statement_splitter import StatementSplitter
from core.sql_model.base import ParseResult
from core.sql_model.index import Index
from core.sql_model.procedure import Procedure
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.view import View

# Import parser system components
from core.sql_parser.parser_factory import SqlParserFactory

# Configure logging
logger = logging.getLogger(__name__)


class SqlAnalyzer:
    """Analyzes SQL statements for type and affected objects."""

    def __init__(
        self,
        dialect: str,
        logger: Optional[Log] = None,
        parser_factory: Any = None,
        statement_splitter: Optional[StatementSplitter] = None,
    ):
        """Initialize SQL analyzer.

        Args:
            dialect: SQL dialect to use (required — callers resolve it from
                config/provider or the plugin registry; ADR-26 E5)
            logger: Optional logger to use
            parser_factory: Optional parser factory to use
        """
        self.dialect = dialect.lower()
        self.logger = logger or logging.getLogger(__name__)

        # Statement execution only needs regex/tokenizer splitting. Rich parser
        # construction remains reserved for schema/object analysis paths.
        self._db_specific_parser = None
        try:
            classification_factory = SqlParserFactory(self.dialect, parser_type="regex")
            self._db_specific_parser = classification_factory.get_parser()

            self.logger.debug(
                f"Initialized parser: {type(self._db_specific_parser).__name__} for dialect: {self.dialect}"
            )
        except Exception as e:
            # Use a basic logger if the class logger isn't available yet
            import logging as log_module

            basic_logger = log_module.getLogger(__name__)
            basic_logger.debug(
                f"Failed to initialize database-specific parser for {self.dialect}: {e}"
            )
            self._db_specific_parser = None

        self.statement_splitter = statement_splitter or StatementSplitter(
            self.dialect, logger=self.logger
        )

        # Set up rich parser factory for object extraction and schema analysis.
        if parser_factory is not None:
            self.parser_factory = parser_factory
        else:
            self.parser_factory = SqlParserFactory(self.dialect)
        self.parser = None

    def get_statement_type(self, sql: str) -> str:
        """Get the high-level type of SQL statement (DDL, DML, QUERY, UNKNOWN).

        Uses database-specific regex parser, falling back to string analysis.
        """
        sql = sql.strip()

        if not sql:
            return "UNKNOWN"

        # Try database-specific parser classification first
        if self.dialect and hasattr(self, "_db_specific_parser") and self._db_specific_parser:
            try:
                # Use database-specific parser's improved classification
                pass

                # Check if the parser has the method before calling it
                if hasattr(self._db_specific_parser, "_identify_statement_type"):
                    stmt_type = self._db_specific_parser._identify_statement_type(sql)

                    # Convert SqlStatementType enum to string (not MigrationType).
                    if hasattr(stmt_type, "value"):
                        result = str(stmt_type.value)
                    else:
                        result = str(stmt_type)  # lint: allow-enum-str  SqlStatementType fallback

                    # If we got a definitive result (not UNKNOWN), use it
                    if result != "UNKNOWN":
                        return result

            except Exception as e:
                logger.debug(f"Database-specific parser classification failed: {e}")

        # Fallback to enhanced string-based classification
        return self._get_statement_type_string(sql)

    def _get_statement_type_string(self, sql: str) -> str:
        """Enhanced string-based statement type identification with EXEC support."""
        # Remove leading/trailing whitespace
        sql_clean = sql.strip()
        # UTF-8 BOM breaks startswith("CREATE") / DDL detection if left in place
        if sql_clean.startswith("\ufeff"):
            sql_clean = sql_clean.lstrip("\ufeff").lstrip()

        # Remove SQL comments to get the actual first keyword
        # Remove block comments /* ... */
        sql_clean = re.sub(r"/\*.*?\*/", "", sql_clean, flags=re.DOTALL)
        # Remove line comments -- ...
        sql_clean = re.sub(r"--.*?$", "", sql_clean, flags=re.MULTILINE)

        # Get the cleaned and normalized statement
        sql_upper = sql_clean.upper().strip()

        if not sql_upper:
            return "UNKNOWN"

        # DDL patterns - include GRANT/REVOKE as they are DDL statements
        ddl_keywords = ["CREATE", "ALTER", "DROP", "TRUNCATE", "COMMENT", "GRANT", "REVOKE"]
        if any(sql_upper.startswith(ddl) for ddl in ddl_keywords):
            return "DDL"

        # Special handling for RENAME - it's DDL but might have different syntax
        if sql_upper.startswith("RENAME"):
            return "DDL"

        # DML patterns (including EXEC/EXECUTE)
        dml_keywords = ["INSERT", "UPDATE", "DELETE", "MERGE", "UPSERT"]
        if any(sql_upper.startswith(dml) for dml in dml_keywords):
            return "DML"

        # Handle EXEC/EXECUTE patterns more carefully
        if re.match(r"^EXEC(?:\s|\t|\n|\r)", sql_upper) or sql_upper.startswith("EXECUTE "):
            return "DML"

        # QUERY patterns
        query_keywords = ["SELECT", "WITH", "SHOW", "DESCRIBE", "DESC", "EXPLAIN"]
        if any(sql_upper.startswith(query) for query in query_keywords):
            return "QUERY"

        return "UNKNOWN"

    def extract_objects(self, sql: str) -> List[Dict[str, str]]:
        """Extract objects from a SQL statement.

        Args:
            sql: SQL statement to analyze

        Returns:
            List of dictionaries with object information
        """
        # Use regex-based extraction

        # Use the regex-based extraction as a reliable method
        return self._extract_objects_regex(sql)

    def analyze_statement(self, sql: str) -> Dict[str, Any]:
        """Analyze a SQL statement for type and affected objects.

        Args:
            sql: SQL statement to analyze

        Returns:
            Dictionary containing analysis results
        """
        # Use regex-based analysis
        try:
            parser = self.parser
            if parser is None:
                parser = self.parser_factory.get_parser(self.dialect)
                self.parser = parser
            if parser is not None:
                parser.parse(sql)

            objects = self.extract_objects(sql)

            analysis = {
                "type": self.get_statement_type(sql),
                "objects": objects,
                "is_valid": True,
                "errors": [],
                "parsed_with": "regex",
            }

            # Log details about the statement for debugging
            if hasattr(self.logger, "is_debug_enabled") and self.logger.is_debug_enabled():
                stmt_type = analysis.get("type", "UNKNOWN")
                obj_names = [
                    f"{obj.get('object_type', 'Unknown')}:{obj.get('object_name', 'unknown')}"
                    for obj in objects
                ]

                self.logger.debug(
                    f"SQL Statement analyzed with regex: Type={stmt_type}, "
                    f"Objects={', '.join(obj_names) if obj_names else 'None'}"
                )
                self.logger.debug(f"SQL: {sql[:100]}{'...' if len(sql) > 100 else ''}")

            return dict(analysis)
        except Exception as e:
            self.logger.warning(f"Error analyzing statement: {e}")
            try:
                objects = self.extract_objects(sql)
            except Exception as obj_e:
                self.logger.debug(f"Could not extract objects from SQL: {obj_e}")
                objects = []

            try:
                stmt_type = self.get_statement_type(sql)
            except Exception as type_e:
                self.logger.debug(f"Could not determine statement type: {type_e}")
                stmt_type = "UNKNOWN"

            return {
                "type": stmt_type,
                "objects": objects,
                "is_valid": False,
                "errors": [str(e)],
                "parsed_with": "regex",
            }

    def validate_sql(self, sql: str) -> Tuple[bool, Optional[str]]:
        """Validate SQL syntax and return (is_valid, error_message)."""
        # Try to use database-specific parser first if available
        if self._db_specific_parser and hasattr(self._db_specific_parser, "validate_sql"):
            try:
                self.logger.debug(f"Using {self.dialect}-specific parser for SQL validation")
                result = self._db_specific_parser.validate_sql(sql)

                # Handle different return formats from database-specific parsers
                if isinstance(result, tuple) and len(result) == 2:
                    is_valid, error_message = result
                elif isinstance(result, dict):
                    is_valid = bool(result.get("is_valid", result.get("valid", True)))
                    raw_error_message = result.get("error_message", None)
                    error_message = (
                        str(raw_error_message) if raw_error_message is not None else None
                    )
                else:
                    # If parser returns something else, assume it's a boolean
                    is_valid = bool(result)
                    error_message = None

                self.logger.debug(
                    f"Validated SQL using {self.dialect}-specific parser: valid={is_valid}"
                )

                # Log validation details for debugging
                if hasattr(self.logger, "is_debug_enabled") and self.logger.is_debug_enabled():
                    truncated_sql = sql[:100] + ("..." if len(sql) > 100 else "")
                    if is_valid:
                        self.logger.debug(f"Valid SQL ({self.dialect}): {truncated_sql}")
                    else:
                        self.logger.debug(f"Invalid SQL ({self.dialect}): {truncated_sql}")
                        self.logger.debug(f"Error: {error_message}")

                return is_valid, error_message
            except Exception as e:
                self.logger.warning(
                    f"{self.dialect}-specific parser validation failed: {e}, assuming SQL is valid"
                )

        # Without database-specific parser validation, we use basic structural checks
        # This provides minimal validation but avoids complex ANTLR-based parsing
        self.logger.info("Using basic structural SQL validation")

        # Basic checks for common syntax errors
        sql_clean = sql.strip()
        if not sql_clean:
            return False, "Empty SQL statement"

        # Check for obvious syntax errors
        if sql_clean.count("(") != sql_clean.count(")"):
            return False, "Unmatched parentheses"

        if sql_clean.count("'") % 2 != 0:
            return False, "Unmatched single quotes"

        # If basic checks pass, assume SQL is valid
        return True, None

    def split_statements(self, sql: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL into individual statements.

        Args:
            sql: SQL script containing multiple statements
            strict_tokenizer: If True, dialect tokenizers fail on unknown
                characters instead of falling back to permissive splitting.

        Returns:
            List of individual SQL statements
        """
        statements = self.statement_splitter.split_statements(
            sql,
            strict_tokenizer=strict_tokenizer,
            fallback=self._split_statements_with_regex,
        )

        # Log each statement for debugging
        for i, stmt in enumerate(statements):
            self.logger.debug(
                f"Execution Statement {i+1}: '{stmt[:50]}{'...' if len(stmt) > 50 else ''}'"
            )

        return list(statements)

    def _split_statements_with_regex(self, sql: str) -> List[str]:
        """Split SQL statements using regex.

        This handles SQL server GO statements, semicolons, and takes into
        account strings, identifiers, and comments.

        Args:
            sql: SQL script containing multiple statements

        Returns:
            List of individual SQL statements
        """
        # Special handling for dialects that use a ``GO`` batch
        # separator (SQL Server / Sybase). The capability flag lives on
        # the plugin's quirks; SQL Server is currently the only opt-in.
        from db.provider_registry import ProviderRegistry

        if ProviderRegistry.get_quirks(self.dialect).supports_go_batch_separator:
            if re.search(r"(?i)^\s*GO\s*(?:--.*)?$", sql, flags=re.MULTILINE):
                return self._split_sqlserver_with_go(sql)

        # Handle normal semicolon-separated statements
        statements = []
        current_statement = []
        in_string = False
        in_identifier = False
        in_line_comment = False
        in_block_comment = False

        # Split by lines to handle line comments properly
        lines = sql.split("\n")

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
                    # Check for escaped quotes
                    if i < len(line) - 1 and line[i + 1] == "'":
                        # This is an escaped quote, not a string delimiter
                        current_statement.append(char)
                        current_statement.append(next_char)
                        i += 2
                        continue
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

    def _split_sqlserver_with_go(self, sql: str) -> List[str]:
        """Split SQL Server script with GO statements.

        Args:
            sql: SQL Server script with GO statements

        Returns:
            List of SQL statements
        """
        # Split on GO statements - properly handle GO statements at the end of lines
        # This regex matches GO on a line by itself, optionally with whitespace and comments
        batches = re.split(r"(?i)^\s*GO\s*(?:--.*)?$", sql, flags=re.MULTILINE)

        # Filter out empty batches and any standalone GO statements
        statements = []
        for batch in batches:
            batch = batch.strip()
            if batch and batch.upper() != "GO":
                statements.append(batch)

        return statements

    def _extract_objects_regex(self, statement: str) -> List[Dict[str, str]]:
        """Extract objects from a SQL statement using regex.

        Args:
            statement: SQL statement to analyze

        Returns:
            List of dictionaries with object information
        """
        objects: List[Dict[str, str]] = []

        # Handle empty input
        if not statement or not statement.strip():
            return objects

        statement = statement.strip()

        # Extract tables from CREATE TABLE
        if statement.upper().startswith("CREATE TABLE"):
            match = re.search(
                r'CREATE\s+TABLE\s+(?:(\w+)\.)?(["\[\]\w]+)', statement, re.IGNORECASE
            )
            if match:
                schema = match.group(1) or "default_schema"
                table = match.group(2)
                objects.append({"object_type": "Table", "object_name": f"{schema}.{table}"})

        # Extract tables from ALTER TABLE
        elif statement.upper().startswith("ALTER TABLE"):
            match = re.search(r'ALTER\s+TABLE\s+(?:(\w+)\.)?(["\[\]\w]+)', statement, re.IGNORECASE)
            if match:
                schema = match.group(1) or "default_schema"
                table = match.group(2)
                objects.append({"object_type": "Table", "object_name": f"{schema}.{table}"})

        # Extract views from CREATE VIEW
        elif statement.upper().startswith("CREATE VIEW") or statement.upper().startswith(
            "CREATE OR REPLACE VIEW"
        ):
            match = re.search(
                r'CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:(\w+)\.)?(["\[\]\w]+)',
                statement,
                re.IGNORECASE,
            )
            if match:
                schema = match.group(1) or "default_schema"
                view = match.group(2)
                objects.append({"object_type": "View", "object_name": f"{schema}.{view}"})

        # Extract indexes from CREATE INDEX
        elif statement.upper().startswith("CREATE INDEX") or statement.upper().startswith(
            "CREATE UNIQUE INDEX"
        ):
            match = re.search(
                r'CREATE\s+(?:UNIQUE\s+)?INDEX\s+(["\[\]\w]+)\s+ON\s+(?:(\w+)\.)?(["\[\]\w]+)',
                statement,
                re.IGNORECASE,
            )
            if match:
                index = match.group(1)
                schema = match.group(2) or "default_schema"
                table = match.group(3)
                objects.append(
                    {"object_type": "Index", "object_name": index, "on_object": f"{schema}.{table}"}
                )

        # Extract objects from DROP statements
        elif statement.upper().startswith("DROP"):
            match = re.search(r'DROP\s+(\w+)\s+(?:(\w+)\.)?(["\[\]\w]+)', statement, re.IGNORECASE)
            if match:
                object_type = match.group(1)
                schema = match.group(2) or "default_schema"
                object_name = match.group(3)
                objects.append(
                    {"object_type": object_type, "object_name": f"{schema}.{object_name}"}
                )

        return objects

    # ========================================================================
    # SQL Model API - Phase 1.4: Rich Object Extraction
    # ========================================================================

    def parse_sql(self, sql: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL and return rich ParseResult with Table/View/Index objects.

        This method provides access to the enhanced SQL Model objects extracted
        by the HybridParser, including:
        - Table objects with columns and constraints
        - View objects with query definitions
        - Index objects with column information
        - Dependency information

        Args:
            sql: SQL script to parse
            default_schema: Default schema name for objects without explicit schema

        Returns:
            ParseResult containing rich SQL Model objects

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            result = analyzer.parse_sql("CREATE TABLE users (id INT PRIMARY KEY);")

            if result.success and result.tables:
                table = result.tables[0]
                print(f"Table: {table.name}")
                print(f"Columns: {len(table.columns)}")
                for constraint in table.constraints:
                    print(f"Constraint: {constraint.constraint_type.value}")
            ```
        """
        try:
            result = self.parser_factory.parse_sql(sql, default_schema)
            return cast(ParseResult, result)
        except Exception as e:
            self.logger.error(f"Error parsing SQL: {e}")
            return ParseResult(success=False, errors=[str(e)])

    def get_tables(self, sql: str, default_schema: Optional[str] = None) -> List[Table]:
        """Extract Table objects from SQL.

        Args:
            sql: SQL script containing CREATE TABLE statements
            default_schema: Default schema name

        Returns:
            List of Table objects with columns and constraints

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            tables = analyzer.get_tables('''
                CREATE TABLE users (
                    id INTEGER PRIMARY KEY,
                    username VARCHAR(100) NOT NULL
                );
            ''')

            for table in tables:
                print(f"Table: {table.name}, Columns: {len(table.columns)}")
            ```
        """
        result = self.parse_sql(sql, default_schema)
        return result.tables if result.tables else []

    def get_views(self, sql: str, default_schema: Optional[str] = None) -> List[View]:
        """Extract View objects from SQL.

        Args:
            sql: SQL script containing CREATE VIEW statements
            default_schema: Default schema name

        Returns:
            List of View objects with query definitions

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            views = analyzer.get_views('''
                CREATE VIEW active_users AS
                SELECT * FROM users WHERE active = true;
            ''')

            for view in views:
                print(f"View: {view.name}")
            ```
        """
        result = self.parse_sql(sql, default_schema)
        return result.views if result.views else []

    def get_indexes(self, sql: str, default_schema: Optional[str] = None) -> List[Index]:
        """Extract Index objects from SQL.

        Args:
            sql: SQL script containing CREATE INDEX statements
            default_schema: Default schema name

        Returns:
            List of Index objects

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            indexes = analyzer.get_indexes('''
                CREATE INDEX idx_users_email ON users(email);
            ''')

            for index in indexes:
                print(f"Index: {index.name} on {index.table_name}")
            ```
        """
        result = self.parse_sql(sql, default_schema)
        return result.indexes if result.indexes else []

    def get_functions(self, sql: str, default_schema: Optional[str] = None) -> List[Procedure]:
        """Extract Function objects from SQL.

        Args:
            sql: SQL script containing CREATE FUNCTION statements
            default_schema: Default schema name

        Returns:
            List of Procedure objects (functions)

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            functions = analyzer.get_functions('''
                CREATE FUNCTION calculate_total(price DECIMAL, tax DECIMAL)
                RETURNS DECIMAL AS $$
                BEGIN
                    RETURN price * (1 + tax);
                END;
                $$ LANGUAGE plpgsql;
            ''')

            for function in functions:
                print(f"Function: {function.name}, Returns: {function.return_type}")
            ```
        """
        result = self.parse_sql(sql, default_schema)
        return result.functions if result.functions else []

    def get_triggers(self, sql: str, default_schema: Optional[str] = None) -> List[Trigger]:
        """Extract Trigger objects from SQL.

        Args:
            sql: SQL script containing CREATE TRIGGER statements
            default_schema: Default schema name

        Returns:
            List of Trigger objects

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            triggers = analyzer.get_triggers('''
                CREATE TRIGGER audit_trigger
                AFTER INSERT ON users
                FOR EACH ROW EXECUTE FUNCTION audit_function();
            ''')

            for trigger in triggers:
                print(f"Trigger: {trigger.name} on {trigger.table_name}")
            ```
        """
        result = self.parse_sql(sql, default_schema)
        return result.triggers if result.triggers else []

    def get_table(
        self, sql: str, table_name: str, default_schema: Optional[str] = None
    ) -> Optional[Table]:
        """Get a specific Table object by name.

        Args:
            sql: SQL script
            table_name: Name of the table to find
            default_schema: Default schema name

        Returns:
            Table object if found, None otherwise

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            table = analyzer.get_table(sql_script, "users")

            if table:
                print(f"Found table: {table.name}")
                for col in table.columns:
                    print(f"  - {col.name}: {col.data_type}")
            ```
        """
        result = self.parse_sql(sql, default_schema)
        return result.get_table(table_name) if result else None

    def get_view(
        self, sql: str, view_name: str, default_schema: Optional[str] = None
    ) -> Optional[View]:
        """Get a specific View object by name.

        Args:
            sql: SQL script
            view_name: Name of the view to find
            default_schema: Default schema name

        Returns:
            View object if found, None otherwise
        """
        result = self.parse_sql(sql, default_schema)
        return result.get_view(view_name) if result else None

    def has_circular_dependencies(self, sql: str, default_schema: Optional[str] = None) -> bool:
        """Check if SQL contains circular dependencies.

        Args:
            sql: SQL script
            default_schema: Default schema name

        Returns:
            True if circular dependencies detected, False otherwise

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            if analyzer.has_circular_dependencies(sql_script):
                print("Warning: Circular dependencies detected!")
            ```
        """
        result = self.parse_sql(sql, default_schema)
        return result.has_circular_dependencies() if result else False

    def get_dependencies(
        self, sql: str, default_schema: Optional[str] = None
    ) -> Dict[str, List[str]]:
        """Get dependency graph from SQL.

        Args:
            sql: SQL script
            default_schema: Default schema name

        Returns:
            Dictionary mapping table names to their dependencies

        Example:
            ```python
            analyzer = SqlAnalyzer("postgresql")
            deps = analyzer.get_dependencies(sql_script)

            for table, dependencies in deps.items():
                print(f"{table} depends on: {', '.join(dependencies)}")
            ```
        """
        result = self.parse_sql(sql, default_schema)
        return result.dependencies if result and result.dependencies else {}
