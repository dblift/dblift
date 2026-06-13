"""Tests for property comparator."""

from unittest.mock import Mock

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.table import Table
from core.validation.property_comparator import (
    ComparisonResult,
    PropertyComparator,
    PropertyDifference,
)


@pytest.mark.unit
class TestPropertyDifference:
    """Test PropertyDifference dataclass."""

    def test_property_difference_creation(self):
        """Test creating a property difference."""
        diff = PropertyDifference(
            object_type="table",
            object_name="test_table",
            property_name="column_count",
            original_value=5,
            regenerated_value=3,
            severity="error",
        )

        assert diff.object_type == "table"
        assert diff.object_name == "test_table"
        assert diff.property_name == "column_count"
        assert diff.original_value == 5
        assert diff.regenerated_value == 3
        assert diff.severity == "error"

    def test_property_difference_str(self):
        """Test string representation."""
        diff = PropertyDifference(
            object_type="column",
            object_name="test_col",
            property_name="data_type",
            original_value="INTEGER",
            regenerated_value="BIGINT",
        )

        result = str(diff)
        assert "column" in result
        assert "test_col" in result
        assert "data_type" in result
        assert "INTEGER" in result
        assert "BIGINT" in result


@pytest.mark.unit
class TestComparisonResult:
    """Test ComparisonResult dataclass."""

    def test_comparison_result_creation(self):
        """Test creating a comparison result."""
        result = ComparisonResult()

        assert result.differences == []
        assert result.errors == []
        assert result.warnings == []

    def test_is_match(self):
        """Test is_match method."""
        result = ComparisonResult()

        assert result.is_match() is True

        diff = PropertyDifference(
            object_type="table",
            object_name="test",
            property_name="prop",
            original_value=1,
            regenerated_value=2,
            severity="warning",
        )
        result.differences.append(diff)

        assert result.is_match() is True  # No errors

        diff2 = PropertyDifference(
            object_type="table",
            object_name="test",
            property_name="prop",
            original_value=1,
            regenerated_value=2,
            severity="error",
        )
        result.differences.append(diff2)

        assert result.is_match() is False  # Has errors

    def test_has_warnings(self):
        """Test has_warnings method."""
        result = ComparisonResult()

        assert result.has_warnings() is False

        diff = PropertyDifference(
            object_type="table",
            object_name="test",
            property_name="prop",
            original_value=1,
            regenerated_value=2,
            severity="warning",
        )
        result.differences.append(diff)

        assert result.has_warnings() is True

    def test_get_summary(self):
        """Test get_summary method."""
        result = ComparisonResult()

        result.differences.append(
            PropertyDifference(
                object_type="table",
                object_name="test",
                property_name="prop1",
                original_value=1,
                regenerated_value=2,
                severity="error",
            )
        )
        result.differences.append(
            PropertyDifference(
                object_type="table",
                object_name="test",
                property_name="prop2",
                original_value=1,
                regenerated_value=2,
                severity="warning",
            )
        )
        result.differences.append(
            PropertyDifference(
                object_type="table",
                object_name="test",
                property_name="prop3",
                original_value=1,
                regenerated_value=2,
                severity="info",
            )
        )

        summary = result.get_summary()

        assert summary["total_differences"] == 3
        assert summary["errors"] == 1
        assert summary["warnings"] == 1
        assert summary["info"] == 1


