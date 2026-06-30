"""SQLGlot-based SQL parser implementation.

This module provides a SQL parser implementation using sqlglot, a powerful
Python SQL parser and transpiler supporting multiple SQL dialects with AST-based parsing.

Supported dialects: Oracle, MySQL, PostgreSQL, SQL Server (TSQL)
Note: DB2 is not supported by sqlglot and uses a separate regex-based parser.
"""

import logging
from typing import Any, Dict, List, Optional, cast

import sqlglot
from sqlglot import exp, parse_one
from sqlglot.errors import ParseError

from core.sql_model.base import (
    ParseResult,
    SqlObject,
    SqlObjectType,
    SqlStatement,
    SqlStatementType,
)
from core.sql_model.dialect import SQLGLOT_DIALECT_MAP as _SQLGLOT_DIALECT_MAP
from core.sql_model.dialect import (
    _ensure_sqlglot_dialect_map,
)
from core.sql_parser.parser_interface import SqlParserInterface

# Setup logger
logger = logging.getLogger(__name__)


class SqlGlotParser(SqlParserInterface):
    """SQL parser implementation using sqlglot for AST-based parsing.

    This parser provides superior accuracy compared to regex-based parsers by:
    - Using proper AST (Abstract Syntax Tree) parsing
    - Handling complex SQL constructs (subqueries, CTEs, nested structures)
    - Extracting dependencies between objects
    - Supporting quoted identifiers and multi-schema references

    For Oracle dialect: Falls back to OracleParser (regex-based) for edge cases
    where sqlglot struggles with Oracle-specific syntax (Q-quotes, complex strings).
    This provides a hybrid approach with best-effort AST parsing and graceful degradation.
    """

    def __init__(self, dialect: str):
        """Initialize the parser with a specific SQL dialect.

        Args:
            dialect: SQL dialect name (oracle, mysql, postgresql, sqlserver)
        """
        self.dialect = dialect.lower()
        _ensure_sqlglot_dialect_map()
        self.sqlglot_dialect = _SQLGLOT_DIALECT_MAP.get(self.dialect) or self.dialect
        logger.debug(
            f"Initialized SqlGlotParser for dialect: {self.dialect} (sqlglot: {self.sqlglot_dialect})"
        )

    @property
    def dialect_name(self) -> str:
        """Return the name of the SQL dialect this parser handles."""
        return self.dialect

    def parse_sql(self, sql_content: str, default_schema: Optional[str] = None) -> ParseResult:
        """Parse SQL content into statements using sqlglot AST parsing.

        For Oracle: Falls back to regex-based OracleParser when sqlglot cannot parse
        Oracle-specific syntax (Q-quotes, complex string literals with escaped quotes).

        Args:
            sql_content: SQL content to parse
            default_schema: Default schema name

        Returns:
            ParseResult containing parsed statements and/or errors
        """
        try:
            # Split into individual statements (uses fallback for Oracle edge cases)
            statement_strings = self.split_statements(sql_content)

            statements = []
            errors = []

            for sql_text in statement_strings:
                if not sql_text.strip():
                    continue

                try:
                    normalized_sql = self._preprocess_sql_content(sql_text)

                    # Parse the statement using sqlglot
                    ast = parse_one(normalized_sql, read=self.sqlglot_dialect)

                    # Convert AST to SqlStatement
                    statement = self._ast_to_statement(
                        cast(exp.Expression, ast), sql_text, default_schema  # type: ignore[redundant-cast]
                    )
                    statements.append(statement)

                except ParseError as e:
                    error_msg = f"Parse error in statement: {str(e)}"
                    logger.debug(error_msg)
                    errors.append(error_msg)

                    # Create a statement with UNKNOWN type for failed parses
                    statement = SqlStatement(
                        sql_text=sql_text,
                        statement_type=SqlStatementType.UNKNOWN,
                        objects=[],
                        affected_objects=[],
                        dialect=self.dialect,
                        schema=default_schema,
                    )
                    statements.append(statement)

                except Exception as e:
                    error_msg = f"Unexpected error parsing statement: {str(e)}"
                    logger.error(error_msg)
                    errors.append(error_msg)

            success = len(errors) == 0
            return ParseResult(success=success, statements=statements, errors=errors)

        except Exception as e:
            error_msg = f"Error parsing SQL content: {str(e)}"
            logger.error(error_msg)
            return ParseResult(success=False, statements=[], errors=[error_msg])

    def split_statements(self, sql_content: str, strict_tokenizer: bool = False) -> List[str]:
        """Split SQL content into individual statements using sqlglot.

        Args:
            sql_content: SQL content to split

        Returns:
            List of SQL statement strings
        """
        try:
            # Parse all statements in the content
            normalized_content = self._preprocess_sql_content(sql_content)
            statements = sqlglot.parse(normalized_content, read=self.sqlglot_dialect)

            # Convert AST nodes back to SQL strings
            return [stmt.sql(dialect=self.sqlglot_dialect) for stmt in statements if stmt]

        except Exception as e:
            logger.warning(
                f"Error splitting statements with sqlglot: {str(e)}, using fallback parser"
            )

            # Fall back to the dialect's regex parser when available.
            from db.provider_registry import ProviderRegistry

            quirks = ProviderRegistry.get_quirks(self.dialect)
            regex_cls = quirks.parser_class("regex")
            if regex_cls is not None:
                try:
                    regex_parser = regex_cls()
                    result: list[str] = regex_parser.split_statements(sql_content)
                    return result
                except Exception as fallback_error:
                    logger.warning(
                        f"Regex fallback parser also failed: {str(fallback_error)}, using simple split"
                    )

            # Final fallback: simple semicolon split
            return [s.strip() for s in sql_content.split(";") if s.strip()]

    def validate_sql(self, sql_content: str) -> Dict[str, Any]:
        """Validate SQL syntax using sqlglot parser.

        Args:
            sql_content: SQL content to validate

        Returns:
            Dict with 'valid' (bool) and 'errors' (list of error messages)
        """
        errors = []

        try:
            # Try to parse the SQL content
            normalized_content = self._preprocess_sql_content(sql_content)
            statements = sqlglot.parse(normalized_content, read=self.sqlglot_dialect)

            if not statements:
                errors.append("No valid SQL statements found")

            for stmt in statements:
                if stmt is None:
                    errors.append("Invalid or empty statement")

        except ParseError as e:
            errors.append(f"Parse error: {str(e)}")
        except Exception as e:
            errors.append(f"Validation error: {str(e)}")

        return {"valid": len(errors) == 0, "errors": errors}

    def extract_objects(
        self, sql_content: str, default_schema: Optional[str] = None
    ) -> List[SqlObject]:
        """Extract database objects from SQL content using sqlglot AST traversal.

        This method provides superior object extraction compared to regex by:
        - Handling quoted identifiers correctly
        - Extracting schema-qualified names
        - Understanding SQL context (CREATE vs SELECT)

        Args:
            sql_content: SQL content to extract objects from
            default_schema: Default schema name

        Returns:
            List of extracted SQL objects
        """
        objects = []

        try:
            normalized_content = self._preprocess_sql_content(sql_content)
            statements = sqlglot.parse(normalized_content, read=self.sqlglot_dialect)

            for stmt in statements:
                if stmt is None:
                    continue

                # Extract objects based on statement type
                objects.extend(
                    self._extract_objects_from_ast(
                        cast(exp.Expression, stmt), default_schema  # type: ignore[redundant-cast]
                    )
                )

        except ParseError as e:
            # SqlGlot has limited support for dialect-specific syntax (e.g. Oracle PARTITION BY REFERENCE)
            logger.debug(f"SqlGlot parse failed for object extraction (use regex fallback): {e}")
        except Exception as e:
            logger.error(f"Error extracting objects: {str(e)}")

        return objects

    def _preprocess_sql_content(self, sql_content: str) -> str:
        """Apply dialect-specific preprocessing before sending SQL to sqlglot."""
        if not sql_content:
            return sql_content
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks(self.dialect)
        return quirks.preprocess_sql_for_sqlglot(sql_content)

    def _ast_to_statement(
        self, ast: exp.Expression, sql_text: str, default_schema: Optional[str]
    ) -> SqlStatement:
        """Convert sqlglot AST to dblift SqlStatement.

        Args:
            ast: sqlglot AST node
            sql_text: Original SQL text
            default_schema: Default schema name

        Returns:
            SqlStatement object
        """
        # Determine statement type
        statement_type = self._determine_statement_type(ast)

        # Extract objects from the AST
        objects = self._extract_objects_from_ast(ast, default_schema)

        # For DDL statements, the primary object is the one being created/altered/dropped
        affected_objects = self._extract_affected_objects(ast, default_schema)

        return SqlStatement(
            sql_text=sql_text,
            statement_type=statement_type,
            objects=objects,
            affected_objects=affected_objects,
            dialect=self.dialect,
            schema=default_schema,
        )

    def _determine_statement_type(self, ast: exp.Expression) -> SqlStatementType:
        """Determine the statement type from sqlglot AST.

        Args:
            ast: sqlglot AST node

        Returns:
            SqlStatementType enum value
        """
        # Map sqlglot expression types to SqlStatementType
        type_map = {
            exp.Create: SqlStatementType.CREATE,
            exp.Drop: SqlStatementType.DROP,
            exp.Insert: SqlStatementType.INSERT,
            exp.Update: SqlStatementType.UPDATE,
            exp.Delete: SqlStatementType.DELETE,
            exp.Select: SqlStatementType.SELECT,
            exp.Merge: SqlStatementType.MERGE,
            exp.Grant: SqlStatementType.GRANT,
            exp.Revoke: SqlStatementType.REVOKE,
            exp.Alter: SqlStatementType.ALTER,
            exp.AlterColumn: SqlStatementType.ALTER,
        }

        for ast_type, stmt_type in type_map.items():
            if isinstance(ast, ast_type):
                return stmt_type

        # Check if it's a query (SELECT)
        if isinstance(ast, (exp.Select, exp.Union, exp.Intersect, exp.Except)):
            return SqlStatementType.QUERY

        return SqlStatementType.UNKNOWN

    def _extract_objects_from_ast(
        self, ast: exp.Expression, default_schema: Optional[str]
    ) -> List[SqlObject]:
        """Extract SQL objects from sqlglot AST.

        Args:
            ast: sqlglot AST node
            default_schema: Default schema name

        Returns:
            List of SqlObject instances
        """
        objects = []

        # For CREATE/DROP/ALTER statements, extract only the primary object being created/altered/dropped
        # Don't extract all referenced tables (e.g., tables referenced in foreign keys)
        if isinstance(ast, (exp.Create, exp.Drop, exp.Alter)):
            # Handle CREATE INDEX specially - sqlglot structures it differently
            # Check both ast.kind and statement text to detect CREATE INDEX
            is_create_index = False
            index_name = None

            if isinstance(ast, exp.Create):
                # Check if it's an INDEX by kind
                if hasattr(ast, "kind") and ast.kind == "INDEX":
                    is_create_index = True
                    # Extract index name from ast.this
                    if hasattr(ast, "this"):
                        if isinstance(ast.this, exp.Index):
                            index_name = ast.this.name if hasattr(ast.this, "name") else None
                        elif hasattr(ast.this, "name"):
                            index_name = ast.this.name
                        elif hasattr(ast.this, "this") and hasattr(ast.this.this, "name"):
                            index_name = ast.this.this.name

                # Also check by examining the expression structure
                # CREATE INDEX statements have a specific structure
                if not is_create_index and hasattr(ast, "this"):
                    # Check if ast.this is an Index expression
                    if isinstance(ast.this, exp.Index):
                        is_create_index = True
                        index_name = ast.this.name if hasattr(ast.this, "name") else None
                    # Check for nested Index structures
                    elif hasattr(ast.this, "this") and isinstance(ast.this.this, exp.Index):
                        is_create_index = True
                        index_name = ast.this.this.name if hasattr(ast.this.this, "name") else None

            if is_create_index and index_name:
                obj = SqlObject(
                    name=index_name,
                    object_type=SqlObjectType.INDEX,
                    schema=default_schema,
                    dialect=self.dialect,
                )
                if obj not in objects:
                    objects.append(obj)
            else:
                # For other CREATE/DROP/ALTER statements, get the primary object
                target = None
                if isinstance(ast.this, exp.Schema) and isinstance(ast.this.this, exp.Table):
                    target = ast.this.this
                elif isinstance(ast.this, exp.Table):
                    target = ast.this
                elif hasattr(ast.this, "name") and isinstance(ast, exp.Create):
                    # Handle cases where ast.this is directly the object (e.g., sequences, some indexes)
                    # Create object directly from ast.this
                    if ast.kind == "SEQUENCE":
                        obj = SqlObject(
                            name=ast.this.name if hasattr(ast.this, "name") else str(ast.this),
                            object_type=SqlObjectType.SEQUENCE,
                            schema=default_schema,
                            dialect=self.dialect,
                        )
                        if obj not in objects:
                            objects.append(obj)
                        target = None  # Already handled

                if target:
                    target_obj = self._table_to_sqlobject(target, default_schema)
                    if target_obj:
                        obj = target_obj
                        # Set the correct object type based on CREATE/DROP kind
                        if isinstance(ast, exp.Create):
                            if ast.kind == "VIEW":
                                obj.object_type = SqlObjectType.VIEW
                            elif ast.kind == "INDEX":
                                obj.object_type = SqlObjectType.INDEX
                            elif ast.kind == "SEQUENCE":
                                obj.object_type = SqlObjectType.SEQUENCE
                            elif ast.kind == "TABLE":
                                obj.object_type = SqlObjectType.TABLE
                        elif isinstance(ast, exp.Drop):
                            # For DROP, infer type from kind or default to TABLE
                            if ast.kind == "VIEW":
                                obj.object_type = SqlObjectType.VIEW
                            elif ast.kind == "INDEX":
                                obj.object_type = SqlObjectType.INDEX
                            elif ast.kind == "SEQUENCE":
                                obj.object_type = SqlObjectType.SEQUENCE
                            else:
                                obj.object_type = SqlObjectType.TABLE
                        # For ALTER, keep the object type as TABLE (most common)

                        if obj not in objects:
                            objects.append(obj)
        else:
            # For non-DDL statements (SELECT, INSERT, etc.), extract all referenced tables
            # But skip COMMENT statements - they should be handled by regex parser with proper object types
            if not isinstance(ast, exp.Comment):
                for table in ast.find_all(exp.Table):
                    table_obj = self._table_to_sqlobject(table, default_schema)
                    if table_obj and table_obj not in objects:
                        objects.append(table_obj)

        # Extract procedures (CREATE PROCEDURE)
        # Note: sqlglot doesn't have a dedicated Procedure expression
        # Procedures are typically parsed as Create with kind="PROCEDURE"
        if isinstance(ast, exp.Create) and ast.kind == "PROCEDURE":
            if hasattr(ast.this, "name"):
                obj = SqlObject(
                    name=ast.this.name if hasattr(ast.this, "name") else str(ast.this),
                    object_type=SqlObjectType.PROCEDURE,
                    schema=default_schema,
                    dialect=self.dialect,
                )
                if obj not in objects:
                    objects.append(obj)

        # Extract functions (CREATE FUNCTION)
        if isinstance(ast, exp.Create) and ast.kind == "FUNCTION":
            # Function name is in ast.this
            if hasattr(ast.this, "name"):
                obj = SqlObject(
                    name=ast.this.name if hasattr(ast.this, "name") else str(ast.this),
                    object_type=SqlObjectType.FUNCTION,
                    schema=default_schema,
                    dialect=self.dialect,
                )
                if obj not in objects:
                    objects.append(obj)

        return objects

    def _extract_affected_objects(
        self, ast: exp.Expression, default_schema: Optional[str]
    ) -> List[SqlObject]:
        """Extract objects that are being created, altered, or dropped.

        Args:
            ast: sqlglot AST node
            default_schema: Default schema name

        Returns:
            List of affected SqlObject instances
        """
        affected = []

        # For CREATE/DROP/ALTER statements, the primary object is affected
        if isinstance(ast, (exp.Create, exp.Drop)):
            # Get the target object
            # For CREATE TABLE, ast.this is a Schema, and the table is in ast.this.this
            # For other objects, ast.this might be directly a Table
            target = None
            if isinstance(ast.this, exp.Schema) and isinstance(ast.this.this, exp.Table):
                target = ast.this.this
            elif isinstance(ast.this, exp.Table):
                target = ast.this

            if target:
                obj = self._table_to_sqlobject(target, default_schema)
                if obj:
                    # Set the correct object type based on CREATE/DROP kind
                    if ast.kind == "VIEW":
                        obj.object_type = SqlObjectType.VIEW
                    elif ast.kind == "INDEX":
                        obj.object_type = SqlObjectType.INDEX
                    elif ast.kind == "SEQUENCE":
                        obj.object_type = SqlObjectType.SEQUENCE
                    elif ast.kind == "TABLE":
                        obj.object_type = SqlObjectType.TABLE
                    affected.append(obj)

        elif isinstance(ast, (exp.Alter, exp.AlterColumn)):
            # Get the table being altered
            table = ast.this
            if isinstance(table, exp.Table):
                obj = self._table_to_sqlobject(table, default_schema)
                if obj:
                    affected.append(obj)

        elif isinstance(ast, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
            # Get the target table
            # For INSERT, ast.this is a Schema, and the table is in ast.this.this
            # For UPDATE/DELETE, ast.this might be directly a Table
            target = None
            if isinstance(ast.this, exp.Schema) and isinstance(ast.this.this, exp.Table):
                target = ast.this.this
            elif isinstance(ast.this, exp.Table):
                target = ast.this

            if target:
                obj = self._table_to_sqlobject(target, default_schema)
                if obj:
                    affected.append(obj)

        return affected

    def _table_to_sqlobject(
        self, table: exp.Table, default_schema: Optional[str]
    ) -> Optional[SqlObject]:
        """Convert sqlglot Table expression to SqlObject.

        Args:
            table: sqlglot Table expression
            default_schema: Default schema name

        Returns:
            SqlObject or None
        """
        if not table or not table.name:
            return None

        return SqlObject(
            name=table.name,
            object_type=SqlObjectType.TABLE,
            schema=table.db or default_schema,
            dialect=self.dialect,
        )
