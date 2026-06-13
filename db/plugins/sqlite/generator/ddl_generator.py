"""
SQLite-specific SQL generation implementation.

This module provides SQLite-specific SQL generation logic, inheriting
common functionality from BaseSqlGenerator and overriding methods that
require SQLite-specific handling.

SQLite has limited DDL capabilities compared to other databases:
- No stored procedures or functions (user-defined functions are in app code)
- No schemas (database file IS the schema)
- Limited ALTER TABLE (ADD COLUMN and RENAME only)
- No materialized views
- No sequences (uses AUTOINCREMENT instead)
"""

import re
from typing import TYPE_CHECKING, List, Optional

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.basic_table_ddl_generator import _build_fk_body_sql
from core.sql_model.base import (
    SqlObject,
    SqlObjectType,
    get_constraint_type_name,
    get_object_type_name,
)

if TYPE_CHECKING:
    from core.sql_model.base import SqlColumn, SqlConstraint
    from core.sql_model.index import Index
    from core.sql_model.table import Table
    from core.sql_model.trigger import Trigger
    from core.sql_model.view import View


class SQLiteSqlGenerator(BaseSqlGenerator):
    """
    SQLite-specific SQL generation implementation.

    This class provides SQLite-specific SQL generation logic while
    inheriting common functionality from BaseSqlGenerator.
    """

    def _requires_dialect_specific_wrapping(self, obj: SqlObject, dialect: str) -> bool:
        """
        Check if object needs SQLite-specific wrapping.

        SQLite doesn't require special wrapping for most objects.

        Args:
            obj: SQL Model object
            dialect: SQL dialect

        Returns:
            True if object needs special wrapping (always False for SQLite)
        """
        return False

    def _wrap_dialect_specific_block(self, sql: str, dialect: str) -> str:
        """
        Wrap SQL block with SQLite-specific directives (none needed).

        Args:
            sql: SQL statement
            dialect: SQL dialect

        Returns:
            SQL unchanged
        """
        return sql

    def _should_skip_formatting(self, obj: SqlObject, sql: str) -> bool:
        """
        Check if we should skip formatting for SQLite objects.

        SQLite trigger definitions should be preserved.

        Args:
            obj: SQL Model object
            sql: SQL statement

        Returns:
            True if formatting should be skipped
        """
        if not sql:
            return False

        # Preserve trigger definitions (they have BEGIN/END blocks)
        if obj.object_type == SqlObjectType.TRIGGER:
            return True

        return False

    def _format_statements(self, statements: List[str], dialect: str) -> str:
        """
        Format statements for SQLite.

        Args:
            statements: List of SQL statements
            dialect: SQL dialect (should be "sqlite")

        Returns:
            Formatted SQL string
        """
        statements = [stmt for stmt in statements if stmt and stmt.strip()]
        if not statements:
            return ""
        return "\n\n".join(statements)

    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """
        Generate a DROP statement for an object (SQLite-specific).

        Note: SQLite doesn't support schemas, so schema prefix is ignored.

        Args:
            obj: SQL Model object to drop
            dialect: SQL dialect (should be "sqlite")

        Returns:
            DROP statement SQL string
        """
        obj_name = obj.format_identifier(obj.name)

        # Handle different object types
        obj_type = get_object_type_name(obj)

        if obj_type == "VIEW":
            return f"DROP VIEW IF EXISTS {obj_name}"

        elif obj_type in ("TABLE", "VIRTUAL_TABLE"):
            return f"DROP TABLE IF EXISTS {obj_name}"

        elif obj_type == "INDEX":
            return f"DROP INDEX IF EXISTS {obj_name}"

        elif obj_type == "TRIGGER":
            return f"DROP TRIGGER IF EXISTS {obj_name}"

        # Default fallback
        return f"DROP {obj_type} IF EXISTS {obj_name}"

    def _get_create_dispatch(self) -> dict[type, str]:
        """Return mapping of {TypeClass: 'method_name'} for SQLite types."""
        # Import here to avoid circular imports
        from core.sql_model.index import Index
        from core.sql_model.table import Table
        from core.sql_model.trigger import Trigger
        from core.sql_model.view import View

        return {
            View: "_generate_view_create_statement",
            Index: "_generate_index_create_statement",
            Table: "_generate_table_create_statement",
            Trigger: "_generate_trigger_create_statement",
        }

    def _generate_create_fallback(self, obj: SqlObject) -> str:
        """Fallback: try to use the object's own create_statement method."""
        if hasattr(obj, "create_statement"):
            result = obj.create_statement()
            return str(result) if result is not None else ""
        return ""

    def _generate_view_create_statement(self, view: "View") -> str:
        """
        Generate a CREATE VIEW statement (SQLite-specific).

        Args:
            view: View object

        Returns:
            CREATE VIEW statement
        """
        view_name = view.format_identifier(view.name)
        temp_clause = "TEMP " if getattr(view, "is_temporary", False) else ""

        # Build the CREATE VIEW statement
        sql = f"CREATE {temp_clause}VIEW"

        # Add IF NOT EXISTS if specified
        if getattr(view, "if_not_exists", False):
            sql += " IF NOT EXISTS"

        sql += f" {view_name}"

        # Add column names if specified
        if hasattr(view, "column_names") and view.column_names:
            columns = ", ".join(view.format_identifier(col) for col in view.column_names)
            sql += f" ({columns})"

        # Add the query
        query = getattr(view, "query", None) or getattr(view, "definition", "")
        if query:
            sql += f" AS {query}"

        return sql

    def _generate_index_create_statement(self, index: "Index") -> str:
        """
        Generate a CREATE INDEX statement (SQLite-specific).

        Args:
            index: Index object

        Returns:
            CREATE INDEX statement
        """
        index_name = index.format_identifier(index.name)
        table_name = index.format_identifier(index.table_name)

        # Build the CREATE INDEX statement
        unique_clause = "UNIQUE " if getattr(index, "unique", False) else ""
        sql = f"CREATE {unique_clause}INDEX"

        # Add IF NOT EXISTS
        if getattr(index, "if_not_exists", True):
            sql += " IF NOT EXISTS"

        sql += f" {index_name} ON {table_name}"

        # Add columns
        columns = []
        for idx, col in enumerate(index.columns):
            if isinstance(col, dict):
                col_name = col.get("name", "")
                # Check if this is an expression
                is_expression = (
                    index.expression_flags[idx] if idx < len(index.expression_flags) else False
                )
                if is_expression:
                    formatted_col = col_name
                else:
                    formatted_col = index.format_identifier(col_name)
                order = col.get("order", "ASC")
                columns.append(f"{formatted_col} {order}")
            else:
                # Check if this is an expression
                is_expression = (
                    index.expression_flags[idx] if idx < len(index.expression_flags) else False
                )
                if is_expression:
                    columns.append(col)  # Don't quote expressions
                else:
                    columns.append(index.format_identifier(col))

        sql += f" ({', '.join(columns)})"

        # Add WHERE clause if present (SQLite partial index predicate).
        # B10-BUG-23: the Index model exposes the predicate as
        # ``condition`` (shared with PostgreSQL / SQL Server filtered
        # indexes). The older ``where_clause`` attribute was never set,
        # so this branch never fired and round-tripped partial indexes
        # lost their predicate.
        predicate = getattr(index, "condition", None) or getattr(index, "where_clause", None)
        if predicate:
            sql += f" WHERE {predicate}"

        return sql

    def _generate_table_create_statement(self, table: "Table") -> str:
        """
        Generate a CREATE TABLE statement (SQLite-specific).

        Args:
            table: Table object

        Returns:
            CREATE TABLE statement
        """
        if get_object_type_name(table) == "VIRTUAL_TABLE" and getattr(table, "raw_ddl", None):
            return str(table.raw_ddl).rstrip().rstrip(";")

        table_name = table.format_identifier(table.name)
        temp_clause = "TEMP " if getattr(table, "is_temporary", False) else ""

        # Build the CREATE TABLE statement
        sql = f"CREATE {temp_clause}TABLE"

        # Add IF NOT EXISTS
        if getattr(table, "if_not_exists", True):
            sql += " IF NOT EXISTS"

        sql += f" {table_name} ("

        # Add columns
        column_defs = []
        for col in table.columns:
            col_def = self._generate_column_definition(col, table)
            column_defs.append(col_def)

        # Add table-level constraints
        for constraint in table.constraints:
            constraint_def = self._generate_constraint_definition(constraint, table)
            if constraint_def:
                column_defs.append(constraint_def)

        sql += ",\n    ".join(column_defs)
        sql += ")"

        # Add WITHOUT ROWID if specified
        if getattr(table, "without_rowid", False):
            sql += " WITHOUT ROWID"

        # Add STRICT if specified (SQLite 3.37+)
        if getattr(table, "strict", False):
            sql += " STRICT"

        return sql

    def _generate_column_definition(self, column: "SqlColumn", table: "Table") -> str:
        """Generate a column definition for SQLite."""
        col_name = table.format_identifier(column.name)
        col_type = getattr(column, "data_type", "TEXT") or "TEXT"

        parts = [col_name, col_type]

        # Check if there's a composite PRIMARY KEY constraint at table level
        # If so, don't add PRIMARY KEY to individual columns
        has_composite_pk = False
        for constraint in table.constraints:
            if get_constraint_type_name(constraint) == "PRIMARY KEY":
                columns = getattr(constraint, "column_names", None) or getattr(
                    constraint, "columns", []
                )
                if len(columns) > 1:
                    has_composite_pk = True
                    break

        # Add PRIMARY KEY if this is the primary key column (but not if there's a composite PK)
        if getattr(column, "is_primary_key", False) and not has_composite_pk:
            parts.append("PRIMARY KEY")
            # Add AUTOINCREMENT if it's an INTEGER PRIMARY KEY
            if col_type.upper() == "INTEGER" and getattr(column, "auto_increment", False):
                parts.append("AUTOINCREMENT")

        # Add NOT NULL constraint (only when explicitly False; nullable=None must not
        # be treated as NOT NULL)
        if column.nullable is False:
            parts.append("NOT NULL")

        # Add GENERATED ALWAYS AS for computed columns (before DEFAULT)
        if getattr(column, "is_computed", False) and getattr(column, "computed_expression", None):
            expression = column.computed_expression
            stored = "STORED" if getattr(column, "computed_stored", False) else "VIRTUAL"
            parts.append(f"GENERATED ALWAYS AS ({expression}) {stored}")
        # Add DEFAULT value (only if not a computed column)
        elif hasattr(column, "default_value") and column.default_value is not None:
            default = column.default_value
            if isinstance(default, str):
                # Check if it's a function call (contains parentheses) or already wrapped
                if "(" in default and ")" in default:
                    # Function call - wrap in parentheses if not already wrapped
                    if not (default.strip().startswith("(") and default.strip().endswith(")")):
                        default = f"({default})"
                elif not default.startswith("(") and not (
                    default.startswith("'") or default.startswith('"')
                ):
                    # Not a quoted string and not already wrapped - might be a keyword or function
                    # Check if it looks like a function name (common SQLite functions)
                    sqlite_functions = [
                        "datetime",
                        "date",
                        "time",
                        "julianday",
                        "strftime",
                        "random",
                        "abs",
                        "changes",
                        "char",
                        "coalesce",
                        "glob",
                        "hex",
                        "ifnull",
                        "instr",
                        "last_insert_rowid",
                        "length",
                        "like",
                        "likelihood",
                        "likely",
                        "lower",
                        "ltrim",
                        "max",
                        "min",
                        "nullif",
                        "printf",
                        "quote",
                        "randomblob",
                        "replace",
                        "round",
                        "rtrim",
                        "soundex",
                        "sqlite_compileoption_get",
                        "sqlite_compileoption_used",
                        "sqlite_source_id",
                        "sqlite_version",
                        "substr",
                        "total_changes",
                        "trim",
                        "typeof",
                        "unicode",
                        "unlikely",
                        "upper",
                        "zeroblob",
                    ]
                    _sql_keyword_defaults = frozenset(
                        {
                            "CURRENT_TIMESTAMP",
                            "CURRENT_DATE",
                            "CURRENT_TIME",
                            "NULL",
                            "TRUE",
                            "FALSE",
                        }
                    )
                    if any(default.lower().startswith(f"{fn}(") for fn in sqlite_functions):
                        default = f"({default})"
                    elif default.upper() in _sql_keyword_defaults:
                        pass  # SQL keyword — emit as-is, not as a string literal
                    else:
                        # Quote as string literal
                        default = f"'{default}'"
            parts.append(f"DEFAULT {default}")

        # Add CHECK constraint
        if hasattr(column, "check_constraint") and column.check_constraint:
            parts.append(f"CHECK ({column.check_constraint})")

        # Add UNIQUE constraint
        # Check both 'is_unique' (standard) and 'unique' (for compatibility)
        is_unique = getattr(column, "is_unique", None)
        if is_unique is None:
            is_unique = getattr(column, "unique", False)
        if is_unique:
            parts.append("UNIQUE")

        return " ".join(parts)

    def _generate_constraint_definition(
        self, constraint: "SqlConstraint", table: "Table"
    ) -> Optional[str]:
        """Generate a constraint definition for SQLite."""
        from core.sql_model.base import ConstraintType

        constraint_type = constraint.constraint_type

        # Get column names - try both 'column_names' and 'columns'
        columns = getattr(constraint, "column_names", None) or getattr(constraint, "columns", [])

        if constraint_type == ConstraintType.PRIMARY_KEY:
            # Skip if already added at column level
            if len(columns) == 1:
                # Check if column already has PRIMARY KEY
                for col in table.columns:
                    if col.name == columns[0] and getattr(col, "is_primary_key", False):
                        return None

            col_str = ", ".join(table.format_identifier(c) for c in columns)
            return f"PRIMARY KEY ({col_str})"

        elif constraint_type == ConstraintType.UNIQUE:
            col_str = ", ".join(table.format_identifier(c) for c in columns)
            constraint_name = getattr(constraint, "name", None)
            if constraint_name:
                return f"CONSTRAINT {table.format_identifier(constraint_name)} UNIQUE ({col_str})"
            return f"UNIQUE ({col_str})"

        elif constraint_type == ConstraintType.FOREIGN_KEY:
            ref_table_name = getattr(constraint, "reference_table", None) or getattr(
                constraint, "referenced_table", None
            )
            if not ref_table_name:
                return ""
            ref_schema = getattr(constraint, "reference_schema", None)
            local_cols = list(columns)
            ref_cols = list(getattr(constraint, "reference_columns", None) or [])
            return _build_fk_body_sql(
                local_cols=local_cols,
                ref_cols=ref_cols,
                ref_table=ref_table_name,
                ref_schema=ref_schema,
                format_identifier=table.format_identifier,
                on_delete=getattr(constraint, "on_delete", None),
                on_update=getattr(constraint, "on_update", None),
                suppress_no_action=False,
            )

        elif constraint_type == ConstraintType.CHECK:
            check_expr = getattr(constraint, "check_expression", None) or getattr(
                constraint, "expression", None
            )
            if check_expr:
                constraint_name = getattr(constraint, "name", None)
                if constraint_name:
                    return f"CONSTRAINT {table.format_identifier(constraint_name)} CHECK ({check_expr})"
                return f"CHECK ({check_expr})"

        return None

    def _generate_trigger_create_statement(self, trigger: "Trigger") -> str:
        """
        Generate a CREATE TRIGGER statement (SQLite-specific).

        Args:
            trigger: Trigger object

        Returns:
            CREATE TRIGGER statement
        """
        definition = getattr(trigger, "definition", None)

        # If definition already contains a complete CREATE TRIGGER statement, use it as-is
        # (SQLite introspection returns the full CREATE TRIGGER SQL from sqlite_master)
        if definition and definition.strip().upper().startswith("CREATE"):
            # Just return the definition, but optionally add IF NOT EXISTS
            # Cast to str since we've verified it's a string at this point
            definition_str = str(definition)
            if (
                getattr(trigger, "if_not_exists", True)
                and "IF NOT EXISTS" not in definition_str.upper()
            ):
                # Insert IF NOT EXISTS after CREATE TRIGGER
                definition_str = re.sub(
                    r"(CREATE\s+(?:TEMP\s+)?TRIGGER)",
                    r"\1 IF NOT EXISTS",
                    definition_str,
                    flags=re.IGNORECASE,
                )
            return definition_str

        # Otherwise, build the statement from components
        trigger_name = trigger.format_identifier(trigger.name)
        table_name = trigger.format_identifier(trigger.table_name)
        temp_clause = "TEMP " if getattr(trigger, "is_temporary", False) else ""

        # Build the CREATE TRIGGER statement
        sql = f"CREATE {temp_clause}TRIGGER"

        # Add IF NOT EXISTS
        if getattr(trigger, "if_not_exists", True):
            sql += " IF NOT EXISTS"

        sql += f" {trigger_name}"

        # Add timing (BEFORE, AFTER, INSTEAD OF)
        timing = getattr(trigger, "timing", "BEFORE") or "BEFORE"
        sql += f" {timing}"

        # Add events
        events = getattr(trigger, "events", ["INSERT"]) or ["INSERT"]
        if isinstance(events, list):
            sql += f" {' OR '.join(events)}"
        else:
            sql += f" {events}"

        sql += f" ON {table_name}"

        # Add FOR EACH ROW
        if getattr(trigger, "for_each_row", True):
            sql += " FOR EACH ROW"

        # Add WHEN clause
        when_clause = getattr(trigger, "when_clause", None)
        if when_clause:
            sql += f" WHEN {when_clause}"

        # Add trigger body
        if definition:
            # Check if definition already contains BEGIN/END
            if "BEGIN" in definition.upper():
                sql += f"\n{definition}"
            else:
                sql += f"\nBEGIN\n    {definition}\nEND"

        return sql

    def generate_alter_statement(self, obj: SqlObject, dialect: Optional[str] = None) -> str:
        """
        Generate an ALTER statement for an SQL object (SQLite-specific).

        Note: SQLite has very limited ALTER TABLE support:
        - ALTER TABLE ... RENAME TO
        - ALTER TABLE ... RENAME COLUMN
        - ALTER TABLE ... ADD COLUMN

        Most other alterations require recreating the table.

        Args:
            obj: SQL Model object to generate ALTER statement for
            dialect: SQL dialect (should be "sqlite")

        Returns:
            ALTER statement SQL string (may be empty if not supported)
        """
        # SQLite has limited ALTER TABLE support
        # Most alterations require recreating the table
        return ""

    def format_identifier(self, identifier: str) -> str:
        """
        Format an identifier for SQLite.

        SQLite uses double quotes for identifier quoting.

        Args:
            identifier: Identifier to format

        Returns:
            Formatted identifier
        """
        if not identifier:
            return identifier

        # Escape double quotes by doubling them
        escaped = identifier.replace('"', '""')
        return f'"{escaped}"'
