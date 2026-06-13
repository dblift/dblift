"""Fallback DDL generator for Table objects.

Handles CREATE TABLE, DROP TABLE, and ALTER TABLE DDL generation
when no dialect-specific generator is available via SqlGeneratorFactory.
"""

import logging
import re
from typing import TYPE_CHECKING, Any, Callable, List, Optional, Set, Tuple

from core.sql_generator.base_generator import _schema_prefix_from_object
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint

if TYPE_CHECKING:
    from core.sql_model.table import Table

logger = logging.getLogger(__name__)


def _quirks_for(dialect: Optional[str]) -> Any:
    """Resolve quirks for *dialect* via the registry."""
    from db.base_quirks import BaseQuirks
    from db.provider_registry import ProviderRegistry

    canonical = ProviderRegistry.canonical_dialect_name(dialect or "")
    if canonical:
        return ProviderRegistry.get_quirks(canonical)
    return BaseQuirks()


def _strip_outer_parens(expr: str) -> str:
    """Remove a single layer of outer parentheses if they wrap the whole expression.

    Uses a depth-based scan to distinguish ``(a > 0)`` (outer parens removable)
    from ``(a) + (b)`` (outer parens are NOT a single wrapper — depth goes
    negative during the inner scan, so they are preserved).
    """
    if expr.startswith("(") and expr.endswith(")"):
        inner = expr[1:-1].strip()
        depth = 0
        for ch in inner:
            if ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth < 0:
                    return expr
        if depth == 0:
            return inner
    return expr


_PG_NEXTVAL_SEQUENCE_PATTERNS = (
    re.compile(r"nextval\s*\(\s*'([^']+)'\s*(?:::regclass)?\s*\)", re.IGNORECASE),
    re.compile(
        r"nextval\s*\(\s*cast\s*\(\s*'([^']+)'\s+as\s+regclass\s*\)\s*\)",
        re.IGNORECASE,
    ),
)


def _identifier_basename(identifier: str) -> str:
    return identifier.split(".")[-1].strip('"').lower()


def _extract_nextval_sequence_name(default_value: object) -> Optional[str]:
    if not isinstance(default_value, str):
        return None
    for pattern in _PG_NEXTVAL_SEQUENCE_PATTERNS:
        match = pattern.search(default_value)
        if match:
            return _identifier_basename(match.group(1))
    return None


def _is_pg_implicit_sequence_default(
    table_name: object, column_name: object, default_value: object
) -> bool:
    sequence_name = _extract_nextval_sequence_name(default_value)
    if not sequence_name:
        return False
    table = str(table_name or "").strip('"').lower()
    column = str(column_name or "").strip('"').lower()
    return bool(table and column and sequence_name == f"{table}_{column}_seq")


def _qualify_pg_nextval_default(default_value: object, schema_name: object) -> object:
    if not isinstance(default_value, str) or not schema_name:
        return default_value

    def replace(match: "re.Match[str]") -> str:
        sequence_ref = match.group(1)
        if "." in sequence_ref:
            return match.group(0)
        schema = str(schema_name).strip('"')
        qualified_ref = f"{schema}.{sequence_ref}"
        return f"nextval('{qualified_ref}'::regclass)"

    return re.sub(
        r"nextval\s*\(\s*'([^']+)'\s*(?:::regclass)?\s*\)",
        replace,
        default_value,
        flags=re.IGNORECASE,
    )


def _build_fk_ref_table(
    ref_table: str,
    ref_schema: Optional[str],
    format_identifier: Callable[[str], str],
) -> str:
    """Return schema-qualified or bare reference table name for FK REFERENCES clause.

    Builds either 'schema.table' or 'table' by applying format_identifier
    (e.g. quoting) to both parts.  The three callers in this codebase each
    use a different format_identifier method, but the logic is identical.

    Args:
        ref_table: Unformatted reference table name.
        ref_schema: Optional schema name; if truthy, prepended as 'schema.'.
        format_identifier: Callable that quotes/formats a single identifier.

    Returns:
        Formatted string, e.g. '"myschema"."my_table"' or '"my_table"'.
    """
    if ref_schema:
        return f"{format_identifier(ref_schema)}.{format_identifier(ref_table)}"
    return format_identifier(ref_table)


