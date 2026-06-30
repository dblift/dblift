"""Tests for core.sql_model.constraint_validator — ValidationError and ConstraintValidator."""

from unittest.mock import Mock

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.constraint_validator import ConstraintValidator, ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_table(name, columns=None, constraints=None):
    t = Mock()
    t.name = name
    t.columns = columns or []
    t.constraints = constraints or []
    return t


def make_column(
    name,
    data_type="VARCHAR(100)",
    nullable=True,
    is_primary_key=False,
    is_computed=False,
    computed_expression=None,
    computed_stored=True,
):
    c = Mock(spec=SqlColumn)
    c.name = name
    c.data_type = data_type
    c.nullable = nullable
    c.is_primary_key = is_primary_key
    c.is_computed = is_computed
    c.computed_expression = computed_expression
    c.computed_stored = computed_stored
    return c


def make_constraint(
    name,
    constraint_type,
    column_names,
    reference_table=None,
    reference_columns=None,
    check_expression=None,
    columns=None,
):
    c = Mock(spec=SqlConstraint)
    c.name = name
    c.constraint_type = constraint_type
    c.column_names = column_names
    c.reference_table = reference_table
    c.reference_columns = reference_columns
    c.check_expression = check_expression
    c.columns = columns
    return c


# ---------------------------------------------------------------------------
# ValidationError dataclass
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidationError:

    def test_required_fields(self):
        err = ValidationError(severity="error", message="msg", object_type="table", object_name="t")
        assert err.severity == "error"
        assert err.message == "msg"
        assert err.property_name is None
        assert err.suggestion is None

    def test_optional_fields(self):
        err = ValidationError(
            severity="warning",
            message="m",
            object_type="column",
            object_name="c",
            property_name="nullable",
            suggestion="fix it",
        )
        assert err.property_name == "nullable"
        assert err.suggestion == "fix it"


# ---------------------------------------------------------------------------
# Constructor
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestConstructor:

    def test_default_dialect(self):
        # ADR-26 E: the validator no longer self-supplies a dialect; the
        # caller (the DDL generator) passes ``self.table.dialect or ""``.
        v = ConstraintValidator()
        assert v.dialect == ""

    def test_dialect_lowered(self):
        v = ConstraintValidator(dialect="MYSQL")
        assert v.dialect == "mysql"


# ---------------------------------------------------------------------------
# validate_table
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateTable:

    def test_no_columns_returns_error_and_stops_early(self):
        table = make_table("empty")
        errors = ConstraintValidator().validate_table(table)
        assert len(errors) == 1
        assert errors[0].severity == "error"
        assert "no columns" in errors[0].message

    def test_valid_table_no_errors(self):
        col = make_column("id", nullable=False)
        table = make_table("ok", columns=[col])
        errors = ConstraintValidator().validate_table(table)
        assert errors == []

    def test_calls_all_validators(self):
        """Ensure validate_table aggregates errors from multiple sub-validators."""
        col = make_column("id", nullable=False, is_computed=True, computed_expression=None)
        pk = make_constraint("pk1", ConstraintType.PRIMARY_KEY, ["id"])
        pk2 = make_constraint("pk2", ConstraintType.PRIMARY_KEY, ["id"])
        table = make_table("t", columns=[col], constraints=[pk, pk2])
        errors = ConstraintValidator().validate_table(table)
        # Should contain at least PK duplication + computed column errors
        assert len(errors) >= 2


