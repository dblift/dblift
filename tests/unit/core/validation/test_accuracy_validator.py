"""Tests for accuracy validator."""

from unittest.mock import Mock

import pytest

from core.comparison.comparator import ObjectComparator
from core.comparison.diff_models import TableDiff
from core.comparison.type_normalizer import DataTypeNormalizer
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.validation.accuracy_validator import AccuracyValidator
from core.validation.result import ValidationResult, ValidationSeverity


@pytest.mark.unit
class TestAccuracyValidator:
    """Test AccuracyValidator class."""

    def test_validator_creation(self):
        """Test creating an accuracy validator."""
        validator = AccuracyValidator()

        assert validator.introspector is None
        assert isinstance(validator.comparator, ObjectComparator)

    def test_validator_creation_with_introspector(self):
        """Test creating validator with introspector."""
        mock_introspector = Mock()
        validator = AccuracyValidator(introspector=mock_introspector)

        assert validator.introspector == mock_introspector

    def test_normalize_name(self):
        """Test name normalization."""
        assert AccuracyValidator._normalize_name("TestName") == "testname"
        assert AccuracyValidator._normalize_name("  Test  ") == "test"
        assert AccuracyValidator._normalize_name(None) == ""
        assert AccuracyValidator._normalize_name("") == ""

    def test_validate_tables(self):
        """Test validating tables."""
        validator = AccuracyValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        captured_tables = [table]
        live_tables = [table]

        result = validator.validate_tables(captured_tables, live_tables, schema="public")

        assert isinstance(result, ValidationResult)
        assert result.validator_name == "AccuracyValidator"

    def test_validate_tables_missing_in_live(self):
        """Test validating tables missing in live database."""
        validator = AccuracyValidator()

        captured_table = Mock(spec=Table)
        captured_table.name = "captured_table"
        captured_table.columns = []
        captured_table.constraints = []

        captured_tables = [captured_table]
        live_tables = []

        result = validator.validate_tables(captured_tables, live_tables, schema="public")

        assert result.passed is False
        assert len(result.issues) > 0
        assert any("not found in live database" in issue.message for issue in result.issues)

    def test_validate_tables_extra_in_live(self):
        """Test validating tables extra in live database."""
        validator = AccuracyValidator()

        live_table = Mock(spec=Table)
        live_table.name = "live_table"
        live_table.columns = []
        live_table.constraints = []

        captured_tables = []
        live_tables = [live_table]

        result = validator.validate_tables(captured_tables, live_tables, schema="public")

        assert len(result.issues) > 0
        assert any("not in captured state" in issue.message for issue in result.issues)

    def test_validate_tables_with_differences(self):
        """Test validating tables with differences."""
        validator = AccuracyValidator()

        captured_table = Mock(spec=Table)
        captured_table.name = "test_table"
        captured_table.columns = []
        captured_table.constraints = []

        live_table = Mock(spec=Table)
        live_table.name = "test_table"
        live_table.columns = []
        live_table.constraints = []

        # Mock comparator to return differences
        mock_diff = Mock(spec=TableDiff)
        mock_diff.missing_columns = ["col1"]
        mock_diff.extra_columns = []
        mock_diff.modified_columns = []
        mock_diff.missing_constraints = []
        mock_diff.extra_constraints = []
        mock_diff.modified_constraints = []

        validator.comparator.compare_tables = Mock(return_value=mock_diff)

        result = validator.validate_tables([captured_table], [live_table], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_tables_metadata(self):
        """Test that metadata is populated."""
        validator = AccuracyValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        result = validator.validate_tables([table], [table], schema="public")

        assert "captured_count" in result.metadata
        assert "live_count" in result.metadata
        assert "common_count" in result.metadata

    def test_validate_indexes(self):
        """Test validating indexes."""
        validator = AccuracyValidator()

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "test_table"

        captured_indexes = [index]
        live_indexes = [index]

        result = validator.validate_indexes(captured_indexes, live_indexes, schema="public")

        assert isinstance(result, ValidationResult)

    def test_validate_indexes_missing_in_live(self):
        """Test validating indexes missing in live database."""
        validator = AccuracyValidator()

        captured_index = Mock(spec=Index)
        captured_index.name = "captured_index"
        captured_index.table_name = "test_table"

        captured_indexes = [captured_index]
        live_indexes = []

        result = validator.validate_indexes(captured_indexes, live_indexes, schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_indexes_extra_in_live(self):
        """Test validating indexes extra in live database."""
        validator = AccuracyValidator()

        live_index = Mock(spec=Index)
        live_index.name = "live_index"
        live_index.table_name = "test_table"

        captured_indexes = []
        live_indexes = [live_index]

        result = validator.validate_indexes(captured_indexes, live_indexes, schema="public")

        assert len(result.issues) > 0

    def test_validate_indexes_with_table_filter(self):
        """Test validating indexes with table filter."""
        validator = AccuracyValidator()

        index1 = Mock(spec=Index)
        index1.name = "index1"
        index1.table_name = "table1"

        index2 = Mock(spec=Index)
        index2.name = "index2"
        index2.table_name = "table2"

        captured_indexes = [index1, index2]
        live_indexes = [index1, index2]

        result = validator.validate_indexes(
            captured_indexes, live_indexes, schema="public", table="table1"
        )

        assert isinstance(result, ValidationResult)

    def test_validate_indexes_metadata(self):
        """Test that metadata is populated."""
        validator = AccuracyValidator()

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "test_table"

        result = validator.validate_indexes([index], [index], schema="public")

        assert "captured_count" in result.metadata
        assert "live_count" in result.metadata

    def test_validate_round_trip(self):
        """Test validating round trip."""
        mock_introspector = Mock()
        mock_introspector.get_tables.return_value = []

        validator = AccuracyValidator(introspector=mock_introspector)

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        result = validator.validate_round_trip([table], schema="public")

        assert isinstance(result, ValidationResult)

    def test_validate_round_trip_no_introspector(self):
        """Test round trip validation without introspector."""
        validator = AccuracyValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        result = validator.validate_round_trip([table], schema="public")

        assert len(result.issues) > 0
        assert any("No introspector" in issue.message for issue in result.issues)

    def test_validate_round_trip_exception(self):
        """Test round trip validation with exception."""
        mock_introspector = Mock()
        mock_introspector.get_tables.side_effect = Exception("Introspection error")

        validator = AccuracyValidator(introspector=mock_introspector)

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        result = validator.validate_round_trip([table], schema="public")

        assert result.passed is False
        assert len(result.issues) > 0

    def test_validate_all(self):
        """Test validating all object types."""
        validator = AccuracyValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        index = Mock(spec=Index)
        index.name = "test_index"
        index.table_name = "test_table"

        captured_objects = {"tables": [table], "indexes": [index]}
        live_objects = {"tables": [table], "indexes": [index]}

        result = validator.validate_all(captured_objects, live_objects, schema="public")

        assert isinstance(result, ValidationResult)
        assert "object_types_validated" in result.metadata

    def test_validate_all_partial_objects(self):
        """Test validating all with partial objects."""
        validator = AccuracyValidator()

        table = Mock(spec=Table)
        table.name = "test_table"
        table.columns = []
        table.constraints = []

        captured_objects = {"tables": [table]}
        live_objects = {"tables": [table]}

        result = validator.validate_all(captured_objects, live_objects, schema="public")

        assert isinstance(result, ValidationResult)

    def test_validate_tables_column_differences(self):
        """Test validating tables with column differences."""
        validator = AccuracyValidator()

        captured_table = Mock(spec=Table)
        captured_table.name = "test_table"
        captured_table.columns = []
        captured_table.constraints = []

        live_table = Mock(spec=Table)
        live_table.name = "test_table"
        live_table.columns = []
        live_table.constraints = []

        mock_diff = Mock(spec=TableDiff)
        mock_diff.missing_columns = ["col1"]
        mock_diff.extra_columns = []
        mock_diff.modified_columns = []
        mock_diff.missing_constraints = []
        mock_diff.extra_constraints = []
        mock_diff.modified_constraints = []

        validator.comparator.compare_tables = Mock(return_value=mock_diff)

        result = validator.validate_tables([captured_table], [live_table], schema="public")

        assert result.passed is False
        assert any("column differences" in issue.message for issue in result.issues)

    def test_validate_tables_constraint_differences(self):
        """Test validating tables with constraint differences."""
        validator = AccuracyValidator()

        captured_table = Mock(spec=Table)
        captured_table.name = "test_table"
        captured_table.columns = []
        captured_table.constraints = []

        live_table = Mock(spec=Table)
        live_table.name = "test_table"
        live_table.columns = []
        live_table.constraints = []

        mock_diff = Mock(spec=TableDiff)
        mock_diff.missing_columns = []
        mock_diff.extra_columns = []
        mock_diff.modified_columns = []
        mock_diff.missing_constraints = ["pk_test"]
        mock_diff.extra_constraints = []
        mock_diff.modified_constraints = []

        validator.comparator.compare_tables = Mock(return_value=mock_diff)

        result = validator.validate_tables([captured_table], [live_table], schema="public")

        assert result.passed is False
        assert any("constraint differences" in issue.message for issue in result.issues)

    def test_validate_tables_comment_differences(self):
        """Test validating tables with comment differences."""
        validator = AccuracyValidator()

        captured_table = Mock(spec=Table)
        captured_table.name = "test_table"
        captured_table.columns = []
        captured_table.constraints = []

        live_table = Mock(spec=Table)
        live_table.name = "test_table"
        live_table.columns = []
        live_table.constraints = []

        mock_diff = Mock(spec=TableDiff)
        mock_diff.missing_columns = []
        mock_diff.extra_columns = []
        mock_diff.modified_columns = []
        mock_diff.missing_constraints = []
        mock_diff.extra_constraints = []
        mock_diff.modified_constraints = []
        mock_diff.comment_changed = True

        validator.comparator.compare_tables = Mock(return_value=mock_diff)

        result = validator.validate_tables([captured_table], [live_table], schema="public")

        assert any("comment differs" in issue.message for issue in result.issues)