@pytest.mark.unit
class TestPropertyComparator:
    """Test PropertyComparator class."""

    def test_comparator_creation(self):
        """Test creating a property comparator."""
        comparator = PropertyComparator()

        # Wave E: default changed from "postgresql" to "" (BaseQuirks fallback).
        assert comparator.dialect == ""
        assert comparator.strict is False

    def test_comparator_creation_custom_dialect(self):
        """Test creating comparator with custom dialect."""
        comparator = PropertyComparator(dialect="oracle", strict=True)

        assert comparator.dialect == "oracle"
        assert comparator.strict is True

    def test_compare_tables(self):
        """Test comparing two tables."""
        comparator = PropertyComparator()

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = []
        original.constraints = []

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = []
        regenerated.constraints = []

        result = comparator.compare_tables(original, regenerated)

        assert isinstance(result, ComparisonResult)

    def test_compare_tables_name_mismatch(self):
        """Test comparing tables with name mismatch."""
        comparator = PropertyComparator()

        original = Mock(spec=Table)
        original.name = "original_table"
        original.schema = "public"
        original.columns = []
        original.constraints = []

        regenerated = Mock(spec=Table)
        regenerated.name = "regenerated_table"
        regenerated.schema = "public"
        regenerated.columns = []
        regenerated.constraints = []

        result = comparator.compare_tables(original, regenerated)

        assert len(result.differences) > 0
        assert any(d.property_name == "name" for d in result.differences)

    def test_compare_tables_schema_mismatch(self):
        """Test comparing tables with schema mismatch."""
        comparator = PropertyComparator()

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "schema1"
        original.columns = []
        original.constraints = []

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "schema2"
        regenerated.columns = []
        regenerated.constraints = []

        result = comparator.compare_tables(original, regenerated)

        assert len(result.differences) > 0
        assert any(d.property_name == "schema" for d in result.differences)

    def test_compare_tables_column_count_mismatch(self):
        """Test comparing tables with different column counts."""
        comparator = PropertyComparator()

        col1 = Mock(spec=SqlColumn)
        col1.name = "col1"
        col1.data_type = "INTEGER"
        col1.nullable = True

        col2 = Mock(spec=SqlColumn)
        col2.name = "col2"
        col2.data_type = "VARCHAR"
        col2.nullable = False

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = [col1, col2]
        original.constraints = []

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = [col1]  # Missing col2
        regenerated.constraints = []

        result = comparator.compare_tables(original, regenerated)

        assert len(result.differences) > 0
        assert any(d.property_name == "column_count" for d in result.differences)

    def test_compare_tables_column_properties(self):
        """Test comparing column properties."""
        comparator = PropertyComparator()

        orig_col = Mock(spec=SqlColumn)
        orig_col.name = "test_col"
        orig_col.data_type = "INTEGER"
        orig_col.nullable = True
        orig_col.default_value = "1"
        orig_col.auto_increment = False
        orig_col.is_computed = False

        regen_col = Mock(spec=SqlColumn)
        regen_col.name = "test_col"
        regen_col.data_type = "BIGINT"  # Different type
        regen_col.nullable = False  # Different nullable
        regen_col.default_value = "2"  # Different default
        regen_col.auto_increment = False
        regen_col.is_computed = False

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = [orig_col]
        original.constraints = []

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = [regen_col]
        regenerated.constraints = []

        result = comparator.compare_tables(original, regenerated)

        assert len(result.differences) > 0

    def test_compare_tables_constraints(self):
        """Test comparing table constraints."""
        comparator = PropertyComparator()

        constraint1 = Mock(spec=SqlConstraint)
        constraint1.constraint_type = ConstraintType.PRIMARY_KEY
        constraint1.name = "pk_test"
        constraint1.column_names = ["id"]

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = []
        original.constraints = [constraint1]

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = []
        regenerated.constraints = []  # Missing constraint

        result = comparator.compare_tables(original, regenerated)

        assert isinstance(result, ComparisonResult)

    def test_normalize_data_type(self):
        """Test data type normalization."""
        comparator = PropertyComparator(dialect="postgresql")

        assert comparator._normalize_data_type("int4") == "INTEGER"
        assert comparator._normalize_data_type("INT8") == "BIGINT"
        assert comparator._normalize_data_type("int2") == "SMALLINT"
        assert comparator._normalize_data_type("float4") == "REAL"
        assert comparator._normalize_data_type("bool") == "BOOLEAN"

    def test_normalize_data_type_with_size(self):
        """Test data type normalization with size."""
        comparator = PropertyComparator(dialect="postgresql")

        result = comparator._normalize_data_type("int4(10)")
        assert "INTEGER" in result
        assert "(10)" in result

    def test_normalize_default_value(self):
        """Test default value normalization."""
        comparator = PropertyComparator()

        assert comparator._normalize_default_value("'test'") == "test"
        assert comparator._normalize_default_value("  test  ") == "test"
        assert comparator._normalize_default_value(None) is None
        assert comparator._normalize_default_value("") is None

    def test_group_constraints_by_type(self):
        """Test grouping constraints by type."""
        comparator = PropertyComparator()

        pk_constraint = Mock(spec=SqlConstraint)
        pk_constraint.constraint_type = ConstraintType.PRIMARY_KEY

        fk_constraint = Mock(spec=SqlConstraint)
        fk_constraint.constraint_type = ConstraintType.FOREIGN_KEY

        constraints = [pk_constraint, fk_constraint]

        grouped = comparator._group_constraints_by_type(constraints)

        assert ConstraintType.PRIMARY_KEY in grouped
        assert ConstraintType.FOREIGN_KEY in grouped
        assert len(grouped[ConstraintType.PRIMARY_KEY]) == 1
        assert len(grouped[ConstraintType.FOREIGN_KEY]) == 1

    def test_constraint_signature(self):
        """Test constraint signature creation."""
        comparator = PropertyComparator()

        constraint = Mock(spec=SqlConstraint)
        constraint.constraint_type = ConstraintType.PRIMARY_KEY
        constraint.column_names = ["col2", "col1"]

        signature = comparator._constraint_signature(constraint)

        # Signature format is "PRIMARY_KEY:('col1', 'col2')" (sorted)
        # But constraint_type.value returns "PRIMARY KEY" (with space), not "PRIMARY_KEY"
        assert "PRIMARY" in signature and "KEY" in signature
        assert "col1" in signature
        assert "col2" in signature

    def test_compare_tables_missing_column(self):
        """Test comparing tables with missing column."""
        comparator = PropertyComparator()

        orig_col = Mock(spec=SqlColumn)
        orig_col.name = "col1"
        orig_col.data_type = "INTEGER"

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = [orig_col]
        original.constraints = []

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = []
        regenerated.constraints = []

        result = comparator.compare_tables(original, regenerated)

        # When column count mismatches, it's added to errors, not differences
        # Check that we detected the mismatch
        assert len(result.errors) > 0 or len(result.differences) > 0
        if result.differences:
            assert any(
                d.object_type == "column" and d.property_name == "existence"
                for d in result.differences
            )

    def test_compare_tables_extra_column(self):
        """Test comparing tables with extra column."""
        comparator = PropertyComparator()

        regen_col = Mock(spec=SqlColumn)
        regen_col.name = "extra_col"
        regen_col.data_type = "VARCHAR"

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = []
        original.constraints = []

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = [regen_col]
        regenerated.constraints = []

        result = comparator.compare_tables(original, regenerated)

        # When column count mismatches, it's added to errors, not differences
        # Check that we detected the mismatch
        assert len(result.errors) > 0 or len(result.differences) > 0

    def test_compare_tables_temporary_flag(self):
        """Test comparing temporary flag."""
        comparator = PropertyComparator()

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = []
        original.constraints = []
        original.temporary = True

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = []
        regenerated.constraints = []
        regenerated.temporary = False

        result = comparator.compare_tables(original, regenerated)

        assert len(result.differences) > 0
        assert any(d.property_name == "temporary" for d in result.differences)

    def test_compare_tables_no_columns(self):
        """Test comparing tables with no columns."""
        comparator = PropertyComparator()

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = None
        original.constraints = []

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = None
        regenerated.constraints = []

        result = comparator.compare_tables(original, regenerated)

        assert isinstance(result, ComparisonResult)

    def test_compare_tables_no_constraints(self):
        """Test comparing tables with no constraints."""
        comparator = PropertyComparator()

        original = Mock(spec=Table)
        original.name = "test_table"
        original.schema = "public"
        original.columns = []
        original.constraints = None

        regenerated = Mock(spec=Table)
        regenerated.name = "test_table"
        regenerated.schema = "public"
        regenerated.columns = []
        regenerated.constraints = None

        result = comparator.compare_tables(original, regenerated)

        assert isinstance(result, ComparisonResult)

    def test_compare_constraint_lists(self):
        """Test comparing constraint lists."""
        comparator = PropertyComparator()

        constraint1 = Mock(spec=SqlConstraint)
        constraint1.constraint_type = ConstraintType.PRIMARY_KEY
        constraint1.name = "pk1"
        constraint1.column_names = ["id"]

        constraint2 = Mock(spec=SqlConstraint)
        constraint2.constraint_type = ConstraintType.PRIMARY_KEY
        constraint2.name = "pk2"
        constraint2.column_names = ["id"]

        orig_list = [constraint1]
        regen_list = [constraint2]

        result = ComparisonResult()

        comparator._compare_constraint_lists(
            orig_list, regen_list, ConstraintType.PRIMARY_KEY, result
        )

        assert isinstance(result, ComparisonResult)
