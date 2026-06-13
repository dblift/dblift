"""Tests for Diff Models.

This module tests the structured diff result classes used for
representing SQL object comparison results.
"""

import pytest

from core.comparison.diff_models import (
    ColumnDiff,
    ConstraintDiff,
    DatabaseLinkDiff,
    DiffResult,
    DiffSeverity,
    ForeignDataWrapperDiff,
    ForeignServerDiff,
    FunctionDiff,
    IndexDiff,
    LinkedServerDiff,
    PackageDiff,
    ProcedureDiff,
    RoutineDiff,
    SchemaDiff,
    SequenceDiff,
    SynonymDiff,
    TableDiff,
    TriggerDiff,
    UserDefinedTypeDiff,
    ViewDiff,
)

pytestmark = [pytest.mark.unit]


class TestDiffSeverity:
    """Test DiffSeverity enum."""

    def test_severity_values(self):
        """Test severity enum values."""
        assert DiffSeverity.ERROR.value == "error"
        assert DiffSeverity.WARNING.value == "warning"
        assert DiffSeverity.INFO.value == "info"


class TestDiffResult:
    """Test base DiffResult class."""

    def test_create_diff_result_no_diffs(self):
        """Test creating a diff result with no differences."""
        result = DiffResult(object_name="test_obj", object_type="table")

        assert result.object_name == "test_obj"
        assert result.object_type == "table"
        assert result.has_diffs is False
        assert result.severity == DiffSeverity.INFO

    def test_create_diff_result_with_diffs(self):
        """Test creating a diff result with differences."""
        result = DiffResult(
            object_name="test_obj",
            object_type="table",
            has_diffs=True,
            severity=DiffSeverity.ERROR,
        )

        assert result.has_diffs is True
        assert result.severity == DiffSeverity.ERROR

    def test_to_dict_no_diffs(self):
        """Test to_dict() with no differences."""
        result = DiffResult(object_name="test_obj", object_type="table")
        data = result.to_dict()

        assert data["object_name"] == "test_obj"
        assert data["object_type"] == "table"
        assert data["has_diffs"] is False
        assert data["severity"] == "info"

    def test_str_no_diffs(self):
        """Test __str__() with no differences."""
        result = DiffResult(object_name="test_obj", object_type="table")
        assert str(result) == "table 'test_obj': No differences"

    def test_str_with_diffs(self):
        """Test __str__() with differences."""
        result = DiffResult(
            object_name="test_obj",
            object_type="table",
            has_diffs=True,
            severity=DiffSeverity.ERROR,
        )
        assert "ERROR" in str(result)
        assert "Differences found" in str(result)

    def test_get_summary(self):
        """Test get_summary() method."""
        result = DiffResult(object_name="test_obj", object_type="table")
        assert result.get_summary() == "table 'test_obj': MATCH"

        result.has_diffs = True
        result.severity = DiffSeverity.WARNING
        assert result.get_summary() == "table 'test_obj': DIFF (warning)"


class TestColumnDiff:
    """Test ColumnDiff class."""

    def test_create_column_diff_no_diffs(self):
        """Test creating column diff with no differences."""
        col_diff = ColumnDiff(object_name="user_id", column_name="user_id")

        assert col_diff.column_name == "user_id"
        assert col_diff.has_diffs is False
        assert col_diff.object_type == "column"

    def test_create_column_diff_data_type(self):
        """Test creating column diff with data type difference."""
        col_diff = ColumnDiff(
            object_name="age", column_name="age", data_type_diff=("INTEGER", "VARCHAR")
        )

        assert col_diff.has_diffs is True
        assert col_diff.severity == DiffSeverity.ERROR
        assert col_diff.data_type_diff == ("INTEGER", "VARCHAR")

    def test_create_column_diff_nullable(self):
        """Test creating column diff with nullable difference."""
        col_diff = ColumnDiff(object_name="email", column_name="email", nullable_diff=(True, False))

        assert col_diff.has_diffs is True
        assert col_diff.severity == DiffSeverity.WARNING
        assert col_diff.nullable_diff == (True, False)

    def test_create_column_diff_multiple(self):
        """Test creating column diff with multiple differences."""
        col_diff = ColumnDiff(
            object_name="status",
            column_name="status",
            data_type_diff=("VARCHAR(50)", "VARCHAR(100)"),
            nullable_diff=(False, True),
            default_diff=("'active'", "'pending'"),
        )

        assert col_diff.has_diffs is True
        assert col_diff.severity == DiffSeverity.ERROR  # Data type diff is error

    def test_column_diff_severity_calculation(self):
        """Test severity calculation with different diff types."""
        # Only nullable diff (WARNING)
        col_diff = ColumnDiff(object_name="col1", nullable_diff=(True, False))
        assert col_diff.severity == DiffSeverity.WARNING

        # Data type diff (ERROR)
        col_diff = ColumnDiff(object_name="col2", data_type_diff=("INT", "VARCHAR"))
        assert col_diff.severity == DiffSeverity.ERROR

        # Identity diff (ERROR)
        col_diff = ColumnDiff(object_name="col3", identity_diff=(True, False))
        assert col_diff.severity == DiffSeverity.ERROR

    def test_column_diff_to_dict(self):
        """Test to_dict() serialization."""
        col_diff = ColumnDiff(
            object_name="price",
            column_name="price",
            data_type_diff=("DECIMAL(10,2)", "DECIMAL(12,2)"),
            nullable_diff=(False, True),
        )

        data = col_diff.to_dict()

        assert data["column_name"] == "price"
        assert "data_type" in data["differences"]
        assert data["differences"]["data_type"]["expected"] == "DECIMAL(10,2)"
        assert data["differences"]["data_type"]["actual"] == "DECIMAL(12,2)"
        assert "nullable" in data["differences"]

    def test_column_diff_str(self):
        """Test __str__() representation."""
        col_diff = ColumnDiff(
            object_name="amount",
            column_name="amount",
            data_type_diff=("INTEGER", "BIGINT"),
            nullable_diff=(False, True),
        )

        str_repr = str(col_diff)
        assert "amount" in str_repr
        assert "data_type: INTEGER → BIGINT" in str_repr
        assert "nullable: False → True" in str_repr


