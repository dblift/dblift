"""Tests for completeness validator."""

from unittest.mock import Mock

import pytest

from core.sql_model.base import SqlColumn, SqlObject
from core.sql_model.table import Table
from core.validation.completeness_validator import CompletenessValidator
from core.validation.result import ValidationResult, ValidationSeverity


@pytest.mark.unit
class TestCompletenessValidator:
    """Test CompletenessValidator class."""

    def test_validator_creation(self):
        """Test creating a completeness validator."""
        validator = CompletenessValidator()

        assert validator is not None

    def test_validate_tables(self):
        """Test validating tables."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []

        result = validator.validate_tables([table])

        assert isinstance(result, ValidationResult)
        assert result.validator_name == "CompletenessValidator"

    def test_validate_tables_count_mismatch(self):
        """Test validating tables with count mismatch."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []

        result = validator.validate_tables([table], expected_count=2)

        assert result.passed is False
        assert len(result.issues) > 0
        assert any("count mismatch" in issue.message.lower() for issue in result.issues)

    def test_validate_tables_missing_name(self):
        """Test validating tables with missing name."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = None
        table.columns = []

        result = validator.validate_tables([table])

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_tables_missing_columns(self):
        """Test validating tables with missing columns."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = None

        result = validator.validate_tables([table])

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_tables_column_missing_name(self):
        """Test validating tables with column missing name."""
        validator = CompletenessValidator()

        col = Mock(spec=SqlColumn)
        col.name = None
        col.data_type = "INTEGER"

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = [col]

        result = validator.validate_tables([table])

        assert result.passed is False
        assert len(result.issues) > 0
        assert any("column missing name" in issue.message.lower() for issue in result.issues)

    def test_validate_tables_column_missing_data_type(self):
        """Test validating tables with column missing data type."""
        validator = CompletenessValidator()

        col = Mock(spec=SqlColumn)
        col.name = "test_col"
        col.data_type = None

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = [col]

        result = validator.validate_tables([table])

        assert result.passed is False
        assert len(result.issues) > 0
        assert any("missing data_type" in issue.message.lower() for issue in result.issues)

    def test_validate_tables_custom_required_properties(self):
        """Test validating tables with custom required properties."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.schema = None  # Missing schema

        result = validator.validate_tables([table], required_properties=["name", "schema"])

        # Schema is not in critical properties, so it adds a WARNING, not ERROR
        # Warnings don't set passed=False, only errors do
        # But we should have issues (warnings)
        assert len(result.issues) > 0
        # Check that schema issue was added
        assert any(issue.property_name == "schema" for issue in result.issues)

    def test_validate_tables_metadata(self):
        """Test that metadata is populated."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []

        result = validator.validate_tables([table], expected_count=1)

        assert "table_count" in result.metadata
        assert result.metadata["table_count"] == 1
        assert result.metadata["expected_count"] == 1

    def test_validate_objects(self):
        """Test validating objects dictionary."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []

        objects = {"tables": [table]}

        result = validator.validate_objects(objects)

        assert isinstance(result, ValidationResult)
        assert "object_counts" in result.metadata

    def test_validate_objects_with_expected_counts(self):
        """Test validating objects with expected counts."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []

        objects = {"tables": [table]}
        expected_counts = {"tables": 2}

        result = validator.validate_objects(objects, expected_counts)

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_objects_multiple_types(self):
        """Test validating multiple object types."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []

        view = Mock(spec=SqlObject)
        view.name = "test_view"

        objects = {"tables": [table], "views": [view]}

        result = validator.validate_objects(objects)

        assert isinstance(result, ValidationResult)
        assert result.metadata["object_counts"]["tables"] == 1
        assert result.metadata["object_counts"]["views"] == 1

    def test_validate_objects_empty(self):
        """Test validating empty objects."""
        validator = CompletenessValidator()

        objects = {}

        result = validator.validate_objects(objects)

        assert isinstance(result, ValidationResult)
        assert result.passed is True

    def test_validate_tables_none_property_warning(self):
        """Test validating tables with None property that's not critical."""
        validator = CompletenessValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.comment = None  # Non-critical property

        result = validator.validate_tables(
            [table], required_properties=["name", "columns", "comment"]
        )

        # Should have warning for None comment
        assert len(result.issues) > 0
        assert any(
            issue.severity == ValidationSeverity.WARNING and "comment" in issue.message.lower()
            for issue in result.issues
        )
