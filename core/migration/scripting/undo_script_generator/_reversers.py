"""Undo Script Generator Reversers Mixin.

Contains all _reverse_*_from_parsed and _reverse_* methods that generate
reversed SQL statements for the undo script.
"""

# mypy: disable-error-code="attr-defined"

import re
import traceback
from typing import Any, Dict, Optional

from sqlglot import exp, parse_one

from core.migration.scripting.undo_script_generator._models import UndoStatement
from core.sql_model.base import SqlStatementType


class _UndoReversersMixin:
    """Mixin providing all _reverse_* methods for reversing SQL statements."""

    dialect: str
    logger: Any
    sql_analyzer: Any

    def _reverse_statement_from_parsed(self, stmt: Any) -> Optional[UndoStatement]:
        """Reverse a parsed SQL statement.

        Args:
            stmt: SqlStatement object from parser

        Returns:
            UndoStatement or None if statement cannot be reversed
        """
        sql = stmt.sql_text
        sql_upper = sql.strip().upper()
        stmt_type = stmt.statement_type

        # If statement type is UNKNOWN or generic (DDL/DML), infer from SQL text
        if stmt_type in (SqlStatementType.UNKNOWN, SqlStatementType.DDL, SqlStatementType.DML):
            if sql_upper.startswith("CREATE"):
                return self._reverse_create_from_parsed(stmt)
            elif sql_upper.startswith("ALTER"):
                return self._reverse_alter_from_parsed(stmt)
            elif sql_upper.startswith("DROP"):
                return self._reverse_drop_from_parsed(stmt)
            elif sql_upper.startswith("INSERT"):
                return self._reverse_insert_from_parsed(stmt)
            elif sql_upper.startswith("UPDATE"):
                return self._reverse_update_from_parsed(stmt)
            elif sql_upper.startswith("DELETE"):
                return self._reverse_delete_from_parsed(stmt)
            elif sql_upper.startswith("COMMENT"):
                return self._reverse_comment_from_parsed(stmt)
        else:
            # Route to appropriate reverser based on statement type
            if stmt_type == SqlStatementType.CREATE:
                return self._reverse_create_from_parsed(stmt)
            elif stmt_type == SqlStatementType.ALTER:
                return self._reverse_alter_from_parsed(stmt)
            elif stmt_type == SqlStatementType.DROP:
                return self._reverse_drop_from_parsed(stmt)
            elif stmt_type == SqlStatementType.INSERT:
                return self._reverse_insert_from_parsed(stmt)
            elif stmt_type == SqlStatementType.UPDATE:
                return self._reverse_update_from_parsed(stmt)
            elif stmt_type == SqlStatementType.DELETE:
                return self._reverse_delete_from_parsed(stmt)
            elif stmt_type == SqlStatementType.COMMENT:
                return self._reverse_comment_from_parsed(stmt)

        # Unknown or unsupported statement type
        # stmt_type is a SqlStatementType, not a MigrationType.
        return UndoStatement(
            sql=f"-- WARNING: Cannot reverse statement type: {stmt_type.value if hasattr(stmt_type, 'value') else stmt_type}",
            original_statement=sql,
            operation_type=str(stmt_type),  # lint: allow-enum-str
            warning="Statement type cannot be automatically reversed",
            requires_manual_review=True,
        )

    def _reverse_statement(self, sql: str) -> Optional[UndoStatement]:
        """Reverse a single SQL statement (fallback method using string parsing).

        Args:
            sql: SQL statement to reverse

        Returns:
            UndoStatement or None if statement cannot be reversed
        """
        sql_upper = sql.strip().upper()

        # Determine specific statement type by parsing SQL directly
        if sql_upper.startswith("CREATE"):
            analysis = self.sql_analyzer.analyze_statement(sql)
            return self._reverse_create(sql, analysis)
        elif sql_upper.startswith("ALTER"):
            analysis = self.sql_analyzer.analyze_statement(sql)
            return self._reverse_alter(sql, analysis)
        elif sql_upper.startswith("DROP"):
            analysis = self.sql_analyzer.analyze_statement(sql)
            return self._reverse_drop(sql, analysis)
        elif sql_upper.startswith("INSERT"):
            analysis = self.sql_analyzer.analyze_statement(sql)
            return self._reverse_insert(sql, analysis)
        elif sql_upper.startswith("UPDATE"):
            analysis = self.sql_analyzer.analyze_statement(sql)
            return self._reverse_update(sql, analysis)
        elif sql_upper.startswith("DELETE"):
            analysis = self.sql_analyzer.analyze_statement(sql)
            return self._reverse_delete(sql, analysis)
        elif sql_upper.startswith("COMMENT"):
            return self._reverse_comment(sql)
        else:
            return UndoStatement(
                sql="-- WARNING: Cannot reverse statement type",
                original_statement=sql,
                operation_type="UNKNOWN",
                warning="Statement type cannot be automatically reversed",
                requires_manual_review=True,
            )

    def _reverse_create_from_parsed(self, stmt: Any) -> Optional[UndoStatement]:
        """Reverse a CREATE statement from parsed SqlStatement.

        Args:
            stmt: SqlStatement object with CREATE statement

        Returns:
            UndoStatement with DROP statement
        """
        sql = stmt.sql_text
        # Get the object being created from affected_objects (more accurate)
        if stmt.affected_objects:
            obj = stmt.affected_objects[0]
            obj_type = obj.object_type.value
            obj_name = obj.name
            schema = obj.schema
        elif stmt.objects:
            obj = stmt.objects[0]
            obj_type = obj.object_type.value
            obj_name = obj.name
            schema = obj.schema
        else:
            # Fallback to regex extraction
            obj_info = self._extract_create_object(sql)
            if not obj_info:
                return UndoStatement(
                    sql="-- WARNING: Could not extract object from CREATE statement",
                    original_statement=sql,
                    operation_type="CREATE",
                    warning="Could not parse CREATE statement",
                    requires_manual_review=True,
                )
            obj_type, obj_name, schema = obj_info

        # Generate DROP statement based on object type
        if obj_type in ("TABLE", "INDEX", "VIEW", "SEQUENCE", "TRIGGER", "PROCEDURE", "FUNCTION"):
            drop_sql = self._generate_drop_statement(obj_type, obj_name, schema)
            return UndoStatement(
                sql=drop_sql,
                original_statement=sql,
                operation_type="CREATE",
            )
        else:
            return UndoStatement(
                sql=f"-- WARNING: Cannot reverse CREATE {obj_type}",
                original_statement=sql,
                operation_type="CREATE",
                warning=f"CREATE {obj_type} reversal not yet implemented",
                requires_manual_review=True,
            )

    def _reverse_create(self, sql: str, analysis: Dict[str, Any]) -> Optional[UndoStatement]:
        """Reverse a CREATE statement.

        Args:
            sql: CREATE statement
            analysis: Statement analysis result

        Returns:
            UndoStatement with DROP statement
        """
        # Extract object name and type
        objects = analysis.get("objects", [])
        if not objects:
            # Try regex extraction
            obj_info = self._extract_create_object(sql)
            if not obj_info:
                return UndoStatement(
                    sql="-- WARNING: Could not extract object from CREATE statement",
                    original_statement=sql,
                    operation_type="CREATE",
                    warning="Could not parse CREATE statement",
                    requires_manual_review=True,
                )
            obj_type, obj_name, schema = obj_info
        else:
            obj = objects[0]
            obj_type = obj.get("object_type", "UNKNOWN").upper()
            obj_name = obj.get("object_name", "")
            schema = obj.get("schema")

        # Generate DROP statement based on object type
        if obj_type in ("TABLE", "INDEX", "VIEW", "SEQUENCE", "TRIGGER", "PROCEDURE", "FUNCTION"):
            drop_sql = self._generate_drop_statement(obj_type, obj_name, schema)
            return UndoStatement(
                sql=drop_sql,
                original_statement=sql,
                operation_type="CREATE",
            )
        else:
            return UndoStatement(
                sql=f"-- WARNING: Cannot reverse CREATE {obj_type}",
                original_statement=sql,
                operation_type="CREATE",
                warning=f"CREATE {obj_type} reversal not yet implemented",
                requires_manual_review=True,
            )

    def _reverse_alter_from_parsed(self, stmt: Any) -> Optional[UndoStatement]:
        """Reverse an ALTER statement from parsed SqlStatement.

        Args:
            stmt: SqlStatement object with ALTER statement

        Returns:
            UndoStatement with reverse ALTER statement
        """
        sql = stmt.sql_text
        sql_upper = sql.strip().upper()

        # Get table name from affected_objects
        if stmt.affected_objects:
            table_obj = stmt.affected_objects[0]
            table_name = table_obj.name
            schema = table_obj.schema
        elif stmt.objects:
            table_obj = stmt.objects[0]
            table_name = table_obj.name
            schema = table_obj.schema
        else:
            return UndoStatement(
                sql="-- WARNING: Could not extract table from ALTER statement",
                original_statement=sql,
                operation_type="ALTER",
                warning="Could not parse ALTER statement",
                requires_manual_review=True,
            )

        # Format table name
        if schema:
            formatted_table = (
                f"{self._quote_identifier(schema)}.{self._quote_identifier(table_name)}"
            )
        else:
            formatted_table = self._quote_identifier(table_name)

        # Handle different ALTER operations
        if "ADD COLUMN" in sql_upper:
            column_name = self._extract_column_name_from_add(sql)
            if column_name:
                drop_sql = f"ALTER TABLE {formatted_table} DROP COLUMN {self._quote_identifier(column_name)};"
                return UndoStatement(
                    sql=drop_sql,
                    original_statement=sql,
                    operation_type="ALTER",
                )
            else:
                return UndoStatement(
                    sql="-- WARNING: Could not extract column name from ADD COLUMN statement",
                    original_statement=sql,
                    operation_type="ALTER",
                    warning="Could not extract column name",
                    requires_manual_review=True,
                )
        elif "DROP COLUMN" in sql_upper:
            return UndoStatement(
                sql="-- WARNING: Cannot reverse DROP COLUMN without original column definition",
                original_statement=sql,
                operation_type="ALTER",
                warning="DROP COLUMN cannot be reversed without original column definition",
                requires_manual_review=True,
            )
        elif (
            "ADD CONSTRAINT" in sql_upper
            or "ADD PRIMARY KEY" in sql_upper
            or "ADD FOREIGN KEY" in sql_upper
        ):
            constraint_name = self._extract_constraint_name_from_add(sql)
            if constraint_name:
                if "PRIMARY KEY" in sql_upper:
                    drop_sql = f"ALTER TABLE {formatted_table} DROP PRIMARY KEY;"
                elif "FOREIGN KEY" in sql_upper:
                    drop_sql = f"ALTER TABLE {formatted_table} DROP FOREIGN KEY {self._quote_identifier(constraint_name)};"
                else:
                    drop_sql = f"ALTER TABLE {formatted_table} DROP CONSTRAINT {self._quote_identifier(constraint_name)};"
                return UndoStatement(
                    sql=drop_sql,
                    original_statement=sql,
                    operation_type="ALTER",
                )
            else:
                return UndoStatement(
                    sql="-- WARNING: Could not extract constraint name from ADD CONSTRAINT statement",
                    original_statement=sql,
                    operation_type="ALTER",
                    warning="Could not extract constraint name",
                    requires_manual_review=True,
                )
        elif (
            "DROP CONSTRAINT" in sql_upper
            or "DROP PRIMARY KEY" in sql_upper
            or "DROP FOREIGN KEY" in sql_upper
        ):
            return UndoStatement(
                sql="-- WARNING: Cannot reverse DROP CONSTRAINT without original constraint definition",
                original_statement=sql,
                operation_type="ALTER",
                warning="DROP CONSTRAINT cannot be reversed without original constraint definition",
                requires_manual_review=True,
            )
        elif "MODIFY COLUMN" in sql_upper or "ALTER COLUMN" in sql_upper:
            return UndoStatement(
                sql="-- WARNING: Cannot reverse MODIFY/ALTER COLUMN without original column definition",
                original_statement=sql,
                operation_type="ALTER",
                warning="MODIFY/ALTER COLUMN cannot be reversed without original column definition",
                requires_manual_review=True,
            )
        else:
            return UndoStatement(
                sql="-- WARNING: ALTER operation type not supported for reversal",
                original_statement=sql,
                operation_type="ALTER",
                warning="This ALTER operation type cannot be automatically reversed",
                requires_manual_review=True,
            )

    def _reverse_alter(self, sql: str, analysis: Dict[str, Any]) -> Optional[UndoStatement]:
        """Reverse an ALTER statement.

        Args:
            sql: ALTER statement
            analysis: Statement analysis result

        Returns:
            UndoStatement with reverse ALTER statement
        """
        sql_upper = sql.strip().upper()

        # Extract table name
        objects = analysis.get("objects", [])
        if not objects:
            return UndoStatement(
                sql="-- WARNING: Could not extract table from ALTER statement",
                original_statement=sql,
                operation_type="ALTER",
                warning="Could not parse ALTER statement",
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

        # Handle different ALTER operations
        if "ADD COLUMN" in sql_upper:
            # ALTER TABLE ... ADD COLUMN col -> ALTER TABLE ... DROP COLUMN col
            column_name = self._extract_column_name_from_add(sql)
            if column_name:
                drop_sql = f"ALTER TABLE {formatted_table} DROP COLUMN {self._quote_identifier(column_name)};"
                return UndoStatement(
                    sql=drop_sql,
                    original_statement=sql,
                    operation_type="ALTER",
                )
            else:
                return UndoStatement(
                    sql="-- WARNING: Could not extract column name from ADD COLUMN statement",
                    original_statement=sql,
                    operation_type="ALTER",
                    warning="Could not extract column name",
                    requires_manual_review=True,
                )
        elif "DROP COLUMN" in sql_upper:
            # ALTER TABLE ... DROP COLUMN col -> Cannot reverse without original definition
            return UndoStatement(
                sql="-- WARNING: Cannot reverse DROP COLUMN without original column definition",
                original_statement=sql,
                operation_type="ALTER",
                warning="DROP COLUMN cannot be reversed without original column definition",
                requires_manual_review=True,
            )
        elif (
            "ADD CONSTRAINT" in sql_upper
            or "ADD PRIMARY KEY" in sql_upper
            or "ADD FOREIGN KEY" in sql_upper
        ):
            # ALTER TABLE ... ADD CONSTRAINT -> ALTER TABLE ... DROP CONSTRAINT
            constraint_name = self._extract_constraint_name_from_add(sql)
            if constraint_name:
                if "PRIMARY KEY" in sql_upper:
                    drop_sql = f"ALTER TABLE {formatted_table} DROP PRIMARY KEY;"
                elif "FOREIGN KEY" in sql_upper:
                    drop_sql = f"ALTER TABLE {formatted_table} DROP FOREIGN KEY {self._quote_identifier(constraint_name)};"
                else:
                    drop_sql = f"ALTER TABLE {formatted_table} DROP CONSTRAINT {self._quote_identifier(constraint_name)};"
                return UndoStatement(
                    sql=drop_sql,
                    original_statement=sql,
                    operation_type="ALTER",
                )
            else:
                return UndoStatement(
                    sql="-- WARNING: Could not extract constraint name from ADD CONSTRAINT statement",
                    original_statement=sql,
                    operation_type="ALTER",
                    warning="Could not extract constraint name",
                    requires_manual_review=True,
                )
        elif (
            "DROP CONSTRAINT" in sql_upper
            or "DROP PRIMARY KEY" in sql_upper
            or "DROP FOREIGN KEY" in sql_upper
        ):
            # ALTER TABLE ... DROP CONSTRAINT -> Cannot reverse without original definition
            return UndoStatement(
                sql="-- WARNING: Cannot reverse DROP CONSTRAINT without original constraint definition",
                original_statement=sql,
                operation_type="ALTER",
                warning="DROP CONSTRAINT cannot be reversed without original constraint definition",
                requires_manual_review=True,
            )
        elif "MODIFY COLUMN" in sql_upper or "ALTER COLUMN" in sql_upper:
            # ALTER TABLE ... MODIFY/ALTER COLUMN -> Cannot reverse without original definition
            return UndoStatement(
                sql="-- WARNING: Cannot reverse MODIFY/ALTER COLUMN without original column definition",
                original_statement=sql,
                operation_type="ALTER",
                warning="MODIFY/ALTER COLUMN cannot be reversed without original column definition",
                requires_manual_review=True,
            )
        else:
            # Other ALTER operations
            return UndoStatement(
                sql="-- WARNING: ALTER operation type not supported for reversal",
                original_statement=sql,
                operation_type="ALTER",
                warning="This ALTER operation type cannot be automatically reversed",
                requires_manual_review=True,
            )

    def _reverse_drop_from_parsed(self, stmt: Any) -> Optional[UndoStatement]:
        """Reverse a DROP statement from parsed SqlStatement.

        Args:
            stmt: SqlStatement object with DROP statement

        Returns:
            UndoStatement with warning (DROP cannot be reversed)
        """
        return UndoStatement(
            sql="-- WARNING: Cannot reverse DROP statement without original object definition",
            original_statement=stmt.sql_text,
            operation_type="DROP",
            warning="DROP statements cannot be reversed without original object definition",
            requires_manual_review=True,
        )

    def _reverse_drop(self, sql: str, analysis: Dict[str, Any]) -> Optional[UndoStatement]:
        """Reverse a DROP statement.

        Args:
            sql: DROP statement
            analysis: Statement analysis result

        Returns:
            UndoStatement with warning (DROP cannot be reversed)
        """
        return UndoStatement(
            sql="-- WARNING: Cannot reverse DROP statement without original object definition",
            original_statement=sql,
            operation_type="DROP",
            warning="DROP statements cannot be reversed without original object definition",
            requires_manual_review=True,
        )

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
                # branch (line below — getattr-based) can assign None without
                # a narrowing-vs-prior-branch incompatibility under mypy 2.x.
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

    def _reverse_comment_from_parsed(self, stmt: Any) -> Optional[UndoStatement]:
        """Reverse a COMMENT statement from parsed SqlStatement.

        Args:
            stmt: SqlStatement object with COMMENT statement

        Returns:
            UndoStatement with COMMENT ... IS NULL to remove comment
        """
        sql = stmt.sql_text

        # Get object from affected_objects or objects
        if stmt.affected_objects:
            obj = stmt.affected_objects[0]
        elif stmt.objects:
            obj = stmt.objects[0]
        else:
            return self._reverse_comment(sql)  # Fallback to regex parsing

        obj_type = obj.object_type.value.upper()
        obj_name = obj.name
        schema = obj.schema

        # Format object name
        if schema:
            formatted_name = f"{self._quote_identifier(schema)}.{self._quote_identifier(obj_name)}"
        else:
            formatted_name = self._quote_identifier(obj_name)

        # Remove comment by setting to NULL
        reverse_sql = f"COMMENT ON {obj_type} {formatted_name} IS NULL;"
        return UndoStatement(
            sql=reverse_sql,
            original_statement=sql,
            operation_type="COMMENT",
        )

    def _reverse_comment(self, sql: str) -> Optional[UndoStatement]:
        """Reverse a COMMENT statement.

        Args:
            sql: COMMENT statement

        Returns:
            UndoStatement with COMMENT ... IS NULL to remove comment
        """
        # Extract object type and name from COMMENT ON
        # Pattern: COMMENT ON TABLE/COLUMN schema.object IS 'text'
        match = re.search(
            r"COMMENT\s+ON\s+(\w+)\s+(?:(\w+)\.)?(\w+)(?:\s+IS\s+.*)?",
            sql,
            re.IGNORECASE,
        )
        if match:
            obj_type = match.group(1).upper()
            schema = match.group(2)
            obj_name = match.group(3)

            # Format object name
            if schema:
                formatted_name = (
                    f"{self._quote_identifier(schema)}.{self._quote_identifier(obj_name)}"
                )
            else:
                formatted_name = self._quote_identifier(obj_name)

            # Remove comment by setting to NULL
            reverse_sql = f"COMMENT ON {obj_type} {formatted_name} IS NULL;"
            return UndoStatement(
                sql=reverse_sql,
                original_statement=sql,
                operation_type="COMMENT",
            )
        else:
            return UndoStatement(
                sql="-- WARNING: Could not parse COMMENT statement",
                original_statement=sql,
                operation_type="COMMENT",
                warning="Could not parse COMMENT statement",
                requires_manual_review=True,
            )