class TestConstraintDiff:
    """Test ConstraintDiff class."""

    def test_create_constraint_diff_no_diffs(self):
        """Test creating constraint diff with no differences."""
        const_diff = ConstraintDiff(
            object_name="pk_users", constraint_name="pk_users", constraint_type="PRIMARY KEY"
        )

        assert const_diff.has_diffs is False
        assert const_diff.object_type == "constraint"

    def test_create_constraint_diff_columns(self):
        """Test creating constraint diff with column differences."""
        const_diff = ConstraintDiff(
            object_name="pk_users",
            constraint_name="pk_users",
            constraint_type="PRIMARY KEY",
            columns_diff=(["user_id"], ["user_id", "tenant_id"]),
        )

        assert const_diff.has_diffs is True
        assert const_diff.severity == DiffSeverity.ERROR

    def test_create_constraint_diff_references(self):
        """Test creating constraint diff with reference differences."""
        const_diff = ConstraintDiff(
            object_name="fk_orders_users",
            constraint_name="fk_orders_users",
            constraint_type="FOREIGN KEY",
            references_diff=(("users", ["user_id"]), ("customers", ["customer_id"])),
        )

        assert const_diff.has_diffs is True
        assert const_diff.severity == DiffSeverity.ERROR

    def test_constraint_diff_to_dict(self):
        """Test to_dict() serialization."""
        const_diff = ConstraintDiff(
            object_name="uk_email",
            constraint_name="uk_email",
            constraint_type="UNIQUE",
            columns_diff=(["email"], ["email", "tenant_id"]),
        )

        data = const_diff.to_dict()

        assert data["constraint_name"] == "uk_email"
        assert data["constraint_type"] == "UNIQUE"
        assert "columns" in data["differences"]

    def test_constraint_diff_str(self):
        """Test __str__() representation."""
        const_diff = ConstraintDiff(
            object_name="fk_test",
            constraint_name="fk_test",
            constraint_type="FOREIGN KEY",
            columns_diff=(["col1"], ["col2"]),
        )

        str_repr = str(const_diff)
        assert "fk_test" in str_repr
        assert "FOREIGN KEY" in str_repr
        assert "columns" in str_repr

    def test_constraint_diff_str_check_clause_concise(self):
        """Test check_clause uses concise 'check clause differs' format (not full SQL)."""
        const_diff = ConstraintDiff(
            object_name="chk_age",
            constraint_name="chk_age",
            constraint_type="CHECK",
            check_clause_diff=(
                "age > 0 AND age < 150",
                "age >= 0 AND age <= 150",
            ),
        )
        str_repr = str(const_diff)
        assert "check clause differs" in str_repr
        assert "age > 0" not in str_repr  # Full SQL should not appear

    def test_constraint_diff_with_state_properties(self):
        """Test ConstraintDiff with state property differences."""
        const_diff = ConstraintDiff(
            object_name="uk_email",
            constraint_name="uk_email",
            constraint_type="UNIQUE",
            enabled_diff=(True, False),
            validated_diff=(True, False),
            deferrable_diff=(True, False),
            initially_deferred_diff=(False, True),
        )

        assert const_diff.has_diffs is True
        assert const_diff.enabled_diff == (True, False)
        assert const_diff.validated_diff == (True, False)
        assert const_diff.deferrable_diff == (True, False)
        assert const_diff.initially_deferred_diff == (False, True)
        # Enabled and validated should be ERROR severity
        assert const_diff.severity == DiffSeverity.ERROR

    def test_constraint_diff_state_severity(self):
        """Test ConstraintDiff severity calculation for state properties."""
        # Only deferrable changes (should be WARNING)
        const_diff = ConstraintDiff(
            object_name="uk_email",
            constraint_name="uk_email",
            constraint_type="UNIQUE",
            deferrable_diff=(True, False),
        )
        assert const_diff.severity == DiffSeverity.WARNING

        # Enabled/validated changes (should be ERROR)
        const_diff = ConstraintDiff(
            object_name="uk_email",
            constraint_name="uk_email",
            constraint_type="UNIQUE",
            enabled_diff=(True, False),
        )
        assert const_diff.severity == DiffSeverity.ERROR

    def test_column_diff_with_collation(self):
        """Test ColumnDiff with collation difference."""
        col_diff = ColumnDiff(
            object_name="name",
            column_name="name",
            collation_diff=("utf8mb4_unicode_ci", "utf8mb4_general_ci"),
        )

        assert col_diff.has_diffs is True
        assert col_diff.collation_diff == ("utf8mb4_unicode_ci", "utf8mb4_general_ci")

        data = col_diff.to_dict()
        assert "collation" in data["differences"]

        str_repr = str(col_diff)
        assert "collation" in str_repr.lower()

    def test_table_diff_with_inheritance(self):
        """Test TableDiff with inheritance change."""
        table_diff = TableDiff(
            object_name="child_table",
            table_name="child_table",
            inherits_changed=(
                ["parent_table1", "parent_table2"],
                ["parent_table1"],
            ),
        )

        assert table_diff.has_diffs is True
        assert table_diff.inherits_changed == (
            ["parent_table1", "parent_table2"],
            ["parent_table1"],
        )

        data = table_diff.to_dict()
        assert "inherits" in data["differences"]

        str_repr = str(table_diff)
        assert "inherits" in str_repr.lower()


class TestTableDiff:
    """Test TableDiff class."""

    def test_create_table_diff_no_diffs(self):
        """Test creating table diff with no differences."""
        table_diff = TableDiff(object_name="users", table_name="users")

        assert table_diff.has_diffs is False
        assert table_diff.object_type == "table"

    def test_create_table_diff_missing_columns(self):
        """Test creating table diff with missing columns."""
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email", "phone"],
        )

        assert table_diff.has_diffs is True
        assert table_diff.severity == DiffSeverity.ERROR

    def test_create_table_diff_extra_columns(self):
        """Test creating table diff with extra columns."""
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            extra_columns=["temp_field"],
        )

        assert table_diff.has_diffs is True
        assert table_diff.severity == DiffSeverity.WARNING

    def test_create_table_diff_modified_columns(self):
        """Test creating table diff with modified columns."""
        col_diff = ColumnDiff(
            object_name="age",
            data_type_diff=("INTEGER", "BIGINT"),
        )

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            modified_columns=[col_diff],
        )

        assert table_diff.has_diffs is True
        assert table_diff.severity == DiffSeverity.ERROR  # Due to column error severity

    def test_table_diff_severity_calculation(self):
        """Test severity calculation with different diff types."""
        # Missing column (ERROR)
        table_diff = TableDiff(
            object_name="t1",
            missing_columns=["col1"],
        )
        assert table_diff.severity == DiffSeverity.ERROR

        # Extra column (WARNING)
        table_diff = TableDiff(
            object_name="t2",
            extra_columns=["col1"],
        )
        assert table_diff.severity == DiffSeverity.WARNING

        # Modified column with error
        col_diff = ColumnDiff(object_name="c1", data_type_diff=("INT", "VARCHAR"))
        table_diff = TableDiff(
            object_name="t3",
            modified_columns=[col_diff],
        )
        assert table_diff.severity == DiffSeverity.ERROR

    def test_table_diff_get_diff_count(self):
        """Test get_diff_count() method."""
        table_diff = TableDiff(
            object_name="users",
            missing_columns=["email", "phone"],
            extra_columns=["temp"],
            missing_constraints=["pk_users"],
        )

        counts = table_diff.get_diff_count()

        assert counts["missing_columns"] == 2
        assert counts["extra_columns"] == 1
        assert counts["missing_constraints"] == 1
        assert counts["modified_columns"] == 0

    def test_table_diff_to_dict(self):
        """Test to_dict() serialization."""
        col_diff = ColumnDiff(object_name="age", data_type_diff=("INT", "BIGINT"))

        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email"],
            modified_columns=[col_diff],
        )

        data = table_diff.to_dict()

        assert data["table_name"] == "users"
        assert data["missing_columns"] == ["email"]
        assert len(data["modified_columns"]) == 1
        assert "diff_count" in data

    def test_table_diff_str(self):
        """Test __str__() representation."""
        table_diff = TableDiff(
            object_name="users",
            table_name="users",
            missing_columns=["email", "phone"],
            extra_columns=["temp"],
        )

        str_repr = str(table_diff)
        assert "users" in str_repr
        assert "2 missing column(s)" in str_repr
        assert "1 extra column(s)" in str_repr

    def test_table_diff_modified_constraint_error_escalates(self):
        """AC#1 — ConstraintDiff ERROR should escalate TableDiff to ERROR."""
        con_diff = ConstraintDiff(
            object_name="fk_orders_users",
            constraint_type="FK",
            columns_diff=(["user_id"], ["customer_id"]),
        )
        table_diff = TableDiff(
            object_name="orders",
            modified_constraints=[con_diff],
        )
        assert table_diff.has_diffs is True
        assert table_diff.severity == DiffSeverity.ERROR

    def test_table_diff_modified_constraint_only_error(self):
        """AC#2 — modified_constraints ERROR, no modified_columns → still ERROR."""
        con_diff = ConstraintDiff(
            object_name="chk_age",
            constraint_type="CHECK",
            check_clause_diff=("age > 0", "age >= 0"),
        )
        table_diff = TableDiff(
            object_name="users",
            modified_constraints=[con_diff],
        )
        assert table_diff.severity == DiffSeverity.ERROR

    def test_table_diff_modified_constraint_warning_only(self):
        """AC#3 — ConstraintDiff WARNING only → TableDiff WARNING."""
        con_diff = ConstraintDiff(
            object_name="chk_status",
            constraint_type="CHECK",
            deferrable_diff=(False, True),
        )
        table_diff = TableDiff(
            object_name="users",
            modified_constraints=[con_diff],
        )
        assert table_diff.severity == DiffSeverity.WARNING


