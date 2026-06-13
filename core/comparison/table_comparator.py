"""Table Comparator for Drift Detection.

This module provides the TableComparator class which compares table objects
from different sources (parsed scripts vs. database introspection) and generates
structured diff results.

Several focused helpers live in their own modules to keep this orchestrator
readable:
- :mod:`core.comparison._default_normalizer` — pure normalization functions
  for default values and CHECK expressions.
- :mod:`core.comparison._table_property_comparator` — dialect-specific
  property comparison (filegroup, system_versioned, partition, inherits, ...).

``TableComparator`` keeps thin wrapper methods (``_normalize_default_value``,
``_normalize_expression``, ``_compare_table_properties``) that delegate to
those helpers, preserving the public surface used by existing tests.
"""

import re
from typing import Any, List, Optional, Tuple

from core.comparison._default_normalizer import (
    normalize_check_expression as _normalize_expression_impl,
)
from core.comparison._default_normalizer import (
    normalize_column_default as _normalize_default_value_impl,
)
from core.comparison._table_property_comparator import (
    compare_table_properties as _compare_table_properties_impl,
)
from core.comparison.comparison_utils import (  # noqa: F401  re-exported for backward compat
    extract_base_identity_type,
    is_system_generated_constraint_name,
    strip_boolean_wrappers,
    strip_redundant_parens,
)
from core.comparison.diff_models import ColumnDiff, ConstraintDiff, SchemaDiff, TableDiff
from core.comparison.type_normalizer import DataTypeNormalizer
from core.logger import NullLog
from core.logger._base import Log
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from db.provider_registry import ProviderRegistry


