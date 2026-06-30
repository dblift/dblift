"""Undo Script Generator Extractors Mixin.

Contains all _extract_* helper methods and utility methods used by
the UndoScriptGenerator to parse SQL statements and generate undo logic.

Also exports ``UndoStatementEmitter`` — a focused, instantiable class (SRP-05)
that wraps the extraction helpers for standalone use without requiring
the full UndoScriptGenerator.
"""

import re
from typing import Any, Optional, Tuple

from sqlglot import exp, parse_one

from core.migration.scripting.undo_script_generator._helpers import (
    resolve_sqlglot_read_dialect,
)
from core.sql_model.dialect import quote_identifier
from db.provider_registry import ProviderRegistry


class _UndoExtractorsMixin:
    """Mixin providing all extraction, utility, and helper methods for undo generation."""

    dialect: str
    logger: Any

    def _extract_create_object(self, sql: str) -> Optional[Tuple[str, str, Optional[str]]]:
        """Extract object type, name, and schema from CREATE statement.

        Args:
            sql: CREATE statement

        Returns:
            Tuple of (object_type, object_name, schema) or None
        """
        sql_upper = sql.strip().upper()

        # Pattern for CREATE [object_type] [schema.]object_name
        patterns = [
            (r"CREATE\s+TABLE\s+(?:(\w+)\.)?(\w+)", "TABLE"),
            (r"CREATE\s+(?:UNIQUE\s+)?INDEX\s+(\w+)\s+ON\s+(?:(\w+)\.)?(\w+)", "INDEX"),
            (r"CREATE\s+(?:OR\s+REPLACE\s+)?VIEW\s+(?:(\w+)\.)?(\w+)", "VIEW"),
            (r"CREATE\s+SEQUENCE\s+(?:(\w+)\.)?(\w+)", "SEQUENCE"),
            (r"CREATE\s+TRIGGER\s+(?:(\w+)\.)?(\w+)", "TRIGGER"),
            (
                r"CREATE\s+(?:OR\s+REPLACE\s+)?(?:PROCEDURE|FUNCTION)\s+(?:(\w+)\.)?(\w+)",
                "PROCEDURE",
            ),
        ]

        for pattern, obj_type in patterns:
            match = re.search(pattern, sql_upper, re.IGNORECASE)
            if match:
                if obj_type == "INDEX":
                    # Index pattern: index_name, schema, table_name
                    index_name = match.group(1)
                    schema = (
                        match.group(2)
                        if match.lastindex is not None and match.lastindex >= 2
                        else None
                    )
                    return (obj_type, index_name, schema)
                else:
                    # Other patterns: schema, object_name
                    schema = (
                        match.group(1)
                        if match.lastindex is not None and match.lastindex >= 1 and match.group(1)
                        else None
                    )
                    obj_name = (
                        match.group(2)
                        if match.lastindex is not None and match.lastindex >= 2
                        else match.group(1)
                    )
                    return (obj_type, obj_name, schema)

        return None

    def _extract_column_name_from_add(self, sql: str) -> Optional[str]:
        """Extract column name from ALTER TABLE ... ADD COLUMN statement.

        Args:
            sql: ALTER TABLE statement with ADD COLUMN

        Returns:
            Column name or None
        """
        # Pattern: ADD COLUMN column_name or ADD column_name
        patterns = [
            r"ADD\s+COLUMN\s+(\w+)",
            r"ADD\s+(\w+)\s+",  # For dialects that don't use COLUMN keyword
        ]

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_constraint_name_from_add(self, sql: str) -> Optional[str]:
        """Extract constraint name from ALTER TABLE ... ADD CONSTRAINT statement.

        Args:
            sql: ALTER TABLE statement with ADD CONSTRAINT

        Returns:
            Constraint name or None
        """
        # Pattern: ADD CONSTRAINT constraint_name or ADD PRIMARY KEY or ADD FOREIGN KEY constraint_name
        patterns = [
            r"ADD\s+CONSTRAINT\s+(\w+)",
            r"ADD\s+FOREIGN\s+KEY\s+(\w+)",
        ]

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(1)

        return None

    def _extract_insert_where_clause_from_ast(
        self, ast: exp.Insert, table_name: str
    ) -> Optional[str]:
        """Extract WHERE clause from INSERT AST for DELETE reversal using sqlglot.

        This tries to create a WHERE clause that matches the inserted rows.
        For best results, we need a primary key or unique constraint to identify rows.

        Args:
            ast: sqlglot Insert AST
            table_name: Table name

        Returns:
            WHERE clause string or None if cannot be determined
        """
        if not isinstance(ast, exp.Insert):
            return None

        # Get the VALUES expression
        if not hasattr(ast, "expression") or not ast.expression:
            return None

        # Handle INSERT ... VALUES (...)
        if isinstance(ast.expression, exp.Values):
            # Get column names if specified
            columns = []
            if ast.this and isinstance(ast.this, exp.Schema):
                # INSERT INTO table (col1, col2) VALUES (...)
                # Columns are in ast.this.expressions as Identifiers
                if hasattr(ast.this, "expressions") and ast.this.expressions:
                    columns = [
                        col.this if hasattr(col, "this") else str(col)
                        for col in ast.this.expressions
                        if hasattr(col, "this") or hasattr(col, "name")
                    ]

            # Get first row of values
            if ast.expression.expressions:
                first_row = ast.expression.expressions[0]
                if isinstance(first_row, exp.Tuple):
                    values = [self._value_to_string(v) for v in first_row.expressions]

                    # If we have columns and values, try to create WHERE clause
                    # For now, use all columns (best effort - may not be unique)
                    if columns and values and len(columns) == len(values):
                        conditions = []
                        for col, val in zip(columns, values):
                            if val is not None:  # Skip NULL values
                                conditions.append(f"{self._quote_identifier(col)} = {val}")

                        if conditions:
                            return " AND ".join(conditions)

        # Handle INSERT ... SELECT ...
        elif isinstance(ast.expression, exp.Select):
            # Cannot reverse INSERT ... SELECT without knowing what was selected
            return None

        return None

    def _value_to_string(self, value_expr: Any) -> Optional[str]:
        """Convert sqlglot value expression to SQL string.

        Args:
            value_expr: sqlglot expression (Literal, Column, etc.)

        Returns:
            SQL string representation or None
        """
        if isinstance(value_expr, exp.Literal):
            if value_expr.is_string:
                # Escape single quotes in strings
                val = str(value_expr.this).replace("'", "''")
                return f"'{val}'"
            else:
                return str(value_expr.this)
        elif isinstance(value_expr, exp.Column):
            return str(value_expr)
        elif isinstance(value_expr, exp.Null):
            return "NULL"
        else:
            # For complex expressions, try to convert to SQL
            try:
                return str(value_expr)
            except Exception:
                # Intentional: complex expression could not be stringified; caller handles None
                return None

    def _extract_insert_where_clause(self, sql: str) -> Optional[str]:
        """Extract WHERE clause from INSERT VALUES for DELETE reversal.

        This is a best-effort approach that tries to match inserted values.

        Args:
            sql: INSERT statement

        Returns:
            WHERE clause string or None
        """
        # This is a simplified implementation
        # For production, would need more sophisticated parsing
        # Pattern: INSERT INTO table (cols) VALUES (vals)
        match = re.search(r"VALUES\s*\(([^)]+)\)", sql, re.IGNORECASE | re.DOTALL)
        if match:
            # Extract column names if provided
            cols_match = re.search(r"INSERT\s+INTO\s+\w+\s*\(([^)]+)\)", sql, re.IGNORECASE)
            if cols_match:
                # Would need to map columns to values - complex
                # For now, return None to indicate manual review needed
                return None
        return None

    def _generate_drop_statement(self, obj_type: str, obj_name: str, schema: Optional[str]) -> str:
        """Generate DROP statement for an object.

        Args:
            obj_type: Object type (TABLE, INDEX, VIEW, etc.)
            obj_name: Object name
            schema: Optional schema name

        Returns:
            DROP statement SQL
        """
        # Format object name
        if schema:
            formatted_name = f"{self._quote_identifier(schema)}.{self._quote_identifier(obj_name)}"
        else:
            formatted_name = self._quote_identifier(obj_name)

        # Generate IF EXISTS clause based on dialect
        _quirks = ProviderRegistry.get_quirks(self.dialect)
        if_exists = "IF EXISTS" if _quirks.drop_supports_if_exists else ""

        # Generate CASCADE for tables (to handle dependencies)
        cascade = " CASCADE" if obj_type == "TABLE" and _quirks.drop_table_default_cascade else ""

        return f"DROP {obj_type} {if_exists} {formatted_name}{cascade};".replace("  ", " ").strip()

    def _quote_identifier(self, identifier: str) -> str:
        """Quote identifier based on dialect.

        Delegates to quote_identifier (story 21-14 dispatch).

        Args:
            identifier: Identifier to quote

        Returns:
            Quoted identifier
        """
        return quote_identifier(self.dialect, identifier)

    def _extract_version_from_filename(self, filename: str) -> Optional[str]:
        """Extract version from migration filename, preserving original format (underscores/dots).

        Args:
            filename: Migration filename (e.g., V1_0_1__description.sql)

        Returns:
            Version string in original format (e.g., "1_0_1") or None
        """
        # Pattern: V{version}__{description}.sql
        # Handle both dots and underscores in version
        match = re.match(
            r"^V([A-Za-z0-9]+(?:(?:\.|_)[A-Za-z0-9]+)*)__(.+)\.sql$",
            filename,
            re.IGNORECASE,
        )
        if match:
            return match.group(1)  # Return version in original format
        return None

    def _extract_table_name_from_drop(self, sql: str) -> Optional[str]:
        """Extract table name from DROP TABLE statement.

        Args:
            sql: DROP TABLE statement

        Returns:
            Table name or None
        """
        # Pattern: DROP TABLE [IF EXISTS] ["schema"]."table_name" or [schema.]table_name
        # Handle quoted identifiers
        patterns = [
            r'DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:"([^"]+)"\.)?"([^"]+)"',  # Quoted identifiers
            r"DROP\s+TABLE\s+(?:IF\s+EXISTS\s+)?(?:(\w+)\.)?(\w+)",  # Unquoted identifiers
        ]

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(2)  # Return table name (group 2)
        return None

    def _extract_table_name_from_comment(self, sql: str) -> Optional[str]:
        """Extract table name from COMMENT ON TABLE statement.

        Args:
            sql: COMMENT ON TABLE statement

        Returns:
            Table name or None
        """
        # Pattern: COMMENT ON TABLE ["schema"]."table_name" or [schema.]table_name
        # Handle quoted identifiers
        patterns = [
            r'COMMENT\s+ON\s+TABLE\s+(?:"([^"]+)"\.)?"([^"]+)"',  # Quoted identifiers
            r"COMMENT\s+ON\s+TABLE\s+(?:(\w+)\.)?(\w+)",  # Unquoted identifiers
        ]

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(2)  # Return table name (group 2)
        return None

    def _extract_table_name_from_insert(self, sql: str) -> Optional[str]:
        """Extract table name from INSERT statement using sqlglot.

        Args:
            sql: INSERT statement

        Returns:
            Table name or None
        """
        try:
            sqlglot_dialect = resolve_sqlglot_read_dialect(self.dialect)
            ast = parse_one(sql, read=sqlglot_dialect)

            if isinstance(ast, exp.Insert):
                table_expr = ast.this
                if isinstance(table_expr, exp.Schema):
                    return table_expr.this.name if table_expr.this else None
                elif isinstance(table_expr, exp.Table):
                    name = table_expr.name
                    return str(name) if name is not None else None
        except Exception:
            # Intentional: sqlglot parse failed; regex fallback follows immediately below
            pass

        # Regex fallback
        patterns = [
            r'INSERT\s+INTO\s+(?:"([^"]+)"\.)?"([^"]+)"',  # Quoted identifiers
            r"INSERT\s+INTO\s+(?:(\w+)\.)?(\w+)",  # Unquoted identifiers
        ]

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(2)  # Return table name (group 2)
        return None

    def _extract_table_name_from_delete(self, sql: str) -> Optional[str]:
        """Extract table name from DELETE FROM statement.

        Args:
            sql: DELETE FROM statement

        Returns:
            Table name or None
        """
        # Pattern: DELETE FROM ["schema"]."table_name" or DELETE FROM [schema.]table_name
        patterns = [
            r'DELETE\s+FROM\s+(?:"([^"]+)"\.)?"([^"]+)"',  # Quoted identifiers
            r"DELETE\s+FROM\s+(?:(\w+)\.)?(\w+)",  # Unquoted identifiers
        ]

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                return match.group(2)  # Return table name (group 2)
        return None

    def _extract_table_name_from_create_index(self, sql: str) -> Optional[str]:
        """Extract table name from CREATE INDEX statement.

        Args:
            sql: CREATE INDEX statement (e.g., CREATE INDEX idx_name ON table_name(column))

        Returns:
            Table name or None
        """
        # Pattern: CREATE INDEX [IF NOT EXISTS] "index_name" ON ["schema"]."table_name"(...)
        # Handle quoted and unquoted identifiers
        patterns = [
            r'CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:[^"\s]+|"[^"]+")\s+ON\s+(?:"([^"]+)"\.)?"([^"]+)"',  # Quoted with ON
            r"CREATE\s+INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?(?:\w+\.)?(\w+)\s+ON\s+(?:(\w+)\.)?(\w+)",  # Unquoted with ON
        ]

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                # Return table name (last group)
                return match.group(match.lastindex) if match.lastindex else None

        return None

    def _extract_table_name_from_index(self, sql: str) -> Optional[str]:
        """Extract table name from DROP INDEX statement.

        Args:
            sql: DROP INDEX statement (e.g., DROP INDEX IF EXISTS "idx_name" ON "table_name")

        Returns:
            Table name or None
        """
        # Pattern 1: DROP INDEX [IF EXISTS] "index_name" ON ["schema"]."table_name"
        # Pattern 2: DROP INDEX [IF EXISTS] index_name ON schema.table_name
        patterns = [
            r'DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?(?:[^"\s]+|"[^"]+")\s+ON\s+(?:"([^"]+)"\.)?"([^"]+)"',  # Quoted with ON
            r"DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?(?:\w+\.)?(\w+)\s+ON\s+(?:(\w+)\.)?(\w+)",  # Unquoted with ON
        ]

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                # Return table name (last group)
                return match.group(match.lastindex) if match.lastindex else None

        # If no ON clause, try to extract from index name pattern
        # Some databases use index_name format like "idx_table_name" or "table_name_idx"
        # This is a fallback - we can't reliably determine table from index name alone
        # But we can try common patterns
        index_match = re.search(
            r'DROP\s+INDEX\s+(?:IF\s+EXISTS\s+)?(?:"([^"]+)"|(\w+))',
            sql,
            re.IGNORECASE,
        )
        if index_match:
            index_name = index_match.group(1) or index_match.group(2)
            if index_name:
                # Try to extract table name from common index naming patterns
                # Pattern: idx_table_name, table_name_idx, idx_table_name_column
                # Remove quotes if present
                index_name = index_name.strip('"')

                # Try idx_* pattern
                if index_name.lower().startswith("idx_"):
                    # Could be idx_table_name or idx_table_name_column
                    parts = index_name[4:].split("_")
                    if len(parts) >= 1:
                        # Return first part as potential table name
                        # This is a heuristic and may not always be correct
                        return parts[0]

                # Try *_idx pattern
                if index_name.lower().endswith("_idx"):
                    parts = index_name[:-4].split("_")
                    if len(parts) >= 1:
                        return parts[0]

        return None


class UndoStatementEmitter(_UndoExtractorsMixin):
    """Focused class for generating individual DDL reversal helpers (SRP-05).

    Provides dialect-aware SQL extraction utilities and DROP statement generation
    as a standalone object, without requiring the full UndoScriptGenerator
    orchestration machinery.

    UndoScriptGenerator continues to inherit from _UndoExtractorsMixin directly;
    this class exists for external callers that only need the emitter helpers.

    Example::

        emitter = UndoStatementEmitter(dialect="postgresql")
        drop = emitter._generate_drop_statement("TABLE", "users", "public")
        # → 'DROP TABLE IF EXISTS "public"."users" CASCADE;'
    """

    def __init__(
        self,
        dialect: str = "",
        logger: Any = None,
    ) -> None:
        """Initialize the emitter.

        Args:
            dialect: SQL dialect identifier (e.g. ``"postgresql"``,
                ``"oracle"``, ``"mysql"``, ``"sqlserver"``). Defaults
                to ``""`` so the framework never assumes a dialect when
                callers haven't supplied one.
            logger: Optional logger (unused by extraction helpers, kept for API symmetry).
        """
        self.dialect = dialect
        self.logger = logger
