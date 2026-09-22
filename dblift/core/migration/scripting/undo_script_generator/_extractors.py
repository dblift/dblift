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

from dblift.core.migration.scripting.undo_script_generator._helpers import (
    resolve_sqlglot_read_dialect,
)
from dblift.core.migration.sql.sql_analyzer import _IDENTIFIER, _QUALIFIED_NAME
from dblift.core.sql_model.dialect import quote_identifier
from dblift.core.sql_model.index import Index
from dblift.db.provider_registry import ProviderRegistry

# Reused rather than redefined: _IDENTIFIER/_QUALIFIED_NAME are the same
# bracket/double-quote/backtick/bare token the rest of the undo generator's
# regex-fallback analysis (sql_analyzer.py) already uses to recognize an
# object reference of one or more dot-separated parts. A second, independent
# copy of this is how an identifier-parsing fix lands in one and not the
# other.


def _strip_identifier_quotes(token: str) -> str:
    """Remove one layer of bracket/quote delimiters matched by ``_IDENTIFIER``.

    The three delimiter styles here (``[]``, ``""``, `` `` ``) are
    ``_IDENTIFIER``'s own alternatives, hardcoded rather than derived from
    it: a quoting style added there would need a matching branch added here.
    """
    if len(token) >= 2 and token[0] == "[" and token[-1] == "]":
        return token[1:-1]
    if len(token) >= 2 and token[0] == token[-1] and token[0] in ('"', "`"):
        return token[1:-1]
    return token


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

    def _generate_drop_statement(
        self,
        obj_type: str,
        obj_name: str,
        schema: Optional[str],
        create_sql: Optional[str] = None,
    ) -> Optional[str]:
        """Generate DROP statement for an object.

        Args:
            obj_type: Object type (TABLE, INDEX, VIEW, etc.)
            obj_name: Object name
            schema: Optional schema name
            create_sql: The original CREATE statement, used for INDEX to find
                the table it was created on (an index isn't schema-qualified
                the way a table is, so some dialects require naming the table
                instead: e.g. SQL Server's ``DROP INDEX name ON table``)

        Returns:
            DROP statement SQL, or ``None`` when an INDEX drop needs the
            table (SQL Server, MySQL) and it could not be found in
            *create_sql* — emitting a schema-qualified guess would be
            invalid there, so the caller must ask for manual review instead.
        """
        if obj_type == "INDEX":
            quirks = ProviderRegistry.get_quirks(self.dialect)
            table_ref = self._extract_table_ref_from_create_index(create_sql or "")
            table_schema, table_name = table_ref if table_ref else (None, None)
            if table_name or not quirks.index_drop_includes_table:
                index = Index(
                    name=obj_name,
                    table_name=table_name or "",
                    columns=[],
                    schema=schema,
                    table_schema=table_schema,
                    dialect=self.dialect,
                )
                return f"{index.drop_statement};"
            return None

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

    def _extract_table_ref_from_create_index(self, sql: str) -> Optional[Tuple[Optional[str], str]]:
        """Extract the ``(schema, table)`` an index is created ON.

        Covers the plain form (``CREATE INDEX idx ON table(col)``, any
        dialect's quoting), PostgreSQL/SQLite's ``IF NOT EXISTS``, and SQL
        Server's ``UNIQUE``/``CLUSTERED``/``NONCLUSTERED``/``PRIMARY XML``
        modifiers plus its own bracket-quoted ``ON`` target -- which SQL
        Server allows as ``database.schema.table``, not just
        ``schema.table``. The whole dot-separated reference is captured as
        one chunk and split in Python, keeping only its last two parts (the
        database part, where a dialect even allows one, is never a valid
        DROP INDEX qualifier); a regex that instead captures "one optional
        leading part, then the rest" stops after that one part, silently
        mistaking the schema for the table on a three-part reference. ``ON``
        may be on its own line -- ``\\s+`` already spans newlines. ``CREATE
        FULLTEXT INDEX`` has no index name of its own, so ``ON`` follows
        ``INDEX`` directly; matched separately.

        Args:
            sql: CREATE INDEX statement

        Returns:
            ``(schema, table)`` -- schema is ``None`` when the ``ON`` target
            named none -- or ``None`` if no ``ON`` target was found, or the
            match looks truncated by an escaped delimiter it doesn't
            understand (see the doubled-delimiter note below).
        """
        patterns = [
            # CREATE FULLTEXT INDEX ON table(...) -- no user-supplied index name.
            r"CREATE\s+FULLTEXT\s+INDEX\s+ON\s+(" + _QUALIFIED_NAME + r")",
            # CREATE [UNIQUE] [CLUSTERED|NONCLUSTERED] [PRIMARY] [XML|BITMAP|SPATIAL|COLUMNSTORE]
            # INDEX [IF NOT EXISTS] index_name ON database.schema.table (or any shorter form)
            r"CREATE\s+(?:UNIQUE\s+)?(?:CLUSTERED\s+|NONCLUSTERED\s+)?"
            r"(?:PRIMARY\s+)?(?:XML\s+|BITMAP\s+|SPATIAL\s+|COLUMNSTORE\s+)?"
            r"INDEX\s+(?:IF\s+NOT\s+EXISTS\s+)?"
            + _IDENTIFIER
            + r"\s+ON\s+("
            + _QUALIFIED_NAME
            + r")",
        ]

        # T-SQL/ANSI escape a delimiter inside a quoted identifier by
        # doubling it (``[foo]]bar]`` is the single identifier ``foo]bar``;
        # ``"foo""bar"`` is ``foo"bar``). _QUALIFIED_NAME doesn't understand
        # that doubling, so it stops at the first occurrence and matches
        # only ``[foo]``/``"foo"``, leaving the rest of the real identifier
        # sitting right after the match. That leftover character is exactly
        # the same delimiter the match just closed with, which is not
        # otherwise a valid way for a CREATE INDEX statement to continue
        # (real SQL follows the ON target with whitespace or ``(``) -- so
        # seeing it here means the captured name is probably truncated:
        # refuse rather than trust a table name that might be wrong.
        # Same three delimiter styles as _IDENTIFIER and _strip_identifier_quotes.
        _CLOSING = {"[": "]", '"': '"', "`": "`"}

        for pattern in patterns:
            match = re.search(pattern, sql, re.IGNORECASE)
            if match:
                raw_parts = re.findall(_IDENTIFIER, match.group(1))
                if not raw_parts:
                    return None
                closing = _CLOSING.get(raw_parts[-1][:1])
                if closing and sql[match.end() : match.end() + 1] == closing:
                    return None
                parts = [_strip_identifier_quotes(p) for p in raw_parts]
                table = parts[-1]
                schema = parts[-2] if len(parts) >= 2 else None
                return schema, table

        return None

    def _extract_table_name_from_create_index(self, sql: str) -> Optional[str]:
        """Extract just the table name from a CREATE INDEX statement.

        Args:
            sql: CREATE INDEX statement

        Returns:
            Table name or None
        """
        table_ref = self._extract_table_ref_from_create_index(sql)
        return table_ref[1] if table_ref else None

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