class TableComparator:
    """Compares table objects and generates diff results.

    This class provides methods to compare table objects from different sources
    (e.g., parsed SQL scripts vs. database metadata) and identify differences.
    """

    _GENERATED_ALWAYS_PATTERN = re.compile(
        r"GENERATED\s+ALWAYS\s+AS\s*\((.+?)\)\s*(STORED|VIRTUAL|PERSISTED)?",
        re.IGNORECASE | re.DOTALL,
    )

    def __init__(self, type_normalizer: DataTypeNormalizer, log: Optional[Log] = None) -> None:
        """Initialize the table comparator.

        Args:
            type_normalizer: DataTypeNormalizer for type comparison
            log: Logger instance; defaults to NullLog
        """
        self.type_normalizer = type_normalizer
        self.log = log if log is not None else NullLog()

    @staticmethod
    def _constraint_key(c: SqlConstraint) -> str:
        """Generate unique key for constraint.

        Matches constraints by type and columns, ignoring system-generated names.
        This ensures that unnamed constraints or those with auto-generated names
        (like Oracle's SYS_C*) are matched correctly.
        """
        # Convert to Python string to handle driver-returned objects
        key_parts = [str(c.constraint_type.value).lower()]

        # Always try to match by columns first (most reliable)
        has_column_signature = False
        if getattr(c, "column_names", None):
            # Convert to Python strings to handle driver-returned objects
            column_signature = ",".join(sorted(str(col).lower() for col in c.column_names if col))
            if column_signature:
                key_parts.append(column_signature)
                has_column_signature = True

        # For foreign keys, add reference information
        if c.constraint_type == ConstraintType.FOREIGN_KEY:
            # Convert to Python string to handle driver-returned objects
            reference_table = str(getattr(c, "reference_table", "") or "").lower()
            if reference_table and "." in reference_table:
                reference_table = reference_table.split(".")[-1]
            reference_columns = None
            if getattr(c, "reference_columns", None):
                # Convert to Python strings to handle driver-returned objects
                reference_columns = ",".join(
                    sorted(str(col).lower() for col in c.reference_columns if col)
                )

            if reference_table:
                key_parts.append(reference_table)
            if reference_columns:
                key_parts.append(reference_columns)

        # For CHECK constraints, use check_expression if available (more reliable than name)
        if c.constraint_type == ConstraintType.CHECK:
            check_expr = getattr(c, "check_expression", None)
            if check_expr:
                # Normalize the expression for matching (remove whitespace, lowercase)
                # Simple normalization inline - remove CHECK keyword, normalize whitespace
                expr_str = str(check_expr).strip()
                # Remove CHECK keyword if present
                if expr_str.upper().startswith("CHECK"):
                    expr_str = expr_str[5:].strip()
                # Remove outer parentheses if present
                if expr_str.startswith("(") and expr_str.endswith(")"):
                    expr_str = expr_str[1:-1].strip()
                # Normalize whitespace and case
                normalized_expr = " ".join(expr_str.split()).upper()
                if normalized_expr:
                    key_parts.append(normalized_expr)
                    has_column_signature = True  # Treat expression as signature

        # Only use name if:
        # 1. We don't have a column signature or check expression (e.g., check constraints without expression)
        # 2. The name is NOT system-generated
        if not has_column_signature and c.name and not is_system_generated_constraint_name(c.name):
            # Convert to Python string to handle driver-returned objects
            key_parts.append(str(c.name).lower())

        return "|".join(part for part in key_parts if part)

    @staticmethod
    def _filter_duplicate_unique_constraints(
        constraints: List[SqlConstraint],
    ) -> List[SqlConstraint]:
        """Remove UNIQUE constraints that duplicate PRIMARY KEY constraints.

        For databases like DB2 and Oracle, PRIMARY KEY constraints can generate
        UNIQUE constraints with different names but identical columns. We filter
        based on column signature only, not name matching, to avoid false positives.
        """
        # Find all PRIMARY KEY constraints with their column signatures
        pk_signatures = set()
        for c in constraints:
            if c.constraint_type == ConstraintType.PRIMARY_KEY:
                col_sig = tuple(sorted(getattr(c, "column_names", [])))
                pk_signatures.add(col_sig)

        # Filter out UNIQUE constraints that match PK signatures
        filtered = []
        for c in constraints:
            if c.constraint_type == ConstraintType.UNIQUE:
                col_sig = tuple(sorted(getattr(c, "column_names", [])))
                # Skip if this UNIQUE constraint has same columns as a PK
                # DB2 and Oracle create separate UNIQUE constraints for PRIMARY KEYs
                # with different names, so we only check column signature
                if col_sig in pk_signatures:
                    continue
            filtered.append(c)

        return filtered

    @staticmethod
    def _extract_generated_metadata(
        data_type: str,
        is_computed: bool,
        computed_expression: Optional[str],
        computed_stored: bool,
    ) -> Tuple[str, bool, Optional[str], bool]:
        """Extract GENERATED ALWAYS AS metadata from data type string.

        Returns:
            Tuple of (base_type, is_computed, expression, stored)
        """
        match = TableComparator._GENERATED_ALWAYS_PATTERN.search(data_type)
        if not match:
            return data_type, is_computed, computed_expression, computed_stored

        base_type = data_type[: match.start()].strip() or data_type
        expr = computed_expression
        if not expr:
            expr_text = match.group(1).strip()
            if expr_text.startswith("(") and expr_text.endswith(")"):
                inner = expr_text[1:-1].strip()
                if inner:
                    expr_text = inner
            expr = expr_text
        stored = computed_stored or (
            match.group(2) is not None and match.group(2).strip().upper() in {"STORED", "PERSISTED"}
        )
        return base_type, True, expr, stored

    @staticmethod
    def _strip_schema(type_name: str) -> str:
        """Strip schema prefix from a type name."""
        stripped = type_name.strip('"')
        if "." in stripped:
            stripped = stripped.split(".")[-1]
        # Strip any residual quotes left after split (e.g. '"public"."mytype"' → 'mytype')
        # Convert to Python string to handle driver-returned objects
        return str(stripped).strip('"').lower()

    @staticmethod
    def _strip_on_update_clause(value: Optional[str]) -> Optional[str]:
        """Strip MySQL ON UPDATE clause from a default value."""
        if not value:
            return value
        return re.sub(r"\s+ON\s+UPDATE\s+.*$", "", value, flags=re.IGNORECASE).strip()

    def compare_tables(
        self,
        expected: Table,
        actual: Table,
        dialect: str = "",
    ) -> TableDiff:
        """Compare two table objects.

        Args:
            expected: Expected table (from scripts)
            actual: Actual table (from database)
            dialect: SQL dialect for type normalization

        Returns:
            TableDiff object with comparison results

        Example:
            >>> diff = comparator.compare_tables(script_table, db_table, "postgresql")
            >>> print(f"Missing columns: {diff.missing_columns}")
        """
        # Check if table is derived (CREATE TABLE AS SELECT or CREATE TABLE LIKE)
        # For derived tables, columns and constraints are defined at execution time, so we skip comparison
        is_derived = getattr(expected, "derived_from", None) is not None

        if is_derived:
            # Skip column and constraint comparison for derived tables
            # Columns and constraints are determined from source table/query at execution time
            missing_cols: List[SqlColumn] = []
            extra_cols: List[SqlColumn] = []
            modified_cols: List[ColumnDiff] = []
            missing_consts: List[SqlConstraint] = []
            extra_consts: List[SqlConstraint] = []
            modified_consts: List[ConstraintDiff] = []
        else:
            # Compare columns normally
            missing_cols, extra_cols, modified_cols = self._compare_columns(
                expected.columns, actual.columns, dialect
            )

            # Compare constraints
            missing_consts, extra_consts, modified_consts = self._compare_constraints(
                expected.constraints, actual.constraints, dialect
            )

        # Create TableDiff
        table_diff = TableDiff(
            object_name=expected.name,
            table_name=expected.name,
            missing_columns=[col.name for col in missing_cols],
            extra_columns=[col.name for col in extra_cols],
            modified_columns=modified_cols,
            missing_constraints=[c.name or f"unnamed_{i}" for i, c in enumerate(missing_consts)],
            extra_constraints=[c.name or f"unnamed_{i}" for i, c in enumerate(extra_consts)],
            modified_constraints=modified_consts,
            expected_table=expected,
            actual_table=actual,
        )

        self._compare_table_properties(table_diff, expected, actual, dialect)

        # Recalculate has_diffs and severity with new properties
        table_diff._calculate_diffs()

        return table_diff

    def _compare_table_properties(
        self, diff: TableDiff, expected: Table, actual: Table, dialect: str
    ) -> None:
        """Delegate to :func:`core.comparison._table_property_comparator.compare_table_properties`.

        Kept as a method (not a free function) so internal callers and any
        ``comp._compare_table_properties(...)`` test access continue to work.
        """
        _compare_table_properties_impl(diff, expected, actual, dialect, self.log)

    def compare_schemas(
        self,
        expected_tables: List[Table],
        actual_tables: List[Table],
        dialect: str = "",
        schema_name: str = "public",
    ) -> SchemaDiff:
        """Compare lists of tables from two schemas.

        Args:
            expected_tables: Expected tables (from scripts)
            actual_tables: Actual tables (from database)
            dialect: SQL dialect for type normalization
            schema_name: Name of the schema being compared

        Returns:
            SchemaDiff object with comparison results
        """
        # Create lookup maps (case-insensitive)
        # Convert to Python strings to handle driver-returned objects
        expected_map = {str(t.name).lower(): t for t in expected_tables}
        actual_map = {str(t.name).lower(): t for t in actual_tables}

        # Find missing, extra, and common tables
        expected_names = set(expected_map.keys())
        actual_names = set(actual_map.keys())

        missing_table_names = list(expected_names - actual_names)
        extra_table_names = list(actual_names - expected_names)
        common_table_names = expected_names & actual_names

        # Compare common tables
        modified_tables = []
        for table_name in common_table_names:
            expected_table = expected_map[table_name]
            actual_table = actual_map[table_name]
            table_diff = self.compare_tables(expected_table, actual_table, dialect)
            if table_diff.has_diffs:
                modified_tables.append(table_diff)
                # Log details about what changed
                self.log.debug(
                    f"Table '{table_name}' has differences (severity: {table_diff.severity})"
                )
                if table_diff.modified_columns:
                    self.log.debug(
                        f"  Modified columns: {[c.object_name for c in table_diff.modified_columns]}"
                    )
                    for col_diff in table_diff.modified_columns:
                        self.log.debug(
                            f"    Column '{col_diff.object_name}' (severity: {col_diff.severity}):"
                        )
                        if col_diff.data_type_diff:
                            self.log.debug(f"      Data type: {col_diff.data_type_diff}")
                        if col_diff.nullable_diff:
                            self.log.debug(f"      Nullable: {col_diff.nullable_diff}")
                        if col_diff.default_diff:
                            self.log.debug(f"      Default: {col_diff.default_diff}")

        # Create SchemaDiff
        schema_diff = SchemaDiff(
            object_name=schema_name,
            schema_name=schema_name,
            missing_tables=missing_table_names,
            extra_tables=extra_table_names,
            modified_tables=modified_tables,
        )

        return schema_diff

    def _compare_columns(
        self, expected_columns: List[SqlColumn], actual_columns: List[SqlColumn], dialect: str
    ) -> Tuple[List[SqlColumn], List[SqlColumn], List[ColumnDiff]]:
        """Compare column lists and identify differences.

        Args:
            expected_columns: Expected columns list
            actual_columns: Actual columns list
            dialect: SQL dialect

        Returns:
            Tuple of (missing, extra, modified) where:
            - missing: Columns in expected but not in actual
            - extra: Columns in actual but not in expected
            - modified: ColumnDiff objects for columns with differences
        """
        # Create lookup maps (case-insensitive)
        # Convert to Python strings to handle driver-returned objects
        expected_map = {str(col.name).lower(): col for col in expected_columns}
        actual_map = {str(col.name).lower(): col for col in actual_columns}

        # Find missing, extra, and common columns
        expected_names = set(expected_map.keys())
        actual_names = set(actual_map.keys())

        missing = [expected_map[name] for name in (expected_names - actual_names)]
        extra = [actual_map[name] for name in (actual_names - expected_names)]

        # Compare common columns for modifications
        modified = []
        common_names = expected_names & actual_names
        for col_name in common_names:
            expected_col = expected_map[col_name]
            actual_col = actual_map[col_name]
            col_diff = self._compare_column_details(expected_col, actual_col, dialect)
            if col_diff is not None and col_diff.has_diffs:
                modified.append(col_diff)

        return missing, extra, modified

    def _compare_constraints(
        self,
        expected_constraints: List[SqlConstraint],
        actual_constraints: List[SqlConstraint],
        dialect: str,
    ) -> Tuple[List[SqlConstraint], List[SqlConstraint], List[ConstraintDiff]]:
        """Compare constraint lists and identify differences.

        Args:
            expected_constraints: Expected constraints list
            actual_constraints: Actual constraints list
            dialect: SQL dialect

        Returns:
            Tuple of (missing, extra, modified) where:
            - missing: Constraints in expected but not in actual
            - extra: Constraints in actual but not in expected
            - modified: ConstraintDiff objects for constraints with differences
        """

        # Apply filtering to both expected and actual constraints
        expected_constraints = TableComparator._filter_duplicate_unique_constraints(
            expected_constraints
        )
        actual_constraints = TableComparator._filter_duplicate_unique_constraints(
            actual_constraints
        )

        expected_map = {TableComparator._constraint_key(c): c for c in expected_constraints}
        actual_map = {TableComparator._constraint_key(c): c for c in actual_constraints}

        # Find missing, extra, and common constraints
        expected_keys = set(expected_map.keys())
        actual_keys = set(actual_map.keys())

        missing = [expected_map[key] for key in (expected_keys - actual_keys)]
        extra = [actual_map[key] for key in (actual_keys - expected_keys)]

        # Compare common constraints for modifications
        modified = []
        common_keys = expected_keys & actual_keys
        for key in common_keys:
            expected_const = expected_map[key]
            actual_const = actual_map[key]
            const_diff = self._compare_constraint_details(expected_const, actual_const)
            if const_diff is not None and const_diff.has_diffs:
                modified.append(const_diff)

        # Additional pass: Match constraints by explicit name if they have the same name
        # but different signatures (indicating a modification)
        # Convert to Python strings to handle driver-returned objects
        missing_by_name = {
            str(c.name).lower(): c
            for c in missing
            if c.name and not is_system_generated_constraint_name(c.name)
        }
        extra_by_name = {
            str(c.name).lower(): c
            for c in extra
            if c.name and not is_system_generated_constraint_name(c.name)
        }

        # Find constraints that exist in both missing and extra with the same name
        # These are likely modifications
        common_names = set(missing_by_name.keys()) & set(extra_by_name.keys())
        for name in common_names:
            expected_const = missing_by_name[name]
            actual_const = extra_by_name[name]

            # Only consider as modification if same type
            if expected_const.constraint_type == actual_const.constraint_type:
                const_diff = self._compare_constraint_details(expected_const, actual_const)
                if const_diff is not None and const_diff.has_diffs:
                    modified.append(const_diff)
                    # Remove from missing and extra lists
                    # Use safe name comparison (handle None names)
                    # Convert to Python strings to handle driver-returned objects
                    missing = [c for c in missing if not (c.name and str(c.name).lower() == name)]
                    extra = [c for c in extra if not (c.name and str(c.name).lower() == name)]

        return missing, extra, modified

    def _compare_column_details(
        self, expected_col: SqlColumn, actual_col: SqlColumn, dialect: str
    ) -> Optional[ColumnDiff]:
        """Compare two column objects in detail.

        Args:
            expected_col: Expected column
            actual_col: Actual column
            dialect: SQL dialect

        Returns:
            ColumnDiff if differences found, None otherwise
        """
        expected_data_type_raw = expected_col.data_type or ""
        actual_data_type_raw = actual_col.data_type or ""
        # Convert to string if not already (handles cases where data_type might be an int)
        if not isinstance(expected_data_type_raw, str):
            expected_data_type_raw = str(expected_data_type_raw)
        if not isinstance(actual_data_type_raw, str):
            actual_data_type_raw = str(actual_data_type_raw)
        expected_raw_type = expected_data_type_raw.upper()
        actual_data_type_raw.upper()

        # Check if both columns are identity/auto-increment columns
        expected_is_identity = (
            getattr(expected_col, "is_identity", False)
            or getattr(expected_col, "is_autoincrement", False)
            or expected_raw_type.startswith("SERIAL")
        )
        actual_is_identity = getattr(actual_col, "is_identity", False) or getattr(
            actual_col, "is_autoincrement", False
        )

        # Capture computed metadata, including cases encoded directly in the data type (e.g., PostgreSQL GENERATED ALWAYS AS)
        expected_is_computed_flag = getattr(expected_col, "is_computed", False)
        actual_is_computed_flag = getattr(actual_col, "is_computed", False)
        expected_computed_expression = getattr(expected_col, "computed_expression", None)
        actual_computed_expression = getattr(actual_col, "computed_expression", None)
        expected_computed_stored = getattr(expected_col, "computed_stored", False)
        actual_computed_stored = getattr(actual_col, "computed_stored", False)

        (
            expected_type_source,
            expected_is_computed_flag,
            expected_computed_expression,
            expected_computed_stored,
        ) = TableComparator._extract_generated_metadata(
            expected_data_type_raw,
            expected_is_computed_flag,
            expected_computed_expression,
            expected_computed_stored,
        )
        (
            actual_type_source,
            actual_is_computed_flag,
            actual_computed_expression,
            actual_computed_stored,
        ) = TableComparator._extract_generated_metadata(
            actual_data_type_raw,
            actual_is_computed_flag,
            actual_computed_expression,
            actual_computed_stored,
        )

        # For identity columns, compare base types without identity keywords
        if expected_is_identity and actual_is_identity:
            expected_base = extract_base_identity_type(expected_type_source, dialect)
            actual_base = extract_base_identity_type(actual_type_source, dialect)
            expected_type = self.type_normalizer.normalize(expected_base, dialect)
            actual_type = self.type_normalizer.normalize(actual_base, dialect)
        else:
            # Normal type comparison
            expected_type = self.type_normalizer.normalize(expected_type_source, dialect)
            actual_type = self.type_normalizer.normalize(actual_type_source, dialect)

        # Check for differences
        data_type_diff = None
        if not (expected_is_computed_flag and actual_is_computed_flag):
            # Convert to string if not already (handles cases where type might
            # be an int). These are column data types (VARCHAR, INT, ...),
            # not MigrationType.
            expected_type_str = str(expected_type) if expected_type else ""  # lint: allow-enum-str
            actual_type_str = str(actual_type) if actual_type else ""  # lint: allow-enum-str
            if expected_type_str.upper() != actual_type_str.upper():
                # Check if they're cross-dialect equivalents
                if not self.type_normalizer.are_equivalent(
                    expected_type_source, actual_type_source, dialect, dialect
                ):
                    if TableComparator._strip_schema(
                        expected_type_str
                    ) != TableComparator._strip_schema(actual_type_str):
                        data_type_diff = (expected_type, actual_type)

        nullable_diff = None
        if expected_col.nullable != actual_col.nullable:
            nullable_diff = (expected_col.nullable, actual_col.nullable)

        default_diff, sequence_default = self._compare_column_default_value(
            expected_col, actual_col, dialect
        )

        identity_diff = None
        if expected_is_identity != actual_is_identity:
            identity_diff = (expected_is_identity, actual_is_identity)
        if sequence_default:
            identity_diff = None

        computed_diff = None
        if expected_is_computed_flag != actual_is_computed_flag:
            computed_diff = (expected_is_computed_flag, actual_is_computed_flag)
        elif expected_is_computed_flag and actual_is_computed_flag:
            # Compare computed expressions if both are computed
            # Oracle stores virtual column expressions in default field if computed_expression is not populated
            expected_expr = self._normalize_expression(expected_computed_expression)
            actual_expr = self._normalize_expression(actual_computed_expression)
            # If actual doesn't have computed_expression but has default with expression-like content,
            # try to extract expression from default (Oracle-specific workaround)
            if not actual_expr and actual_col.default_value:
                # Check if default looks like a computed expression (contains operators, not a literal)
                default_val = actual_col.default_value
                if any(
                    op in default_val
                    for op in ["*", "+", "-", "/", "(", ")", "||", "AND", "OR", "CASE"]
                ):
                    actual_expr = self._normalize_expression(default_val)
            if expected_expr and actual_expr and expected_expr != actual_expr:
                computed_diff = (expected_computed_expression, actual_computed_expression)  # type: ignore[assignment]
            elif expected_expr and not actual_expr:
                # Expected has expression but actual doesn't (shouldn't happen if enrichment works)
                computed_diff = (expected_computed_expression, None)  # type: ignore[assignment]
            elif not expected_expr and actual_expr:
                # Actual has expression but expected doesn't (shouldn't happen)
                computed_diff = (None, actual_computed_expression)  # type: ignore[assignment]
            # Only suppress when actual IS computed but we couldn't introspect its expression
            # (dialects whose introspection omits expressions). Without
            # actual_is_computed_flag, we'd wrongly suppress when expected is
            # computed but actual is not (actual_expr naturally None).
            if (
                computed_diff
                and ProviderRegistry.get_quirks(dialect).computed_column_introspection_incomplete
                and actual_is_computed_flag
                and not actual_expr
            ):
                computed_diff = None

        # For identity columns, ignore nullable/default/identity flag differences
        # These are implicit properties of identity columns
        if expected_is_identity and actual_is_identity:
            nullable_diff = None
            default_diff = None
            identity_diff = None

        # For computed columns, ignore default differences (default is irrelevant for computed)
        # Expression differences are still reported when they differ after normalization
        if expected_is_computed_flag and actual_is_computed_flag:
            default_diff = None

        # Compare collation (diff-relevant - affects behavior)
        collation_diff = None
        expected_collation = getattr(expected_col, "collation", None)
        actual_collation = getattr(actual_col, "collation", None)
        # Normalize: None and empty string are equivalent
        expected_collation_norm = (
            str(expected_collation).strip().upper() if expected_collation else None
        )
        actual_collation_norm = str(actual_collation).strip().upper() if actual_collation else None
        if expected_collation_norm != actual_collation_norm:
            collation_diff = (expected_collation, actual_collation)

        # Create ColumnDiff if any differences found
        if any(
            [
                data_type_diff,
                nullable_diff,
                default_diff,
                identity_diff,
                computed_diff,
                collation_diff,
            ]
        ):
            self.log.info(f"[COMPARATOR] Column '{expected_col.name}' HAS DIFFERENCES:")
            self.log.info(f"[COMPARATOR]   data_type_diff={data_type_diff}")
            self.log.info(f"[COMPARATOR]   nullable_diff={nullable_diff}")
            self.log.info(f"[COMPARATOR]   default_diff={default_diff}")
            self.log.info(f"[COMPARATOR]   identity_diff={identity_diff}")
            self.log.info(f"[COMPARATOR]   computed_diff={computed_diff}")
            self.log.info(f"[COMPARATOR]   collation_diff={collation_diff}")

            return ColumnDiff(
                object_name=expected_col.name,
                column_name=expected_col.name,
                data_type_diff=data_type_diff,
                nullable_diff=nullable_diff,
                default_diff=default_diff,
                identity_diff=identity_diff,
                computed_diff=computed_diff,
                collation_diff=collation_diff,
            )

        return None

    def _compare_column_default_value(
        self,
        expected_col: SqlColumn,
        actual_col: SqlColumn,
        dialect: str,
    ) -> Tuple[Optional[Tuple[Any, Any]], bool]:
        """Compare default values of two columns.

        Returns:
            Tuple of (default_diff, is_sequence_default) where default_diff is
            None if no difference, or (expected_raw, actual_raw) if different.
        """
        _quirks = ProviderRegistry.get_quirks(dialect)
        default_diff = None
        expected_default = self._normalize_default_value(expected_col.default_value)
        actual_default = self._normalize_default_value(actual_col.default_value)
        if _quirks.table_column_default_has_on_update:
            expected_default = TableComparator._strip_on_update_clause(expected_default)
            actual_default = TableComparator._strip_on_update_clause(actual_default)

        if expected_default != actual_default:
            default_diff = (expected_col.default_value, actual_col.default_value)
            self.log.info(
                f"[COMPARATOR] Default value difference for column '{expected_col.name}':"
            )
            self.log.info(f"[COMPARATOR]   Expected (raw): '{expected_col.default_value}'")
            self.log.info(f"[COMPARATOR]   Actual (raw): '{actual_col.default_value}'")
            self.log.info(f"[COMPARATOR]   Expected (normalized): '{expected_default}'")
            self.log.info(f"[COMPARATOR]   Actual (normalized): '{actual_default}'")
        sequence_default = (
            _quirks.seq_uses_nextval_syntax
            and expected_default
            and actual_default
            # Convert to Python strings to handle driver-returned objects
            and str(expected_default).lower().startswith("nextval(")
            and str(actual_default).lower().startswith("nextval(")
        )
        if sequence_default:
            expected_seq_match = (
                re.search(r"nextval\('([^']+)'", expected_default, re.IGNORECASE)
                if expected_default is not None
                else None
            )
            actual_seq_match = (
                re.search(r"nextval\('([^']+)'", actual_default, re.IGNORECASE)
                if actual_default is not None
                else None
            )
            if expected_seq_match and actual_seq_match:
                expected_seq = expected_seq_match.group(1)
                actual_seq = actual_seq_match.group(1)
                if (
                    expected_seq == actual_seq
                    or expected_seq.split(".")[-1] == actual_seq.split(".")[-1]
                ):
                    default_diff = None

        return default_diff, bool(sequence_default)

    def _compare_constraint_details(
        self, expected_const: SqlConstraint, actual_const: SqlConstraint
    ) -> Optional[ConstraintDiff]:
        """Compare two constraint objects in detail.

        Args:
            expected_const: Expected constraint
            actual_const: Actual constraint

        Returns:
            ConstraintDiff if differences found, None otherwise
        """
        # Check for differences
        columns_diff = None
        # Convert to Python strings to handle driver-returned objects
        expected_cols = sorted([str(c).lower() for c in expected_const.column_names])
        actual_cols = sorted([str(c).lower() for c in actual_const.column_names])
        if expected_cols != actual_cols:
            columns_diff = (expected_const.column_names, actual_const.column_names)

        references_diff = None
        if expected_const.reference_table or actual_const.reference_table:
            expected_ref = expected_const.reference_table
            actual_ref = actual_const.reference_table
            # Convert to Python strings to handle driver-returned objects
            if str(expected_ref or "").lower() != str(actual_ref or "").lower():
                references_diff = (expected_ref, actual_ref)
            else:
                # Check reference columns
                # Convert to Python strings to handle driver-returned objects
                expected_ref_cols = sorted(
                    [str(c).lower() for c in (expected_const.reference_columns or [])]
                )
                actual_ref_cols = sorted(
                    [str(c).lower() for c in (actual_const.reference_columns or [])]
                )
                if expected_ref_cols != actual_ref_cols:
                    references_diff = (  # type: ignore[assignment]
                        expected_const.reference_columns,
                        actual_const.reference_columns,
                    )

        check_clause_diff = None
        # Only compare if at least one has a check_expression
        # If both are None/empty, they match (no check constraint)
        # If one is None and the other has a value, that's a difference
        expected_has_expr = (
            expected_const.check_expression and str(expected_const.check_expression).strip()
        )
        actual_has_expr = (
            actual_const.check_expression and str(actual_const.check_expression).strip()
        )

        if expected_has_expr or actual_has_expr:
            try:
                expected_expr = self._normalize_expression(expected_const.check_expression)
                actual_expr = self._normalize_expression(actual_const.check_expression)

                if expected_expr != actual_expr:
                    check_clause_diff = (
                        expected_const.check_expression,
                        actual_const.check_expression,
                    )
            except AttributeError as e:
                # Handle case where check_expression might be an integer or other non-string type
                self.log.warning(
                    f"Error normalizing check expression for constraint {expected_const.name or actual_const.name}: {e}. "
                    f"Expected type: {type(expected_const.check_expression)}, "
                    f"Actual type: {type(actual_const.check_expression)}"
                )
                # Convert to string and try again
                expected_expr = self._normalize_expression(
                    str(expected_const.check_expression)
                    if expected_const.check_expression
                    else None
                )
                actual_expr = self._normalize_expression(
                    str(actual_const.check_expression) if actual_const.check_expression else None
                )
                if expected_expr != actual_expr:
                    check_clause_diff = (
                        expected_const.check_expression,
                        actual_const.check_expression,
                    )
            except Exception as e:
                # Catch any other exceptions and log them
                self.log.error_with_exception(
                    f"Unexpected error comparing check expressions for constraint {expected_const.name or actual_const.name}: {e}",
                    e,
                )
                # Still set the diff if we can't compare
                check_clause_diff = (
                    expected_const.check_expression,
                    actual_const.check_expression,
                )

        # Compare constraint state (Oracle, SQL Server) - Diff-relevant
        enabled_diff = None
        expected_enabled = getattr(expected_const, "is_enabled", None)
        actual_enabled = getattr(actual_const, "is_enabled", None)
        if expected_enabled is not None and actual_enabled is not None:
            if expected_enabled != actual_enabled:
                enabled_diff = (expected_enabled, actual_enabled)

        validated_diff = None
        expected_validated = getattr(expected_const, "is_validated", None)
        actual_validated = getattr(actual_const, "is_validated", None)
        if expected_validated is not None and actual_validated is not None:
            if expected_validated != actual_validated:
                validated_diff = (expected_validated, actual_validated)

        # Compare deferrable properties (PostgreSQL, Oracle) - Diff-relevant
        deferrable_diff = None
        expected_deferrable = getattr(expected_const, "is_deferrable", None)
        actual_deferrable = getattr(actual_const, "is_deferrable", None)
        if expected_deferrable is not None and actual_deferrable is not None:
            if expected_deferrable != actual_deferrable:
                deferrable_diff = (expected_deferrable, actual_deferrable)

        initially_deferred_diff = None
        expected_initially_deferred = getattr(expected_const, "initially_deferred", None)
        actual_initially_deferred = getattr(actual_const, "initially_deferred", None)
        if expected_initially_deferred is not None and actual_initially_deferred is not None:
            if expected_initially_deferred != actual_initially_deferred:
                initially_deferred_diff = (expected_initially_deferred, actual_initially_deferred)

        # Create ConstraintDiff if any differences found
        if any(
            [
                columns_diff,
                references_diff,
                check_clause_diff,
                enabled_diff,
                validated_diff,
                deferrable_diff,
                initially_deferred_diff,
            ]
        ):
            constraint_name = expected_const.name or actual_const.name or "unnamed"
            return ConstraintDiff(
                object_name=constraint_name,
                constraint_name=constraint_name,
                columns_diff=columns_diff,
                references_diff=references_diff,
                check_clause_diff=check_clause_diff,
                enabled_diff=enabled_diff,
                validated_diff=validated_diff,
                deferrable_diff=deferrable_diff,
                initially_deferred_diff=initially_deferred_diff,
            )

        return None

    def _normalize_default_value(self, value: Optional[str]) -> Optional[str]:
        """Delegate to :func:`core.comparison._default_normalizer.normalize_default_value`.

        Kept as a method so test code accessing ``comp._normalize_default_value(...)``
        keeps working. The implementation lives in the helper module.
        """
        return _normalize_default_value_impl(value)

    def _normalize_expression(self, expr: Optional[str]) -> Optional[str]:
        """Delegate to :func:`core.comparison._default_normalizer.normalize_expression`.

        Kept as a method so test code accessing ``comp._normalize_expression(...)``
        keeps working. The implementation lives in the helper module.
        """
        return _normalize_expression_impl(expr)
