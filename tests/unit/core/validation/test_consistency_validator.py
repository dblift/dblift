"""Tests for consistency validator."""

from unittest.mock import MagicMock, Mock

import pytest

from core.sql_model.base import ConstraintType, SqlColumn, SqlConstraint
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.view import View
from core.validation.consistency_validator import ConsistencyValidator
from core.validation.result import ValidationResult, ValidationSeverity


@pytest.mark.unit
class TestConsistencyValidator:
    """Test ConsistencyValidator class."""

    def test_validator_creation(self):
        """Test creating a consistency validator."""
        validator = ConsistencyValidator()

        assert validator is not None

    def test_validate_foreign_keys(self):
        """Test validating foreign keys."""
        validator = ConsistencyValidator()

        # Use MagicMock without spec to allow setting constraints attribute
        table1 = MagicMock()
        table1.name = "table1"
        table1.columns = []
        table1.constraints = []

        table2 = MagicMock()
        table2.name = "table2"
        col = Mock(spec=SqlColumn)
        col.name = "id"
        table2.columns = [col]
        table2.constraints = []  # table2 also needs constraints

        fk_constraint = Mock(spec=SqlConstraint)
        fk_constraint.constraint_type = ConstraintType.FOREIGN_KEY
        fk_constraint.name = "fk_test"
        fk_constraint.reference_table = "table2"
        fk_constraint.reference_columns = ["id"]
        fk_constraint.column_names = ["ref_id"]

        table1.constraints = [fk_constraint]

        result = validator.validate_foreign_keys([table1, table2], schema="public")

        assert isinstance(result, ValidationResult)

    def test_validate_foreign_keys_missing_reference_table(self):
        """Test validating foreign keys with missing reference table."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "table1"
        table.columns = []

        fk_constraint = Mock(spec=SqlConstraint)
        fk_constraint.constraint_type = ConstraintType.FOREIGN_KEY
        fk_constraint.name = "fk_test"
        fk_constraint.reference_table = None
        fk_constraint.reference_columns = []
        fk_constraint.column_names = ["ref_id"]

        table.constraints = [fk_constraint]

        result = validator.validate_foreign_keys([table], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_foreign_keys_nonexistent_table(self):
        """Test validating foreign keys referencing nonexistent table."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "table1"
        table.columns = []

        fk_constraint = Mock(spec=SqlConstraint)
        fk_constraint.constraint_type = ConstraintType.FOREIGN_KEY
        fk_constraint.name = "fk_test"
        fk_constraint.reference_table = "nonexistent"
        fk_constraint.reference_columns = ["id"]
        fk_constraint.column_names = ["ref_id"]

        table.constraints = [fk_constraint]

        result = validator.validate_foreign_keys([table], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_foreign_keys_nonexistent_column(self):
        """Test validating foreign keys referencing nonexistent column."""
        validator = ConsistencyValidator()

        table1 = MagicMock()
        table1.constraints = []
        table1.name = "table1"
        table1.columns = []

        table2 = MagicMock()
        table2.constraints = []
        table2.name = "table2"
        table2.columns = []  # No columns

        fk_constraint = Mock(spec=SqlConstraint)
        fk_constraint.constraint_type = ConstraintType.FOREIGN_KEY
        fk_constraint.name = "fk_test"
        fk_constraint.reference_table = "table2"
        fk_constraint.reference_columns = ["nonexistent"]
        fk_constraint.column_names = ["ref_id"]

        table1.constraints = [fk_constraint]

        result = validator.validate_foreign_keys([table1, table2], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_foreign_keys_nonexistent_local_column(self):
        """Test validating foreign keys with nonexistent local column."""
        validator = ConsistencyValidator()

        table1 = MagicMock()
        table1.constraints = []
        table1.name = "table1"
        table1.columns = []  # No columns

        table2 = MagicMock()
        table2.constraints = []
        table2.name = "table2"
        col = Mock(spec=SqlColumn)
        col.name = "id"
        table2.columns = [col]

        fk_constraint = Mock(spec=SqlConstraint)
        fk_constraint.constraint_type = ConstraintType.FOREIGN_KEY
        fk_constraint.name = "fk_test"
        fk_constraint.reference_table = "table2"
        fk_constraint.reference_columns = ["id"]
        fk_constraint.column_names = ["nonexistent"]

        table1.constraints = [fk_constraint]

        result = validator.validate_foreign_keys([table1, table2], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_indexes(self):
        """Test validating indexes."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        col = Mock(spec=SqlColumn)
        col.name = "id"
        table.columns = [col]

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "test_table"
        index.columns = ["id"]

        result = validator.validate_indexes([table], [index], schema="public")

        assert isinstance(result, ValidationResult)

    def test_validate_indexes_nonexistent_table(self):
        """Test validating indexes with nonexistent table."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = []

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "nonexistent"
        index.columns = ["id"]

        result = validator.validate_indexes([table], [index], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_indexes_nonexistent_column(self):
        """Test validating indexes with nonexistent column."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = []  # No columns

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "test_table"
        index.columns = ["nonexistent"]

        result = validator.validate_indexes([table], [index], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_indexes_expression_column(self):
        """Test validating indexes with expression column."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = []

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "test_table"
        index.columns = ["UPPER(name)"]  # Expression

        result = validator.validate_indexes([table], [index], schema="public")

        # Expression columns should be skipped
        assert isinstance(result, ValidationResult)

    def test_validate_indexes_cosmosdb_wildcard_column(self):
        """CosmosDB auto indexes use * to mean all document paths."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = []

        index = Index(
            name="auto_index_test_table",
            table_name="test_table",
            columns=["*"],
            dialect="cosmosdb",
        )

        result = validator.validate_indexes([table], [index], schema="public")

        assert result.passed is True
        assert not any("non-existent column" in issue.message for issue in result.issues)

    def test_validate_indexes_non_cosmosdb_wildcard_column_still_errors(self):
        """The wildcard skip is limited to CosmosDB synthetic indexes."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = []

        index = Index(
            name="wildcard_index",
            table_name="test_table",
            columns=["*"],
            dialect="postgresql",
        )

        result = validator.validate_indexes([table], [index], schema="public")

        assert result.passed is False
        assert any("non-existent column" in issue.message for issue in result.issues)

    def test_validate_constraints(self):
        """Test validating constraints."""
        validator = ConsistencyValidator()

        col = Mock(spec=SqlColumn)
        col.name = "id"

        constraint = Mock(spec=SqlConstraint)
        constraint.constraint_type = ConstraintType.PRIMARY_KEY
        constraint.name = "pk_test"
        constraint.column_names = ["id"]

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = [col]
        table.constraints = [constraint]

        result = validator.validate_constraints([table], schema="public")

        assert isinstance(result, ValidationResult)

    def test_validate_constraints_nonexistent_column(self):
        """Test validating constraints with nonexistent column."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = []  # No columns

        constraint = Mock(spec=SqlConstraint)
        constraint.constraint_type = ConstraintType.PRIMARY_KEY
        constraint.name = "pk_test"
        constraint.column_names = ["nonexistent"]

        table.constraints = [constraint]

        result = validator.validate_constraints([table], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_all(self):
        """Test validating all consistency checks."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "test_table"
        index.columns = []

        view = Mock(spec=View)
        view.name = "test_view"

        result = validator.validate_all([table], indexes=[index], views=[view], schema="public")

        assert isinstance(result, ValidationResult)
        assert "table_count" in result.metadata
        assert result.metadata["index_count"] == 1
        assert result.metadata["view_count"] == 1

    def test_validate_all_no_indexes(self):
        """Test validating all without indexes."""
        validator = ConsistencyValidator()

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        result = validator.validate_all([table], schema="public")

        assert isinstance(result, ValidationResult)
        assert result.metadata["index_count"] == 0

    def test_validate_foreign_keys_reference_schema(self):
        """Test validating foreign keys with reference schema."""
        validator = ConsistencyValidator()

        table1 = MagicMock()
        table1.constraints = []
        table1.name = "table1"
        table1.columns = []

        table2 = MagicMock()
        table2.constraints = []
        table2.name = "table2"
        col = Mock(spec=SqlColumn)
        col.name = "id"
        table2.columns = [col]

        fk_constraint = Mock(spec=SqlConstraint)
        fk_constraint.constraint_type = ConstraintType.FOREIGN_KEY
        fk_constraint.name = "fk_test"
        fk_constraint.reference_table = "table2"
        fk_constraint.reference_schema = "other_schema"
        fk_constraint.reference_columns = ["id"]
        fk_constraint.column_names = ["ref_id"]

        table1.constraints = [fk_constraint]

        result = validator.validate_foreign_keys([table1, table2], schema="public")

        assert isinstance(result, ValidationResult)

    def test_validate_indexes_quoted_column(self):
        """Test validating indexes with quoted column names."""
        validator = ConsistencyValidator()

        col = Mock(spec=SqlColumn)
        col.name = "TestCol"

        table = MagicMock()
        table.constraints = []
        table.name = "test_table"
        table.columns = [col]

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "test_table"
        index.columns = ['"TestCol"']  # Quoted

        result = validator.validate_indexes([table], [index], schema="public")

        # Should handle quoted columns
        assert isinstance(result, ValidationResult)

    def test_validate_indexes_view_with_string_columns_does_not_crash(self):
        """View.columns is List[str]; validate_indexes must not call .name on strings."""
        validator = ConsistencyValidator()

        view = View(name="v_orders", columns=["order_id", "total"])

        index = Mock(spec=Index)
        index.name = "idx_v_orders_order_id"
        index.table_name = "v_orders"
        index.columns = ["order_id"]

        result = validator.validate_indexes([], [index], schema="public", views=[view])

        assert result.passed is True
        assert len(result.issues) == 0

    def test_validate_indexes_view_with_string_columns_flags_missing_column(self):
        """Index on an unknown view column must be flagged, even when columns are strings."""
        validator = ConsistencyValidator()

        view = View(name="v_orders", columns=["order_id"])

        index = Mock(spec=Index)
        index.name = "idx_v_orders_missing"
        index.table_name = "v_orders"
        index.columns = ["nonexistent"]

        result = validator.validate_indexes([], [index], schema="public", views=[view])

        assert result.passed is False
        assert any("non-existent column" in i.message for i in result.issues)

    def test_indexed_view_index_no_error_when_views_passed(self):
        """Index referencing a view (SQL Server indexed view) must not produce
        an error when the view is included in the views list."""
        validator = ConsistencyValidator()

        col = Mock(spec=SqlColumn)
        col.name = "col1"

        view = MagicMock()
        view.name = "my_indexed_view"
        view.columns = [col]

        index = Mock(spec=Index)
        index.name = "idx_my_indexed_view"
        index.table_name = "my_indexed_view"  # references the VIEW, not a table
        index.columns = ["col1"]

        result = validator.validate_indexes([], [index], schema="dbo", views=[view])

        errors = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        assert len(errors) == 0, f"Unexpected errors: {[i.message for i in errors]}"