class TestTableDiffToDict6MissingFields:
    """Tests AC#1/2 de story 15-4 : 6 champs manquants dans TableDiff.to_dict()."""

    def test_six_fields_present_with_default_false(self):
        """AC#1 — Les 11 booléens (5 pré-existants + 6 nouveaux) sont présents et à False."""
        table_diff = TableDiff(object_name="t", table_name="t")
        data = table_diff.to_dict()
        for field in [
            # 5 champs pré-existants (régression)
            "temporary_changed",
            "filegroup_changed",
            "memory_optimized_changed",
            "system_versioned_changed",
            "history_table_changed",
            # 6 nouveaux champs (story 15-4)
            "partition_method_changed",
            "partition_columns_changed",
            "compress_changed",
            "compress_type_changed",
            "logged_changed",
            "organize_by_changed",
        ]:
            assert field in data, f"Champ manquant : {field}"
            assert data[field] is False, f"Valeur par défaut attendue False pour {field}"

    def test_diff_count_boolean_field_is_counted(self):
        """AC#2 — get_diff_count inclut les booléens (fix du gap 15-13)."""
        table_diff = TableDiff(object_name="t", table_name="t", partition_method_changed=True)
        assert table_diff.has_diffs is True
        counts = table_diff.to_dict()["diff_count"]
        assert counts["partition_method_changed"] == 1
        assert counts["missing_columns"] == 0

    def test_partition_method_changed_serialized(self):
        """AC#2 — partition_method_changed=True est sérialisé et has_diffs=True."""
        table_diff = TableDiff(object_name="t", table_name="t", partition_method_changed=True)
        assert table_diff.has_diffs is True
        assert table_diff.to_dict()["partition_method_changed"] is True

    def test_partition_columns_changed_serialized(self):
        """AC#2 — partition_columns_changed=True est sérialisé et has_diffs=True."""
        table_diff = TableDiff(object_name="t", table_name="t", partition_columns_changed=True)
        assert table_diff.has_diffs is True
        assert table_diff.to_dict()["partition_columns_changed"] is True

    def test_compress_changed_serialized(self):
        """AC#2 — compress_changed=True est sérialisé et has_diffs=True."""
        table_diff = TableDiff(object_name="t", table_name="t", compress_changed=True)
        assert table_diff.has_diffs is True
        assert table_diff.to_dict()["compress_changed"] is True

    def test_compress_type_changed_serialized(self):
        """AC#2 — compress_type_changed=True est sérialisé et has_diffs=True."""
        table_diff = TableDiff(object_name="t", table_name="t", compress_type_changed=True)
        assert table_diff.has_diffs is True
        assert table_diff.to_dict()["compress_type_changed"] is True

    def test_logged_changed_serialized(self):
        """AC#2 — logged_changed=True est sérialisé et has_diffs=True."""
        table_diff = TableDiff(object_name="t", table_name="t", logged_changed=True)
        assert table_diff.has_diffs is True
        assert table_diff.to_dict()["logged_changed"] is True

    def test_organize_by_changed_serialized(self):
        """AC#2 — organize_by_changed=True est sérialisé et has_diffs=True."""
        table_diff = TableDiff(object_name="t", table_name="t", organize_by_changed=True)
        assert table_diff.has_diffs is True
        assert table_diff.to_dict()["organize_by_changed"] is True


