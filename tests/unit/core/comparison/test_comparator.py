"""Tests for ObjectComparator.

This module tests the SQL object comparison functionality across all
comparison scenarios.
"""

import pytest

from core.comparison.comparator import ObjectComparator
from core.comparison.diff_models import DiffSeverity
from core.comparison.type_normalizer import DataTypeNormalizer
from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.table_options import PostgresTableOptions, TableOptions
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view_options import MaterializedViewOptions, PostgresViewOptions, ViewOptions

pytestmark = [pytest.mark.unit]


class TestObjectComparator:
    """Test ObjectComparator class."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    # ========== Table Comparison - No Differences ==========

    def test_compare_identical_tables(self):
        """Test comparing two identical tables returns no diffs."""
        col1 = SqlColumn("id", "INTEGER", is_nullable=False)
        col2 = SqlColumn("name", "VARCHAR(100)", is_nullable=True)

        table1 = Table("users", columns=[col1, col2], dialect="postgresql")
        table2 = Table("users", columns=[col1, col2], dialect="postgresql")

        diff = self.comparator.compare_tables(table1, table2, "postgresql")

        assert diff.has_diffs is False
        assert len(diff.missing_columns) == 0
        assert len(diff.extra_columns) == 0
        assert len(diff.modified_columns) == 0

    # ========== Column Detection ==========

    def test_detect_missing_column(self):
        """Test detection of missing columns in actual table."""
        col1 = SqlColumn("id", "INTEGER")
        col2 = SqlColumn("name", "VARCHAR(100)")

        expected_table = Table("users", columns=[col1, col2], dialect="postgresql")
        actual_table = Table("users", columns=[col1], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert "name" in diff.missing_columns
        assert len(diff.extra_columns) == 0

    def test_detect_extra_column(self):
        """Test detection of extra columns in actual table."""
        col1 = SqlColumn("id", "INTEGER")
        col2 = SqlColumn("email", "VARCHAR(255)")

        expected_table = Table("users", columns=[col1], dialect="postgresql")
        actual_table = Table("users", columns=[col1, col2], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.missing_columns) == 0
        assert "email" in diff.extra_columns

    # ========== Column Modifications ==========

    def test_detect_data_type_change(self):
        """Test detection of data type changes."""
        expected_col = SqlColumn("age", "INTEGER")
        actual_col = SqlColumn("age", "VARCHAR(10)")

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        col_diff = diff.modified_columns[0]
        assert col_diff.column_name == "age"
        assert col_diff.data_type_diff is not None
        assert col_diff.severity == DiffSeverity.ERROR

    def test_detect_nullable_change(self):
        """Test detection of nullable changes."""
        expected_col = SqlColumn("email", "VARCHAR(255)", is_nullable=True)
        actual_col = SqlColumn("email", "VARCHAR(255)", is_nullable=False)

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        col_diff = diff.modified_columns[0]
        assert col_diff.nullable_diff == (True, False)
        assert col_diff.severity == DiffSeverity.WARNING

    def test_detect_default_value_change(self):
        """Test detection of default value changes."""
        expected_col = SqlColumn("status", "VARCHAR(20)", default_value="'active'")
        actual_col = SqlColumn("status", "VARCHAR(20)", default_value="'pending'")

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        col_diff = diff.modified_columns[0]
        assert col_diff.default_diff is not None
        assert col_diff.severity == DiffSeverity.WARNING

    def test_detect_identity_change(self):
        """Test detection of identity column changes."""
        expected_col = SqlColumn("id", "INTEGER", is_identity=True)
        actual_col = SqlColumn("id", "INTEGER", is_identity=False)

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        col_diff = diff.modified_columns[0]
        assert col_diff.identity_diff == (True, False)
        assert col_diff.severity == DiffSeverity.ERROR

    def test_detect_computed_column_change(self):
        """Test detection of computed column changes."""
        expected_col = SqlColumn(
            "full_name",
            "VARCHAR(200)",
            is_computed=True,
            computed_expression="first_name || ' ' || last_name",
        )
        actual_col = SqlColumn("full_name", "VARCHAR(200)", is_computed=False)

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        col_diff = diff.modified_columns[0]
        assert col_diff.computed_diff is not None

    # ========== Computed Column Expression Diffs (Story 13-6) ==========

    def test_computed_diff_detected_when_expressions_differ(self):
        """AC#1: Two computed columns with different expressions → computed_diff non-None."""
        expected_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a + b")
        actual_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a * b")
        expected_table = Table("t", columns=[expected_col], dialect="postgresql")
        actual_table = Table("t", columns=[actual_col], dialect="postgresql")
        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")
        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        assert diff.modified_columns[0].computed_diff is not None
        assert diff.modified_columns[0].computed_diff == ("a + b", "a * b")

    def test_computed_diff_none_when_expressions_identical(self):
        """AC#2: Two computed columns with same expression → computed_diff None."""
        expected_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a + b")
        actual_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a + b")
        expected_table = Table("t", columns=[expected_col], dialect="postgresql")
        actual_table = Table("t", columns=[actual_col], dialect="postgresql")
        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")
        # Identical computed expressions → no diff at all
        assert diff.has_diffs is False

    def test_computed_diff_none_when_expressions_normalized_equal(self):
        """AC#5: Expressions differing only by whitespace normalize to same → computed_diff None."""
        expected_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a  +  b")
        actual_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a + b")
        expected_table = Table("t", columns=[expected_col], dialect="postgresql")
        actual_table = Table("t", columns=[actual_col], dialect="postgresql")
        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")
        # _normalize_expression collapses whitespace → both normalize to "A + B" → no diff
        assert diff.has_diffs is False

    def test_default_diff_suppressed_for_computed_columns(self):
        """AC#3: Two computed columns with different defaults → default_diff None."""
        expected_col = SqlColumn(
            "calc",
            "INT",
            is_computed=True,
            computed_expression="a + b",
            default_value="10",
        )
        actual_col = SqlColumn(
            "calc",
            "INT",
            is_computed=True,
            computed_expression="a + b",
            default_value="20",
        )
        expected_table = Table("t", columns=[expected_col], dialect="postgresql")
        actual_table = Table("t", columns=[actual_col], dialect="postgresql")
        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")
        # default_diff must be suppressed for computed columns
        has_default_diff = any(cd.default_diff is not None for cd in diff.modified_columns)
        assert has_default_diff is False

    def test_computed_diff_detected_computed_vs_non_computed(self):
        """AC#4: Computed vs non-computed → computed_diff non-None (regression guard)."""
        expected_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a + b")
        actual_col = SqlColumn("calc", "INT", is_computed=False)
        expected_table = Table("t", columns=[expected_col], dialect="postgresql")
        actual_table = Table("t", columns=[actual_col], dialect="postgresql")
        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")
        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        assert diff.modified_columns[0].computed_diff is not None

    def test_computed_diff_none_for_non_computed_columns(self):
        """AC#6: Non-computed columns → computed_diff None."""
        expected_col = SqlColumn("name", "VARCHAR(100)", is_computed=False)
        actual_col = SqlColumn("name", "VARCHAR(100)", is_computed=False)
        expected_table = Table("t", columns=[expected_col], dialect="postgresql")
        actual_table = Table("t", columns=[actual_col], dialect="postgresql")
        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")
        # Identical non-computed columns → no diff at all
        assert diff.has_diffs is False

    def test_postgresql_suppresses_computed_diff_when_introspection_omits_expression(self):
        """PostgreSQL introspection can set is_computed without computed_expression."""
        expected_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a + b")
        actual_col = SqlColumn("calc", "INT", is_computed=True, computed_expression=None)

        expected_table = Table("t", columns=[expected_col], dialect="postgresql")
        actual_table = Table("t", columns=[actual_col], dialect="postgresql")
        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")
        assert diff.has_diffs is False

    def test_oracle_reports_computed_diff_when_expression_missing_without_default_workaround(self):
        """Oracle keeps (expr, None) unless default fills actual_expr — not gated on nextval quirks."""
        expected_col = SqlColumn("calc", "INT", is_computed=True, computed_expression="a + b")
        actual_col = SqlColumn("calc", "INT", is_computed=True, computed_expression=None)

        expected_table = Table("t", columns=[expected_col], dialect="oracle")
        actual_table = Table("t", columns=[actual_col], dialect="oracle")
        diff = self.comparator.compare_tables(expected_table, actual_table, "oracle")
        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        assert diff.modified_columns[0].computed_diff is not None

    # ========== Computed Column Oracle Workaround (Story 15-2) ==========

    def test_oracle_expression_in_default_same_as_expected_no_diff(self):
        """Oracle workaround: actual.computed_expression=None, default contains same expression → no diff."""
        expected_col = SqlColumn(
            "total", "NUMBER", is_computed=True, computed_expression="qty * price"
        )
        actual_col = SqlColumn("total", "NUMBER", is_computed=True)
        actual_col.default_value = "qty * price"
        actual_col.computed_expression = None

        expected_table = Table("orders", columns=[expected_col], dialect="oracle")
        actual_table = Table("orders", columns=[actual_col], dialect="oracle")
        diff = self.comparator.compare_tables(expected_table, actual_table, "oracle")
        assert diff.has_diffs is False
        assert len(diff.modified_columns) == 0

    def test_oracle_expression_in_default_different_from_expected_diff_detected(self):
        """Oracle workaround: actual.default contains different expression → diff detected."""
        expected_col = SqlColumn(
            "total", "NUMBER", is_computed=True, computed_expression="qty * price"
        )
        actual_col = SqlColumn("total", "NUMBER", is_computed=True)
        actual_col.default_value = "qty + price"
        actual_col.computed_expression = None

        expected_table = Table("orders", columns=[expected_col], dialect="oracle")
        actual_table = Table("orders", columns=[actual_col], dialect="oracle")
        diff = self.comparator.compare_tables(expected_table, actual_table, "oracle")
        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        assert diff.modified_columns[0].computed_diff is not None

    def test_oracle_literal_default_not_treated_as_expression(self):
        """Default without operator (e.g. '42') must NOT be interpreted as computed expression."""
        expected_col = SqlColumn(
            "total", "NUMBER", is_computed=True, computed_expression="qty * price"
        )
        actual_col = SqlColumn("total", "NUMBER", is_computed=True)
        actual_col.default_value = "42"  # Literal — no operator from the list
        actual_col.computed_expression = None

        expected_table = Table("orders", columns=[expected_col], dialect="oracle")
        actual_table = Table("orders", columns=[actual_col], dialect="oracle")
        diff = self.comparator.compare_tables(expected_table, actual_table, "oracle")
        # actual_expr stays None → computed_diff = (expected_expression, None)
        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        assert diff.modified_columns[0].computed_diff is not None

    def test_computed_stored_divergence_not_surfaced(self):
        """AC#2 contract: computed_stored (STORED vs VIRTUAL) difference is intentionally not compared.
        ColumnDiff has no field for it — divergence must not produce a computed_diff."""
        expected_col = SqlColumn(
            "total", "NUMBER", is_computed=True, computed_expression="qty * price"
        )
        actual_col = SqlColumn(
            "total", "NUMBER", is_computed=True, computed_expression="qty * price"
        )
        expected_col.computed_stored = True  # STORED
        actual_col.computed_stored = False  # VIRTUAL

        expected_table = Table("orders", columns=[expected_col], dialect="oracle")
        actual_table = Table("orders", columns=[actual_col], dialect="oracle")
        diff = self.comparator.compare_tables(expected_table, actual_table, "oracle")
        assert diff.has_diffs is False
        assert len(diff.modified_columns) == 0

    # ========== Type Normalization ==========

    def test_type_normalization_no_false_positive(self):
        """Test that equivalent types don't trigger false diffs."""
        # INT should normalize to INTEGER in PostgreSQL
        expected_col = SqlColumn("id", "INT")
        actual_col = SqlColumn("id", "INTEGER")

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        # Should not detect differences - types are equivalent
        assert len(diff.modified_columns) == 0
        assert diff.has_diffs is False

    def test_type_normalization_with_precision(self):
        """Test type normalization preserves precision."""
        expected_col = SqlColumn("price", "DECIMAL(10,2)")
        actual_col = SqlColumn("price", "DECIMAL(10,2)")

        expected_table = Table("products", columns=[expected_col], dialect="postgresql")
        actual_table = Table("products", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert len(diff.modified_columns) == 0
        assert diff.has_diffs is False

    def test_cross_dialect_type_equivalence(self):
        """Test cross-dialect type equivalence detection."""
        # TEXT (PostgreSQL) vs TEXT (PostgreSQL) should be equivalent
        # Even if normalized differently
        expected_col = SqlColumn("description", "TEXT")
        actual_col = SqlColumn("description", "TEXT")

        expected_table = Table("products", columns=[expected_col], dialect="postgresql")
        actual_table = Table("products", columns=[actual_col], dialect="postgresql")

        # Compare using PostgreSQL dialect
        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        # Should not detect differences - types are identical
        assert len(diff.modified_columns) == 0

    def test_different_types_not_equivalent(self):
        """Test that different types are detected as differences."""
        # TEXT vs VARCHAR should be detected as different
        expected_col = SqlColumn("description", "TEXT")
        actual_col = SqlColumn("description", "VARCHAR(1000)")

        expected_table = Table("products", columns=[expected_col], dialect="postgresql")
        actual_table = Table("products", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        # Should detect difference
        assert len(diff.modified_columns) == 1

    # ========== Constraint Comparison ==========

    def test_detect_missing_constraint(self):
        """Test detection of missing constraints."""
        col = SqlColumn("id", "INTEGER")
        pk_constraint = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_users", ["id"])

        expected_table = Table(
            "users", columns=[col], constraints=[pk_constraint], dialect="postgresql"
        )
        actual_table = Table("users", columns=[col], constraints=[], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.missing_constraints) == 1
        assert "pk_users" in diff.missing_constraints

    def test_detect_extra_constraint(self):
        """Test detection of extra constraints."""
        col = SqlColumn("email", "VARCHAR(255)")
        unique_constraint = SqlConstraint(ConstraintType.UNIQUE, "uk_email", ["email"])

        expected_table = Table("users", columns=[col], constraints=[], dialect="postgresql")
        actual_table = Table(
            "users", columns=[col], constraints=[unique_constraint], dialect="postgresql"
        )

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.extra_constraints) == 1
        assert "uk_email" in diff.extra_constraints

    def test_detect_constraint_column_change(self):
        """Test detection of constraint column changes.

        When constraint columns change, the improved comparator treats them as
        different constraints (missing + extra) because the constraint key includes
        the column signature. This is more accurate than treating it as a modification.
        """
        expected_constraint = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_users", ["id"])
        actual_constraint = SqlConstraint(
            ConstraintType.PRIMARY_KEY, "pk_users", ["id", "tenant_id"]
        )

        col1 = SqlColumn("id", "INTEGER")
        col2 = SqlColumn("tenant_id", "INTEGER")

        expected_table = Table(
            "users", columns=[col1, col2], constraints=[expected_constraint], dialect="postgresql"
        )
        actual_table = Table(
            "users", columns=[col1, col2], constraints=[actual_constraint], dialect="postgresql"
        )

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        # Constraint with different columns is treated as missing + extra (more accurate)
        # Constraint column change is treated as a modified constraint
        assert len(diff.modified_constraints) == 1
        mod = diff.modified_constraints[0]
        assert mod.columns_diff == (["id"], ["id", "tenant_id"]) or mod.columns_diff == (
            ["id"],
            ["id", "tenant_id"],
        )
        # No missing/extra when treated as modified
        assert len(diff.missing_constraints) == 0
        assert len(diff.extra_constraints) == 0

    def test_detect_foreign_key_reference_change(self):
        """Test detection of foreign key reference changes.

        When FK reference table changes, the improved comparator treats them as
        different constraints (missing + extra) because the constraint key includes
        the reference table. This is more accurate than treating it as a modification.
        """
        expected_fk = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            "fk_user_dept",
            ["dept_id"],
            reference_table="departments",
            reference_columns=["id"],
        )
        actual_fk = SqlConstraint(
            ConstraintType.FOREIGN_KEY,
            "fk_user_dept",
            ["dept_id"],
            reference_table="departments_new",
            reference_columns=["id"],
        )

        col = SqlColumn("dept_id", "INTEGER")

        expected_table = Table(
            "users", columns=[col], constraints=[expected_fk], dialect="postgresql"
        )
        actual_table = Table("users", columns=[col], constraints=[actual_fk], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        # FK with different reference table is treated as missing + extra (more accurate)
        # FK reference table change is treated as a modified constraint
        assert len(diff.modified_constraints) == 1
        mod = diff.modified_constraints[0]
        assert mod.references_diff == ("departments", "departments_new")
        # No missing/extra when treated as modified
        assert len(diff.missing_constraints) == 0
        assert len(diff.extra_constraints) == 0

    def test_detect_check_constraint_change(self):
        """Test detection of check constraint changes."""
        expected_check = SqlConstraint(
            ConstraintType.CHECK, "chk_age", ["age"], check_expression="age >= 18"
        )
        actual_check = SqlConstraint(
            ConstraintType.CHECK, "chk_age", ["age"], check_expression="age >= 21"
        )

        col = SqlColumn("age", "INTEGER")

        expected_table = Table(
            "users", columns=[col], constraints=[expected_check], dialect="postgresql"
        )
        actual_table = Table(
            "users", columns=[col], constraints=[actual_check], dialect="postgresql"
        )

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.modified_constraints) == 1
        const_diff = diff.modified_constraints[0]
        assert const_diff.check_clause_diff is not None

    def test_detect_column_collation_change(self):
        """Test detection of column collation changes."""
        expected_col = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_unicode_ci")
        actual_col = SqlColumn("name", "VARCHAR(100)", collation="utf8mb4_general_ci")

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.modified_columns) == 1
        col_diff = diff.modified_columns[0]
        assert col_diff.collation_diff == ("utf8mb4_unicode_ci", "utf8mb4_general_ci")

    def test_detect_constraint_enabled_change(self):
        """Test detection of constraint enabled state changes."""
        expected_const = SqlConstraint(
            ConstraintType.UNIQUE, "uk_email", ["email"], is_enabled=True
        )
        actual_const = SqlConstraint(ConstraintType.UNIQUE, "uk_email", ["email"], is_enabled=False)

        col = SqlColumn("email", "VARCHAR(255)")

        expected_table = Table(
            "users", columns=[col], constraints=[expected_const], dialect="oracle"
        )
        actual_table = Table("users", columns=[col], constraints=[actual_const], dialect="oracle")

        diff = self.comparator.compare_tables(expected_table, actual_table, "oracle")

        assert diff.has_diffs is True
        assert len(diff.modified_constraints) == 1
        const_diff = diff.modified_constraints[0]
        assert const_diff.enabled_diff == (True, False)
        assert const_diff.severity == DiffSeverity.ERROR

    def test_detect_constraint_validated_change(self):
        """Test detection of constraint validated state changes."""
        expected_const = SqlConstraint(
            ConstraintType.UNIQUE, "uk_email", ["email"], is_validated=True
        )
        actual_const = SqlConstraint(
            ConstraintType.UNIQUE, "uk_email", ["email"], is_validated=False
        )

        col = SqlColumn("email", "VARCHAR(255)")

        expected_table = Table(
            "users", columns=[col], constraints=[expected_const], dialect="oracle"
        )
        actual_table = Table("users", columns=[col], constraints=[actual_const], dialect="oracle")

        diff = self.comparator.compare_tables(expected_table, actual_table, "oracle")

        assert diff.has_diffs is True
        assert len(diff.modified_constraints) == 1
        const_diff = diff.modified_constraints[0]
        assert const_diff.validated_diff == (True, False)
        assert const_diff.severity == DiffSeverity.ERROR

    def test_detect_constraint_deferrable_change(self):
        """Test detection of constraint deferrable state changes."""
        expected_const = SqlConstraint(
            ConstraintType.UNIQUE, "uk_email", ["email"], is_deferrable=True
        )
        actual_const = SqlConstraint(
            ConstraintType.UNIQUE, "uk_email", ["email"], is_deferrable=False
        )

        col = SqlColumn("email", "VARCHAR(255)")

        expected_table = Table(
            "users", columns=[col], constraints=[expected_const], dialect="postgresql"
        )
        actual_table = Table(
            "users", columns=[col], constraints=[actual_const], dialect="postgresql"
        )

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert len(diff.modified_constraints) == 1
        const_diff = diff.modified_constraints[0]
        assert const_diff.deferrable_diff == (True, False)
        assert const_diff.severity == DiffSeverity.WARNING

    def test_detect_table_inheritance_change(self):
        """Test detection of table inheritance changes (PostgreSQL)."""
        expected_table = Table.from_options(
            "child_table",
            schema="public",
            dialect="postgresql",
            options=TableOptions(
                postgres=PostgresTableOptions(inherits=["parent_table1", "parent_table2"])
            ),
        )
        actual_table = Table.from_options(
            "child_table",
            schema="public",
            dialect="postgresql",
            options=TableOptions(postgres=PostgresTableOptions(inherits=["parent_table1"])),
        )

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert diff.inherits_changed == (["parent_table1", "parent_table2"], ["parent_table1"])

    def test_detect_view_security_definer_change(self):
        """Test detection of view security_definer changes."""
        from core.sql_model.view import View

        expected = View.from_options(
            name="secure_view",
            query="SELECT * FROM data",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_definer=False)),
        )
        actual = View.from_options(
            name="secure_view",
            query="SELECT * FROM data",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_definer=True)),
        )

        diff = self.comparator.compare_views(expected, actual, "postgresql")
        assert diff is not None
        assert diff.security_definer_changed == (False, True)
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_view_security_invoker_change(self):
        """Test detection of view security_invoker changes."""
        from core.sql_model.view import View

        expected = View.from_options(
            name="secure_view",
            query="SELECT * FROM data",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_invoker=False)),
        )
        actual = View.from_options(
            name="secure_view",
            query="SELECT * FROM data",
            dialect="postgresql",
            options=ViewOptions(postgres=PostgresViewOptions(security_invoker=True)),
        )

        diff = self.comparator.compare_views(expected, actual, "postgresql")
        assert diff is not None
        assert diff.security_invoker_changed == (False, True)
        assert diff.severity == DiffSeverity.ERROR

    # ========== Case Sensitivity ==========

    def test_case_insensitive_column_comparison(self):
        """Test that column comparison is case-insensitive."""
        expected_col = SqlColumn("UserName", "VARCHAR(100)")
        actual_col = SqlColumn("username", "VARCHAR(100)")

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        # Should match despite case difference
        assert len(diff.missing_columns) == 0
        assert len(diff.extra_columns) == 0
        assert diff.has_diffs is False

    # ========== Schema Comparison ==========

    def test_compare_schemas_no_differences(self):
        """Test comparing schemas with identical tables."""
        col = SqlColumn("id", "INTEGER")
        table1 = Table("users", columns=[col], dialect="postgresql")
        table2 = Table("orders", columns=[col], dialect="postgresql")

        expected_tables = [table1, table2]
        actual_tables = [table1, table2]

        diff = self.comparator.compare_schemas(
            expected_tables, actual_tables, "postgresql", "public"
        )

        assert diff.has_diffs is False
        assert len(diff.missing_tables) == 0
        assert len(diff.extra_tables) == 0
        assert len(diff.modified_tables) == 0

    def test_detect_missing_table_in_schema(self):
        """Test detection of missing tables in schema."""
        col = SqlColumn("id", "INTEGER")
        table1 = Table("users", columns=[col], dialect="postgresql")
        table2 = Table("orders", columns=[col], dialect="postgresql")

        expected_tables = [table1, table2]
        actual_tables = [table1]

        diff = self.comparator.compare_schemas(
            expected_tables, actual_tables, "postgresql", "public"
        )

        assert diff.has_diffs is True
        assert "orders" in diff.missing_tables
        assert len(diff.extra_tables) == 0

    def test_detect_extra_table_in_schema(self):
        """Test detection of extra tables in schema."""
        col = SqlColumn("id", "INTEGER")
        table1 = Table("users", columns=[col], dialect="postgresql")
        table2 = Table("audit_log", columns=[col], dialect="postgresql")

        expected_tables = [table1]
        actual_tables = [table1, table2]

        diff = self.comparator.compare_schemas(
            expected_tables, actual_tables, "postgresql", "public"
        )

        assert diff.has_diffs is True
        assert len(diff.missing_tables) == 0
        assert "audit_log" in diff.extra_tables

    def test_detect_modified_table_in_schema(self):
        """Test detection of modified tables in schema."""
        expected_col = SqlColumn("id", "INTEGER")
        actual_col = SqlColumn("id", "VARCHAR(50)")

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        expected_tables = [expected_table]
        actual_tables = [actual_table]

        diff = self.comparator.compare_schemas(
            expected_tables, actual_tables, "postgresql", "public"
        )

        assert diff.has_diffs is True
        assert len(diff.modified_tables) == 1
        table_diff = diff.modified_tables[0]
        assert table_diff.table_name == "users"
        assert len(table_diff.modified_columns) == 1

    # ========== Default Value Normalization ==========

    def test_normalize_null_default_values(self):
        """Test normalization of NULL default values."""
        # Different representations of NULL should be treated as equivalent
        expected_col = SqlColumn("status", "VARCHAR(20)", default_value="NULL")
        actual_col = SqlColumn("status", "VARCHAR(20)", default_value=None)

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        # Should not detect difference - both are NULL
        assert len(diff.modified_columns) == 0

    def test_normalize_boolean_default_values(self):
        """Test normalization of boolean default values."""
        # TRUE and 1 should be treated as equivalent
        expected_col = SqlColumn("active", "BOOLEAN", default_value="TRUE")
        actual_col = SqlColumn("active", "BOOLEAN", default_value="1")

        expected_table = Table("users", columns=[expected_col], dialect="postgresql")
        actual_table = Table("users", columns=[actual_col], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        # Should not detect difference - both are TRUE
        assert len(diff.modified_columns) == 0

    # ========== Expression Normalization ==========

    def test_normalize_whitespace_in_expressions(self):
        """Test that expressions with different whitespace are treated as equal."""
        expected_check = SqlConstraint(
            ConstraintType.CHECK, "chk_amount", ["amount"], check_expression="amount   >   0"
        )
        actual_check = SqlConstraint(
            ConstraintType.CHECK, "chk_amount", ["amount"], check_expression="amount > 0"
        )

        col = SqlColumn("amount", "DECIMAL(10,2)")

        expected_table = Table(
            "transactions", columns=[col], constraints=[expected_check], dialect="postgresql"
        )
        actual_table = Table(
            "transactions", columns=[col], constraints=[actual_check], dialect="postgresql"
        )

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        # Should not detect difference - expressions are equivalent
        assert len(diff.modified_constraints) == 0

    # ========== Complex Scenarios ==========

    def test_multiple_differences_in_single_table(self):
        """Test detection of multiple types of differences in one table."""
        # Expected table
        expected_cols = [
            SqlColumn("id", "INTEGER", is_nullable=False),
            SqlColumn("name", "VARCHAR(100)"),
            SqlColumn("age", "INTEGER"),
        ]
        expected_pk = SqlConstraint(ConstraintType.PRIMARY_KEY, "pk_users", ["id"])
        expected_table = Table(
            "users", columns=expected_cols, constraints=[expected_pk], dialect="postgresql"
        )

        # Actual table - missing column, modified column, missing constraint
        actual_cols = [
            SqlColumn("id", "VARCHAR(50)", is_nullable=False),  # Type changed
            SqlColumn("name", "VARCHAR(100)"),
            # age column missing
        ]
        actual_table = Table("users", columns=actual_cols, constraints=[], dialect="postgresql")

        diff = self.comparator.compare_tables(expected_table, actual_table, "postgresql")

        assert diff.has_diffs is True
        assert "age" in diff.missing_columns
        assert len(diff.modified_columns) == 1  # id type change
        assert "pk_users" in diff.missing_constraints

    def test_schema_with_multiple_table_differences(self):
        """Test schema comparison with multiple modified tables."""
        # Table 1: Missing column
        table1_expected = Table(
            "users",
            columns=[SqlColumn("id", "INTEGER"), SqlColumn("name", "VARCHAR(100)")],
            dialect="postgresql",
        )
        table1_actual = Table("users", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql")

        # Table 2: Modified column
        table2_expected = Table(
            "orders", columns=[SqlColumn("id", "INTEGER")], dialect="postgresql"
        )
        table2_actual = Table(
            "orders", columns=[SqlColumn("id", "VARCHAR(50)")], dialect="postgresql"
        )

        expected_tables = [table1_expected, table2_expected]
        actual_tables = [table1_actual, table2_actual]

        diff = self.comparator.compare_schemas(
            expected_tables, actual_tables, "postgresql", "public"
        )

        assert diff.has_diffs is True
        assert len(diff.modified_tables) == 2
        assert diff.get_total_diff_count() > 0


class TestViewComparison:
    """Test view comparison functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_views(self):
        """Test comparing two identical views returns no diffs."""
        from core.sql_model.view import View

        view1 = View(
            name="user_summary",
            query="SELECT id, name FROM users",
            schema="public",
            dialect="postgresql",
        )
        view2 = View(
            name="user_summary",
            query="SELECT id, name FROM users",
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_views(view1, view2, "postgresql")

        assert diff is None  # No differences

    def test_detect_view_definition_change(self):
        """Test detection of view definition changes."""
        from core.sql_model.view import View

        expected_view = View(
            name="user_summary",
            query="SELECT id, name FROM users",
            schema="public",
            dialect="postgresql",
        )
        actual_view = View(
            name="user_summary",
            query="SELECT id, name, email FROM users",
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.definition_changed is True
        assert diff.expected_definition == "SELECT id, name FROM users"
        assert diff.actual_definition == "SELECT id, name, email FROM users"
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_materialized_view_change(self):
        """Test detection of materialized view status changes."""
        from core.sql_model.view import View

        expected_view = View(
            name="user_summary",
            query="SELECT id, name FROM users",
            schema="public",
            dialect="postgresql",
            materialized=False,
        )
        actual_view = View(
            name="user_summary",
            query="SELECT id, name FROM users",
            schema="public",
            dialect="postgresql",
            materialized=True,
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.materialized_changed == (False, True)
        assert diff.severity == DiffSeverity.WARNING

    def test_view_definition_normalization(self):
        """Test that view definitions are normalized for comparison."""
        from core.sql_model.view import View

        # Same query with different whitespace and case
        view1 = View(
            name="user_summary",
            query="SELECT id, name FROM users",
            schema="public",
            dialect="postgresql",
        )
        view2 = View(
            name="user_summary",
            query="  SELECT  ID,  NAME  FROM  USERS  ",
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_views(view1, view2, "postgresql")

        # Should be considered identical after normalization
        assert diff is None

    def test_view_with_comments_ignored(self):
        """Test that SQL comments in view definitions are ignored."""
        from core.sql_model.view import View

        view1 = View(
            name="user_summary",
            query="SELECT id, name FROM users",
            schema="public",
            dialect="postgresql",
        )
        view2 = View(
            name="user_summary",
            query="-- This is a comment\nSELECT id, name FROM users",
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_views(view1, view2, "postgresql")

        # Should be considered identical after comment removal
        assert diff is None

    # ========== Materialized View Property Tests ==========

    def test_materialized_view_is_populated_changed(self):
        """Test detection of is_populated status changes."""
        from core.sql_model.view import View

        expected_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="public",
            dialect="postgresql",
            materialized=True,
            options=ViewOptions(materialized_view=MaterializedViewOptions(is_populated=True)),
        )
        actual_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="public",
            dialect="postgresql",
            materialized=True,
            options=ViewOptions(materialized_view=MaterializedViewOptions(is_populated=False)),
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.is_populated_changed == (True, False)
        assert diff.severity == DiffSeverity.WARNING

    def test_materialized_view_refresh_method_changed(self):
        """Test detection of refresh_method changes (Oracle)."""
        from core.sql_model.view import View

        expected_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(materialized_view=MaterializedViewOptions(refresh_method="FAST")),
        )
        actual_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(refresh_method="COMPLETE")
            ),
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "oracle")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.refresh_method_changed == ("FAST", "COMPLETE")
        assert diff.severity == DiffSeverity.WARNING

    def test_materialized_view_refresh_method_case_insensitive(self):
        """Test that refresh_method comparison is case-insensitive."""
        from core.sql_model.view import View

        expected_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(materialized_view=MaterializedViewOptions(refresh_method="fast")),
        )
        actual_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(materialized_view=MaterializedViewOptions(refresh_method="FAST")),
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "oracle")

        # Should be considered identical (case-insensitive)
        assert diff is None

    def test_materialized_view_refresh_mode_changed(self):
        """Test detection of refresh_mode changes (Oracle)."""
        from core.sql_model.view import View

        expected_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(refresh_mode="ON DEMAND")
            ),
        )
        actual_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(refresh_mode="ON COMMIT")
            ),
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "oracle")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.refresh_mode_changed == ("ON DEMAND", "ON COMMIT")
        assert diff.severity == DiffSeverity.WARNING

    def test_materialized_view_fast_refreshable_changed(self):
        """Test detection of fast_refreshable changes (Oracle)."""
        from core.sql_model.view import View

        expected_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(materialized_view=MaterializedViewOptions(fast_refreshable=True)),
        )
        actual_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(materialized_view=MaterializedViewOptions(fast_refreshable=False)),
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "oracle")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.fast_refreshable_changed == (True, False)
        assert diff.severity == DiffSeverity.WARNING

    def test_materialized_view_multiple_property_changes(self):
        """Test detection of multiple materialized view property changes."""
        from core.sql_model.view import View

        expected_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(
                    is_populated=True,
                    refresh_method="FAST",
                    refresh_mode="ON DEMAND",
                    fast_refreshable=True,
                )
            ),
        )
        actual_view = View.from_options(
            name="mv_sales",
            query="SELECT * FROM sales",
            schema="hr",
            dialect="oracle",
            materialized=True,
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(
                    is_populated=False,
                    refresh_method="COMPLETE",
                    refresh_mode="ON COMMIT",
                    fast_refreshable=False,
                )
            ),
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "oracle")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.is_populated_changed == (True, False)
        assert diff.refresh_method_changed == ("FAST", "COMPLETE")
        assert diff.refresh_mode_changed == ("ON DEMAND", "ON COMMIT")
        assert diff.fast_refreshable_changed == (True, False)
        assert diff.severity == DiffSeverity.WARNING

    def test_materialized_view_properties_only_compared_when_both_materialized(self):
        """Test that refresh properties are only compared when both views are materialized."""
        from core.sql_model.view import View

        # One materialized, one not
        expected_view = View(
            name="v_sales",
            query="SELECT * FROM sales",
            schema="public",
            dialect="postgresql",
            materialized=False,
        )
        actual_view = View.from_options(
            name="v_sales",
            query="SELECT * FROM sales",
            schema="public",
            dialect="postgresql",
            materialized=True,
            options=ViewOptions(
                materialized_view=MaterializedViewOptions(
                    is_populated=True, refresh_method="MANUAL"
                )
            ),
        )

        diff = self.comparator.compare_views(expected_view, actual_view, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        # Only materialized status should be flagged, not refresh properties
        assert diff.materialized_changed == (False, True)
        assert diff.is_populated_changed is None
        assert diff.refresh_method_changed is None


class TestIndexComparison:
    """Test index comparison functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_indexes(self):
        """Test comparing two identical indexes returns no diffs."""
        from core.sql_model.index import Index

        index1 = Index(
            name="idx_users_email",
            table_name="users",
            columns=["email"],
            unique=False,
            schema="public",
            dialect="postgresql",
        )
        index2 = Index(
            name="idx_users_email",
            table_name="users",
            columns=["email"],
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(index1, index2, "postgresql")

        assert diff is None  # No differences

    def test_detect_index_column_change(self):
        """Test detection of index column changes."""
        from core.sql_model.index import Index

        expected_index = Index(
            name="idx_users_name",
            table_name="users",
            columns=["name"],
            unique=False,
            schema="public",
            dialect="postgresql",
        )
        actual_index = Index(
            name="idx_users_name",
            table_name="users",
            columns=["name", "email"],
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.columns_changed is True
        assert diff.expected_columns == ["name"]
        assert diff.actual_columns == ["name", "email"]
        assert diff.severity == DiffSeverity.ERROR  # columns_changed is breaking

    def test_detect_index_uniqueness_change(self):
        """Test detection of index uniqueness changes."""
        from core.sql_model.index import Index

        expected_index = Index(
            name="idx_users_email",
            table_name="users",
            columns=["email"],
            unique=False,
            schema="public",
            dialect="postgresql",
        )
        actual_index = Index(
            name="idx_users_email",
            table_name="users",
            columns=["email"],
            unique=True,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.uniqueness_changed == (False, True)
        assert diff.severity == DiffSeverity.ERROR  # uniqueness_changed is breaking

    def test_detect_index_type_change(self):
        """Test detection of index type changes."""
        from core.sql_model.index import Index

        expected_index = Index(
            name="idx_users_data",
            table_name="users",
            columns=["data"],
            unique=False,
            type="BTREE",
            schema="public",
            dialect="postgresql",
        )
        actual_index = Index(
            name="idx_users_data",
            table_name="users",
            columns=["data"],
            unique=False,
            type="HASH",
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "postgresql")

        assert diff is not None
        assert diff.has_diffs is True
        assert diff.type_changed == ("btree", "hash")  # Normalized to lowercase
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_sqlserver_include_column_change(self):
        """SQL Server INCLUDE columns should be compared."""
        from core.sql_model.index import Index

        expected_index = Index(
            name="idx_orders_user_id",
            table_name="orders",
            columns=["user_id"],
            include_columns=["created_at"],
            unique=False,
            schema="dbo",
            dialect="sqlserver",
        )
        actual_index = Index(
            name="idx_orders_user_id",
            table_name="orders",
            columns=["user_id"],
            include_columns=["updated_at"],
            unique=False,
            schema="dbo",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_indexes(expected_index, actual_index, "sqlserver")

        assert diff is not None
        assert diff.include_columns_changed == (["created_at"], ["updated_at"])
        assert diff.severity == DiffSeverity.WARNING

    def test_index_column_order_matters(self):
        """Test that index column order is significant."""
        from core.sql_model.index import Index

        index1 = Index(
            name="idx_users_name_email",
            table_name="users",
            columns=["name", "email"],
            unique=False,
            schema="public",
            dialect="postgresql",
        )
        index2 = Index(
            name="idx_users_name_email",
            table_name="users",
            columns=["email", "name"],
            unique=False,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_indexes(index1, index2, "postgresql")

        # Column order matters for indexes
        assert diff is not None
        assert diff.columns_changed is True
        assert diff.expected_columns == ["name", "email"]
        assert diff.actual_columns == ["email", "name"]


class TestSequenceComparison:
    """Test sequence comparison functionality."""

    def setup_method(self):
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_sequences(self):
        from core.sql_model.sequence import Sequence

        seq1 = Sequence(
            name="user_id_seq",
            schema="public",
            start_with=1,
            increment_by=1,
            min_value=1,
            max_value=999999,
            cycle=False,
            dialect="postgresql",
        )
        seq2 = Sequence(
            name="user_id_seq",
            schema="public",
            start_with=1,
            increment_by=1,
            min_value=1,
            max_value=999999,
            cycle=False,
            dialect="postgresql",
        )

        diff = self.comparator.compare_sequences(seq1, seq2, "postgresql")
        assert diff is None

    def test_detect_sequence_start_increment_cycle_changes(self):
        from core.comparison.diff_models import DiffSeverity
        from core.sql_model.sequence import Sequence

        expected = Sequence(
            name="order_seq",
            schema="public",
            start_with=1,
            increment_by=1,
            cycle=False,
            dialect="postgresql",
        )
        actual = Sequence(
            name="order_seq",
            schema="public",
            start_with=10,
            increment_by=5,
            cycle=True,
            dialect="postgresql",
        )

        diff = self.comparator.compare_sequences(expected, actual, "postgresql")
        assert diff is not None
        assert diff.start_value_changed == (1, 10)
        assert diff.increment_changed == (1, 5)
        assert diff.cycle_changed == (False, True)
        assert diff.severity == DiffSeverity.INFO

    def test_detect_sequence_min_max_changes(self):
        from core.sql_model.sequence import Sequence

        expected = Sequence(
            name="inv_seq",
            schema="public",
            min_value=1,
            max_value=1000,
            dialect="postgresql",
        )
        actual = Sequence(
            name="inv_seq",
            schema="public",
            min_value=10,
            max_value=2000,
            dialect="postgresql",
        )

        diff = self.comparator.compare_sequences(expected, actual, "postgresql")
        assert diff is not None
        assert diff.min_value_changed == (1, 10)
        assert diff.max_value_changed == (1000, 2000)


class TestTriggerComparison:
    """Test trigger comparison functionality."""

    def setup_method(self):
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_triggers(self):
        from core.sql_model.trigger import Trigger

        trg1 = Trigger(
            name="trg_users_ai",
            table_name="users",
            schema="public",
            timing="AFTER",
            events=["INSERT"],
            definition="EXECUTE FUNCTION audit_insert()",
            dialect="postgresql",
        )
        trg2 = Trigger(
            name="trg_users_ai",
            table_name="users",
            schema="public",
            timing="AFTER",
            events=["INSERT"],
            definition="EXECUTE FUNCTION audit_insert()",
            dialect="postgresql",
        )

        diff = self.comparator.compare_triggers(trg1, trg2, "postgresql")
        assert diff is None

    def test_detect_trigger_timing_and_event_changes(self):
        from core.sql_model.trigger import Trigger

        expected = Trigger(
            name="trg_users_upd",
            table_name="users",
            schema="public",
            timing="BEFORE",
            events=["UPDATE"],
            definition="EXECUTE FUNCTION audit_update()",
            dialect="postgresql",
        )
        actual = Trigger(
            name="trg_users_upd",
            table_name="users",
            schema="public",
            timing="AFTER",
            events=["INSERT"],
            definition="EXECUTE FUNCTION audit_update()",
            dialect="postgresql",
        )

        diff = self.comparator.compare_triggers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.timing_changed == ("before", "after")
        assert diff.event_changed == (["update"], ["insert"]) or diff.event_changed == (
            "update",
            "insert",
        )

    def test_detect_trigger_definition_change(self):
        from core.sql_model.trigger import Trigger

        expected = Trigger(
            name="trg_users_del",
            table_name="users",
            schema="public",
            timing="AFTER",
            events=["DELETE"],
            definition="EXECUTE FUNCTION audit_delete_v1()",
            dialect="postgresql",
        )
        actual = Trigger(
            name="trg_users_del",
            table_name="users",
            schema="public",
            timing="AFTER",
            events=["DELETE"],
            definition="EXECUTE FUNCTION audit_delete_v2()",
            dialect="postgresql",
        )

        diff = self.comparator.compare_triggers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.definition_changed is True

    def test_detect_trigger_function_and_when_clause_changes(self):
        from core.sql_model.trigger import Trigger

        expected = Trigger(
            name="trg_users_fn",
            table_name="users",
            schema="public",
            timing="AFTER",
            events=["INSERT", "UPDATE"],
            definition="EXECUTE FUNCTION audit_fn_v1()",
            function_schema="public",
            function_name="audit_fn_v1",
            function_arguments="integer",
            when_clause="OLD.value IS DISTINCT FROM NEW.value",
            is_constraint_trigger=True,
            constraint_deferrable=False,
            constraint_initially_deferred=False,
            dialect="postgresql",
        )
        actual = Trigger(
            name="trg_users_fn",
            table_name="users",
            schema="public",
            timing="AFTER",
            events=["INSERT", "UPDATE"],
            definition="EXECUTE FUNCTION audit_fn_v2(text)",
            function_schema="audit",
            function_name="audit_fn_v2",
            function_arguments="integer, text",
            when_clause=None,
            is_constraint_trigger=True,
            constraint_deferrable=True,
            constraint_initially_deferred=True,
            dialect="postgresql",
        )

        diff = self.comparator.compare_triggers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.function_changed == ("audit_fn_v1", "audit_fn_v2")
        assert diff.function_schema_changed == ("public", "audit")
        assert diff.function_arguments_changed == ("integer", "integer, text")
        assert diff.when_clause_changed == (
            "OLD.VALUE IS DISTINCT FROM NEW.VALUE",
            "",
        )
        assert diff.constraint_deferrable_changed == (False, True)
        assert diff.constraint_initially_deferred_changed == (False, True)


class TestProcedureComparison:
    """Test procedure comparison functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_procedures(self):
        """Test comparing two identical procedures returns no diffs."""
        from core.sql_model.procedure import Parameter, Procedure

        params = [Parameter("p_id", "INTEGER", "IN"), Parameter("p_name", "VARCHAR", "IN")]
        proc1 = Procedure(
            name="get_user",
            schema="public",
            parameters=params,
            body="SELECT * FROM users WHERE id = p_id",
            dialect="postgresql",
        )
        proc2 = Procedure(
            name="get_user",
            schema="public",
            parameters=params,
            body="SELECT * FROM users WHERE id = p_id",
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(proc1, proc2, "postgresql")
        assert diff is None

    def test_detect_procedure_parameter_change(self):
        """Test detection of procedure parameter changes."""
        from core.sql_model.procedure import Parameter, Procedure

        params1 = [Parameter("p_id", "INTEGER", "IN")]
        params2 = [Parameter("p_id", "INTEGER", "IN"), Parameter("p_name", "VARCHAR", "IN")]

        expected = Procedure(
            name="get_user",
            schema="public",
            parameters=params1,
            body="SELECT * FROM users WHERE id = p_id",
            dialect="postgresql",
        )
        actual = Procedure(
            name="get_user",
            schema="public",
            parameters=params2,
            body="SELECT * FROM users WHERE id = p_id",
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(expected, actual, "postgresql")
        assert diff is not None
        assert diff.parameters_changed is True
        assert len(diff.expected_parameters) == 1
        assert len(diff.actual_parameters) == 2

    def test_detect_procedure_definition_change(self):
        """Test detection of procedure body/definition changes."""
        from core.sql_model.procedure import Parameter, Procedure

        params = [Parameter("p_id", "INTEGER", "IN")]

        expected = Procedure(
            name="get_user",
            schema="public",
            parameters=params,
            body="SELECT * FROM users WHERE id = p_id",
            dialect="postgresql",
        )
        actual = Procedure(
            name="get_user",
            schema="public",
            parameters=params,
            body="SELECT id, name FROM users WHERE id = p_id",
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(expected, actual, "postgresql")
        assert diff is not None
        assert diff.definition_changed is True

    def test_detect_procedure_security_definer_change(self):
        """Test detection of SECURITY DEFINER changes for procedures."""
        from core.sql_model.procedure import Procedure

        expected = Procedure(
            name="do_work",
            schema="public",
            body="BEGIN NULL; END;",
            security_definer=False,
            dialect="postgresql",
        )
        actual = Procedure(
            name="do_work",
            schema="public",
            body="BEGIN NULL; END;",
            security_definer=True,
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(expected, actual, "postgresql")
        assert diff is not None
        assert diff.security_definer_changed == (False, True)

    def test_detect_parameter_default_value_change(self):
        """Test detection of parameter default value changes."""
        from core.sql_model.procedure import Parameter, Procedure

        expected = Procedure(
            name="test_proc",
            schema="public",
            parameters=[
                Parameter("param1", "INTEGER", direction="IN", default_value="10"),
                Parameter("param2", "VARCHAR(100)", direction="IN"),
            ],
            body="BEGIN NULL; END;",
            dialect="postgresql",
        )
        actual = Procedure(
            name="test_proc",
            schema="public",
            parameters=[
                Parameter("param1", "INTEGER", direction="IN", default_value="20"),
                Parameter("param2", "VARCHAR(100)", direction="IN"),
            ],
            body="BEGIN NULL; END;",
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(expected, actual, "postgresql")
        assert diff is not None
        assert diff.parameters_changed is True
        # Verify that default values are included in parameter comparison
        assert "param1" in str(diff.expected_parameters[0])
        assert "param1" in str(diff.actual_parameters[0])

    def test_detect_procedure_volatility_change(self):
        """Test detection of procedure volatility changes."""
        from core.sql_model.procedure import Procedure

        expected = Procedure(
            name="do_work",
            schema="public",
            body="BEGIN NULL; END;",
            volatility="STABLE",
            dialect="postgresql",
        )
        actual = Procedure(
            name="do_work",
            schema="public",
            body="BEGIN NULL; END;",
            volatility="VOLATILE",
            dialect="postgresql",
        )

        diff = self.comparator.compare_procedures(expected, actual, "postgresql")
        assert diff is not None
        assert diff.volatility_changed == ("STABLE", "VOLATILE")


class TestFunctionComparison:
    """Test function comparison functionality."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_functions(self):
        """Test comparing two identical functions returns no diffs."""
        from core.sql_model.procedure import Parameter, Procedure

        params = [Parameter("p_id", "INTEGER", "IN")]
        func1 = Procedure(
            name="get_user_name",
            schema="public",
            parameters=params,
            body="RETURN (SELECT name FROM users WHERE id = p_id)",
            is_function=True,
            return_type="VARCHAR",
            dialect="postgresql",
        )
        func2 = Procedure(
            name="get_user_name",
            schema="public",
            parameters=params,
            body="RETURN (SELECT name FROM users WHERE id = p_id)",
            is_function=True,
            return_type="VARCHAR",
            dialect="postgresql",
        )

        diff = self.comparator.compare_functions(func1, func2, "postgresql")
        assert diff is None

    def test_detect_function_return_type_change(self):
        """Test detection of function return type changes."""
        from core.sql_model.procedure import Parameter, Procedure

        params = [Parameter("p_id", "INTEGER", "IN")]

        expected = Procedure(
            name="get_user_name",
            schema="public",
            parameters=params,
            body="RETURN (SELECT name FROM users WHERE id = p_id)",
            is_function=True,
            return_type="VARCHAR",
            dialect="postgresql",
        )
        actual = Procedure(
            name="get_user_name",
            schema="public",
            parameters=params,
            body="RETURN (SELECT name FROM users WHERE id = p_id)",
            is_function=True,
            return_type="TEXT",
            dialect="postgresql",
        )

        diff = self.comparator.compare_functions(expected, actual, "postgresql")
        assert diff is not None
        assert diff.return_type_changed == ("VARCHAR", "TEXT")

    def test_detect_function_parameter_and_definition_change(self):
        """Test detection of both parameter and definition changes in functions."""
        from core.sql_model.procedure import Parameter, Procedure

        params1 = [Parameter("p_id", "INTEGER", "IN")]
        params2 = [Parameter("p_user_id", "BIGINT", "IN")]

        expected = Procedure(
            name="calc_total",
            schema="public",
            parameters=params1,
            body="RETURN p_id * 100",
            is_function=True,
            return_type="INTEGER",
            dialect="postgresql",
        )
        actual = Procedure(
            name="calc_total",
            schema="public",
            parameters=params2,
            body="RETURN p_user_id * 200",
            is_function=True,
            return_type="INTEGER",
            dialect="postgresql",
        )

        diff = self.comparator.compare_functions(expected, actual, "postgresql")
        assert diff is not None
        assert diff.parameters_changed is True
        assert diff.definition_changed is True

    def test_detect_function_volatility_change(self):
        """Test detection of function volatility changes."""
        from core.sql_model.procedure import Procedure

        expected = Procedure(
            name="calc_value",
            schema="public",
            body="RETURN 1;",
            is_function=True,
            return_type="INTEGER",
            volatility="IMMUTABLE",
            dialect="postgresql",
        )
        actual = Procedure(
            name="calc_value",
            schema="public",
            body="RETURN 1;",
            is_function=True,
            return_type="INTEGER",
            volatility="STABLE",
            dialect="postgresql",
        )

        diff = self.comparator.compare_functions(expected, actual, "postgresql")
        assert diff is not None
        assert diff.volatility_changed == ("IMMUTABLE", "STABLE")

    def test_detect_function_security_definer_change(self):
        """Test detection of function SECURITY DEFINER changes."""
        from core.sql_model.procedure import Procedure

        expected = Procedure(
            name="calc_value",
            schema="public",
            body="RETURN 1;",
            is_function=True,
            return_type="INTEGER",
            security_definer=False,
            dialect="postgresql",
        )
        actual = Procedure(
            name="calc_value",
            schema="public",
            body="RETURN 1;",
            is_function=True,
            return_type="INTEGER",
            security_definer=True,
            dialect="postgresql",
        )

        diff = self.comparator.compare_functions(expected, actual, "postgresql")
        assert diff is not None
        assert diff.security_definer_changed == (False, True)

    # ========== Synonym Comparison ==========

    def test_compare_identical_synonyms(self):
        """Test comparing two identical synonyms returns no diffs."""
        syn1 = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="public",
            target_schema="hr",
            dialect="postgresql",
        )
        syn2 = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="public",
            target_schema="hr",
            dialect="postgresql",
        )

        diff = self.comparator.compare_synonyms(syn1, syn2, "postgresql")
        assert diff is None

    def test_detect_synonym_target_changed(self):
        """Test detection of synonym target object change."""
        expected = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="public",
            target_schema="hr",
            dialect="postgresql",
        )
        actual = Synonym(
            name="emp_syn",
            target_object="emp_table",
            schema="public",
            target_schema="hr",
            dialect="postgresql",
        )

        diff = self.comparator.compare_synonyms(expected, actual, "postgresql")
        assert diff is not None
        assert diff.target_changed == ("employees", "emp_table")
        assert diff.expected_target == '"hr"."employees"'
        assert diff.actual_target == '"hr"."emp_table"'
        assert diff.severity == DiffSeverity.ERROR  # target_changed is breaking

    def test_detect_synonym_target_schema_changed(self):
        """Test detection of synonym target schema change."""
        expected = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="public",
            target_schema="hr",
            dialect="postgresql",
        )
        actual = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="public",
            target_schema="finance",
            dialect="postgresql",
        )

        diff = self.comparator.compare_synonyms(expected, actual, "postgresql")
        assert diff is not None
        assert diff.target_schema_changed == ("hr", "finance")
        assert diff.severity == DiffSeverity.ERROR  # target_schema_changed is breaking

    def test_detect_synonym_target_database_changed_sqlserver(self):
        """Test detection of synonym target database change (SQL Server)."""
        expected = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="dbo",
            target_database="db1",
            dialect="sqlserver",
        )
        actual = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="dbo",
            target_database="db2",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_synonyms(expected, actual, "sqlserver")
        assert diff is not None
        assert diff.target_database_changed == ("db1", "db2")
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_synonym_db_link_changed_oracle(self):
        """Test detection of synonym database link change (Oracle)."""
        expected = Synonym(
            name="EMP_SYN",
            target_object="EMPLOYEES",
            schema="HR",
            db_link="LINK1",
            dialect="oracle",
        )
        actual = Synonym(
            name="EMP_SYN",
            target_object="EMPLOYEES",
            schema="HR",
            db_link="LINK2",
            dialect="oracle",
        )

        diff = self.comparator.compare_synonyms(expected, actual, "oracle")
        assert diff is not None
        assert diff.db_link_changed == ("LINK1", "LINK2")
        assert diff.severity == DiffSeverity.WARNING

    def test_synonym_case_normalization_oracle(self):
        """Test synonym comparison with Oracle case normalization (uppercase)."""
        expected = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="hr",
            dialect="oracle",
        )
        actual = Synonym(
            name="EMP_SYN",
            target_object="EMPLOYEES",
            schema="HR",
            dialect="oracle",
        )

        # Should match because Oracle normalizes to uppercase
        diff = self.comparator.compare_synonyms(expected, actual, "oracle")
        assert diff is None

    def test_synonym_case_normalization_postgresql(self):
        """Test synonym comparison with PostgreSQL case normalization (lowercase)."""
        expected = Synonym(
            name="EMP_SYN",
            target_object="EMPLOYEES",
            schema="PUBLIC",
            dialect="postgresql",
        )
        actual = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="public",
            dialect="postgresql",
        )

        # Should match because PostgreSQL normalizes to lowercase
        diff = self.comparator.compare_synonyms(expected, actual, "postgresql")
        assert diff is None

    def test_synonym_multiple_changes(self):
        """Test synonym with multiple changes."""
        expected = Synonym(
            name="emp_syn",
            target_object="employees",
            schema="public",
            target_schema="hr",
            dialect="postgresql",
        )
        actual = Synonym(
            name="emp_syn",
            target_object="emp_table",
            schema="public",
            target_schema="finance",
            dialect="postgresql",
        )

        diff = self.comparator.compare_synonyms(expected, actual, "postgresql")
        assert diff is not None
        assert diff.target_changed == ("employees", "emp_table")
        assert diff.target_schema_changed == ("hr", "finance")
        assert diff.severity == DiffSeverity.ERROR  # target/target_schema are breaking

    def test_synonym_quoted_vs_unquoted_identifiers_postgresql(self):
        """Test that quoted and unquoted identifiers are treated as equivalent (PostgreSQL)."""
        # PostgreSQL: unquoted identifiers are folded to lowercase
        expected = Synonym(
            name="emp_syn",
            target_object="Employees",  # Unquoted, will be lowercase
            schema="public",
            target_schema="HR",  # Unquoted, will be lowercase
            dialect="postgresql",
        )
        actual = Synonym(
            name="emp_syn",
            target_object='"employees"',  # Quoted, explicit lowercase
            schema="public",
            target_schema='"hr"',  # Quoted, explicit lowercase
            dialect="postgresql",
        )

        # Should match because both normalize to lowercase
        diff = self.comparator.compare_synonyms(expected, actual, "postgresql")
        assert diff is None

    def test_synonym_quoted_vs_unquoted_identifiers_oracle(self):
        """Test that quoted and unquoted identifiers are treated as equivalent (Oracle)."""
        # Oracle: unquoted identifiers are folded to uppercase
        expected = Synonym(
            name="EMP_SYN",
            target_object="employees",  # Unquoted, will be uppercase
            schema="HR",
            target_schema="hr",  # Unquoted, will be uppercase
            dialect="oracle",
        )
        actual = Synonym(
            name="EMP_SYN",
            target_object='"EMPLOYEES"',  # Quoted, explicit uppercase
            schema="HR",
            target_schema='"HR"',  # Quoted, explicit uppercase
            dialect="oracle",
        )

        # Should match because both normalize to uppercase
        diff = self.comparator.compare_synonyms(expected, actual, "oracle")
        assert diff is None

    def test_synonym_quoted_different_case_postgresql(self):
        """Test that quoted identifiers with different case are detected as different (PostgreSQL)."""
        # PostgreSQL: quoted identifiers are case-sensitive
        expected = Synonym(
            name="emp_syn",
            target_object='"Employees"',  # Quoted, stays "Employees"
            schema="public",
            dialect="postgresql",
        )
        actual = Synonym(
            name="emp_syn",
            target_object='"employees"',  # Quoted, stays "employees"
            schema="public",
            dialect="postgresql",
        )

        # Should differ because "Employees" != "employees" (both quoted, case-sensitive)
        diff = self.comparator.compare_synonyms(expected, actual, "postgresql")
        assert diff is not None
        assert diff.target_changed is not None

    def test_synonym_quoted_different_case_oracle(self):
        """Test that quoted identifiers with different case are detected as different (Oracle)."""
        # Oracle: quoted identifiers are case-sensitive
        expected = Synonym(
            name="EMP_SYN",
            target_object='"EMPLOYEES"',  # Quoted, stays "EMPLOYEES"
            schema="HR",
            dialect="oracle",
        )
        actual = Synonym(
            name="EMP_SYN",
            target_object='"employees"',  # Quoted, stays "employees"
            schema="HR",
            dialect="oracle",
        )

        # Should differ because "EMPLOYEES" != "employees" (both quoted, case-sensitive)
        diff = self.comparator.compare_synonyms(expected, actual, "oracle")
        assert diff is not None
        assert diff.target_changed is not None

    # ========== User-Defined Type Comparison Tests ==========

    def test_compare_identical_udts(self):
        """Test comparing two identical UDTs returns None."""
        expected = UserDefinedType(
            name="address_type",
            schema="public",
            type_category="COMPOSITE",
            attributes=[{"name": "street", "type": "VARCHAR(100)"}],
        )
        actual = UserDefinedType(
            name="address_type",
            schema="public",
            type_category="COMPOSITE",
            attributes=[{"name": "street", "type": "VARCHAR(100)"}],
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is None

    def test_detect_udt_type_category_changed(self):
        """Test detecting type category change (breaking change - ERROR)."""
        expected = UserDefinedType(
            name="test_type",
            schema="public",
            type_category="COMPOSITE",
        )
        actual = UserDefinedType(
            name="test_type",
            schema="public",
            type_category="ENUM",
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is not None
        assert diff.type_category_changed == ("COMPOSITE", "ENUM")
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_udt_base_type_changed(self):
        """Test detecting base type change (breaking change - ERROR)."""
        expected = UserDefinedType(
            name="email_type",
            schema="public",
            type_category="DOMAIN",
            base_type="VARCHAR(100)",
        )
        actual = UserDefinedType(
            name="email_type",
            schema="public",
            type_category="DOMAIN",
            base_type="VARCHAR(255)",
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is not None
        assert diff.base_type_changed == ("VARCHAR(100)", "VARCHAR(255)")
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_udt_attributes_changed(self):
        """Test detecting attribute changes in composite types (WARNING)."""
        expected = UserDefinedType(
            name="address_type",
            schema="public",
            type_category="COMPOSITE",
            attributes=[{"name": "street", "type": "VARCHAR(100)"}],
        )
        actual = UserDefinedType(
            name="address_type",
            schema="public",
            type_category="COMPOSITE",
            attributes=[{"name": "street", "type": "VARCHAR(200)"}],
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is not None
        assert diff.attributes_changed is True
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_udt_enum_values_changed(self):
        """Test detecting enum value changes (WARNING)."""
        expected = UserDefinedType(
            name="status_enum",
            schema="public",
            type_category="ENUM",
            enum_values=["active", "inactive"],
        )
        actual = UserDefinedType(
            name="status_enum",
            schema="public",
            type_category="ENUM",
            enum_values=["active", "inactive", "pending"],
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is not None
        assert diff.enum_values_changed is True
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_udt_definition_changed(self):
        """Test detecting definition changes (WARNING)."""
        expected = UserDefinedType(
            name="custom_type",
            schema="public",
            type_category="DOMAIN",
            definition="CREATE DOMAIN custom_type AS INTEGER CHECK (VALUE > 0)",
        )
        actual = UserDefinedType(
            name="custom_type",
            schema="public",
            type_category="DOMAIN",
            definition="CREATE DOMAIN custom_type AS INTEGER CHECK (VALUE >= 0)",
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is not None
        assert diff.definition_changed is True
        assert diff.severity == DiffSeverity.WARNING

    def test_udt_type_category_case_insensitive(self):
        """Test type category comparison is case-insensitive."""
        expected = UserDefinedType(
            name="test_type",
            schema="public",
            type_category="composite",
        )
        actual = UserDefinedType(
            name="test_type",
            schema="public",
            type_category="COMPOSITE",
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is None

    def test_udt_base_type_case_insensitive(self):
        """Test base type comparison is case-insensitive."""
        expected = UserDefinedType(
            name="email_type",
            schema="public",
            type_category="DOMAIN",
            base_type="varchar(100)",
        )
        actual = UserDefinedType(
            name="email_type",
            schema="public",
            type_category="DOMAIN",
            base_type="VARCHAR(100)",
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is None

    def test_udt_enum_values_order_independent(self):
        """Test enum value comparison is order-independent (sorted)."""
        expected = UserDefinedType(
            name="status_enum",
            schema="public",
            type_category="ENUM",
            enum_values=["inactive", "active"],
        )
        actual = UserDefinedType(
            name="status_enum",
            schema="public",
            type_category="ENUM",
            enum_values=["active", "inactive"],
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is None

    def test_udt_multiple_breaking_changes(self):
        """Test multiple breaking changes result in ERROR severity."""
        expected = UserDefinedType(
            name="test_type",
            schema="public",
            type_category="DOMAIN",
            base_type="INTEGER",
        )
        actual = UserDefinedType(
            name="test_type",
            schema="public",
            type_category="DISTINCT",
            base_type="BIGINT",
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is not None
        assert diff.type_category_changed is not None
        assert diff.base_type_changed is not None
        assert diff.severity == DiffSeverity.ERROR

    def test_udt_only_compares_attributes_for_composite(self):
        """Test attributes are only compared when both types are composite."""
        expected = UserDefinedType(
            name="test_type",
            schema="public",
            type_category="COMPOSITE",
            attributes=[{"name": "field1", "type": "INTEGER"}],
        )
        actual = UserDefinedType(
            name="test_type",
            schema="public",
            type_category="COMPOSITE",
            attributes=[{"name": "field2", "type": "VARCHAR"}],
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is not None
        assert diff.attributes_changed is True

    def test_udt_only_compares_enum_values_for_enum(self):
        """Test enum values are only compared when both types are enum."""
        expected = UserDefinedType(
            name="test_enum",
            schema="public",
            type_category="ENUM",
            enum_values=["a", "b"],
        )
        actual = UserDefinedType(
            name="test_enum",
            schema="public",
            type_category="ENUM",
            enum_values=["a", "b", "c"],
        )

        diff = self.comparator.compare_user_defined_types(expected, actual, "postgresql")
        assert diff is not None
        assert diff.enum_values_changed is True


class TestPackageComparison:
    """Test package comparison functionality (Oracle)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_packages(self):
        """Test comparing two identical packages returns no diffs."""
        from core.sql_model.package import Package

        spec = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
            PROCEDURE update_salary(p_id NUMBER, p_salary NUMBER);
        END;"""

        body = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2 IS
            BEGIN
                RETURN 'John Doe';
            END;
            
            PROCEDURE update_salary(p_id NUMBER, p_salary NUMBER) IS
            BEGIN
                UPDATE employees SET salary = p_salary WHERE id = p_id;
            END;
        END;"""

        pkg1 = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec,
            body=body,
            dialect="oracle",
        )
        pkg2 = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec,
            body=body,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(pkg1, pkg2, "oracle")
        assert diff is None

    def test_detect_package_spec_change(self):
        """Test detection of package specification changes."""
        from core.sql_model.package import Package

        spec1 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
        END;"""

        spec2 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
            PROCEDURE update_salary(p_id NUMBER, p_salary NUMBER);
        END;"""

        body = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2 IS
            BEGIN
                RETURN 'John Doe';
            END;
        END;"""

        expected = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec1,
            body=body,
            dialect="oracle",
        )
        actual = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec2,
            body=body,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(expected, actual, "oracle")
        assert diff is not None
        assert diff.spec_changed is True
        assert diff.body_changed is False
        assert diff.severity == DiffSeverity.ERROR  # spec_changed is breaking

    def test_detect_package_body_change(self):
        """Test detection of package body changes."""
        from core.sql_model.package import Package

        spec = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
        END;"""

        body1 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2 IS
            BEGIN
                RETURN 'John Doe';
            END;
        END;"""

        body2 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2 IS
            BEGIN
                RETURN 'Jane Smith';
            END;
        END;"""

        expected = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec,
            body=body1,
            dialect="oracle",
        )
        actual = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec,
            body=body2,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(expected, actual, "oracle")
        assert diff is not None
        assert diff.spec_changed is False
        assert diff.body_changed is True
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_package_both_spec_and_body_change(self):
        """Test detection when both package spec and body change."""
        from core.sql_model.package import Package

        spec1 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
        END;"""

        spec2 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
            PROCEDURE update_salary(p_id NUMBER, p_salary NUMBER);
        END;"""

        body1 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2 IS
            BEGIN
                RETURN 'John Doe';
            END;
        END;"""

        body2 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2 IS
            BEGIN
                RETURN 'Jane Smith';
            END;
            
            PROCEDURE update_salary(p_id NUMBER, p_salary NUMBER) IS
            BEGIN
                UPDATE employees SET salary = p_salary WHERE id = p_id;
            END;
        END;"""

        expected = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec1,
            body=body1,
            dialect="oracle",
        )
        actual = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec2,
            body=body2,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(expected, actual, "oracle")
        assert diff is not None
        assert diff.spec_changed is True
        assert diff.body_changed is True
        assert diff.severity == DiffSeverity.ERROR  # spec_changed is breaking

    def test_package_spec_only_comparison(self):
        """Test comparing packages with only spec (no body)."""
        from core.sql_model.package import Package

        spec1 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
        END;"""

        spec2 = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
            PROCEDURE update_salary(p_id NUMBER, p_salary NUMBER);
        END;"""

        expected = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec1,
            body=None,
            dialect="oracle",
        )
        actual = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec2,
            body=None,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(expected, actual, "oracle")
        assert diff is not None
        assert diff.spec_changed is True
        assert diff.body_changed is False

    def test_package_normalization_whitespace_and_comments(self):
        """Test that packages with different whitespace and comments are considered identical."""
        from core.sql_model.package import Package

        spec1 = """AS
            -- This is a comment
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
        END;"""

        spec2 = """AS
            FUNCTION   get_employee_name(  p_id   NUMBER  )   RETURN   VARCHAR2;
        END;"""

        body1 = """AS
            /* Multi-line
               comment */
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2 IS
            BEGIN
                RETURN 'John Doe';  -- Inline comment
            END;
        END;"""

        body2 = """AS
            FUNCTION   get_employee_name(p_id   NUMBER)   RETURN   VARCHAR2   IS
            BEGIN
                RETURN   'John Doe';
            END;
        END;"""

        expected = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec1,
            body=body1,
            dialect="oracle",
        )
        actual = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec2,
            body=body2,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(expected, actual, "oracle")
        assert diff is None

    def test_package_case_insensitive_comparison_oracle(self):
        """Test that Oracle packages are compared case-insensitively for keywords."""
        from core.sql_model.package import Package

        spec1 = """as
            function get_employee_name(p_id number) return varchar2;
        end;"""

        spec2 = """AS
            FUNCTION GET_EMPLOYEE_NAME(P_ID NUMBER) RETURN VARCHAR2;
        END;"""

        body1 = """as
            function get_employee_name(p_id number) return varchar2 is
            begin
                return 'John Doe';
            end;
        end;"""

        body2 = """AS
            FUNCTION GET_EMPLOYEE_NAME(P_ID NUMBER) RETURN VARCHAR2 IS
            BEGIN
                RETURN 'John Doe';
            END;
        END;"""

        expected = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec1,
            body=body1,
            dialect="oracle",
        )
        actual = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec2,
            body=body2,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(expected, actual, "oracle")
        assert diff is None

    def test_package_with_null_spec_and_body(self):
        """Test comparing packages where spec or body is None."""
        from core.sql_model.package import Package

        # Both have None values
        pkg1 = Package(
            name="emp_pkg",
            schema="hr",
            spec=None,
            body=None,
            dialect="oracle",
        )
        pkg2 = Package(
            name="emp_pkg",
            schema="hr",
            spec=None,
            body=None,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(pkg1, pkg2, "oracle")
        assert diff is None

    def test_package_one_has_spec_other_doesnt(self):
        """Test comparing packages where one has spec and the other doesn't."""
        from core.sql_model.package import Package

        spec = """AS
            FUNCTION get_employee_name(p_id NUMBER) RETURN VARCHAR2;
        END;"""

        expected = Package(
            name="emp_pkg",
            schema="hr",
            spec=spec,
            body=None,
            dialect="oracle",
        )
        actual = Package(
            name="emp_pkg",
            schema="hr",
            spec=None,
            body=None,
            dialect="oracle",
        )

        diff = self.comparator.compare_packages(expected, actual, "oracle")
        assert diff is not None
        assert diff.spec_changed is True


class TestExtensionComparison:
    """Test extension comparison functionality (PostgreSQL)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_extensions(self):
        """Test comparing two identical extensions returns no diffs."""
        from core.sql_model.extension import Extension

        ext1 = Extension(
            name="postgis",
            version="3.3.0",
            schema="public",
            dialect="postgresql",
        )
        ext2 = Extension(
            name="postgis",
            version="3.3.0",
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_extensions(ext1, ext2, "postgresql")
        assert diff is None

    def test_detect_extension_version_change(self):
        """Test detection of extension version changes."""
        from core.sql_model.extension import Extension

        expected = Extension(
            name="postgis",
            version="3.3.0",
            schema="public",
            dialect="postgresql",
        )
        actual = Extension(
            name="postgis",
            version="3.4.0",
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_extensions(expected, actual, "postgresql")
        assert diff is not None
        assert diff.version_changed == ("3.3.0", "3.4.0")
        assert diff.expected_version == "3.3.0"
        assert diff.actual_version == "3.4.0"
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_extension_schema_change(self):
        """Test detection of extension schema changes."""
        from core.sql_model.extension import Extension

        expected = Extension(
            name="postgis",
            version="3.3.0",
            schema="public",
            dialect="postgresql",
        )
        actual = Extension(
            name="postgis",
            version="3.3.0",
            schema="extensions",
            dialect="postgresql",
        )

        diff = self.comparator.compare_extensions(expected, actual, "postgresql")
        assert diff is not None
        assert diff.schema_changed == ("public", "extensions")
        assert diff.severity == DiffSeverity.ERROR  # schema_changed is breaking

    def test_extension_version_and_schema_change(self):
        """Test detection of both version and schema changes."""
        from core.sql_model.extension import Extension

        expected = Extension(
            name="pg_trgm",
            version="1.5",
            schema="public",
            dialect="postgresql",
        )
        actual = Extension(
            name="pg_trgm",
            version="1.6",
            schema="extensions",
            dialect="postgresql",
        )

        diff = self.comparator.compare_extensions(expected, actual, "postgresql")
        assert diff is not None
        assert diff.version_changed == ("1.5", "1.6")
        assert diff.schema_changed == ("public", "extensions")
        assert diff.severity == DiffSeverity.ERROR  # schema_changed is breaking

    def test_extension_with_null_versions(self):
        """Test comparing extensions where version is None."""
        from core.sql_model.extension import Extension

        ext1 = Extension(
            name="uuid-ossp",
            version=None,
            schema="public",
            dialect="postgresql",
        )
        ext2 = Extension(
            name="uuid-ossp",
            version=None,
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_extensions(ext1, ext2, "postgresql")
        assert diff is None

    def test_extension_case_insensitive_postgresql(self):
        """Test that extension names are compared case-insensitively in PostgreSQL."""
        from core.sql_model.extension import Extension

        expected = Extension(
            name="PostGIS",
            version="3.3.0",
            schema="PUBLIC",
            dialect="postgresql",
        )
        actual = Extension(
            name="postgis",
            version="3.3.0",
            schema="public",
            dialect="postgresql",
        )

        diff = self.comparator.compare_extensions(expected, actual, "postgresql")
        assert diff is None


class TestEventComparison:
    """Test event comparison functionality (MySQL)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_events(self):
        """Test comparing two identical events returns no diffs."""
        from core.sql_model.event import Event

        evt1 = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )
        evt2 = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )

        diff = self.comparator.compare_events(evt1, evt2, "mysql")
        assert diff is None

    def test_detect_event_definition_change(self):
        """Test detection of event definition changes."""
        from core.sql_model.event import Event

        expected = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )
        actual = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 60 DAY",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )

        diff = self.comparator.compare_events(expected, actual, "mysql")
        assert diff is not None
        assert diff.definition_changed is True
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_event_schedule_change(self):
        """Test detection of event schedule changes."""
        from core.sql_model.event import Event

        expected = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )
        actual = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 HOUR",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )

        diff = self.comparator.compare_events(expected, actual, "mysql")
        assert diff is not None
        assert diff.schedule_changed == ("EVERY 1 DAY", "EVERY 1 HOUR")
        assert diff.severity == DiffSeverity.WARNING

    def test_detect_event_enabled_status_change(self):
        """Test detection of event enabled status changes."""
        from core.sql_model.event import Event

        expected = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )
        actual = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 DAY",
            enabled=False,
            event_type="RECURRING",
            dialect="mysql",
        )

        diff = self.comparator.compare_events(expected, actual, "mysql")
        assert diff is not None
        assert diff.enabled_changed == (True, False)
        assert diff.severity == DiffSeverity.INFO  # enabled_changed alone is INFO

    def test_detect_event_type_change(self):
        """Test detection of event type changes."""
        from core.sql_model.event import Event

        expected = Event(
            name="one_time_update",
            schema="mydb",
            definition="UPDATE settings SET value = 'new' WHERE key = 'config'",
            schedule="AT '2025-12-31 23:59:59'",
            enabled=True,
            event_type="ONE TIME",
            dialect="mysql",
        )
        actual = Event(
            name="one_time_update",
            schema="mydb",
            definition="UPDATE settings SET value = 'new' WHERE key = 'config'",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )

        diff = self.comparator.compare_events(expected, actual, "mysql")
        assert diff is not None
        assert diff.event_type_changed == ("ONE TIME", "RECURRING")
        assert diff.severity == DiffSeverity.WARNING

    def test_event_multiple_changes(self):
        """Test detection of multiple event changes."""
        from core.sql_model.event import Event

        expected = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )
        actual = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 60 DAY",
            schedule="EVERY 1 HOUR",
            enabled=False,
            event_type="RECURRING",
            dialect="mysql",
        )

        diff = self.comparator.compare_events(expected, actual, "mysql")
        assert diff is not None
        assert diff.definition_changed is True
        assert diff.schedule_changed == ("EVERY 1 DAY", "EVERY 1 HOUR")
        assert diff.enabled_changed == (True, False)
        assert diff.severity == DiffSeverity.WARNING

    def test_event_definition_normalization(self):
        """Test that event definitions are normalized for comparison."""
        from core.sql_model.event import Event

        # Same definition with different whitespace and case
        evt1 = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs WHERE created_at < NOW() - INTERVAL 30 DAY",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )
        evt2 = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="  DELETE  FROM  logs  WHERE  created_at  <  NOW()  -  INTERVAL  30  DAY  ",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )

        diff = self.comparator.compare_events(evt1, evt2, "mysql")
        assert diff is None

    def test_event_schedule_case_insensitive(self):
        """Test that event schedule comparison is case-insensitive."""
        from core.sql_model.event import Event

        expected = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs",
            schedule="every 1 day",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )
        actual = Event(
            name="cleanup_logs",
            schema="mydb",
            definition="DELETE FROM logs",
            schedule="EVERY 1 DAY",
            enabled=True,
            event_type="RECURRING",
            dialect="mysql",
        )

        diff = self.comparator.compare_events(expected, actual, "mysql")
        assert diff is None