# ---------------------------------------------------------------------------
# _validate_primary_keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidatePrimaryKeys:

    def setup_method(self):
        self.v = ConstraintValidator()

    def test_no_constraints(self):
        table = make_table("t", columns=[make_column("id")])
        table.constraints = None
        assert self.v._validate_primary_keys(table) == []

    def test_duplicate_pk_same_columns(self):
        col = make_column("id", nullable=False)
        pk1 = make_constraint("pk1", ConstraintType.PRIMARY_KEY, ["id"])
        pk2 = make_constraint("pk2", ConstraintType.PRIMARY_KEY, ["id"])
        table = make_table("t", columns=[col], constraints=[pk1, pk2])
        errors = self.v._validate_primary_keys(table)
        assert any("Duplicate PRIMARY KEY" in e.message for e in errors)

    def test_multiple_pks_different_columns(self):
        cols = [make_column("a", nullable=False), make_column("b", nullable=False)]
        pk1 = make_constraint("pk1", ConstraintType.PRIMARY_KEY, ["a"])
        pk2 = make_constraint("pk2", ConstraintType.PRIMARY_KEY, ["b"])
        table = make_table("t", columns=cols, constraints=[pk1, pk2])
        errors = self.v._validate_primary_keys(table)
        assert any("Multiple PRIMARY KEY" in e.message for e in errors)

    def test_pk_references_nonexistent_column(self):
        col = make_column("id", nullable=False)
        pk = make_constraint("pk1", ConstraintType.PRIMARY_KEY, ["missing"])
        table = make_table("t", columns=[col], constraints=[pk])
        errors = self.v._validate_primary_keys(table)
        assert any("non-existent column 'missing'" in e.message for e in errors)
        assert any(e.severity == "error" for e in errors)

    def test_pk_column_is_nullable(self):
        col = make_column("id", nullable=True)
        pk = make_constraint("pk1", ConstraintType.PRIMARY_KEY, ["id"])
        table = make_table("t", columns=[col], constraints=[pk])
        errors = self.v._validate_primary_keys(table)
        assert any(e.severity == "warning" and "nullable" in e.message for e in errors)

    def test_inline_pk_and_table_pk_conflict(self):
        col_a = make_column("a", nullable=False, is_primary_key=True)
        col_b = make_column("b", nullable=False)
        pk = make_constraint("pk1", ConstraintType.PRIMARY_KEY, ["b"])
        table = make_table("t", columns=[col_a, col_b], constraints=[pk])
        errors = self.v._validate_primary_keys(table)
        assert any("Conflicting PRIMARY KEY" in e.message for e in errors)

    def test_inline_pk_matching_table_pk_no_conflict(self):
        col = make_column("id", nullable=False, is_primary_key=True)
        pk = make_constraint("pk1", ConstraintType.PRIMARY_KEY, ["id"])
        table = make_table("t", columns=[col], constraints=[pk])
        errors = self.v._validate_primary_keys(table)
        assert not any("Conflicting" in e.message for e in errors)


# ---------------------------------------------------------------------------
# _validate_foreign_keys
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateForeignKeys:

    def setup_method(self):
        self.v = ConstraintValidator()

    def test_fk_column_not_exist(self):
        col = make_column("id")
        fk = make_constraint(
            "fk1",
            ConstraintType.FOREIGN_KEY,
            ["ghost"],
            reference_table="other",
            reference_columns=["id"],
        )
        table = make_table("t", columns=[col], constraints=[fk])
        errors = self.v._validate_foreign_keys(table)
        assert any("non-existent column 'ghost'" in e.message for e in errors)

    def test_fk_missing_reference_table(self):
        col = make_column("ref_id")
        fk = make_constraint(
            "fk1",
            ConstraintType.FOREIGN_KEY,
            ["ref_id"],
            reference_table=None,
            reference_columns=["id"],
        )
        table = make_table("t", columns=[col], constraints=[fk])
        errors = self.v._validate_foreign_keys(table)
        assert any("missing referenced table" in e.message for e in errors)

    def test_fk_missing_reference_columns(self):
        col = make_column("ref_id")
        fk = make_constraint(
            "fk1",
            ConstraintType.FOREIGN_KEY,
            ["ref_id"],
            reference_table="other",
            reference_columns=None,
        )
        table = make_table("t", columns=[col], constraints=[fk])
        errors = self.v._validate_foreign_keys(table)
        assert any(
            e.severity == "warning" and "missing referenced columns" in e.message for e in errors
        )

    def test_fk_column_count_mismatch(self):
        cols = [make_column("a"), make_column("b")]
        fk = make_constraint(
            "fk1",
            ConstraintType.FOREIGN_KEY,
            ["a", "b"],
            reference_table="other",
            reference_columns=["x"],
        )
        table = make_table("t", columns=cols, constraints=[fk])
        errors = self.v._validate_foreign_keys(table)
        assert any("column count mismatch" in e.message for e in errors)

    def test_valid_fk_no_errors(self):
        col = make_column("ref_id")
        fk = make_constraint(
            "fk1",
            ConstraintType.FOREIGN_KEY,
            ["ref_id"],
            reference_table="other",
            reference_columns=["id"],
        )
        table = make_table("t", columns=[col], constraints=[fk])
        errors = self.v._validate_foreign_keys(table)
        assert errors == []