class TestTableDiffCreateStatementSerialization:
    """JSON keys `expected_create_statement` / `actual_create_statement` are
    rendered lazily from attached Table refs via the single render path.
    Public API surface preserved for downstream consumers (JSON output).
    """

    def _make_table(self, dialect="postgresql"):
        from core.sql_model.base import SqlColumn
        from core.sql_model.table import Table

        return Table(
            name="orders",
            schema="public",
            columns=[
                SqlColumn(name="id", data_type="serial", is_nullable=False, is_identity=True),
                SqlColumn(name="amount", data_type="numeric(10, 2)", is_nullable=False),
            ],
            constraints=[],
            dialect=dialect,
        )

    def test_keys_present_when_tables_attached(self):
        table = self._make_table()
        diff = TableDiff(
            object_name="orders",
            table_name="orders",
            expected_table=table,
            actual_table=table,
        )
        data = diff.to_dict()
        assert "expected_create_statement" in data
        assert "actual_create_statement" in data
        assert data["expected_create_statement"] is not None
        assert data["actual_create_statement"] is not None

    def test_keys_present_with_none_when_tables_missing(self):
        diff = TableDiff(object_name="orders", table_name="orders")
        data = diff.to_dict()
        assert data["expected_create_statement"] is None
        assert data["actual_create_statement"] is None

    def test_native_pg_types_in_serialized_ddl(self):
        table = self._make_table()
        diff = TableDiff(
            object_name="orders",
            table_name="orders",
            expected_table=table,
            actual_table=table,
        )
        data = diff.to_dict()
        ddl = data["expected_create_statement"].lower()
        assert "serial" in ddl
        assert "numeric(10, 2)" in ddl
        assert "decimal" not in ddl
        assert "generated by default as identity" not in ddl

    def test_dialect_resolved_from_table_when_set(self):
        """Non-PG dialect on Table honored — no silent postgres fallback."""
        mysql_table = self._make_table(dialect="mysql")
        diff = TableDiff(
            object_name="orders",
            table_name="orders",
            expected_table=mysql_table,
            actual_table=mysql_table,
        )
        data = diff.to_dict()
        ddl = data["expected_create_statement"]
        # MySQL identity strategy emits AUTO_INCREMENT, not GENERATED AS IDENTITY.
        assert "AUTO_INCREMENT" in ddl

    def test_dialect_resolved_from_sibling_when_one_side_none(self):
        """expected_table=None → dialect resolved from actual_table."""
        oracle_table = self._make_table(dialect="oracle")
        diff = TableDiff(
            object_name="orders",
            table_name="orders",
            expected_table=None,
            actual_table=oracle_table,
        )
        data = diff.to_dict()
        assert data["expected_create_statement"] is None
        ddl = data["actual_create_statement"]
        assert ddl is not None
        # Oracle identity strategy emits GENERATED AS IDENTITY.
        assert "GENERATED AS IDENTITY" in ddl

    def test_dialect_falls_back_to_postgres_when_none_set(self):
        """Both Table refs missing dialect → falls back to postgres."""
        from core.sql_model.base import SqlColumn
        from core.sql_model.table import Table

        table_no_dialect = Table(
            name="orders",
            schema="public",
            columns=[SqlColumn(name="id", data_type="serial", is_identity=True)],
            constraints=[],
            dialect=None,
        )
        diff = TableDiff(
            object_name="orders",
            table_name="orders",
            expected_table=table_no_dialect,
            actual_table=table_no_dialect,
        )
        data = diff.to_dict()
        ddl = data["expected_create_statement"]
        assert ddl is not None
        # Postgres serial type preserved.
        assert "serial" in ddl.lower()


class TestSchemaDiff:
    """Test SchemaDiff class."""

    def test_create_schema_diff_no_diffs(self):
        """Test creating schema diff with no differences."""
        schema_diff = SchemaDiff(object_name="public", schema_name="public")

        assert schema_diff.has_diffs is False
        assert schema_diff.object_type == "schema"

    def test_create_schema_diff_missing_tables(self):
        """Test creating schema diff with missing tables."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users", "orders"],
        )

        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.ERROR

    def test_create_schema_diff_modified_tables(self):
        """Test creating schema diff with modified tables."""
        table_diff = TableDiff(
            object_name="users",
            missing_columns=["email"],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            modified_tables=[table_diff],
        )

        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.ERROR

    def test_schema_diff_get_diff_count(self):
        """Test get_diff_count() method."""
        schema_diff = SchemaDiff(
            object_name="public",
            missing_tables=["t1", "t2"],
            extra_tables=["t3"],
            missing_views=["v1"],
        )

        counts = schema_diff.get_diff_count()

        assert counts["missing_tables"] == 2
        assert counts["extra_tables"] == 1
        assert counts["missing_views"] == 1

    def test_schema_diff_get_total_diff_count(self):
        """Test get_total_diff_count() method."""
        table_diff = TableDiff(object_name="users", missing_columns=["email"])

        schema_diff = SchemaDiff(
            object_name="public",
            missing_tables=["t1"],
            extra_views=["v1"],
            modified_tables=[table_diff],
        )

        total = schema_diff.get_total_diff_count()
        assert total == 3  # 1 missing table + 1 extra view + 1 modified table

    def test_schema_diff_to_dict(self):
        """Test to_dict() serialization."""
        table_diff = TableDiff(object_name="users", missing_columns=["email"])

        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["orders"],
            modified_tables=[table_diff],
        )

        data = schema_diff.to_dict()

        assert data["schema_name"] == "public"
        assert data["missing_tables"] == ["orders"]
        assert len(data["modified_tables"]) == 1
        assert "diff_count" in data
        assert "total_diff_count" in data
        assert data["total_diff_count"] == 2

    def test_schema_diff_str(self):
        """Test __str__() representation."""
        schema_diff = SchemaDiff(
            object_name="public",
            schema_name="public",
            missing_tables=["users", "orders"],
            extra_views=["v_temp"],
        )

        str_repr = str(schema_diff)
        assert "public" in str_repr
        assert "3 difference(s)" in str_repr
        assert "2 missing table(s)" in str_repr
        assert "1 extra view(s)" in str_repr

    def test_schema_diff_modified_indexes_error_escalates(self):
        """AC#5 — IndexDiff with ERROR severity escalates SchemaDiff to ERROR."""
        index_diff = IndexDiff(object_name="idx_email", columns_changed=True)
        schema_diff = SchemaDiff(
            object_name="public",
            modified_indexes=[index_diff],
        )
        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.ERROR

    def test_schema_diff_modified_triggers_error_escalates(self):
        """AC#6 — TriggerDiff with ERROR severity escalates SchemaDiff to ERROR."""
        trigger_diff = TriggerDiff(object_name="trg_audit", timing_changed=("BEFORE", "AFTER"))
        schema_diff = SchemaDiff(
            object_name="public",
            modified_triggers=[trigger_diff],
        )
        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.ERROR

    def test_schema_diff_modified_sequences_warning_only(self):
        """AC#7 — SequenceDiff with increment_changed=INFO → SchemaDiff WARNING."""
        seq_diff = SequenceDiff(
            object_name="seq_orders",
            increment_changed=(1, 10),
        )
        schema_diff = SchemaDiff(
            object_name="public",
            modified_sequences=[seq_diff],
        )
        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.WARNING

    def test_schema_diff_modified_database_links_error_escalates(self):
        """AC#8 — DatabaseLinkDiff with ERROR severity escalates SchemaDiff to ERROR."""
        link_diff = DatabaseLinkDiff(
            object_name="remote_db",
            host_changed=("host1", "host2"),
        )
        schema_diff = SchemaDiff(
            object_name="public",
            modified_database_links=[link_diff],
        )
        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.ERROR

    def test_schema_diff_modified_linked_servers_error_escalates(self):
        """AC#9 — LinkedServerDiff with ERROR severity escalates SchemaDiff to ERROR."""
        server_diff = LinkedServerDiff(
            object_name="prod_server",
            data_source_changed=("old_host", "new_host"),
        )
        schema_diff = SchemaDiff(
            object_name="dbo",
            modified_linked_servers=[server_diff],
        )
        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.ERROR

    def test_schema_diff_modified_objects_error_not_downgraded(self):
        """Regression — modified_tables WARNING + modified_indexes ERROR → SchemaDiff ERROR."""
        table_diff = TableDiff(
            object_name="users",
            extra_columns=["temp_col"],
        )
        assert table_diff.severity == DiffSeverity.WARNING

        index_diff = IndexDiff(object_name="idx_email", columns_changed=True)

        schema_diff = SchemaDiff(
            object_name="public",
            modified_tables=[table_diff],
            modified_indexes=[index_diff],
        )
        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.ERROR


