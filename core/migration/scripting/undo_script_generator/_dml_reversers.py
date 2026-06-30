"""Undo Script Generator — DML Reverser Mixin.

Contains methods for reversing DML statements: INSERT, UPDATE, DELETE.
"""

# mypy: disable-error-code="attr-defined"

import traceback
from typing import Any, Callable, Dict, Optional

from sqlglot import exp, parse_one

from core.migration.scripting.undo_script_generator._models import UndoStatement


class _UndoDmlReverserMixin:
    """Mixin providing methods to reverse DML statements.

    Requires the host class to provide:
      - self.dialect (str)
      - self.logger (Optional[Log])
      - self._quote_identifier(identifier)
      - self._extract_insert_where_clause_from_ast(ast, table_name)
      - self._extract_insert_where_clause(sql)
    """

    # Must be provided by the concrete class
    dialect: str
    logger: Any
    _quote_identifier: Callable[..., str]
    _extract_insert_where_clause_from_ast: Callable[..., Optional[str]]
    _extract_insert_where_clause: Callable[..., Optional[str]]

    def _reverse_insert_from_parsed(self, stmt: Any) -> Optional[UndoStatement]:
        """Reverse an INSERT statement from parsed SqlStatement.

        Args:
            stmt: SqlStatement object with INSERT statement

        Returns:
            UndoStatement with DELETE statement (if possible) or warning
        """
        sql = stmt.sql_text

        # Try to parse with sqlglot for better extraction
        try:
            from core.migration.scripting.undo_script_generator._helpers import (
                resolve_sqlglot_read_dialect,
            )

            sqlglot_dialect = resolve_sqlglot_read_dialect(self.dialect)
            ast = parse_one(sql, read=sqlglot_dialect)

            if isinstance(ast, exp.Insert):
                # Extract table name from sqlglot AST
                # For INSERT, ast.this is a Schema, and the table is in ast.this.this
                # table_name is declared Optional[str] up-front so the fallback
                # branch (getattr-based) can assign None without a narrowing-
                # vs-prior-branch incompatibility under mypy 2.x.
                table_name: Optional[str]
                schema: Optional[str]
                table_expr = ast.this
                if isinstance(table_expr, exp.Schema):
                    # Table is in ast.this.this
                    if isinstance(table_expr.this, exp.Table):
                        table_name = table_expr.this.name
                        schema = table_expr.this.db  # Schema is in the Table, not Schema
                    else:
                        # Sometimes the table name is directly in the Schema
                        name_value = (
                            getattr(table_expr.this, "name", None)
                            if hasattr(table_expr.this, "name")
                            else None
                        )
                        table_name = str(name_value) if name_value else None
                        schema = None
                elif isinstance(table_expr, exp.Table):
                    table_name = table_expr.name
                    schema = table_expr.db
                else:
                    table_name = None
                    schema = None

                if not table_name:
                    # Fallback to objects from parsed statement
                    if stmt.objects:
                        table_obj = stmt.objects[0]
                        table_name = table_obj.name
                        schema = table_obj.schema
                    else:
                        return UndoStatement(
                            sql="-- WARNING: Could not extract table from INSERT statement",
                            original_statement=sql,
                            operation_type="INSERT",
                            warning="Could not parse INSERT statement",
                            requires_manual_review=True,
                        )

                # At this point, table_name must not be None
                if not table_name:
                    return UndoStatement(
                        sql="-- WARNING: Could not extract table from INSERT statement",
                        original_statement=sql,
                        operation_type="INSERT",
                        warning="Could not parse INSERT statement",
                        requires_manual_review=True,
                    )

                # Format table name
                if schema:
                    formatted_table = (
                        f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"
                    )
                else:
                    formatted_table = self._quote_identifier(table_name)

                # Try to extract WHERE clause from INSERT VALUES using sqlglot
                where_clause = self._extract_insert_where_clause_from_ast(ast, table_name)
                if not where_clause:
                    # If sqlglot extraction fails, try regex fallback
                    where_clause = self._extract_insert_where_clause(sql)
                if where_clause:
                    delete_sql = f"DELETE FROM {formatted_table} WHERE {where_clause};"
                    return UndoStatement(
                        sql=delete_sql,
                        original_statement=sql,
                        operation_type="INSERT",
                        warning="INSERT reversal is best-effort - verify DELETE statement matches inserted rows",
                        requires_manual_review=True,
                    )
                else:
                    return UndoStatement(
                        sql="-- WARNING: Cannot automatically reverse INSERT statement (complex INSERT or no unique identifier)",
                        original_statement=sql,
                        operation_type="INSERT",
                        warning="INSERT statement cannot be automatically reversed - manual review required",
                        requires_manual_review=True,
                    )
        except Exception as e:
            # Fallback to regex-based extraction if sqlglot fails
            if self.logger:
                self.logger.debug(f"Sqlglot parsing failed for INSERT, using fallback: {e}")
                self.logger.debug(traceback.format_exc())

        # Fallback: use objects from parsed statement
        if stmt.objects:
            table_obj = stmt.objects[0]
            table_name = table_obj.name
            schema = table_obj.schema
        else:
            return UndoStatement(
                sql="-- WARNING: Could not extract table from INSERT statement",
                original_statement=sql,
                operation_type="INSERT",
                warning="Could not parse INSERT statement",
                requires_manual_review=True,
            )

        # Ensure table_name is not None
        if not table_name:
            return UndoStatement(
                sql="-- WARNING: Could not extract table from INSERT statement",
                original_statement=sql,
                operation_type="INSERT",
                warning="Could not parse INSERT statement",
                requires_manual_review=True,
            )

        # Format table name
        if schema:
            formatted_table = (
                f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"
            )
        else:
            formatted_table = self._quote_identifier(table_name)

        # Try regex-based extraction as last resort
        where_clause = self._extract_insert_where_clause(sql)
        if where_clause:
            delete_sql = f"DELETE FROM {formatted_table} WHERE {where_clause};"
            return UndoStatement(
                sql=delete_sql,
                original_statement=sql,
                operation_type="INSERT",
                warning="INSERT reversal is best-effort - verify DELETE statement matches inserted rows",
                requires_manual_review=True,
            )
        else:
            return UndoStatement(
                sql="-- WARNING: Cannot automatically reverse INSERT statement",
                original_statement=sql,
                operation_type="INSERT",
                warning="INSERT statement cannot be automatically reversed - manual review required",
                requires_manual_review=True,
            )

    def _reverse_insert(self, sql: str, analysis: Dict[str, Any]) -> Optional[UndoStatement]:
        """Reverse an INSERT statement.

        Args:
            sql: INSERT statement
            analysis: Statement analysis result

        Returns:
            UndoStatement with DELETE statement (if possible) or warning
        """
        # Extract table name
        objects = analysis.get("objects", [])
        if not objects:
            return UndoStatement(
                sql="-- WARNING: Could not extract table from INSERT statement",
                original_statement=sql,
                operation_type="INSERT",
                warning="Could not parse INSERT statement",
                requires_manual_review=True,
            )

        table_obj = objects[0]
        table_name = table_obj.get("object_name", "")
        schema = table_obj.get("schema")

        # Format table name
        if schema:
            formatted_table = (
                f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"
            )
        else:
            formatted_table = self._quote_identifier(table_name)

        # Try to extract WHERE clause from INSERT VALUES
        # This is a best-effort approach - may not be 100% accurate
        where_clause = self._extract_insert_where_clause(sql)
        if where_clause:
            delete_sql = f"DELETE FROM {formatted_table} WHERE {where_clause};"
            return UndoStatement(
                sql=delete_sql,
                original_statement=sql,
                operation_type="INSERT",
                warning="INSERT reversal is best-effort - verify DELETE statement matches inserted rows",
                requires_manual_review=True,
            )
        else:
            return UndoStatement(
                sql="-- WARNING: Cannot automatically reverse INSERT statement",
                original_statement=sql,
                operation_type="INSERT",
                warning="INSERT statement cannot be automatically reversed - manual review required",
                requires_manual_review=True,
            )

    def _reverse_update_from_parsed(self, stmt: Any) -> Optional[UndoStatement]:
        """Reverse an UPDATE statement from parsed SqlStatement.

        Args:
            stmt: SqlStatement object with UPDATE statement

        Returns:
            UndoStatement with warning (UPDATE cannot be reversed without old values)
        """
        return UndoStatement(
            sql="-- WARNING: Cannot reverse UPDATE statement without original values",
            original_statement=stmt.sql_text,
            operation_type="UPDATE",
            warning="UPDATE statements cannot be reversed without original column values",
            requires_manual_review=True,
        )

    def _reverse_update(self, sql: str, analysis: Dict[str, Any]) -> Optional[UndoStatement]:
        """Reverse an UPDATE statement.

        Args:
            sql: UPDATE statement
            analysis: Statement analysis result

        Returns:
            UndoStatement with warning (UPDATE cannot be reversed without old values)
        """
        return UndoStatement(
            sql="-- WARNING: Cannot reverse UPDATE statement without original values",
            original_statement=sql,
            operation_type="UPDATE",
            warning="UPDATE statements cannot be reversed without original column values",
            requires_manual_review=True,
        )

    def _reverse_delete_from_parsed(self, stmt: Any) -> Optional[UndoStatement]:
        """Reverse a DELETE statement from parsed SqlStatement.

        Args:
            stmt: SqlStatement object with DELETE statement

        Returns:
            UndoStatement with warning (DELETE cannot be reversed without deleted data)
        """
        return UndoStatement(
            sql="-- WARNING: Cannot reverse DELETE statement without deleted data",
            original_statement=stmt.sql_text,
            operation_type="DELETE",
            warning="DELETE statements cannot be reversed without deleted row data",
            requires_manual_review=True,
        )

    def _reverse_delete(self, sql: str, analysis: Dict[str, Any]) -> Optional[UndoStatement]:
        """Reverse a DELETE statement.

        Args:
            sql: DELETE statement
            analysis: Statement analysis result

        Returns:
            UndoStatement with warning (DELETE cannot be reversed without deleted data)
        """
        return UndoStatement(
            sql="-- WARNING: Cannot reverse DELETE statement without deleted data",
            original_statement=sql,
            operation_type="DELETE",
            warning="DELETE statements cannot be reversed without deleted row data",
            requires_manual_review=True,
        )