class TestDatabaseLinkComparison:
    """Test database link comparison functionality (Oracle)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_database_links(self):
        """Test comparing two identical database links returns no diffs."""
        from core.sql_model.database_link import DatabaseLink

        link1 = DatabaseLink(
            name="remote_prod",
            host="prod.server.com",
            username="app_user",
            connect_string="(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=prod.server.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=PROD)))",
            public=False,
            dialect="oracle",
        )
        link2 = DatabaseLink(
            name="remote_prod",
            host="prod.server.com",
            username="app_user",
            connect_string="(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=prod.server.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=PROD)))",
            public=False,
            dialect="oracle",
        )

        diff = self.comparator.compare_database_links(link1, link2, "oracle")
        assert diff is None

    def test_detect_database_link_host_change(self):
        """Test detection of database link host changes."""
        from core.sql_model.database_link import DatabaseLink

        expected = DatabaseLink(
            name="remote_db",
            host="old.server.com",
            username="app_user",
            public=False,
            dialect="oracle",
        )
        actual = DatabaseLink(
            name="remote_db",
            host="new.server.com",
            username="app_user",
            public=False,
            dialect="oracle",
        )

        diff = self.comparator.compare_database_links(expected, actual, "oracle")
        assert diff is not None
        assert diff.host_changed == ("old.server.com", "new.server.com")
        assert diff.expected_host == "old.server.com"
        assert diff.actual_host == "new.server.com"
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_database_link_username_change(self):
        """Test detection of database link username changes."""
        from core.sql_model.database_link import DatabaseLink

        expected = DatabaseLink(
            name="remote_db",
            host="server.com",
            username="old_user",
            public=False,
            dialect="oracle",
        )
        actual = DatabaseLink(
            name="remote_db",
            host="server.com",
            username="new_user",
            public=False,
            dialect="oracle",
        )

        diff = self.comparator.compare_database_links(expected, actual, "oracle")
        assert diff is not None
        assert diff.username_changed == ("old_user", "new_user")
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_database_link_public_status_change(self):
        """Test detection of public/private status changes."""
        from core.sql_model.database_link import DatabaseLink

        expected = DatabaseLink(
            name="remote_db",
            host="server.com",
            username="app_user",
            public=False,
            dialect="oracle",
        )
        actual = DatabaseLink(
            name="remote_db",
            host="server.com",
            username="app_user",
            public=True,
            dialect="oracle",
        )

        diff = self.comparator.compare_database_links(expected, actual, "oracle")
        assert diff is not None
        assert diff.public_changed == (False, True)
        assert diff.severity == DiffSeverity.WARNING  # public_changed alone is WARNING

    def test_database_link_multiple_changes(self):
        """Test detection of multiple database link changes."""
        from core.sql_model.database_link import DatabaseLink

        expected = DatabaseLink(
            name="remote_db",
            host="old.server.com",
            username="old_user",
            public=False,
            dialect="oracle",
        )
        actual = DatabaseLink(
            name="remote_db",
            host="new.server.com",
            username="new_user",
            public=True,
            dialect="oracle",
        )

        diff = self.comparator.compare_database_links(expected, actual, "oracle")
        assert diff is not None
        assert diff.host_changed == ("old.server.com", "new.server.com")
        assert diff.username_changed == ("old_user", "new_user")
        assert diff.public_changed == (False, True)
        assert diff.severity == DiffSeverity.ERROR

    def test_database_link_connect_string_comparison(self):
        """Test comparing database links with connect strings."""
        from core.sql_model.database_link import DatabaseLink

        link1 = DatabaseLink(
            name="remote_db",
            connect_string="(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=server.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=DB)))",
            username="app_user",
            public=False,
            dialect="oracle",
        )
        link2 = DatabaseLink(
            name="remote_db",
            connect_string="(DESCRIPTION=(ADDRESS=(PROTOCOL=TCP)(HOST=server.com)(PORT=1521))(CONNECT_DATA=(SERVICE_NAME=DB)))",
            username="app_user",
            public=False,
            dialect="oracle",
        )

        diff = self.comparator.compare_database_links(link1, link2, "oracle")
        assert diff is None

    def test_database_link_case_insensitive_oracle(self):
        """Test that database link names and hosts are compared case-insensitively in Oracle."""
        from core.sql_model.database_link import DatabaseLink

        expected = DatabaseLink(
            name="REMOTE_DB",
            host="SERVER.COM",
            username="APP_USER",
            public=False,
            dialect="oracle",
        )
        actual = DatabaseLink(
            name="remote_db",
            host="server.com",
            username="app_user",
            public=False,
            dialect="oracle",
        )

        diff = self.comparator.compare_database_links(expected, actual, "oracle")
        assert diff is None

    def test_database_link_with_null_host(self):
        """Test comparing database links with null hosts."""
        from core.sql_model.database_link import DatabaseLink

        link1 = DatabaseLink(
            name="remote_db",
            host=None,
            username="app_user",
            public=False,
            dialect="oracle",
        )
        link2 = DatabaseLink(
            name="remote_db",
            host=None,
            username="app_user",
            public=False,
            dialect="oracle",
        )

        diff = self.comparator.compare_database_links(link1, link2, "oracle")
        assert diff is None


class TestLinkedServerComparison:
    """Test linked server comparison functionality (SQL Server)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_linked_servers(self):
        """Test comparing two identical linked servers returns no diffs."""
        from core.sql_model.linked_server import LinkedServer

        srv1 = LinkedServer(
            name="RemoteServer",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="remote.server.com",
            catalog="RemoteDB",
            username="remote_user",
            dialect="sqlserver",
        )
        srv2 = LinkedServer(
            name="RemoteServer",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="remote.server.com",
            catalog="RemoteDB",
            username="remote_user",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(srv1, srv2, "sqlserver")
        assert diff is None

    def test_detect_linked_server_data_source_change(self):
        """Test detection of data source changes."""
        from core.sql_model.linked_server import LinkedServer

        expected = LinkedServer(
            name="RemoteServer",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="old.server.com",
            catalog="RemoteDB",
            dialect="sqlserver",
        )
        actual = LinkedServer(
            name="RemoteServer",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="new.server.com",
            catalog="RemoteDB",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(expected, actual, "sqlserver")
        assert diff is not None
        assert diff.data_source_changed == ("old.server.com", "new.server.com")
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_linked_server_provider_change(self):
        """Test detection of provider changes."""
        from core.sql_model.linked_server import LinkedServer

        expected = LinkedServer(
            name="OracleServer",
            product="Oracle",
            provider="OraOLEDB.Oracle",
            data_source="oracle.server.com",
            dialect="sqlserver",
        )
        actual = LinkedServer(
            name="OracleServer",
            product="Oracle",
            provider="MSDAORA",
            data_source="oracle.server.com",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(expected, actual, "sqlserver")
        assert diff is not None
        assert diff.provider_changed == ("OraOLEDB.Oracle", "MSDAORA")
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_linked_server_product_change(self):
        """Test detection of product name changes."""
        from core.sql_model.linked_server import LinkedServer

        expected = LinkedServer(
            name="RemoteServer",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="server.com",
            dialect="sqlserver",
        )
        actual = LinkedServer(
            name="RemoteServer",
            product="Oracle",
            provider="SQLNCLI",
            data_source="server.com",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(expected, actual, "sqlserver")
        assert diff is not None
        assert diff.product_changed == ("SQL Server", "Oracle")
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_linked_server_catalog_change(self):
        """Test detection of catalog changes."""
        from core.sql_model.linked_server import LinkedServer

        expected = LinkedServer(
            name="RemoteServer",
            data_source="server.com",
            catalog="OldDB",
            dialect="sqlserver",
        )
        actual = LinkedServer(
            name="RemoteServer",
            data_source="server.com",
            catalog="NewDB",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(expected, actual, "sqlserver")
        assert diff is not None
        assert diff.catalog_changed == ("OldDB", "NewDB")
        assert diff.severity == DiffSeverity.WARNING  # catalog_changed alone is WARNING

    def test_detect_linked_server_username_change(self):
        """Test detection of username changes."""
        from core.sql_model.linked_server import LinkedServer

        expected = LinkedServer(
            name="RemoteServer",
            data_source="server.com",
            username="old_user",
            dialect="sqlserver",
        )
        actual = LinkedServer(
            name="RemoteServer",
            data_source="server.com",
            username="new_user",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(expected, actual, "sqlserver")
        assert diff is not None
        assert diff.username_changed == ("old_user", "new_user")
        assert diff.severity == DiffSeverity.ERROR

    def test_linked_server_multiple_changes(self):
        """Test detection of multiple linked server changes."""
        from core.sql_model.linked_server import LinkedServer

        expected = LinkedServer(
            name="RemoteServer",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="old.server.com",
            catalog="OldDB",
            username="old_user",
            dialect="sqlserver",
        )
        actual = LinkedServer(
            name="RemoteServer",
            product="Oracle",
            provider="OraOLEDB.Oracle",
            data_source="new.server.com",
            catalog="NewDB",
            username="new_user",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(expected, actual, "sqlserver")
        assert diff is not None
        assert diff.product_changed == ("SQL Server", "Oracle")
        assert diff.provider_changed == ("SQLNCLI", "OraOLEDB.Oracle")
        assert diff.data_source_changed == ("old.server.com", "new.server.com")
        assert diff.catalog_changed == ("OldDB", "NewDB")
        assert diff.username_changed == ("old_user", "new_user")
        assert diff.severity == DiffSeverity.ERROR

    def test_linked_server_case_insensitive_sqlserver(self):
        """Test that linked server names are compared case-insensitively in SQL Server."""
        from core.sql_model.linked_server import LinkedServer

        expected = LinkedServer(
            name="REMOTESERVER",
            product="SQL SERVER",
            data_source="SERVER.COM",
            catalog="REMOTEDB",
            dialect="sqlserver",
        )
        actual = LinkedServer(
            name="remoteserver",
            product="sql server",
            data_source="server.com",
            catalog="remotedb",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(expected, actual, "sqlserver")
        assert diff is None

    def test_linked_server_with_null_values(self):
        """Test comparing linked servers with null optional fields."""
        from core.sql_model.linked_server import LinkedServer

        srv1 = LinkedServer(
            name="RemoteServer",
            data_source="server.com",
            product=None,
            provider=None,
            catalog=None,
            username=None,
            dialect="sqlserver",
        )
        srv2 = LinkedServer(
            name="RemoteServer",
            data_source="server.com",
            product=None,
            provider=None,
            catalog=None,
            username=None,
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(srv1, srv2, "sqlserver")
        assert diff is None

    def test_linked_server_minimal_config(self):
        """Test comparing linked servers with minimal configuration."""
        from core.sql_model.linked_server import LinkedServer

        srv1 = LinkedServer(
            name="MinimalServer",
            data_source="server.com",
            dialect="sqlserver",
        )
        srv2 = LinkedServer(
            name="MinimalServer",
            data_source="server.com",
            dialect="sqlserver",
        )

        diff = self.comparator.compare_linked_servers(srv1, srv2, "sqlserver")
        assert diff is None


class TestForeignDataWrapperComparison:
    """Test foreign data wrapper comparison functionality (PostgreSQL)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_fdw(self):
        """Test comparing two identical FDWs returns no diffs."""
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        fdw1 = ForeignDataWrapper(
            name="postgres_fdw",
            handler="postgres_fdw_handler",
            validator="postgres_fdw_validator",
            dialect="postgresql",
        )
        fdw2 = ForeignDataWrapper(
            name="postgres_fdw",
            handler="postgres_fdw_handler",
            validator="postgres_fdw_validator",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_data_wrappers(fdw1, fdw2, "postgresql")
        assert diff is None

    def test_detect_fdw_handler_change(self):
        """Test detection of FDW handler changes."""
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        expected = ForeignDataWrapper(
            name="custom_fdw",
            handler="old_handler",
            dialect="postgresql",
        )
        actual = ForeignDataWrapper(
            name="custom_fdw",
            handler="new_handler",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_data_wrappers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.handler_changed == ("old_handler", "new_handler")
        assert diff.severity == DiffSeverity.ERROR  # handler_changed is breaking

    def test_detect_fdw_validator_change(self):
        """Test detection of FDW validator changes."""
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        expected = ForeignDataWrapper(
            name="custom_fdw",
            handler="handler_func",
            validator="old_validator",
            dialect="postgresql",
        )
        actual = ForeignDataWrapper(
            name="custom_fdw",
            handler="handler_func",
            validator="new_validator",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_data_wrappers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.validator_changed == ("old_validator", "new_validator")
        assert diff.severity == DiffSeverity.ERROR  # validator_changed is breaking

    def test_detect_fdw_options_change(self):
        """Test detection of FDW options changes."""
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        expected = ForeignDataWrapper(
            name="custom_fdw",
            handler="handler_func",
            options={"option1": "value1"},
            dialect="postgresql",
        )
        actual = ForeignDataWrapper(
            name="custom_fdw",
            handler="handler_func",
            options={"option1": "value2"},
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_data_wrappers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.options_changed is not None
        assert diff.severity == DiffSeverity.WARNING

    def test_fdw_case_insensitive_postgresql(self):
        """Test that FDW names are compared case-insensitively in PostgreSQL."""
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        expected = ForeignDataWrapper(
            name="POSTGRES_FDW",
            handler="POSTGRES_FDW_HANDLER",
            dialect="postgresql",
        )
        actual = ForeignDataWrapper(
            name="postgres_fdw",
            handler="postgres_fdw_handler",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_data_wrappers(expected, actual, "postgresql")
        assert diff is None


class TestForeignServerComparison:
    """Test foreign server comparison functionality (PostgreSQL)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.normalizer = DataTypeNormalizer()
        self.comparator = ObjectComparator(self.normalizer)

    def test_compare_identical_foreign_servers(self):
        """Test comparing two identical foreign servers returns no diffs."""
        from core.sql_model.foreign_server import ForeignServer

        srv1 = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="remote.server.com",
            port=5432,
            dbname="remote_db",
            dialect="postgresql",
        )
        srv2 = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="remote.server.com",
            port=5432,
            dbname="remote_db",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(srv1, srv2, "postgresql")
        assert diff is None

    def test_detect_foreign_server_host_change(self):
        """Test detection of foreign server host changes."""
        from core.sql_model.foreign_server import ForeignServer

        expected = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="old.server.com",
            port=5432,
            dbname="remote_db",
            dialect="postgresql",
        )
        actual = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="new.server.com",
            port=5432,
            dbname="remote_db",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.host_changed == ("old.server.com", "new.server.com")
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_foreign_server_port_change(self):
        """Test detection of foreign server port changes."""
        from core.sql_model.foreign_server import ForeignServer

        expected = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="server.com",
            port=5432,
            dbname="remote_db",
            dialect="postgresql",
        )
        actual = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="server.com",
            port=5433,
            dbname="remote_db",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.port_changed == (5432, 5433)
        assert diff.severity == DiffSeverity.ERROR

    def test_detect_foreign_server_dbname_change(self):
        """Test detection of foreign server database name changes."""
        from core.sql_model.foreign_server import ForeignServer

        expected = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="server.com",
            port=5432,
            dbname="old_db",
            dialect="postgresql",
        )
        actual = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="server.com",
            port=5432,
            dbname="new_db",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.dbname_changed == ("old_db", "new_db")
        assert diff.severity == DiffSeverity.WARNING  # dbname_changed alone is WARNING

    def test_detect_foreign_server_fdw_change(self):
        """Test detection of FDW name changes."""
        from core.sql_model.foreign_server import ForeignServer

        expected = ForeignServer(
            name="remote_server",
            fdw_name="postgres_fdw",
            host="server.com",
            dialect="postgresql",
        )
        actual = ForeignServer(
            name="remote_server",
            fdw_name="oracle_fdw",
            host="server.com",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.fdw_changed == ("postgres_fdw", "oracle_fdw")
        assert diff.severity == DiffSeverity.ERROR

    def test_foreign_server_multiple_changes(self):
        """Test detection of multiple foreign server changes."""
        from core.sql_model.foreign_server import ForeignServer

        expected = ForeignServer(
            name="remote_server",
            fdw_name="postgres_fdw",
            host="old.server.com",
            port=5432,
            dbname="old_db",
            dialect="postgresql",
        )
        actual = ForeignServer(
            name="remote_server",
            fdw_name="oracle_fdw",
            host="new.server.com",
            port=1521,
            dbname="new_db",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(expected, actual, "postgresql")
        assert diff is not None
        assert diff.fdw_changed == ("postgres_fdw", "oracle_fdw")
        assert diff.host_changed == ("old.server.com", "new.server.com")
        assert diff.port_changed == (5432, 1521)
        assert diff.dbname_changed == ("old_db", "new_db")
        assert diff.severity == DiffSeverity.ERROR

    def test_foreign_server_case_insensitive_postgresql(self):
        """Test that foreign server names are compared case-insensitively."""
        from core.sql_model.foreign_server import ForeignServer

        expected = ForeignServer(
            name="REMOTE_POSTGRES",
            fdw_name="POSTGRES_FDW",
            host="SERVER.COM",
            dbname="REMOTE_DB",
            dialect="postgresql",
        )
        actual = ForeignServer(
            name="remote_postgres",
            fdw_name="postgres_fdw",
            host="server.com",
            dbname="remote_db",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(expected, actual, "postgresql")
        assert diff is None

    def test_foreign_server_with_null_port(self):
        """Test comparing foreign servers with null port."""
        from core.sql_model.foreign_server import ForeignServer

        srv1 = ForeignServer(
            name="remote_server",
            fdw_name="postgres_fdw",
            host="server.com",
            port=None,
            dbname="remote_db",
            dialect="postgresql",
        )
        srv2 = ForeignServer(
            name="remote_server",
            fdw_name="postgres_fdw",
            host="server.com",
            port=None,
            dbname="remote_db",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(srv1, srv2, "postgresql")
        assert diff is None

    def test_foreign_server_minimal_config(self):
        """Test comparing foreign servers with minimal configuration."""
        from core.sql_model.foreign_server import ForeignServer

        srv1 = ForeignServer(
            name="minimal_server",
            fdw_name="file_fdw",
            dialect="postgresql",
        )
        srv2 = ForeignServer(
            name="minimal_server",
            fdw_name="file_fdw",
            dialect="postgresql",
        )

        diff = self.comparator.compare_foreign_servers(srv1, srv2, "postgresql")
        assert diff is None


class TestForeignServerBugFixes:
    """Test bug fixes for ForeignServer class."""

    def test_foreign_server_does_not_mutate_options(self):
        """Test that ForeignServer doesn't mutate the caller's options dictionary."""
        from core.sql_model.foreign_server import ForeignServer

        # Create options dictionary
        original_options = {"option1": "value1", "option2": "value2"}
        options_copy = original_options.copy()

        # Create foreign server with host, port, dbname
        server = ForeignServer(
            name="test_server",
            fdw_name="postgres_fdw",
            host="localhost",
            port=5432,
            dbname="testdb",
            options=original_options,
            dialect="postgresql",
        )

        # Verify original options dictionary was not mutated
        assert original_options == options_copy, "Original options dictionary was mutated!"
        assert "host" not in original_options, "host was added to original options"
        assert "port" not in original_options, "port was added to original options"
        assert "dbname" not in original_options, "dbname was added to original options"

        # Verify server has the merged options
        assert server.options["host"] == "localhost"
        assert server.options["port"] == "5432"
        assert server.options["dbname"] == "testdb"
        assert server.options["option1"] == "value1"
        assert server.options["option2"] == "value2"

    def test_foreign_server_uses_correct_object_type(self):
        """Test that ForeignServer uses FOREIGN_SERVER type, not TYPE."""
        from core.sql_model.base import SqlObjectType
        from core.sql_model.foreign_server import ForeignServer

        server = ForeignServer(name="test_server", fdw_name="postgres_fdw", dialect="postgresql")

        # Verify it uses FOREIGN_SERVER, not TYPE or DATABASE_LINK
        assert server.object_type == SqlObjectType.FOREIGN_SERVER
        assert server.object_type != SqlObjectType.TYPE
        assert server.object_type != SqlObjectType.DATABASE_LINK  # DATABASE_LINK is for Oracle

    def test_foreign_data_wrapper_does_not_mutate_options(self):
        """Test that ForeignDataWrapper doesn't mutate the caller's options dictionary."""
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        # Create options dictionary
        original_options = {"option1": "value1", "option2": "value2"}
        options_copy = original_options.copy()

        # Create FDW
        fdw = ForeignDataWrapper(
            name="test_fdw", handler="test_handler", options=original_options, dialect="postgresql"
        )

        # Verify original options dictionary was not mutated
        assert original_options == options_copy, "Original options dictionary was mutated!"

        # Verify FDW has copy of options
        assert fdw.options == original_options
        assert fdw.options is not original_options, "Options should be a copy, not the same object"

    def test_foreign_data_wrapper_uses_correct_object_type(self):
        """Test that ForeignDataWrapper uses FOREIGN_DATA_WRAPPER type, not TYPE."""
        from core.sql_model.base import SqlObjectType
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper

        fdw = ForeignDataWrapper(name="test_fdw", handler="test_handler", dialect="postgresql")

        # Verify it uses FOREIGN_DATA_WRAPPER, not TYPE or DATABASE_LINK
        assert fdw.object_type == SqlObjectType.FOREIGN_DATA_WRAPPER
        assert fdw.object_type != SqlObjectType.TYPE
        assert fdw.object_type != SqlObjectType.DATABASE_LINK  # DATABASE_LINK is for Oracle


class TestModuleBugFix:
    """Test bug fix for Module object type classification."""

    def test_module_uses_correct_object_type(self):
        """Test that Module uses PACKAGE type, not PROCEDURE."""
        from core.sql_model.base import SqlObjectType
        from core.sql_model.module import Module

        module = Module(
            name="test_module", definition="CREATE MODULE test_module END MODULE", dialect="db2"
        )

        # Verify it uses PACKAGE (modules are containers like packages)
        assert (
            module.object_type == SqlObjectType.PACKAGE
        ), f"Expected PACKAGE but got {module.object_type}"

        # Verify it's NOT PROCEDURE (procedures are individual routines)
        assert (
            module.object_type != SqlObjectType.PROCEDURE
        ), "Module should not be classified as PROCEDURE"

    def test_module_and_package_have_same_type(self):
        """Test that Module (DB2) and Package (Oracle) use the same object type.

        Both are containers for routines and should be classified identically.
        """
        from core.sql_model.base import SqlObjectType
        from core.sql_model.module import Module
        from core.sql_model.package import Package

        module = Module(
            name="db2_module", definition="CREATE MODULE db2_module END MODULE", dialect="db2"
        )

        package = Package(
            name="oracle_package", spec="CREATE PACKAGE oracle_package AS END;", dialect="oracle"
        )

        # Both should be classified as PACKAGE
        assert module.object_type == SqlObjectType.PACKAGE
        assert package.object_type == SqlObjectType.PACKAGE
        assert (
            module.object_type == package.object_type
        ), "Module and Package should have the same object type"

    def test_module_object_type_consistency(self):
        """Test that Module object type is consistent across operations."""
        from core.sql_model.base import SqlObjectType
        from core.sql_model.module import Module

        module = Module(
            name="test_module",
            definition="CREATE MODULE test_module PROCEDURE proc1() END MODULE",
            schema="TESTSCHEMA",
            dialect="db2",
        )

        # Verify object type in different contexts
        assert module.object_type == SqlObjectType.PACKAGE
        assert module.object_type.name == "PACKAGE"
        assert module.object_type.value == "PACKAGE"

        # Verify in string representation
        str_repr = str(module)
        assert "MODULE" in str_repr  # String still says MODULE (correct)

        # But object type classification is PACKAGE
        assert module.object_type == SqlObjectType.PACKAGE


class TestStripRedundantParens:
    """Tests for NEW-BUG-09: _strip_redundant_parens handles nested expressions correctly."""

    def _make_comparator(self):
        from core.comparison.table_comparator import TableComparator
        from core.comparison.type_normalizer import DataTypeNormalizer

        return TableComparator(DataTypeNormalizer())

    def test_strip_redundant_parens_nested(self):
        """((a + b)) should be stripped to 'a + b' but (a) + (b) should stay."""
        comp = self._make_comparator()
        # Double-wrapped expression — both outer layers should be removed
        result1 = comp._normalize_expression("((a + b))")
        assert "a + b" in result1.lower() or "a+b" in result1.lower().replace(" ", "")
        # Expression with separate paren groups — should NOT strip outer
        result2 = comp._normalize_expression("(a) + (b)")
        assert "(" in result2  # Parentheses should remain


class TestComparatorDuplicateFunctionsRemoved:
    """Contract tests: comparator.py must NOT define its own copies of comparison_utils functions."""

    def test_is_system_generated_not_defined_in_comparator_module(self):
        """_is_system_generated_constraint_name must not exist in comparator module namespace."""
        import core.comparison.comparator as mod

        assert "_is_system_generated_constraint_name" not in vars(mod)

    def test_extract_base_identity_not_defined_in_comparator_module(self):
        """_extract_base_identity_type must not exist in comparator module namespace."""
        import core.comparison.comparator as mod

        assert "_extract_base_identity_type" not in vars(mod)

    def test_public_functions_not_re_exported_via_comparator_module(self):
        """Public comparison_utils functions must not be re-exported from comparator (story 23-1).

        No production code imports these functions via comparator; re-exporting them
        would be a dead import that story 23-1 explicitly removed.
        """
        import core.comparison.comparator as mod

        assert "is_system_generated_constraint_name" not in vars(mod)
        assert "extract_base_identity_type" not in vars(mod)

    def test_extract_base_identity_type_none_returns_empty_string(self):
        """extract_base_identity_type(None, ...) must return '' not None (canonical behavior).

        The former private _extract_base_identity_type returned None when data_type=None.
        The public canonical version returns '' instead. This test locks the new behavior.
        """
        from core.comparison.comparison_utils import extract_base_identity_type

        result = extract_base_identity_type(None, "mysql")
        assert (
            result == ""
        ), f"Expected '' but got {result!r} — regression from private function behavior"

    def test_extract_base_identity_type_empty_string_returns_empty_string(self):
        """extract_base_identity_type('', ...) must return '' (falsy string, not None branch)."""
        from core.comparison.comparison_utils import extract_base_identity_type

        result = extract_base_identity_type("", "postgresql")
        assert result == ""