class TestDiffModelIntegration:
    """Test integration between diff model classes."""

    def test_complete_schema_diff_hierarchy(self):
        """Test complete hierarchy from schema to column diffs."""
        # Create column diffs
        col_diff1 = ColumnDiff(
            object_name="email",
            data_type_diff=("VARCHAR(100)", "VARCHAR(255)"),
        )
        col_diff2 = ColumnDiff(
            object_name="age",
            nullable_diff=(False, True),
        )

        # Create table diff with column diffs
        table_diff = TableDiff(
            object_name="users",
            missing_columns=["phone"],
            modified_columns=[col_diff1, col_diff2],
        )

        # Create schema diff with table diff
        schema_diff = SchemaDiff(
            object_name="public",
            missing_tables=["orders"],
            modified_tables=[table_diff],
        )

        # Verify hierarchy
        assert schema_diff.has_diffs is True
        assert schema_diff.severity == DiffSeverity.ERROR
        assert len(schema_diff.modified_tables) == 1
        assert schema_diff.modified_tables[0].table_name == "users"
        assert len(schema_diff.modified_tables[0].modified_columns) == 2

    def test_to_dict_serialization_complete(self):
        """Test complete to_dict() serialization."""
        col_diff = ColumnDiff(
            object_name="status",
            data_type_diff=("VARCHAR(20)", "VARCHAR(50)"),
        )

        table_diff = TableDiff(
            object_name="orders",
            modified_columns=[col_diff],
        )

        schema_diff = SchemaDiff(
            object_name="public",
            modified_tables=[table_diff],
        )

        data = schema_diff.to_dict()

        # Verify complete structure
        assert "schema_name" in data
        assert "modified_tables" in data
        assert len(data["modified_tables"]) == 1
        assert "modified_columns" in data["modified_tables"][0]
        assert len(data["modified_tables"][0]["modified_columns"]) == 1
        assert "differences" in data["modified_tables"][0]["modified_columns"][0]


class TestSynonymDiff:
    """Test SynonymDiff class."""

    def test_create_synonym_diff_no_diffs(self):
        """Test creating synonym diff with no differences."""
        syn_diff = SynonymDiff(object_name="emp_synonym", synonym_name="emp_synonym")

        assert syn_diff.synonym_name == "emp_synonym"
        assert syn_diff.has_diffs is False
        assert syn_diff.object_type == "synonym"
        assert syn_diff.severity == DiffSeverity.INFO

    def test_create_synonym_diff_target_changed(self):
        """Test synonym diff with target object changed."""
        syn_diff = SynonymDiff(
            object_name="emp_synonym",
            synonym_name="emp_synonym",
            target_changed=("employees", "emp_table"),
            expected_target="public.employees",
            actual_target="public.emp_table",
        )

        assert syn_diff.has_diffs is True
        assert syn_diff.severity == DiffSeverity.ERROR
        assert syn_diff.target_changed == ("employees", "emp_table")
        assert syn_diff.expected_target == "public.employees"
        assert syn_diff.actual_target == "public.emp_table"

    def test_create_synonym_diff_target_schema_changed(self):
        """Test synonym diff with target schema changed."""
        syn_diff = SynonymDiff(
            object_name="emp_synonym",
            synonym_name="emp_synonym",
            target_schema_changed=("public", "hr"),
        )

        assert syn_diff.has_diffs is True
        assert syn_diff.severity == DiffSeverity.ERROR
        assert syn_diff.target_schema_changed == ("public", "hr")

    def test_create_synonym_diff_target_database_changed(self):
        """Test synonym diff with target database changed (SQL Server)."""
        syn_diff = SynonymDiff(
            object_name="emp_synonym",
            synonym_name="emp_synonym",
            target_database_changed=("db1", "db2"),
        )

        assert syn_diff.has_diffs is True
        assert syn_diff.severity == DiffSeverity.WARNING
        assert syn_diff.target_database_changed == ("db1", "db2")

    def test_create_synonym_diff_db_link_changed(self):
        """Test synonym diff with database link changed (Oracle)."""
        syn_diff = SynonymDiff(
            object_name="emp_synonym",
            synonym_name="emp_synonym",
            db_link_changed=("link1", "link2"),
        )

        assert syn_diff.has_diffs is True
        assert syn_diff.severity == DiffSeverity.WARNING
        assert syn_diff.db_link_changed == ("link1", "link2")

    def test_create_synonym_diff_multiple_changes(self):
        """Test synonym diff with multiple changes."""
        syn_diff = SynonymDiff(
            object_name="emp_synonym",
            synonym_name="emp_synonym",
            target_changed=("employees", "emp_table"),
            target_schema_changed=("public", "hr"),
            expected_target="public.employees",
            actual_target="hr.emp_table",
        )

        assert syn_diff.has_diffs is True
        assert syn_diff.severity == DiffSeverity.ERROR
        assert syn_diff.target_changed == ("employees", "emp_table")
        assert syn_diff.target_schema_changed == ("public", "hr")

    def test_synonym_diff_severity_field_based(self):
        """Test that synonym diffs have field-based severity (story 15-6)."""
        # target_changed → ERROR
        syn_diff1 = SynonymDiff(
            object_name="syn1",
            target_changed=("table1", "table2"),
        )
        assert syn_diff1.severity == DiffSeverity.ERROR

        # Multiple ERROR fields
        syn_diff2 = SynonymDiff(
            object_name="syn2",
            target_changed=("table1", "table2"),
            target_schema_changed=("schema1", "schema2"),
            target_database_changed=("db1", "db2"),
        )
        assert syn_diff2.severity == DiffSeverity.ERROR

    def test_synonym_diff_to_dict(self):
        """Test SynonymDiff to_dict() serialization."""
        syn_diff = SynonymDiff(
            object_name="emp_synonym",
            synonym_name="emp_synonym",
            target_changed=("employees", "emp_table"),
            expected_target="public.employees",
            actual_target="public.emp_table",
        )

        data = syn_diff.to_dict()

        assert data["object_name"] == "emp_synonym"
        assert data["object_type"] == "synonym"
        assert data["has_diffs"] is True
        assert data["severity"] == "error"

    def test_synonym_name_defaults_to_object_name(self):
        """Test that synonym_name defaults to object_name if not provided."""
        syn_diff = SynonymDiff(
            object_name="test_synonym",
            target_changed=("table1", "table2"),
        )

        assert syn_diff.synonym_name == "test_synonym"


