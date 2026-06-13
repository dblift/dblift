"""
SQLite-specific schema introspection implementation.

This module provides SQLite-specific introspection logic, inheriting
common functionality from BaseIntrospector and overriding methods that
require SQLite-specific handling.

Note: SQLite is simpler than other databases - it doesn't support:
- Schemas (the database file IS the schema)
- Stored procedures
- Materialized views
- User-defined types
"""

import re
from typing import Any, Dict, List, Optional, Tuple

from core.introspection.base_introspector import BaseIntrospector
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint, SqlObjectType
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.table_options import TableOptions
from core.sql_model.trigger import Trigger
from core.sql_model.view import View

FTS5_SHADOW_SUFFIXES = (
    "_data",
    "_idx",
    "_content",
    "_docsize",
    "_config",
    "_segdir",
    "_segments",
    "_stat",
)


def _is_sqlite_virtual_table(create_sql: Optional[str]) -> bool:
    return bool(create_sql and re.match(r"^\s*CREATE\s+VIRTUAL\s+TABLE\b", create_sql, re.I))


def _is_fts5_virtual_table(create_sql: Optional[str]) -> bool:
    return bool(
        _is_sqlite_virtual_table(create_sql)
        and re.search(r"\bUSING\s+fts5\b", create_sql or "", re.I)
    )