def _build_fk_body_sql(
    local_cols: List[str],
    ref_cols: List[str],
    ref_table: str,
    ref_schema: Optional[str],
    format_identifier: Callable[[str], str],
    on_delete: Optional[str] = None,
    on_update: Optional[str] = None,
    suppress_no_action: bool = True,
    suppress_on_update: bool = False,
) -> str:
    """Build the core FK body: FOREIGN KEY (...) REFERENCES ... (...) [ON DELETE ...] [ON UPDATE ...].

    Args:
        local_cols: Local column names (already deduplicated by caller).
        ref_cols: Reference column names.
        ref_table: Reference table name (unformatted).
        ref_schema: Optional reference schema name.
        format_identifier: Callable for quoting/formatting identifiers.
        on_delete: ON DELETE action string, or None.
        on_update: ON UPDATE action string, or None.
        suppress_no_action: If True, omit ON DELETE/UPDATE when action is NO ACTION or RESTRICT.
        suppress_on_update: If True, omit ON UPDATE clause entirely.

    Returns:
        FK body string starting with "FOREIGN KEY".
    """
    cols = ", ".join(format_identifier(col) for col in local_cols)
    ref_cols_str = ", ".join(format_identifier(col) for col in ref_cols)
    ref_table_formatted = _build_fk_ref_table(ref_table, ref_schema, format_identifier)

    body = f"FOREIGN KEY ({cols}) REFERENCES {ref_table_formatted}"
    if ref_cols_str:
        body += f" ({ref_cols_str})"

    if on_delete:
        action = str(on_delete).upper()
        if not suppress_no_action or action not in {"NO ACTION", "RESTRICT"}:
            body += f" ON DELETE {action}"

    if not suppress_on_update and on_update:
        action = str(on_update).upper()
        if not suppress_no_action or action not in {"NO ACTION", "RESTRICT"}:
            body += f" ON UPDATE {action}"

    return body