class TestUserDefinedTypeDiff:
    """Test UserDefinedTypeDiff class."""

    def test_create_udt_diff_no_diffs(self):
        """Test creating UDT diff with no differences."""
        udt_diff = UserDefinedTypeDiff(object_name="address_type", type_name="address_type")

        assert udt_diff.type_name == "address_type"
        assert udt_diff.has_diffs is False
        assert udt_diff.object_type == "user_defined_type"
        assert udt_diff.severity == DiffSeverity.INFO

    def test_create_udt_diff_type_category_changed(self):
        """Test UDT diff with type category changed (ERROR severity)."""
        udt_diff = UserDefinedTypeDiff(
            object_name="address_type",
            type_name="address_type",
            type_category_changed=("COMPOSITE", "ENUM"),
            expected_type_category="COMPOSITE",
            actual_type_category="ENUM",
        )

        assert udt_diff.has_diffs is True
        assert udt_diff.severity == DiffSeverity.ERROR  # Category change is breaking
        assert udt_diff.type_category_changed == ("COMPOSITE", "ENUM")
        assert udt_diff.expected_type_category == "COMPOSITE"
        assert udt_diff.actual_type_category == "ENUM"

    def test_create_udt_diff_base_type_changed(self):
        """Test UDT diff with base type changed (ERROR severity)."""
        udt_diff = UserDefinedTypeDiff(
            object_name="email_type",
            type_name="email_type",
            base_type_changed=("VARCHAR(100)", "VARCHAR(255)"),
            expected_base_type="VARCHAR(100)",
            actual_base_type="VARCHAR(255)",
        )

        assert udt_diff.has_diffs is True
        assert udt_diff.severity == DiffSeverity.ERROR  # Base type change is breaking
        assert udt_diff.base_type_changed == ("VARCHAR(100)", "VARCHAR(255)")
        assert udt_diff.expected_base_type == "VARCHAR(100)"
        assert udt_diff.actual_base_type == "VARCHAR(255)"

    def test_create_udt_diff_attributes_changed(self):
        """Test UDT diff with attributes changed (WARNING severity)."""
        expected_attrs = [{"name": "street", "type": "VARCHAR(100)"}]
        actual_attrs = [{"name": "street", "type": "VARCHAR(200)"}]

        udt_diff = UserDefinedTypeDiff(
            object_name="address_type",
            type_name="address_type",
            attributes_changed=True,
            expected_attributes=expected_attrs,
            actual_attributes=actual_attrs,
        )

        assert udt_diff.has_diffs is True
        assert udt_diff.severity == DiffSeverity.WARNING  # Attribute change is warning
        assert udt_diff.attributes_changed is True
        assert udt_diff.expected_attributes == expected_attrs
        assert udt_diff.actual_attributes == actual_attrs

    def test_create_udt_diff_enum_values_changed(self):
        """Test UDT diff with enum values changed (WARNING severity)."""
        expected_values = ["active", "inactive"]
        actual_values = ["active", "inactive", "pending"]

        udt_diff = UserDefinedTypeDiff(
            object_name="status_enum",
            type_name="status_enum",
            enum_values_changed=True,
            expected_enum_values=expected_values,
            actual_enum_values=actual_values,
        )

        assert udt_diff.has_diffs is True
        assert udt_diff.severity == DiffSeverity.WARNING  # Enum value change is warning
        assert udt_diff.enum_values_changed is True
        assert udt_diff.expected_enum_values == expected_values
        assert udt_diff.actual_enum_values == actual_values

    def test_create_udt_diff_definition_changed(self):
        """Test UDT diff with definition changed (WARNING severity)."""
        udt_diff = UserDefinedTypeDiff(
            object_name="custom_type",
            type_name="custom_type",
            definition_changed=True,
        )

        assert udt_diff.has_diffs is True
        assert udt_diff.severity == DiffSeverity.WARNING  # Definition change is warning
        assert udt_diff.definition_changed is True

    def test_create_udt_diff_multiple_changes_with_category(self):
        """Test UDT diff with multiple changes including category (ERROR severity)."""
        udt_diff = UserDefinedTypeDiff(
            object_name="mixed_type",
            type_name="mixed_type",
            type_category_changed=("DOMAIN", "DISTINCT"),
            base_type_changed=("INTEGER", "BIGINT"),
            definition_changed=True,
        )

        assert udt_diff.has_diffs is True
        assert udt_diff.severity == DiffSeverity.ERROR  # Category change makes it ERROR
        assert udt_diff.type_category_changed == ("DOMAIN", "DISTINCT")
        assert udt_diff.base_type_changed == ("INTEGER", "BIGINT")
        assert udt_diff.definition_changed is True

    def test_create_udt_diff_multiple_changes_without_breaking(self):
        """Test UDT diff with multiple non-breaking changes (WARNING severity)."""
        udt_diff = UserDefinedTypeDiff(
            object_name="composite_type",
            type_name="composite_type",
            attributes_changed=True,
            definition_changed=True,
        )

        assert udt_diff.has_diffs is True
        assert udt_diff.severity == DiffSeverity.WARNING  # No breaking changes
        assert udt_diff.attributes_changed is True
        assert udt_diff.definition_changed is True

    def test_udt_diff_serialization(self):
        """Test UDT diff can be serialized to dict."""
        udt_diff = UserDefinedTypeDiff(
            object_name="email_type",
            type_name="email_type",
            base_type_changed=("VARCHAR(100)", "VARCHAR(255)"),
        )

        data = udt_diff.to_dict()

        assert data["object_name"] == "email_type"
        assert data["object_type"] == "user_defined_type"
        assert data["has_diffs"] is True
        assert data["severity"] == "error"

    def test_type_name_defaults_to_object_name(self):
        """Test that type_name defaults to object_name if not provided."""
        udt_diff = UserDefinedTypeDiff(
            object_name="test_type",
            attributes_changed=True,
        )

        assert udt_diff.type_name == "test_type"


class TestViewDiff:
    """Test ViewDiff class."""

    def test_create_view_diff_with_security_properties(self):
        """Test ViewDiff with security property differences."""
        view_diff = ViewDiff(
            object_name="secure_view",
            view_name="secure_view",
            security_definer_changed=(False, True),
            security_invoker_changed=(True, False),
        )

        assert view_diff.has_diffs is True
        assert view_diff.security_definer_changed == (False, True)
        assert view_diff.security_invoker_changed == (True, False)
        # Security changes should be ERROR severity
        assert view_diff.severity == DiffSeverity.ERROR

    def test_view_diff_security_severity(self):
        """Test ViewDiff severity calculation for security changes."""
        # Security changes (should be ERROR)
        view_diff = ViewDiff(
            object_name="secure_view",
            view_name="secure_view",
            security_definer_changed=(False, True),
        )
        assert view_diff.severity == DiffSeverity.ERROR

        # Definition changes only (should be WARNING)
        view_diff = ViewDiff(
            object_name="test_view",
            view_name="test_view",
            definition_changed=True,
        )
        assert view_diff.severity == DiffSeverity.WARNING

    def test_view_diff_to_dict_with_security(self):
        """Test ViewDiff to_dict() with security properties."""
        view_diff = ViewDiff(
            object_name="secure_view",
            view_name="secure_view",
            security_definer_changed=(False, True),
        )

        data = view_diff.to_dict()
        assert "security_definer" in data.get("differences", {})
        assert data["severity"] == "error"