# ---------------------------------------------------------------------------
# _validate_unique_constraints
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateUniqueConstraints:

    def setup_method(self):
        self.v = ConstraintValidator()

    def test_column_does_not_exist(self):
        col = make_column("id")
        uq = make_constraint("uq1", ConstraintType.UNIQUE, ["missing"])
        table = make_table("t", columns=[col], constraints=[uq])
        errors = self.v._validate_unique_constraints(table)
        assert any("non-existent column" in e.message for e in errors)

    def test_empty_column_list(self):
        col = make_column("id")
        uq = make_constraint("uq1", ConstraintType.UNIQUE, [])
        table = make_table("t", columns=[col], constraints=[uq])
        errors = self.v._validate_unique_constraints(table)
        assert any("has no columns" in e.message for e in errors)

    def test_duplicate_unique_constraints(self):
        col = make_column("email")
        uq1 = make_constraint("uq1", ConstraintType.UNIQUE, ["email"])
        uq2 = make_constraint("uq2", ConstraintType.UNIQUE, ["email"])
        table = make_table("t", columns=[col], constraints=[uq1, uq2])
        errors = self.v._validate_unique_constraints(table)
        assert any(e.severity == "warning" and "Duplicate UNIQUE" in e.message for e in errors)

    def test_valid_unique(self):
        col = make_column("email")
        uq = make_constraint("uq1", ConstraintType.UNIQUE, ["email"])
        table = make_table("t", columns=[col], constraints=[uq])
        errors = self.v._validate_unique_constraints(table)
        assert errors == []


# ---------------------------------------------------------------------------
# _validate_check_constraints
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateCheckConstraints:

    def setup_method(self):
        self.v = ConstraintValidator()

    def test_no_check_expression(self):
        col = make_column("val")
        ck = make_constraint(
            "ck1", ConstraintType.CHECK, ["val"], check_expression=None, columns=None
        )
        table = make_table("t", columns=[col], constraints=[ck])
        errors = self.v._validate_check_constraints(table)
        assert any(
            e.severity == "warning" and "no meaningful expression" in e.message for e in errors
        )

    def test_trivial_expression_1eq1(self):
        col = make_column("val")
        ck = make_constraint(
            "ck1", ConstraintType.CHECK, ["val"], check_expression="1=1", columns=None
        )
        table = make_table("t", columns=[col], constraints=[ck])
        errors = self.v._validate_check_constraints(table)
        assert any("no meaningful expression" in e.message for e in errors)

    def test_trivial_expression_parenthesised(self):
        col = make_column("val")
        ck = make_constraint(
            "ck1", ConstraintType.CHECK, ["val"], check_expression="(1=1)", columns=None
        )
        table = make_table("t", columns=[col], constraints=[ck])
        errors = self.v._validate_check_constraints(table)
        assert any("no meaningful expression" in e.message for e in errors)

    def test_valid_check_expression(self):
        col = make_column("age")
        ck = make_constraint(
            "ck_age", ConstraintType.CHECK, ["age"], check_expression="age > 0", columns=None
        )
        table = make_table("t", columns=[col], constraints=[ck])
        errors = self.v._validate_check_constraints(table)
        assert errors == []

    def test_fallback_to_columns_field(self):
        """When check_expression is None, columns list is joined as expression."""
        col = make_column("val")
        ck = make_constraint(
            "ck1", ConstraintType.CHECK, ["val"], check_expression=None, columns=["val", ">", "0"]
        )
        table = make_table("t", columns=[col], constraints=[ck])
        errors = self.v._validate_check_constraints(table)
        assert errors == []


# ---------------------------------------------------------------------------
# _validate_constraint_names
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateConstraintNames:

    def setup_method(self):
        self.v = ConstraintValidator()

    def test_duplicate_names(self):
        col = make_column("id")
        c1 = make_constraint("my_constraint", ConstraintType.UNIQUE, ["id"])
        c2 = make_constraint(
            "my_constraint", ConstraintType.CHECK, ["id"], check_expression="id > 0"
        )
        table = make_table("t", columns=[col], constraints=[c1, c2])
        errors = self.v._validate_constraint_names(table)
        assert any("Duplicate constraint name" in e.message for e in errors)

    def test_duplicate_names_case_insensitive(self):
        col = make_column("id")
        c1 = make_constraint("MY_CONST", ConstraintType.UNIQUE, ["id"])
        c2 = make_constraint("my_const", ConstraintType.CHECK, ["id"], check_expression="id > 0")
        table = make_table("t", columns=[col], constraints=[c1, c2])
        errors = self.v._validate_constraint_names(table)
        assert any("Duplicate constraint name" in e.message for e in errors)

    def test_system_generated_names_skipped(self):
        col = make_column("id")
        c1 = make_constraint("SYS_C001", ConstraintType.UNIQUE, ["id"])
        c2 = make_constraint("SYS_C001", ConstraintType.CHECK, ["id"], check_expression="id > 0")
        table = make_table("t", columns=[col], constraints=[c1, c2])
        errors = self.v._validate_constraint_names(table)
        assert not any("Duplicate constraint name" in e.message for e in errors)

    def test_none_names_skipped(self):
        col = make_column("id")
        c1 = make_constraint(None, ConstraintType.UNIQUE, ["id"])
        c2 = make_constraint(None, ConstraintType.CHECK, ["id"], check_expression="id > 0")
        table = make_table("t", columns=[col], constraints=[c1, c2])
        errors = self.v._validate_constraint_names(table)
        assert errors == []