class SQLiteIntrospector(BaseIntrospector):
    """
    SQLite-specific schema introspection implementation.

    This class provides SQLite-specific introspection logic while
    inheriting common functionality from BaseIntrospector.
    """

    def __init__(self, provider: Any, log: Any = None, use_vendor_queries: bool = True) -> None:
        """Initialize SQLite introspector."""
        super().__init__(provider, log, use_vendor_queries)

    def ensure_connection(self) -> None:
        """Ensure we have an active connection."""
        if self.connection is None:
            self.provider._ensure_connection()
            self.connection = self.provider.connection

    def get_tables(
        self, schema: str, include_views: bool = False, table_pattern: str = "%"
    ) -> List[Table]:
        """
        Get all tables in the database.

        Args:
            schema: Schema name (ignored for SQLite)

        Returns:
            List of Table objects
        """
        self.ensure_connection()

        tables: List[Table] = []

        try:
            # Query sqlite_master for tables
            query = """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'table' AND name NOT LIKE 'sqlite_%'
                ORDER BY name
            """

            results = self.provider.execute_query(query)
            rows: List[tuple[str, Optional[str]]] = []
            fts5_virtual_tables = set()
            for row in results:
                table_name = self._get_row_value(row, "name")
                create_sql = self._get_row_value(row, "sql")

                if not table_name:
                    continue

                rows.append((table_name, create_sql))
                if _is_fts5_virtual_table(create_sql):
                    fts5_virtual_tables.add(table_name)

            shadow_table_names = {
                f"{table_name}{suffix}"
                for table_name in fts5_virtual_tables
                for suffix in FTS5_SHADOW_SUFFIXES
            }

            for table_name, create_sql in rows:
                if table_name in shadow_table_names:
                    continue

                create_sql_text = create_sql or ""
                is_virtual_table = _is_sqlite_virtual_table(create_sql_text)

                # Create table object
                table = Table.from_options(
                    name=table_name,
                    schema=None,  # SQLite doesn't use schemas
                    dialect="sqlite",
                    object_type=(
                        SqlObjectType.VIRTUAL_TABLE if is_virtual_table else SqlObjectType.TABLE
                    ),
                    options=TableOptions(raw_ddl=create_sql_text if is_virtual_table else None),
                )

                # Get columns using PRAGMA (doesn't include generated columns)
                columns = self._get_table_columns(table_name)
                self._mark_autoincrement_columns(columns, create_sql_text)

                # Parse and add generated columns from CREATE TABLE SQL
                # PRAGMA table_info doesn't include generated columns, so we need to parse them
                generated_columns = self._parse_generated_columns(create_sql_text, table_name)

                # Merge generated columns into the columns list
                # Generated columns should be added in their proper position
                all_columns = self._merge_columns_with_generated(
                    columns, generated_columns, create_sql_text
                )

                table.columns = all_columns

                # Get primary key
                pk_columns = self._get_primary_key_columns(table_name)
                if pk_columns:
                    pk_constraint = SqlConstraint(
                        name=f"pk_{table_name}",
                        constraint_type=ConstraintType.PRIMARY_KEY,
                        column_names=pk_columns,
                    )
                    table.constraints.append(pk_constraint)

                # Get foreign keys
                fk_constraints = self._get_foreign_keys(table_name)
                table.constraints.extend(fk_constraints)

                # Get indexes
                self._get_table_indexes(table_name)
                # Note: Table doesn't have indexes attribute, indexes are stored separately
                # table.indexes = indexes  # Commented out - indexes are handled separately

                # Parse unique constraints from CREATE TABLE statement
                unique_constraints = self._parse_unique_constraints(create_sql_text, table_name)
                table.constraints.extend(unique_constraints)

                # Parse CHECK constraints from CREATE TABLE statement
                check_constraints = self._parse_check_constraints(create_sql_text, table_name)
                table.constraints.extend(check_constraints)

                tables.append(table)

            self.log.debug(f"Found {len(tables)} tables in SQLite database")

        except Exception as e:
            self.log.error(f"Error getting tables: {str(e)}")
            raise

        return tables

    @staticmethod
    def _unquote_keyword_default(raw: str) -> str:
        """SQLite stores keyword defaults without quotes in pragma_table_info,
        but some paths may add quotes. Strip them for known SQL keywords."""
        if raw is None:
            return raw
        stripped = raw.strip()
        # Remove surrounding single quotes if present
        if stripped.startswith("'") and stripped.endswith("'") and len(stripped) > 1:
            inner = stripped[1:-1]
            if inner.upper() in (
                "CURRENT_TIMESTAMP",
                "CURRENT_DATE",
                "CURRENT_TIME",
                "NULL",
                "TRUE",
                "FALSE",
            ):
                return inner.upper()
        return raw

    def _get_table_columns(self, table_name: str) -> List[SqlColumn]:
        """Get columns for a table using PRAGMA table_info."""
        columns: List[SqlColumn] = []

        try:
            pragma_query = f"PRAGMA table_info('{table_name}')"
            results = self.provider.execute_query(pragma_query)

            for row in results:
                col_name = self._get_row_value(row, "name")
                col_type = self._get_row_value(row, "type") or "TEXT"
                not_null = self._get_row_value(row, "notnull")
                default_value = self._get_row_value(row, "dflt_value")
                default_value = self._unquote_keyword_default(default_value)
                is_pk = self._get_row_value(row, "pk")

                column = SqlColumn(
                    name=col_name,
                    data_type=col_type.upper(),
                    is_nullable=not bool(not_null),
                    default_value=default_value,
                    is_primary_key=bool(is_pk),
                )

                # Check for AUTOINCREMENT (INTEGER PRIMARY KEY)
                if is_pk and col_type.upper() == "INTEGER":
                    column.is_identity = True
                    column.identity_generation = "ALWAYS"

                columns.append(column)

        except Exception as e:
            self.log.debug(f"Error getting columns for {table_name}: {str(e)}")

        return columns

    @staticmethod
    def _mark_autoincrement_columns(columns: List[SqlColumn], create_sql: str) -> None:
        """Mark columns that explicitly use SQLite AUTOINCREMENT."""
        if not create_sql:
            return

        for column in columns:
            col_type = getattr(column, "data_type", "") or ""
            if not getattr(column, "is_primary_key", False) or col_type.upper() != "INTEGER":
                continue
            name = re.escape(column.name)
            identifier = rf'(?:"{name}"|`{name}`|\[{name}\]|{name})'
            pattern = (
                rf"(?is)(?:^|[\s,(]){identifier}\s+INTEGER\s+PRIMARY\s+KEY\s+"
                r"AUTOINCREMENT(?:\s|,|\)|$)"
            )
            if re.search(pattern, create_sql):
                setattr(column, "auto_increment", True)

    def _get_primary_key_columns(self, table_name: str) -> List[str]:
        """Get primary key columns for a table."""
        pk_columns: List[str] = []

        try:
            pragma_query = f"PRAGMA table_info('{table_name}')"
            results = self.provider.execute_query(pragma_query)

            for row in results:
                is_pk = self._get_row_value(row, "pk")
                if is_pk:
                    col_name = self._get_row_value(row, "name")
                    pk_columns.append(col_name)

        except Exception as e:
            self.log.debug(f"Error getting primary key for {table_name}: {str(e)}")

        return pk_columns

    def _get_foreign_keys(self, table_name: str) -> List[SqlConstraint]:
        """Get foreign key constraints for a table."""
        constraints: List[SqlConstraint] = []

        try:
            pragma_query = f"PRAGMA foreign_key_list('{table_name}')"
            results = self.provider.execute_query(pragma_query)

            # Group by foreign key id
            fk_groups: Dict[int, Dict[str, Any]] = {}
            sorted_results = sorted(
                results,
                key=lambda row: (
                    self._get_row_value(row, "id") or 0,
                    self._get_row_value(row, "seq") or 0,
                ),
            )
            for row in sorted_results:
                fk_id = self._get_row_value(row, "id")
                if fk_id not in fk_groups:
                    fk_groups[fk_id] = {
                        "ref_table": self._get_row_value(row, "table"),
                        "columns": [],
                        "ref_columns": [],
                        "on_update": self._get_row_value(row, "on_update"),
                        "on_delete": self._get_row_value(row, "on_delete"),
                    }

                fk_groups[fk_id]["columns"].append(self._get_row_value(row, "from"))
                fk_groups[fk_id]["ref_columns"].append(self._get_row_value(row, "to"))

            # Create constraints
            seen_fk_keys: set[Tuple[Tuple[str, ...], str, Tuple[str, ...], Any, Any]] = set()
            for fk_id, fk_data in fk_groups.items():
                fk_key = (
                    tuple(fk_data["columns"]),
                    fk_data["ref_table"],
                    tuple(fk_data["ref_columns"]),
                    fk_data["on_update"],
                    fk_data["on_delete"],
                )
                if fk_key in seen_fk_keys:
                    continue
                seen_fk_keys.add(fk_key)

                constraint = SqlConstraint(
                    name=f"fk_{table_name}_{fk_id}",
                    constraint_type=ConstraintType.FOREIGN_KEY,
                    column_names=fk_data["columns"],
                    reference_table=fk_data["ref_table"],
                    reference_columns=fk_data["ref_columns"],
                    on_update=fk_data["on_update"],
                    on_delete=fk_data["on_delete"],
                )
                constraints.append(constraint)

        except Exception as e:
            self.log.debug(f"Error getting foreign keys for {table_name}: {str(e)}")

        return constraints

    def _get_table_indexes(self, table_name: str) -> List[Index]:
        """Get indexes for a table."""
        indexes: List[Index] = []

        try:
            # Get index list
            query = """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'index' AND tbl_name = ?
                AND name NOT LIKE 'sqlite_%'
            """
            results = self.provider.execute_query(query, [table_name])

            for row in results:
                index_name = self._get_row_value(row, "name")
                index_sql = self._get_row_value(row, "sql") or ""

                if not index_name:
                    continue

                self.log.debug(
                    f"Processing index {index_name} for table {table_name}, SQL present: {bool(index_sql)}"
                )

                # Get index columns using PRAGMA
                columns = self._get_index_columns(index_name)

                self.log.debug(
                    f"Index {index_name}: PRAGMA returned {len(columns)} columns: {columns}"
                )

                # Check if this is an expression index (PRAGMA returns -2 for expression indexes)
                # If columns is empty or contains None, parse expression from CREATE INDEX SQL
                expression = None
                expression_flags = [False] * len(columns) if columns else []

                # For expression indexes, PRAGMA index_info returns empty list or None values
                # We need to parse from CREATE INDEX SQL
                if not columns or any(c is None for c in columns):
                    # Always try to get SQL if it's missing (some SQLite versions might not return it in the initial query)
                    if not index_sql:
                        # If SQL is missing, try to get it directly
                        sql_query = """
                            SELECT sql
                            FROM sqlite_master
                            WHERE type = 'index' AND name = ? AND tbl_name = ?
                        """
                        sql_results = self.provider.execute_query(
                            sql_query, [index_name, table_name]
                        )
                        if sql_results:
                            index_sql = self._get_row_value(sql_results[0], "sql") or ""
                            if index_sql:
                                self.log.debug(
                                    f"Retrieved index SQL from sqlite_master: {index_sql[:100]}"
                                )

                    if index_sql:
                        expression = self._parse_index_expression(index_sql)
                        if expression:
                            # For expression indexes, store the expression as a column-like entry
                            columns = [expression]
                            expression_flags = [True]  # Mark as expression
                            self.log.debug(f"Parsed expression index {index_name}: {expression}")
                        else:
                            self.log.debug(
                                f"Could not parse expression from index SQL: {index_sql[:100]}"
                            )
                    else:
                        self.log.debug(
                            f"Index {index_name} has no SQL in sqlite_master (table: {table_name})"
                        )
                        # Try to find the index with the table name
                        sql_query = """
                            SELECT sql
                            FROM sqlite_master
                            WHERE type = 'index' AND name = ? AND tbl_name = ?
                        """
                        sql_results = self.provider.execute_query(
                            sql_query, [index_name, table_name]
                        )
                        if sql_results:
                            index_sql = self._get_row_value(sql_results[0], "sql") or ""
                            if index_sql:
                                expression = self._parse_index_expression(index_sql)
                                if expression:
                                    columns = [expression]
                                    expression_flags = [True]
                                    self.log.debug(
                                        f"Found index SQL with table name, parsed: {expression}"
                                    )

                # Check if unique
                is_unique = "UNIQUE" in index_sql.upper()

                # B10-BUG-23: SQLite partial indexes carry a WHERE clause
                # that lives only in ``sqlite_master.sql``. It was never
                # extracted, so diff saw every partial index as "missing
                # predicate" and generators re-emitted the index without
                # its WHERE — silently promoting partial indexes to full
                # indexes on round-trip.
                partial_condition = self._parse_index_where_clause(index_sql)

                # Filter out None values from columns (mypy requirement)
                columns_filtered: list[str] = [col for col in columns if col is not None]

                index = Index(
                    name=index_name,
                    table_name=table_name,
                    columns=columns_filtered,
                    unique=is_unique,
                    condition=partial_condition,
                    schema=None,
                    table_schema=None,
                    dialect="sqlite",
                    expression_flags=expression_flags,
                )

                indexes.append(index)

        except Exception as e:
            self.log.debug(f"Error getting indexes for {table_name}: {str(e)}")

        return indexes

    def _get_index_columns(self, index_name: str) -> List[Optional[str]]:
        """Get columns for an index.

        Returns:
            List of column names. For expression indexes, returns a list with None
            to indicate that the caller should parse the expression from CREATE INDEX SQL.
        """
        columns: List[Optional[str]] = []

        try:
            pragma_query = f"PRAGMA index_info('{index_name}')"
            results = self.provider.execute_query(pragma_query)

            for row in results:
                col_name = self._get_row_value(row, "name")
                cid = self._get_row_value(row, "cid")
                # For expression indexes, col_name is None and cid is -2
                # Return a list with None to signal that this is an expression index
                if col_name:
                    columns.append(col_name)
                elif cid == -2:
                    # Expression index - return None to signal caller to parse from SQL
                    columns.append(None)
                    break  # Expression indexes have only one entry

        except Exception as e:
            self.log.debug(f"Error getting columns for index {index_name}: {str(e)}")

        return columns

    def _parse_index_where_clause(self, index_sql: str) -> Optional[str]:
        """Parse ``WHERE`` predicate from CREATE INDEX SQL (SQLite partial index).

        SQLite stores the full ``CREATE INDEX`` text in ``sqlite_master.sql``.
        The column list ends at the matching close-paren of
        ``ON table(columns)``; anything after that up to end-of-statement is
        the partial-index predicate. Returns ``None`` for non-partial indexes.
        """
        if not index_sql:
            return None
        try:
            normalized = " ".join(index_sql.split())
            match = re.search(r"ON\s+(?:\"[^\"]+\"\.)?\"?[\w.]+\"?\s*\(", normalized, re.IGNORECASE)
            if not match:
                return None
            paren_count = 1
            pos = match.end()
            while pos < len(normalized) and paren_count > 0:
                if normalized[pos] == "(":
                    paren_count += 1
                elif normalized[pos] == ")":
                    paren_count -= 1
                pos += 1
            if paren_count != 0:
                return None
            tail = normalized[pos:].strip()
            where_match = re.match(r"WHERE\s+(.+?)\s*;?\s*$", tail, re.IGNORECASE)
            if not where_match:
                return None
            predicate = where_match.group(1).strip()
            return predicate or None
        except Exception as exc:
            self.log.debug(f"Failed to parse partial-index WHERE clause: {exc}")
            return None

    def _parse_index_expression(self, index_sql: str) -> Optional[str]:
        """Parse expression from CREATE INDEX SQL for expression indexes.

        Args:
            index_sql: CREATE INDEX SQL statement

        Returns:
            Expression string if found, None otherwise
        """
        if not index_sql:
            return None

        try:
            # Pattern: CREATE [UNIQUE] INDEX name ON table(expression)
            # Need to handle nested parentheses in expressions
            # Table name might be schema-qualified (e.g., "main_test.customers")
            # Table name might be quoted (e.g., "customers" or "main_test"."customers")
            normalized_sql = " ".join(index_sql.split())

            # Find ON table_name( part
            # Handle: ON table(, ON "table"(, ON schema.table(, ON "schema"."table"(
            # Pattern matches: ON [optional quotes]identifier[optional quotes] (optional schema prefix)
            match = re.search(
                r"ON\s+(?:\"[^\"]+\"\.)?\"?[\w.]+\"?\s*\(", normalized_sql, re.IGNORECASE
            )
            if match:
                # Find the matching closing parenthesis
                start_pos = match.end()
                paren_count = 1
                pos = start_pos
                while pos < len(normalized_sql) and paren_count > 0:
                    if normalized_sql[pos] == "(":
                        paren_count += 1
                    elif normalized_sql[pos] == ")":
                        paren_count -= 1
                    pos += 1

                if paren_count == 0:
                    expression = normalized_sql[start_pos : pos - 1].strip()
                    # Check if it's a simple column name or an expression
                    # Simple column names don't contain function calls or operators
                    if any(
                        op in expression
                        for op in [
                            "(",
                            ")",
                            "+",
                            "-",
                            "*",
                            "/",
                            "||",
                            "LOWER",
                            "UPPER",
                            "LENGTH",
                            "SUBSTR",
                            "INSTR",
                            "TRIM",
                            "DATE",
                            "DATETIME",
                        ]
                    ):
                        return expression
        except Exception as e:
            self.log.debug(f"Error parsing index expression: {str(e)}")

        return None

    def _parse_unique_constraints(self, create_sql: str, table_name: str) -> List[SqlConstraint]:
        """Parse unique constraints from CREATE TABLE statement."""
        constraints: List[SqlConstraint] = []

        if not create_sql:
            return constraints

        try:
            # Simple regex to find UNIQUE constraints
            # Match: UNIQUE (col1, col2, ...)
            unique_pattern = r"UNIQUE\s*\(([^)]+)\)"
            matches = re.findall(unique_pattern, create_sql, re.IGNORECASE)

            for i, match in enumerate(matches):
                columns = [col.strip().strip('"').strip("'") for col in match.split(",")]
                constraint = SqlConstraint(
                    name=f"unique_{table_name}_{i}",
                    constraint_type=ConstraintType.UNIQUE,
                    column_names=columns,
                )
                constraints.append(constraint)

        except Exception as e:
            self.log.debug(f"Error parsing unique constraints for {table_name}: {str(e)}")

        return constraints

    def _parse_check_constraints(self, create_sql: str, table_name: str) -> List[SqlConstraint]:
        """Parse CHECK constraints from CREATE TABLE statement.

        SQLite stores CHECK constraints in the CREATE TABLE SQL, not in a separate
        system table. We need to parse them from the SQL string.

        CHECK constraints can appear as:
        1. Column-level: column_name TEXT CHECK (expression)
        2. Table-level: CHECK (expression) or CONSTRAINT name CHECK (expression)
        """
        constraints: List[SqlConstraint] = []

        if not create_sql:
            return constraints

        try:
            # Normalize whitespace for easier parsing
            normalized_sql = " ".join(create_sql.split())

            # Track matched positions to avoid duplicates
            matched_positions = set()

            # Pattern 1: Named table-level CHECK constraint
            # CONSTRAINT constraint_name CHECK (expression)
            # Need to handle nested parentheses in expressions like length(name) > 0
            named_pattern = r"CONSTRAINT\s+([^\s]+)\s+CHECK\s*\("
            named_constraints_data: List[tuple[int, int, str, str]] = []
            for match in re.finditer(named_pattern, normalized_sql, re.IGNORECASE):
                # Find the matching closing parenthesis
                start_pos = match.end()
                paren_count = 1
                pos = start_pos
                while pos < len(normalized_sql) and paren_count > 0:
                    if normalized_sql[pos] == "(":
                        paren_count += 1
                    elif normalized_sql[pos] == ")":
                        paren_count -= 1
                    pos += 1

                if paren_count == 0:
                    constraint_name = match.group(1).strip().strip('"').strip("'")
                    check_expression = normalized_sql[start_pos : pos - 1].strip()
                    named_constraints_data.append(
                        (match.start(), pos, constraint_name, check_expression)
                    )

            for start, end, constraint_name, check_expression in named_constraints_data:
                matched_positions.add((start, end))

                constraint = SqlConstraint(
                    name=constraint_name,
                    constraint_type=ConstraintType.CHECK,
                    check_expression=check_expression,
                )
                constraints.append(constraint)

            # Pattern 2: Unnamed table-level CHECK constraint
            # CHECK (expression) - but not already matched by named pattern
            # Need to handle nested parentheses
            check_pattern = r"CHECK\s*\("
            unnamed_constraints_data: List[tuple[int, int, str]] = []
            for match in re.finditer(check_pattern, normalized_sql, re.IGNORECASE):
                # Skip if this is part of a named constraint we already matched
                is_named = any(
                    start <= match.start() <= end for start, end, _, _ in named_constraints_data
                )
                if is_named:
                    continue

                # Find the matching closing parenthesis
                start_pos = match.end()
                paren_count = 1
                pos = start_pos
                while pos < len(normalized_sql) and paren_count > 0:
                    if normalized_sql[pos] == "(":
                        paren_count += 1
                    elif normalized_sql[pos] == ")":
                        paren_count -= 1
                    pos += 1

                if paren_count == 0:
                    check_expression = normalized_sql[start_pos : pos - 1].strip()
                    unnamed_constraints_data.append((match.start(), pos, check_expression))

            # Filter out named constraints (those already matched)
            for start, end, check_expression in unnamed_constraints_data:
                match_pos = (start, end)
                if match_pos in matched_positions:
                    continue

                # Check if this is part of a named constraint by looking immediately before
                # We need to check if "CONSTRAINT name" appears right before this CHECK
                # Look back up to 100 chars to find CONSTRAINT keyword
                before_check = normalized_sql[max(0, start - 100) : start]

                # Check if there's a CONSTRAINT keyword followed by a name before this CHECK
                # Pattern: CONSTRAINT name CHECK - we want to skip these
                constraint_pattern = r"CONSTRAINT\s+[^\s]+\s+CHECK\s*$"
                is_named_constraint = bool(
                    re.search(constraint_pattern, before_check, re.IGNORECASE)
                )

                if not is_named_constraint:
                    # This is an unnamed table-level CHECK constraint (or column-level)
                    # Column-level CHECK constraints are harder to distinguish, but we'll include them
                    # Skip if already added
                    already_added = any(c.check_expression == check_expression for c in constraints)
                    if not already_added:
                        constraint = SqlConstraint(
                            name=f"check_{table_name}_{len(constraints)}",
                            constraint_type=ConstraintType.CHECK,
                            check_expression=check_expression,
                        )
                        constraints.append(constraint)

        except Exception as e:
            self.log.debug(f"Error parsing CHECK constraints for {table_name}: {str(e)}")

        return constraints

    def _parse_generated_columns(self, create_sql: str, table_name: str) -> List[SqlColumn]:
        """Parse generated columns from CREATE TABLE SQL.

        SQLite's PRAGMA table_info doesn't include generated columns, so we need
        to parse them from the CREATE TABLE SQL statement.

        Args:
            create_sql: CREATE TABLE SQL statement
            table_name: Table name

        Returns:
            List of SqlColumn objects for generated columns
        """
        generated_columns: List[SqlColumn] = []

        if not create_sql:
            return generated_columns

        try:
            # Normalize whitespace for easier parsing
            normalized_sql = " ".join(create_sql.split())

            # Pattern: column_name TYPE GENERATED ALWAYS AS (expression) STORED|VIRTUAL
            # Need to handle nested parentheses in expressions
            # Match column name and type before GENERATED
            pattern = r'(["\']?)(\w+)\1\s+(\w+)\s+GENERATED\s+ALWAYS\s+AS\s*\('

            for match in re.finditer(pattern, normalized_sql, re.IGNORECASE):
                col_name = match.group(2).strip().strip('"').strip("'")
                col_type = match.group(3).strip()

                # Find the matching closing parenthesis for the expression
                start_pos = match.end()
                paren_count = 1
                pos = start_pos
                while pos < len(normalized_sql) and paren_count > 0:
                    if normalized_sql[pos] == "(":
                        paren_count += 1
                    elif normalized_sql[pos] == ")":
                        paren_count -= 1
                    pos += 1

                if paren_count == 0:
                    expression = normalized_sql[start_pos : pos - 1].strip()

                    # Check if STORED or VIRTUAL follows
                    remaining = normalized_sql[pos:].strip()
                    is_stored = remaining.upper().startswith("STORED")
                    is_virtual = remaining.upper().startswith("VIRTUAL")

                    # Create column object
                    column = SqlColumn(
                        name=col_name,
                        data_type=col_type.upper(),
                        is_nullable=True,  # Generated columns are always nullable in SQLite
                        is_computed=True,
                        computed_expression=expression,
                        computed_stored=is_stored and not is_virtual,
                    )
                    generated_columns.append(column)

        except Exception as e:
            self.log.debug(f"Error parsing generated columns for {table_name}: {str(e)}")

        return generated_columns

    def _merge_columns_with_generated(
        self,
        regular_columns: List[SqlColumn],
        generated_columns: List[SqlColumn],
        create_sql: str,
    ) -> List[SqlColumn]:
        """Merge regular columns with generated columns in correct order.

        Args:
            regular_columns: Columns from PRAGMA table_info
            generated_columns: Generated columns parsed from CREATE TABLE SQL
            create_sql: CREATE TABLE SQL to determine column order

        Returns:
            Combined list of columns in correct order
        """
        if not generated_columns:
            return regular_columns

        # Create a map of column names to generated columns
        generated_map = {col.name: col for col in generated_columns}

        # Parse column order from CREATE TABLE SQL
        # Extract column definitions in order
        try:
            # Find the column definitions section (between parentheses)
            start = create_sql.find("(")
            end = create_sql.rfind(")")
            if start == -1 or end == -1:
                # Fallback: just append generated columns
                return regular_columns + generated_columns

            column_section = create_sql[start + 1 : end]

            # Split by commas, but be careful with nested parentheses
            column_defs = []
            current_def = ""
            paren_count = 0
            for char in column_section:
                if char == "(":
                    paren_count += 1
                    current_def += char
                elif char == ")":
                    paren_count -= 1
                    current_def += char
                elif char == "," and paren_count == 0:
                    column_defs.append(current_def.strip())
                    current_def = ""
                else:
                    current_def += char
            if current_def.strip():
                column_defs.append(current_def.strip())

            # Build ordered list
            all_columns = []
            regular_map = {col.name: col for col in regular_columns}
            seen_names = set()

            for col_def in column_defs:
                # Extract column name (first word, may be quoted)
                col_name_match = re.search(r'^["\']?(\w+)["\']?', col_def.strip())
                if col_name_match:
                    col_name = col_name_match.group(1)
                    if col_name in regular_map and col_name not in seen_names:
                        all_columns.append(regular_map[col_name])
                        seen_names.add(col_name)
                    elif col_name in generated_map and col_name not in seen_names:
                        all_columns.append(generated_map[col_name])
                        seen_names.add(col_name)

            # Add any remaining columns
            for col in regular_columns:
                if col.name not in seen_names:
                    all_columns.append(col)
            for col in generated_columns:
                if col.name not in seen_names:
                    all_columns.append(col)

            return all_columns

        except Exception as e:
            self.log.debug(f"Error merging columns: {str(e)}")
            # Fallback: append generated columns at the end
            return regular_columns + generated_columns

    def get_views(self, schema: str) -> List[View]:
        """
        Get all views in the database.

        Args:
            schema: Schema name (ignored for SQLite)

        Returns:
            List of View objects
        """
        self.ensure_connection()

        views: List[View] = []

        try:
            query = """
                SELECT name, sql
                FROM sqlite_master
                WHERE type = 'view'
                ORDER BY name
            """

            results = self.provider.execute_query(query)

            for row in results:
                view_name = self._get_row_value(row, "name")
                view_sql = self._get_row_value(row, "sql")

                if not view_name:
                    continue

                # Extract query from CREATE VIEW statement
                query_text = self._extract_view_query(view_sql) if view_sql else None

                view = View(
                    name=view_name,
                    schema=None,
                    query=query_text,
                    dialect="sqlite",
                )

                views.append(view)

            self.log.debug(f"Found {len(views)} views in SQLite database")

        except Exception as e:
            self.log.error(f"Error getting views: {str(e)}")
            raise

        return views

    def _extract_view_query(self, create_sql: str) -> Optional[str]:
        """Extract the query from a CREATE VIEW statement."""
        if not create_sql:
            return None

        try:
            # Match CREATE VIEW ... AS ...
            match = re.search(r"\bAS\s+(.+)", create_sql, re.IGNORECASE | re.DOTALL)
            if match:
                return match.group(1).strip()
        except Exception as e:
            self.log.debug(f"Could not extract view definition from CREATE VIEW SQL: {e}")

        return None

    def get_triggers(self, schema: str, table: Optional[str] = None) -> List[Trigger]:
        """
        Get all triggers in the database.

        Args:
            schema: Schema name (ignored for SQLite)

        Returns:
            List of Trigger objects
        """
        self.ensure_connection()

        triggers: List[Trigger] = []

        try:
            query = """
                SELECT name, tbl_name, sql
                FROM sqlite_master
                WHERE type = 'trigger'
                ORDER BY name
            """

            results = self.provider.execute_query(query)

            for row in results:
                trigger_name = self._get_row_value(row, "name")
                table_name = self._get_row_value(row, "tbl_name")
                trigger_sql = self._get_row_value(row, "sql")

                if not trigger_name:
                    continue

                # Parse trigger timing and events from SQL
                timing, events = self._parse_trigger_info(trigger_sql)

                trigger = Trigger(
                    name=trigger_name,
                    table_name=table_name,
                    schema=None,
                    timing=timing,
                    events=events,
                    definition=trigger_sql,
                    dialect="sqlite",
                )

                triggers.append(trigger)

            self.log.debug(f"Found {len(triggers)} triggers in SQLite database")

        except Exception as e:
            self.log.error(f"Error getting triggers: {str(e)}")
            raise

        return triggers

    def _parse_trigger_info(self, trigger_sql: str) -> tuple[Any, List[str]]:
        """Parse timing and events from trigger SQL."""
        timing = None
        events: List[str] = []

        if not trigger_sql:
            return timing, events

        sql_upper = trigger_sql.upper()

        # Parse timing
        if "BEFORE " in sql_upper:
            timing = "BEFORE"
        elif "AFTER " in sql_upper:
            timing = "AFTER"
        elif "INSTEAD OF " in sql_upper:
            timing = "INSTEAD OF"

        # Parse events
        if " INSERT " in sql_upper or " INSERT\n" in sql_upper:
            events.append("INSERT")
        if " UPDATE " in sql_upper or " UPDATE\n" in sql_upper:
            events.append("UPDATE")
        if " DELETE " in sql_upper or " DELETE\n" in sql_upper:
            events.append("DELETE")

        return timing, events

    def _get_row_value(self, row: Dict[str, Any], key: str) -> Any:
        """Get value from row with case-insensitive key lookup."""
        if key in row:
            return row[key]
        if key.lower() in row:
            return row[key.lower()]
        if key.upper() in row:
            return row[key.upper()]
        return None

    # Methods that return empty results for unsupported SQLite features

    def get_sequences(self, schema: str) -> List[Any]:
        """SQLite doesn't support sequences."""
        return []

    def get_materialized_views(self, schema: str) -> List[Any]:
        """SQLite doesn't support materialized views."""
        return []

    def get_procedures(self, schema: str) -> List[Any]:
        """SQLite doesn't support stored procedures."""
        return []

    def get_indexes(self, schema: str, table: str) -> List[Index]:
        """Get all indexes for a table."""
        return self._get_table_indexes(table)

    def get_check_constraints(self, schema: str, table: str) -> List[SqlConstraint]:
        """Get CHECK constraints for a table by parsing CREATE TABLE SQL."""
        self.ensure_connection()

        try:
            # Get CREATE TABLE SQL
            query = """
                SELECT sql
                FROM sqlite_master
                WHERE type = 'table' AND name = ?
            """
            results = self.provider.execute_query(query, [table])

            if not results:
                return []

            create_sql = self._get_row_value(results[0], "sql")
            return self._parse_check_constraints(create_sql, table)

        except Exception as e:
            self.log.debug(f"Error getting CHECK constraints for {table}: {str(e)}")
            return []

    def introspect_schema(self, schema: str, **kwargs: Any) -> Dict[str, Any]:
        """Introspect entire SQLite database schema."""
        self.ensure_connection()

        include_views = kwargs.get("include_views", True)
        include_triggers = kwargs.get("include_triggers", True)

        tables = self.get_tables(schema)
        views = self.get_views(schema) if include_views else []
        triggers = self.get_triggers(schema) if include_triggers else []

        # Get indexes for all tables
        indexes: Dict[str, List[Index]] = {}
        for table in tables:
            table_indexes = self._get_table_indexes(table.name)
            if table_indexes:
                indexes[table.name] = table_indexes

        return {
            "schema": schema,
            "tables": tables,
            "views": views,
            "triggers": triggers,
            "indexes": indexes,
            "sequences": [],
            "procedures": [],
            "functions": [],
            "table_count": len(tables),
            "view_count": len(views),
            "trigger_count": len(triggers),
            "total_columns": sum(len(t.columns) for t in tables),
            "total_indexes": sum(len(idx) for idx in indexes.values()),
        }

    def get_functions(self, schema: str) -> List[Any]:
        """SQLite doesn't support user-defined SQL functions."""
        return []

    def get_user_defined_types(self, schema: str) -> List[Any]:
        """SQLite doesn't support user-defined types."""
        return []