class TestSequenceDiffTruthiness:
    """Tests for NEW-BUG-10: SequenceDiff with (None, None) tuples should not report diffs."""

    def test_sequence_diff_all_none_none_tuples_has_no_diffs(self):
        """SequenceDiff with all fields set to (None, None) should have has_diffs == False."""
        from core.comparison.diff_models import SequenceDiff

        diff = SequenceDiff(
            object_name="test_seq",
            sequence_name="test_seq",
            start_value_changed=None,
            increment_changed=None,
            min_value_changed=None,
            max_value_changed=None,
            cycle_changed=None,
            temp_changed=None,
            owned_by_changed=None,
        )
        assert diff.has_diffs is False


class TestViewDiffToDict:
    """Tests for NEW-BUG-11: ViewDiff.to_dict() should serialize tuple fields as dicts."""

    def test_to_dict_serializes_tuple_fields_as_dicts(self):
        """ViewDiff.to_dict() should return {'expected': val, 'actual': val} for modified tuple fields."""
        from core.comparison.diff_models import ViewDiff

        view_diff = ViewDiff(
            object_name="test_view",
            view_name="test_view",
            materialized_changed=(True, False),
        )
        data = view_diff.to_dict()
        mat = data["materialized_changed"]
        assert isinstance(mat, dict)
        assert mat["expected"] is True
        assert mat["actual"] is False


class TestSchemaDiffDataDriven:
    """Tests for SchemaDiff data-driven refactoring (Story 13-11)."""

    # AC#8 — get_diff_count() data-driven
    def test_get_diff_count_returns_51_keys(self):
        """get_diff_count() returns exactly 51 keys, all zero for empty SchemaDiff."""
        diff = SchemaDiff(object_name="test")
        counts = diff.get_diff_count()
        assert len(counts) == 51
        assert all(v == 0 for v in counts.values())

    def test_get_diff_count_counts_correctly(self):
        """get_diff_count() reflects actual list lengths."""
        diff = SchemaDiff(object_name="test", missing_views=["v1", "v2"])
        counts = diff.get_diff_count()
        assert counts["missing_views"] == 2
        assert counts["extra_views"] == 0

    # AC#9 — to_dict() data-driven
    def test_to_dict_contains_all_51_fields(self):
        """to_dict() contains all 51 object-type keys + schema_name + diff_count + total_diff_count."""
        diff = SchemaDiff(object_name="s1")
        data = diff.to_dict()
        assert "schema_name" in data
        assert "diff_count" in data
        assert "total_diff_count" in data
        expected_keys = set()
        for prefix, _ in SchemaDiff._OBJECT_TYPE_LABELS:
            for action in ("missing", "extra", "modified"):
                expected_keys.add(f"{action}_{prefix}")
        assert expected_keys.issubset(data.keys())
        assert len(expected_keys) == 51

    # AC#10 — _calculate_diffs() has_diffs data-driven
    def test_has_diffs_false_when_empty(self):
        """Empty SchemaDiff has has_diffs == False."""
        diff = SchemaDiff(object_name="s")
        assert diff.has_diffs is False

    def test_has_diffs_true_for_each_action_prefix(self):
        """has_diffs is True for missing_tables, extra_indexes, missing_user_defined_types."""
        for field_name in ("missing_tables", "extra_indexes", "missing_user_defined_types"):
            diff = SchemaDiff(object_name="s", **{field_name: ["x"]})
            assert diff.has_diffs is True, f"Expected has_diffs=True for {field_name}"

    def test_has_diffs_true_for_modified_prefix(self):
        """modified_* lists trigger has_diffs == True."""
        table_diff = TableDiff(object_name="t", missing_columns=["c"])
        diff = SchemaDiff(object_name="s", modified_tables=[table_diff])
        assert diff.has_diffs is True

    # AC#11 — Severity preserved
    def test_severity_error_on_missing_tables(self):
        """missing_tables triggers DiffSeverity.ERROR."""
        diff = SchemaDiff(object_name="s", missing_tables=["t1"])
        assert diff.severity == DiffSeverity.ERROR

    def test_severity_warning_on_extra_views(self):
        """extra_views (without missing critical types) triggers DiffSeverity.WARNING."""
        diff = SchemaDiff(object_name="s", extra_views=["v1"])
        assert diff.severity == DiffSeverity.WARNING

    def test_severity_error_on_extra_user_defined_types(self):
        """extra_user_defined_types triggers DiffSeverity.ERROR (special case)."""
        diff = SchemaDiff(object_name="s", extra_user_defined_types=["MyType"])
        assert diff.severity == DiffSeverity.ERROR

    def test_to_dict_modified_lists_are_serialized(self):
        """to_dict() serializes modified_* lists via .to_dict(), not as raw objects."""
        table_diff = TableDiff(object_name="users", missing_columns=["email"])
        diff = SchemaDiff(object_name="s", modified_tables=[table_diff])
        data = diff.to_dict()
        assert isinstance(data["modified_tables"], list)
        assert len(data["modified_tables"]) == 1
        assert isinstance(
            data["modified_tables"][0], dict
        ), "modified_* items must be dicts (serialized via .to_dict()), not raw objects"


class TestRoutineDiff:
    """Tests for RoutineDiff base class and ProcedureDiff/FunctionDiff inheritance (AC#6)."""

    def test_procedure_and_function_are_instances_of_routine_diff(self):
        """ProcedureDiff and FunctionDiff are subclasses of RoutineDiff."""
        proc = ProcedureDiff(object_name="sp_test")
        func = FunctionDiff(object_name="fn_test")
        assert isinstance(proc, RoutineDiff), "ProcedureDiff must be a RoutineDiff"
        assert isinstance(func, RoutineDiff), "FunctionDiff must be a RoutineDiff"

    def test_has_base_diffs_false_when_clean(self):
        """_has_base_diffs() returns False when no fields are changed."""
        proc = ProcedureDiff(object_name="sp_test")
        assert proc._has_base_diffs() is False

    def test_has_base_diffs_true_for_definition_changed(self):
        """_has_base_diffs() returns True when definition_changed is True."""
        proc = ProcedureDiff(object_name="sp_test", definition_changed=True)
        assert proc._has_base_diffs() is True

    def test_has_base_diffs_true_for_volatility_changed(self):
        """_has_base_diffs() returns True when a tuple field is not None."""
        proc = ProcedureDiff(object_name="sp_test", volatility_changed=("VOLATILE", "STABLE"))
        assert proc._has_base_diffs() is True

    def test_function_diff_has_diffs_true_for_return_type_changed(self):
        """FunctionDiff.has_diffs is True when only return_type_changed is set (AC#7)."""
        func = FunctionDiff(object_name="fn_test", return_type_changed=("int", "bigint"))
        assert func.has_diffs is True
        assert func.severity == DiffSeverity.ERROR

    def test_procedure_diff_has_no_return_type_changed(self):
        """ProcedureDiff does not have return_type_changed attribute (AC#8)."""
        proc = ProcedureDiff(object_name="sp_test")
        assert not hasattr(proc, "return_type_changed")

    def test_procedure_diff_parameters_changed_is_error_severity(self):
        """ProcedureDiff with parameters_changed=True has severity ERROR (AC#3)."""
        proc = ProcedureDiff(object_name="sp_test", parameters_changed=True)
        assert proc.has_diffs is True
        assert proc.severity == DiffSeverity.ERROR

    def test_function_diff_definition_changed_only_is_warning_severity(self):
        """FunctionDiff with only definition_changed has severity WARNING (AC#4)."""
        func = FunctionDiff(object_name="fn_test", definition_changed=True)
        assert func.has_diffs is True
        assert func.severity == DiffSeverity.WARNING