# ---------------------------------------------------------------------------
# _validate_column_references
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateColumnReferences:

    def setup_method(self):
        self.v = ConstraintValidator()

    def test_nonexistent_column(self):
        col = make_column("id")
        c = make_constraint("c1", ConstraintType.UNIQUE, ["ghost"])
        table = make_table("t", columns=[col], constraints=[c])
        errors = self.v._validate_column_references(table)
        assert any("non-existent column 'ghost'" in e.message for e in errors)

    def test_existing_column_no_error(self):
        col = make_column("id")
        c = make_constraint("c1", ConstraintType.UNIQUE, ["id"])
        table = make_table("t", columns=[col], constraints=[c])
        errors = self.v._validate_column_references(table)
        assert errors == []

    def test_case_insensitive_match(self):
        col = make_column("ID")
        c = make_constraint("c1", ConstraintType.UNIQUE, ["id"])
        table = make_table("t", columns=[col], constraints=[c])
        errors = self.v._validate_column_references(table)
        assert errors == []


# ---------------------------------------------------------------------------
# _validate_computed_columns
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestValidateComputedColumns:

    def test_computed_no_expression(self):
        col = make_column("total", is_computed=True, computed_expression=None)
        table = make_table("t", columns=[col])
        errors = ConstraintValidator().validate_table(table)
        assert any("no expression" in e.message and e.severity == "error" for e in errors)

    def test_postgresql_virtual_computed_warning(self):
        col = make_column(
            "total", is_computed=True, computed_expression="a + b", computed_stored=False
        )
        table = make_table("t", columns=[col])
        errors = ConstraintValidator(dialect="postgresql")._validate_computed_columns(table)
        assert any(e.severity == "warning" and "VIRTUAL" in e.message for e in errors)

    def test_mysql_virtual_computed_no_warning(self):
        col = make_column(
            "total", is_computed=True, computed_expression="a + b", computed_stored=False
        )
        table = make_table("t", columns=[col])
        errors = ConstraintValidator(dialect="mysql")._validate_computed_columns(table)
        assert not any("VIRTUAL" in e.message for e in errors)

    def test_computed_with_expression_no_error(self):
        col = make_column(
            "total", is_computed=True, computed_expression="a + b", computed_stored=True
        )
        table = make_table("t", columns=[col])
        errors = ConstraintValidator()._validate_computed_columns(table)
        assert errors == []

    def test_non_computed_column_ignored(self):
        col = make_column("name", is_computed=False)
        table = make_table("t", columns=[col])
        errors = ConstraintValidator()._validate_computed_columns(table)
        assert errors == []


# ---------------------------------------------------------------------------
# _find_column
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFindColumn:

    def test_case_insensitive_search(self):
        v = ConstraintValidator()
        col = make_column("UserName")
        table = make_table("t", columns=[col])
        assert v._find_column(table, "username") is col
        assert v._find_column(table, "USERNAME") is col
        assert v._find_column(table, "UserName") is col

    def test_not_found_returns_none(self):
        v = ConstraintValidator()
        table = make_table("t", columns=[make_column("id")])
        assert v._find_column(table, "missing") is None


# ---------------------------------------------------------------------------
# _is_system_constraint_name
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestIsSystemConstraintName:

    def setup_method(self):
        self.v = ConstraintValidator()

    def test_none_returns_true(self):
        assert self.v._is_system_constraint_name(None) is True

    def test_empty_string_returns_true(self):
        assert self.v._is_system_constraint_name("") is True

    def test_oracle_sys_underscore(self):
        assert self.v._is_system_constraint_name("SYS_C00123") is True

    def test_oracle_sys_dollar(self):
        assert self.v._is_system_constraint_name("SYS$00123") is True

    def test_db2_sql_digits(self):
        assert self.v._is_system_constraint_name("SQL251208171332370") is True

    def test_db2_sql_alpha_not_system(self):
        assert self.v._is_system_constraint_name("SQLHelper") is False

    def test_pk_prefix(self):
        assert self.v._is_system_constraint_name("pk_users") is True

    def test_fk_prefix(self):
        assert self.v._is_system_constraint_name("fk_orders_user") is True

    def test_uk_prefix(self):
        assert self.v._is_system_constraint_name("uk_email") is True

    def test_ck_prefix(self):
        assert self.v._is_system_constraint_name("ck_age_positive") is True

    def test_dollar_prefix(self):
        assert self.v._is_system_constraint_name("$generated_001") is True

    def test_normal_name_is_not_system(self):
        assert self.v._is_system_constraint_name("my_unique_idx") is False

    def test_case_insensitive_sys(self):
        assert self.v._is_system_constraint_name("sys_c999") is True