class BasicTableDdlGenerator:
    """Fallback DDL generator for Table objects.

    Handles CREATE TABLE, DROP TABLE, and ALTER TABLE DDL generation
    when no dialect-specific generator is available via SqlGeneratorFactory.
    """

    def __init__(self, table: "Table") -> None:
        """Bind to the table whose CREATE/DROP/ALTER DDL this generator will produce."""
        self.table = table

    def _is_self_referencing_fk(self, constraint: "SqlConstraint") -> bool:
        """Return True if the FK references the same table (self-referencing)."""
        ref_table = constraint.reference_table
        if not ref_table:
            return False
        if ref_table.lower() != self.table.name.lower():
            return False
        ref_schema = constraint.reference_schema or self.table.schema
        if ref_schema and self.table.schema:
            return ref_schema.lower() == self.table.schema.lower()
        return True

    def _build_fk_body(
        self, constraint: "SqlConstraint", *, suppress_on_update: bool = False
    ) -> Optional[str]:
        """Build the FK constraint body: FOREIGN KEY (...) REFERENCES ... (...) [ON DELETE ...].

        Returns None if local columns or reference table are absent.
        """
        ref_table = constraint.reference_table
        if not ref_table:
            return None

        local_cols_list: List[str] = []
        for col in constraint.column_names:
            if col not in local_cols_list:
                local_cols_list.append(col)
        if not local_cols_list:
            return None

        ref_cols_list: List[str] = list(constraint.reference_columns or [])
        if not ref_cols_list or len(ref_cols_list) != len(local_cols_list):
            ref_cols_list = local_cols_list[:]

        return _build_fk_body_sql(
            local_cols=local_cols_list,
            ref_cols=ref_cols_list,
            ref_table=ref_table,
            ref_schema=constraint.reference_schema,
            format_identifier=self.table.format_identifier,
            on_delete=getattr(constraint, "on_delete", None),
            on_update=getattr(constraint, "on_update", None),
            suppress_no_action=True,
            suppress_on_update=suppress_on_update,
        )

    def generate_create_statement(self) -> str:
        """Generate a basic CREATE TABLE statement as fallback."""
        # Validate the table before generating SQL (non-blocking)
        try:
            from core.sql_model.constraint_validator import ConstraintValidator

            validator = ConstraintValidator(dialect=self.table.dialect or "")
            validation_errors = validator.validate_table(self.table)

            # Log validation errors (but don't block SQL generation)
            for error in validation_errors:
                if error.severity == "error":
                    logger.warning(
                        f"Table '{self.table.name}' validation error: {error.message} (will attempt generation anyway)"
                    )
                elif error.severity == "warning":
                    logger.debug(f"Table '{self.table.name}' validation warning: {error.message}")
        except Exception as e:
            # Validator not available or failed, skip validation
            logger.debug(f"Validation skipped: {e}")

        # Build each section and assemble the final statement
        stmt = self._format_table_header()

        inline_pk_columns, skip_constraint_ids, pk_constraints, columns_in_skipped_pks = (
            self._resolve_primary_key()
        )

        # Pre-compute composite PK check once (used in column loop and constraint loop)
        has_composite_pk_final = any(
            c
            for c in (self.table.constraints or [])
            if c.constraint_type == ConstraintType.PRIMARY_KEY
            and len(c.column_names) > 1
            and id(c) not in skip_constraint_ids
        )

        # Add columns
        if self.table.columns:
            column_definitions = []
            for col in self.table.columns:
                col_def = self._generate_column_definition(
                    col,
                    inline_pk_columns,
                    skip_constraint_ids,
                    pk_constraints,
                    columns_in_skipped_pks,
                    has_composite_pk_final,
                )
                if col_def:
                    column_definitions.append(col_def)

            constraint_definitions = self._generate_constraint_definitions(
                skip_constraint_ids, pk_constraints
            )

            all_definitions = column_definitions + constraint_definitions

            # Filter empty entries only (no comma stripping needed — generators are clean)
            cleaned_definitions = [d for d in all_definitions if d and d.strip()]

            if cleaned_definitions:
                definitions_text = ",\n    ".join(cleaned_definitions)
                stmt += f" (\n    {definitions_text}\n)"
            else:
                # Empty table definition
                stmt += " ()"
        else:
            stmt += " ()"

        stmt += self._generate_table_suffix()

        return stmt

    def generate_drop_statement(self) -> str:
        """Generate DROP TABLE statement.

        Returns:
            SQL DROP TABLE statement for this table
        """
        schema_prefix = _schema_prefix_from_object(self.table)
        table_name = self.table.format_identifier(self.table.name)
        quirks = _quirks_for(self.table.dialect)

        style = quirks.table_drop_style
        if style == "cascade_constraints":
            return f"DROP TABLE {schema_prefix}{table_name} CASCADE CONSTRAINTS"
        elif style == "if_exists":
            return f"DROP TABLE IF EXISTS {schema_prefix}{table_name}"
        else:
            return f"DROP TABLE IF EXISTS {schema_prefix}{table_name} CASCADE"

    def generate_alter_check_constraints(self) -> List[str]:
        """Generate ALTER TABLE statements for CHECK constraints.

        For DB2, CHECK constraints should be added via ALTER TABLE instead of inline
        in CREATE TABLE, matching the pattern in original migration scripts.

        Returns:
            List of ALTER TABLE statements for CHECK constraints
        """
        quirks = _quirks_for(self.table.dialect)
        if not quirks.table_check_via_alter:
            return []

        statements = []
        seen_constraint_names: set[str] = set()
        seen_constraint_defs: set[str] = set()
        schema_prefix = _schema_prefix_from_object(self.table)
        table_name = self.table.format_identifier(self.table.name)

        for constraint in self.table.get_check_constraints():
            # Deduplicate by constraint name if present
            if constraint.name:
                constraint_name_lower = constraint.name.lower()
                if constraint_name_lower in seen_constraint_names:
                    continue
                seen_constraint_names.add(constraint_name_lower)

            check_expr = None
            if hasattr(constraint, "check_expression") and constraint.check_expression:
                check_expr = constraint.check_expression
            elif constraint.columns:
                check_expr = " ".join(constraint.columns)

            if not check_expr or check_expr.strip() in ("1=1", "(1=1)"):
                continue

            # Remove outer parentheses if already present (depth-based)
            check_expr = _strip_outer_parens(check_expr.strip())

            constraint_def = f"CHECK ({check_expr})"
            if constraint.name and not self._is_system_constraint_name(constraint.name):
                constraint_def = (
                    f"CONSTRAINT {self.table.format_identifier(constraint.name)} {constraint_def}"
                )

            # Also deduplicate by the full constraint definition (in case same constraint without name)
            if constraint_def in seen_constraint_defs:
                continue
            seen_constraint_defs.add(constraint_def)

            stmt = f"ALTER TABLE {schema_prefix}{table_name}\n    ADD {constraint_def}"
            statements.append(stmt)

        return statements

    def generate_alter_self_referencing_fks(self) -> List[str]:
        """Generate ALTER TABLE statements for self-referencing foreign keys.

        For DB2, self-referencing foreign keys should be added via ALTER TABLE
        instead of inline in CREATE TABLE, as DB2 doesn't allow them in CREATE TABLE.

        Returns:
            List of ALTER TABLE statements for self-referencing foreign keys
        """
        quirks = _quirks_for(self.table.dialect)
        if not quirks.table_self_ref_fk_via_alter:
            return []

        statements = []
        schema_prefix = _schema_prefix_from_object(self.table)
        table_name = self.table.format_identifier(self.table.name)

        for constraint in self.table.constraints:
            if constraint.constraint_type != ConstraintType.FOREIGN_KEY:
                continue
            if not self._is_self_referencing_fk(constraint):
                continue

            constraint_def = self._build_fk_body(constraint, suppress_on_update=False)
            if constraint_def is None:
                continue

            # Add constraint name if present
            if constraint.name and not self._is_system_constraint_name(constraint.name):
                constraint_def = (
                    f"CONSTRAINT {self.table.format_identifier(constraint.name)} {constraint_def}"
                )

            # Add constraint properties
            constraint_def = self._add_constraint_properties(constraint, constraint_def)

            stmt = f"ALTER TABLE {schema_prefix}{table_name}\n    ADD {constraint_def}"
            statements.append(stmt)

        return statements

    def _format_table_header(self) -> str:
        """Return the CREATE TABLE prefix including TEMPORARY/GLOBAL TEMPORARY and schema.table_name."""
        schema_prefix = _schema_prefix_from_object(self.table)
        table_name = self.table.format_identifier(self.table.name)
        quirks = _quirks_for(self.table.dialect)

        keyword = quirks.table_create_keyword
        if keyword != "TABLE":
            return f"CREATE {keyword} {table_name}"

        if self.table.temporary:
            style = quirks.table_temporary_style
            if style == "global_temporary":
                return f"CREATE GLOBAL TEMPORARY TABLE {schema_prefix}{table_name}"
            elif style == "hash_prefix":
                if self.table.name.startswith("#"):
                    formatted_temp_name = self.table.format_identifier(self.table.name)
                else:
                    formatted_temp_name = f"#{self.table.name}"
                return f"CREATE TABLE {schema_prefix}{formatted_temp_name}"
            else:
                return f"CREATE TEMPORARY TABLE {schema_prefix}{table_name}"
        else:
            return f"CREATE TABLE {schema_prefix}{table_name}"

    def _resolve_primary_key(
        self,
    ) -> Tuple[Set[str], Set[int], list, Set[str]]:
        """Resolve primary key constraints and return tracking sets.

        Returns a tuple of:
            - inline_pk_columns: Set of column names that should have inline PK
            - skip_constraint_ids: Set of constraint object IDs to skip in table-level output
            - pk_constraints: List of all PK constraints
            - columns_in_skipped_pks: Set of column names that are part of skipped PK constraints
        """
        inline_pk_columns: Set[str] = set()
        skip_constraint_ids: Set[int] = set()

        pk_constraints = [
            c
            for c in (self.table.constraints or [])
            if c.constraint_type == ConstraintType.PRIMARY_KEY
        ]

        has_composite_pk_constraint = any(c for c in pk_constraints if len(c.column_names) > 1)

        columns_in_skipped_pks: Set[str] = set()

        if len(pk_constraints) > 1 or has_composite_pk_constraint:
            composite_pk = next((c for c in pk_constraints if len(c.column_names) > 1), None)
            if composite_pk:
                for constraint in pk_constraints:
                    if len(constraint.column_names) == 1:
                        skip_constraint_ids.add(id(constraint))
                        columns_in_skipped_pks.add(constraint.column_names[0].lower())
                        inline_pk_columns.discard(constraint.column_names[0].lower())
                for col in self.table.columns or []:
                    if col.name.lower() not in [cn.lower() for cn in composite_pk.column_names]:
                        inline_pk_columns.discard(col.name.lower())
                        if getattr(col, "is_primary_key", False):
                            columns_in_skipped_pks.add(col.name.lower())

        # Handle inline PKs.
        # Oracle/DB2: always inline single-column PKs (table_not_null_implicit_on_inline_pk
        #   or table_check_via_alter is True).
        # PostgreSQL: inline only when there is at most one PK constraint
        #   (table_prefers_inline_single_pk=True, len(pk_constraints) <= 1).
        # All other dialects: never inline (both flags are False).
        quirks = _quirks_for(self.table.dialect)
        is_oracle_or_db2 = (
            quirks.table_not_null_implicit_on_inline_pk or quirks.table_check_via_alter
        )
        if self.table.constraints and (
            is_oracle_or_db2 or (quirks.table_prefers_inline_single_pk and len(pk_constraints) <= 1)
        ):
            for constraint in self.table.constraints:
                if (
                    constraint.constraint_type == ConstraintType.PRIMARY_KEY
                    and len(constraint.column_names) == 1
                    and id(constraint) not in skip_constraint_ids
                ):
                    constraint_name = constraint.name or ""
                    if not constraint_name or self._is_system_constraint_name(constraint_name):
                        inline_pk_columns.add(constraint.column_names[0].lower())
                        skip_constraint_ids.add(id(constraint))

        return inline_pk_columns, skip_constraint_ids, pk_constraints, columns_in_skipped_pks

    @staticmethod
    def _normalize_column_data_type(col, dialect: Optional[str] = None) -> str:
        """Normalize column data type via the dialect's quirks hook."""
        from db.provider_registry import ProviderRegistry

        data_type: str = str(col.data_type)
        quirks = ProviderRegistry.get_quirks((dialect or "").lower())
        return quirks.normalize_column_data_type(col, data_type)

    def _build_collation_clause(self, col) -> Optional[str]:
        """Return COLLATE clause if collation is applicable, else None."""
        if hasattr(col, "collation") and col.collation:
            quirks = _quirks_for(self.table.dialect)
            if quirks.table_supports_inline_collate:
                return f"COLLATE {self.table.format_identifier(col.collation)}"
        return None

    def _build_temporal_clause(self, col) -> Optional[str]:
        """Return GENERATED ALWAYS AS ROW START/END for SQL Server system-versioned columns, else None."""
        quirks = _quirks_for(self.table.dialect)
        if not quirks.table_supports_system_versioned or not self.table.system_versioned:
            return None
        start_col = (self.table.period_start_column or "").lower()
        end_col = (self.table.period_end_column or "").lower()
        if start_col and col.name.lower() == start_col:
            return "GENERATED ALWAYS AS ROW START"
        if end_col and col.name.lower() == end_col:
            return "GENERATED ALWAYS AS ROW END"
        return None

    def _build_identity_clause(self, col, dialect: Optional[str] = None) -> Optional[str]:
        """Return the identity/auto-increment clause appropriate for the dialect, or None."""
        is_postgresql = (dialect or "").lower() in {
            "postgresql",  # lint: allow-dialect-string: PG nextval compatibility path
            "postgres",  # lint: allow-dialect-string: PG alias compatibility path
        }
        table_name = getattr(self.table, "name", None)
        if is_postgresql and _is_pg_implicit_sequence_default(
            table_name, getattr(col, "name", None), getattr(col, "default_value", None)
        ):
            return "GENERATED BY DEFAULT AS IDENTITY"
        if not getattr(col, "is_identity", False):
            return None
        if is_postgresql and "nextval(" in str(getattr(col, "default_value", "") or "").lower():
            return None
        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks((dialect or "").lower())
        return quirks.render_identity_clause(col)

    @staticmethod
    def _build_not_null_clause(
        col, inline_pk_columns: Set[str], dialect: Optional[str] = None
    ) -> Optional[str]:
        """Return 'NOT NULL' unless dialect-specific exceptions apply, else None.

        Exceptions: DB2 identity inline PK, Oracle inline PK — NOT NULL is implicit.
        Only adds NOT NULL when nullable is explicitly False; nullable=None (unknown)
        must not be treated as NOT NULL.
        """
        if col.nullable is not False:
            return None
        quirks = _quirks_for(dialect)
        if (
            quirks.table_not_null_implicit_on_identity_pk
            and getattr(col, "is_identity", False)
            and col.name.lower() in inline_pk_columns
        ):
            return None
        if quirks.table_not_null_implicit_on_inline_pk and col.name.lower() in inline_pk_columns:
            return None
        return "NOT NULL"

    def _build_computed_clause(self, col) -> Tuple[Optional[str], Optional[str]]:
        """Return (clause_to_append, new_parts0) for computed/generated columns.

        Delegates to ``quirks.render_computed_column`` (PR-G8) so per-dialect
        rendering shapes (PostgreSQL ``GENERATED … [STORED]``, Oracle ``…
        [VIRTUAL]``, SQL Server ``col AS (expr) [PERSISTED]``, MySQL ``AS
        (expr) STORED|VIRTUAL``) live with each plugin's quirks instead of an
        ``if style == X`` chain.
        """
        quirks = _quirks_for(self.table.dialect)
        result: Tuple[Optional[str], Optional[str]] = quirks.render_computed_column(
            col, self.table.format_identifier(col.name)
        )
        return result

    @staticmethod
    def _build_inline_pk_clause(
        col,
        inline_pk_columns: Set[str],
        columns_in_skipped_pks: Set[str],
        pk_constraints: list,
        has_composite_pk_final: bool,
    ) -> Optional[str]:
        """Return 'PRIMARY KEY' if the column should have an inline PK, else None."""
        col_name_lower = col.name.lower()
        is_in_skipped_pk = col_name_lower in columns_in_skipped_pks
        has_multiple_pks = len(pk_constraints) > 1
        if has_composite_pk_final or is_in_skipped_pk or has_multiple_pks:
            return None
        if col_name_lower in inline_pk_columns:
            return "PRIMARY KEY"
        has_table_level_pk = any(
            col_name_lower in {name.lower() for name in constraint.column_names}
            for constraint in pk_constraints
        )
        if has_table_level_pk:
            return None
        if getattr(col, "is_primary_key", False):
            return "PRIMARY KEY"
        return None

    def _build_inline_unique_clause_db2(self, col, skip_constraint_ids: Set[int]) -> Optional[str]:
        """Return 'UNIQUE' for single-column unique constraints (DB2), else None.

        Adds the matched constraint id to skip_constraint_ids as a side effect.
        """
        quirks = _quirks_for(self.table.dialect)
        if not quirks.table_inline_unique_single_col:
            return None
        for constraint in self.table.constraints:
            if (
                constraint.constraint_type == ConstraintType.UNIQUE
                and len(constraint.column_names) == 1
                and constraint.column_names[0].lower() == col.name.lower()
            ):
                skip_constraint_ids.add(id(constraint))
                return "UNIQUE"
        return None

    def _generate_column_definition(
        self,
        col,
        inline_pk_columns: Set[str],
        skip_constraint_ids: Set[int],
        pk_constraints: list,
        columns_in_skipped_pks: Set[str],
        has_composite_pk_final: bool,
    ) -> str:
        """Generate DDL for a single column.

        Orchestrates helper methods for data type normalization, collation,
        temporal columns, identity, NOT NULL, computed/generated, DEFAULT,
        inline PK, and inline UNIQUE (DB2).
        """
        dialect = self.table.dialect
        data_type = self._normalize_column_data_type(col, dialect)
        parts: List[str] = [f"{self.table.format_identifier(col.name)} {data_type}"]

        collation = self._build_collation_clause(col)
        if collation:
            parts.append(collation)

        temporal = self._build_temporal_clause(col)
        if temporal:
            parts.append(temporal)

        identity = self._build_identity_clause(col, dialect)
        if identity:
            parts.append(identity)

        not_null = self._build_not_null_clause(col, inline_pk_columns, dialect)
        if not_null:
            parts.append(not_null)

        computed_clause, new_parts0 = self._build_computed_clause(col)
        if new_parts0 is not None:
            parts[0] = new_parts0
        if computed_clause:
            parts.append(computed_clause)
        if computed_clause is None and new_parts0 is None:
            default_clause = self._format_default_value(col)
            identity_clause = self._build_identity_clause(col, dialect)
            if default_clause is not None and identity_clause is None:
                parts.append(f"DEFAULT {default_clause}")

        inline_pk = self._build_inline_pk_clause(
            col, inline_pk_columns, columns_in_skipped_pks, pk_constraints, has_composite_pk_final
        )
        if inline_pk:
            parts.append(inline_pk)

        inline_unique = self._build_inline_unique_clause_db2(col, skip_constraint_ids)
        if inline_unique:
            parts.append(inline_unique)

        return " ".join(parts)

    def _generate_constraint_definitions(
        self,
        skip_constraint_ids: Set[int],
        pk_constraints: list,
    ) -> List[str]:
        """Generate non-inline constraint DDL lines (PK, FK, CHECK, UNIQUE).

        Returns a list of constraint definition strings.
        """
        quirks = _quirks_for(self.table.dialect)
        constraint_definitions = []
        seen_constraints: Set[str] = set()
        for constraint in self.table.constraints:
            if id(constraint) in skip_constraint_ids:
                continue
            if constraint.constraint_type == ConstraintType.PRIMARY_KEY:
                if not constraint.column_names:
                    continue
                cols = ", ".join(
                    self.table.format_identifier(col) for col in constraint.column_names
                )
                constraint_def = f"PRIMARY KEY ({cols})"
                if constraint.name and not self._is_system_constraint_name(constraint.name):
                    constraint_def = f"CONSTRAINT {self.table.format_identifier(constraint.name)} {constraint_def}"
                constraint_def = self._add_constraint_properties(constraint, constraint_def)
                if (
                    constraint_def
                    and constraint_def.strip()
                    and constraint_def not in seen_constraints
                ):
                    seen_constraints.add(constraint_def)
                    constraint_definitions.append(constraint_def)

            elif constraint.constraint_type == ConstraintType.FOREIGN_KEY:
                # Skip self-referencing FKs when dialect requires post-CREATE ALTER
                if self._is_self_referencing_fk(constraint) and quirks.table_self_ref_fk_via_alter:
                    continue

                suppress_on_update = quirks.table_fk_suppress_on_update
                fk_body = self._build_fk_body(constraint, suppress_on_update=suppress_on_update)
                if fk_body is None:
                    continue
                constraint_def = fk_body

                if constraint.name and not self._is_system_constraint_name(constraint.name):
                    constraint_def = f"CONSTRAINT {self.table.format_identifier(constraint.name)} {constraint_def}"
                constraint_def = self._add_constraint_properties(constraint, constraint_def)
                if (
                    constraint_def
                    and constraint_def.strip()
                    and constraint_def not in seen_constraints
                ):
                    seen_constraints.add(constraint_def)
                    constraint_definitions.append(constraint_def)

            elif constraint.constraint_type == ConstraintType.UNIQUE:
                if not constraint.columns and not constraint.column_names:
                    continue
                cols_list = (
                    constraint.column_names
                    if hasattr(constraint, "column_names") and constraint.column_names
                    else constraint.columns
                )
                if not cols_list:
                    continue
                cols = ", ".join(self.table.format_identifier(col) for col in cols_list)
                constraint_def = f"UNIQUE ({cols})"
                if constraint.name and not self._is_system_constraint_name(constraint.name):
                    constraint_def = f"CONSTRAINT {self.table.format_identifier(constraint.name)} {constraint_def}"
                constraint_def = self._add_constraint_properties(constraint, constraint_def)
                if (
                    constraint_def
                    and constraint_def.strip()
                    and constraint_def not in seen_constraints
                ):
                    seen_constraints.add(constraint_def)
                    constraint_definitions.append(constraint_def)

            elif constraint.constraint_type == ConstraintType.CHECK:
                check_expr = None
                if hasattr(constraint, "check_expression") and constraint.check_expression:
                    check_expr = constraint.check_expression
                elif constraint.columns:
                    check_expr = " ".join(constraint.columns)

                if not check_expr or check_expr.strip() in ("1=1", "(1=1)"):
                    continue

                # Skip inline CHECK when dialect requires post-CREATE ALTER
                if quirks.table_check_via_alter:
                    continue

                # Remove outer parentheses if already present (depth-based)
                check_expr = _strip_outer_parens(check_expr.strip())

                # Clean up _utf8mb4 prefixes and escaped quotes
                if quirks.table_check_strip_utf8mb4:
                    check_expr = re.sub(r"_utf8mb4\\'", "'", check_expr)
                    check_expr = re.sub(r"_utf8mb4'", "'", check_expr)
                    check_expr = check_expr.replace("\\'", "'")
                    check_expr = check_expr.replace('\\"', '"')

                constraint_def = f"CHECK ({check_expr})"
                if constraint.name and not self._is_system_constraint_name(constraint.name):
                    constraint_def = f"CONSTRAINT {self.table.format_identifier(constraint.name)} {constraint_def}"
                constraint_def = self._add_constraint_properties(constraint, constraint_def)
                if (
                    constraint_def
                    and constraint_def.strip()
                    and constraint_def not in seen_constraints
                ):
                    seen_constraints.add(constraint_def)
                    constraint_definitions.append(constraint_def)

        # Combine: add PERIOD FOR SYSTEM_TIME clause for SQL Server temporal tables
        if (
            quirks.table_supports_system_versioned
            and self.table.system_versioned
            and self.table.period_start_column
            and self.table.period_end_column
        ):
            period_clause = (
                f"PERIOD FOR SYSTEM_TIME ("
                f"{self.table.format_identifier(self.table.period_start_column)}, "
                f"{self.table.format_identifier(self.table.period_end_column)})"
            )
            constraint_definitions.append(period_clause)

        return constraint_definitions

    def _generate_table_suffix(self) -> str:
        """Generate everything after the closing paren."""
        suffix = ""
        quirks = _quirks_for(self.table.dialect)

        partition_clause = self._build_partition_clause()
        if partition_clause:
            suffix += f"\n{partition_clause}"

        if self.table.tablespace:
            ts_style = quirks.table_tablespace_style
            if ts_style == "skip":
                pass
            elif ts_style == "quoted":
                tablespace_name = self.table.format_identifier(self.table.tablespace)
                suffix += f" TABLESPACE {tablespace_name}"
            else:
                tablespace_name = self.table.tablespace
                suffix += f" TABLESPACE {tablespace_name}"

        if self.table.filegroup and quirks.table_uses_filegroup_syntax:
            if self.table.filegroup.upper() == "PRIMARY":
                suffix += " ON [PRIMARY]"
            else:
                suffix += f" ON {self.table.format_identifier(self.table.filegroup)}"

        if self.table.memory_optimized and quirks.table_supports_memory_optimized:
            suffix += " WITH (MEMORY_OPTIMIZED = ON)"

        if self.table.system_versioned and quirks.table_supports_system_versioned:
            suffix += " WITH (SYSTEM_VERSIONING = ON"
            if self.table.history_table:
                history_schema = (
                    self.table.format_identifier(self.table.history_schema)
                    if self.table.history_schema
                    else (
                        self.table.format_identifier(self.table.schema) if self.table.schema else ""
                    )
                )
                history_table = self.table.format_identifier(self.table.history_table)
                if history_schema:
                    suffix += f" (HISTORY_TABLE = {history_schema}.{history_table})"
                else:
                    suffix += f" (HISTORY_TABLE = {history_table})"
            suffix += ")"

        if quirks.table_supports_storage_params:
            storage_params = []
            if self.table.pctfree is not None:
                storage_params.append(f"PCTFREE {self.table.pctfree}")
            if self.table.pctused is not None:
                storage_params.append(f"PCTUSED {self.table.pctused}")
            if self.table.initial is not None:
                storage_params.append(f"INITIAL {self.table.initial}")
            if self.table.next is not None:
                storage_params.append(f"NEXT {self.table.next}")
            if storage_params:
                suffix += f"\n{', '.join(storage_params)}"

        if quirks.table_supports_inherits and self.table.inherits:
            formatted_inherits = []
            for parent in self.table.inherits:
                if "." in parent:
                    schema_part, table_part = parent.rsplit(".", 1)
                    formatted_inherits.append(
                        f"{self.table.format_identifier(schema_part)}.{self.table.format_identifier(table_part)}"
                    )
                else:
                    formatted_inherits.append(self.table.format_identifier(parent))
            if formatted_inherits:
                suffix += f"\nINHERITS ({', '.join(formatted_inherits)})"

        return suffix

    def _add_constraint_properties(self, constraint: SqlConstraint, constraint_def: str) -> str:
        """Add constraint properties (deferrable, enabled, validated) to constraint definition."""
        quirks = _quirks_for(self.table.dialect)

        if quirks.table_supports_deferrable_constraints:
            is_deferrable = getattr(constraint, "is_deferrable", None)
            initially_deferred = getattr(constraint, "initially_deferred", None)
            if is_deferrable is True:
                constraint_def += " DEFERRABLE"
                if initially_deferred is True:
                    constraint_def += " INITIALLY DEFERRED"
                elif initially_deferred is False:
                    constraint_def += " INITIALLY IMMEDIATE"
            elif is_deferrable is False:
                constraint_def += " NOT DEFERRABLE"

        if quirks.table_supports_constraint_state:
            is_enabled = getattr(constraint, "is_enabled", None)
            is_validated = getattr(constraint, "is_validated", None)
            if is_enabled is False:
                constraint_def += " DISABLE"
            elif is_enabled is True:
                constraint_def += " ENABLE"
            if is_validated is False:
                constraint_def += " NOVALIDATE"
            elif is_validated is True:
                constraint_def += " VALIDATE"

        if quirks.table_supports_constraint_nocheck:
            is_enabled = getattr(constraint, "is_enabled", None)
            if is_enabled is False:
                constraint_def += " WITH NOCHECK"

        return constraint_def

    def _format_default_value(self, column: SqlColumn) -> Optional[str]:
        """Return a dialect-appropriate DEFAULT expression for a column."""
        default_value = getattr(column, "default_value", None)
        if default_value is None:
            return None

        if (self.table.dialect or "").lower() in {
            "postgresql",  # lint: allow-dialect-string: PG nextval export compatibility
            "postgres",  # lint: allow-dialect-string: PG alias export compatibility
        }:
            default_value = _qualify_pg_nextval_default(default_value, self.table.schema)

        default_str = str(default_value).strip()
        if not default_str:
            return "''"

        from db.provider_registry import ProviderRegistry

        quirks = ProviderRegistry.get_quirks((self.table.dialect or "").lower())
        return quirks.unwrap_default_value(default_str, column)

    @staticmethod
    def _is_system_constraint_name(name: str) -> bool:
        """Return True if constraint name is system-generated (Oracle/DB2)."""
        if not name:
            return False
        normalized = name.strip().upper()
        if normalized.startswith("SYS_") or normalized.startswith("SYS$"):
            return True
        if normalized.startswith("SQL"):
            return bool(re.match(r"^SQL\d+$", normalized))
        return False

    def _build_partition_clause(self) -> str:
        """Return a dialect-appropriate PARTITION BY clause if partition metadata is present."""
        if not self.table.partition_method:
            return ""

        method = self.table.partition_method.upper()
        columns = self.table.partition_columns or []

        clause = f"PARTITION BY {method}"
        if columns:
            formatted_columns = ", ".join(self.table.format_identifier(col) for col in columns)
            clause += f" ({formatted_columns})"

        if self.table.export_partitions:
            partition_defs = ",\n    ".join(
                part.create_statement for part in self.table.export_partitions
            )
            clause += f" (\n    {partition_defs}\n)"

        return clause