@pytest.mark.unit
class TestIndexDiffSeverity:
    """Tests story 15-6 : IndexDiff severity field-based (AC#1)."""

    def test_columns_changed_is_error(self):
        diff = IndexDiff(object_name="idx", columns_changed=True)
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "columns_changed must be ERROR"

    def test_uniqueness_changed_is_error(self):
        diff = IndexDiff(object_name="idx", uniqueness_changed=("UNIQUE", "NON_UNIQUE"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "uniqueness_changed must be ERROR"

    def test_type_changed_only_is_warning(self):
        diff = IndexDiff(object_name="idx", type_changed=("BTREE", "HASH"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "type_changed alone must be WARNING"

    def test_tablespace_changed_only_is_warning(self):
        diff = IndexDiff(object_name="idx", tablespace_changed=("TBS1", "TBS2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "tablespace_changed alone must be WARNING"


@pytest.mark.unit
@pytest.mark.unit
class TestSequenceDiffSeverity:
    """Tests story 15-6 : SequenceDiff severity field-based (AC#2)."""

    def test_owned_by_changed_is_warning(self):
        diff = SequenceDiff(object_name="seq", owned_by_changed=(("t", "id"), ("t2", "id")))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "owned_by_changed must be WARNING"

    def test_increment_changed_is_info(self):
        diff = SequenceDiff(object_name="seq", increment_changed=(1, 10))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.INFO, "increment_changed must be INFO"

    def test_start_value_changed_is_info(self):
        diff = SequenceDiff(object_name="seq", start_value_changed=(1, 100))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.INFO, "start_value_changed must be INFO"


@pytest.mark.unit
class TestTriggerDiffSeverity:
    """Tests story 15-6 : TriggerDiff severity field-based (AC#3)."""

    def test_timing_changed_is_error(self):
        diff = TriggerDiff(object_name="trg", timing_changed=("BEFORE", "AFTER"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "timing_changed must be ERROR"

    def test_event_changed_is_error(self):
        diff = TriggerDiff(object_name="trg", event_changed=("INSERT", "UPDATE"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "event_changed must be ERROR"

    def test_function_changed_is_error(self):
        diff = TriggerDiff(object_name="trg", function_changed=("fn_old", "fn_new"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "function_changed must be ERROR"

    def test_definition_changed_only_is_warning(self):
        diff = TriggerDiff(object_name="trg", definition_changed=True)
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "definition_changed alone must be WARNING"

    def test_enabled_changed_only_is_warning(self):
        diff = TriggerDiff(object_name="trg", enabled_changed=(True, False))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "enabled_changed alone must be WARNING"

    def test_function_schema_changed_is_error(self):
        diff = TriggerDiff(object_name="trg", function_schema_changed=("public", "hr"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "function_schema_changed must be ERROR"

    def test_function_arguments_changed_is_error(self):
        diff = TriggerDiff(object_name="trg", function_arguments_changed=("()", "(int)"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "function_arguments_changed must be ERROR"

    def test_constraint_trigger_changed_is_error(self):
        diff = TriggerDiff(object_name="trg", constraint_trigger_changed=(False, True))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "constraint_trigger_changed must be ERROR"


@pytest.mark.unit
class TestSynonymDiffSeverity:
    """Tests story 15-6 : SynonymDiff severity field-based (AC#4)."""

    def test_target_changed_is_error(self):
        diff = SynonymDiff(object_name="syn", target_changed=("old_tbl", "new_tbl"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "target_changed must be ERROR"

    def test_target_schema_changed_is_error(self):
        diff = SynonymDiff(object_name="syn", target_schema_changed=("public", "hr"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "target_schema_changed must be ERROR"

    def test_db_link_changed_only_is_warning(self):
        diff = SynonymDiff(object_name="syn", db_link_changed=("link1", "link2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "db_link_changed alone must be WARNING"


@pytest.mark.unit
class TestPackageDiffSeverity:
    """Tests story 15-6 : PackageDiff severity field-based (AC#4)."""

    def test_spec_changed_is_error(self):
        diff = PackageDiff(object_name="pkg", spec_changed=True)
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "spec_changed must be ERROR"

    def test_body_changed_only_is_warning(self):
        diff = PackageDiff(object_name="pkg", body_changed=True)
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "body_changed alone must be WARNING"


@pytest.mark.unit
class TestFdwDiffSeverity:
    """Tests story 15-6 : ForeignDataWrapperDiff severity field-based (AC#4)."""

    def test_handler_changed_is_error(self):
        diff = ForeignDataWrapperDiff(object_name="fdw", handler_changed=("h1", "h2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "handler_changed must be ERROR"

    def test_options_changed_only_is_warning(self):
        diff = ForeignDataWrapperDiff(object_name="fdw", options_changed=("o1", "o2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "options_changed alone must be WARNING"


@pytest.mark.unit
class TestDbLinkDiffSeverity:
    """Tests story 15-6 : DatabaseLinkDiff severity field-based (AC#5)."""

    def test_host_changed_is_error(self):
        diff = DatabaseLinkDiff(object_name="dblink", host_changed=("h1", "h2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "host_changed must be ERROR"

    def test_public_changed_only_is_warning(self):
        diff = DatabaseLinkDiff(object_name="dblink", public_changed=(True, False))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "public_changed alone must be WARNING"


@pytest.mark.unit
class TestLinkedServerDiffSeverity:
    """Tests story 15-6 : LinkedServerDiff severity field-based (AC#5)."""

    def test_data_source_changed_is_error(self):
        diff = LinkedServerDiff(object_name="srv", data_source_changed=("ds1", "ds2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "data_source_changed must be ERROR"

    def test_catalog_changed_only_is_warning(self):
        diff = LinkedServerDiff(object_name="srv", catalog_changed=("cat1", "cat2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "catalog_changed alone must be WARNING"


@pytest.mark.unit
class TestForeignServerDiffSeverity:
    """Tests story 15-6 : ForeignServerDiff severity field-based (AC#5)."""

    def test_fdw_changed_is_error(self):
        diff = ForeignServerDiff(object_name="fsrv", fdw_changed=("fdw1", "fdw2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.ERROR, "fdw_changed must be ERROR"

    def test_dbname_changed_only_is_warning(self):
        diff = ForeignServerDiff(object_name="fsrv", dbname_changed=("db1", "db2"))
        assert diff.has_diffs is True
        assert diff.severity == DiffSeverity.WARNING, "dbname_changed alone must be WARNING"
