"""Tests for state validator."""

from unittest.mock import MagicMock, Mock, create_autospec

import pytest

from core.sql_model.base import SqlColumn
from core.sql_model.index import Index
from core.sql_model.table import Table
from core.sql_model.view import View
from core.validation.result import ValidationResult, ValidationSeverity
from core.validation.state_validator import StateValidator


@pytest.mark.unit
class TestStateValidator:
    """Test StateValidator class."""

    def test_validator_creation(self):
        """Test creating a state validator."""
        validator = StateValidator()

        assert validator.completeness_validator is not None
        assert validator.consistency_validator is not None
        assert validator.accuracy_validator is not None

    def test_validator_creation_with_introspector(self):
        """Test creating validator with introspector."""
        mock_introspector = Mock()
        validator = StateValidator(introspector=mock_introspector)

        assert validator.accuracy_validator.introspector == mock_introspector

    def test_validate_schema(self):
        """Test validating a complete schema."""
        validator = StateValidator()

        # Use create_autospec to create a mock that passes isinstance checks
        table = Table(name="test_table", schema="public", columns=[], constraints=[])
        table.name = "test_table"
        table.schema = "public"
        table.columns = []
        table.constraints = []

        tables = [table]
        indexes = []
        views = []

        results = validator.validate_schema(tables, indexes, views, schema="public")

        assert "completeness" in results
        assert "consistency" in results
        assert isinstance(results["completeness"], ValidationResult)
        assert isinstance(results["consistency"], ValidationResult)

    def test_validate_schema_with_indexes(self):
        """Test validating schema with indexes."""
        validator = StateValidator()

        # Create a real Table instance to pass isinstance checks
        table = Table(name="test_table", schema="public", columns=[], constraints=[])

        index = MagicMock()
        index.name = "test_index"
        index.table_name = "test_table"
        index.columns = []  # Index needs columns attribute

        tables = [table]
        indexes = [index]
        views = []

        results = validator.validate_schema(tables, indexes, views, schema="public")

        assert "completeness" in results
        assert "consistency" in results

    def test_validate_schema_with_views(self):
        """Test validating schema with views."""
        validator = StateValidator()

        # Create a real Table instance to pass isinstance checks
        table = Table(name="test_table", schema="public", columns=[], constraints=[])

        view = Mock(spec=View)
        view.name = "test_view"
        view.schema = "public"

        tables = [table]
        indexes = []
        views = [view]

        results = validator.validate_schema(tables, indexes, views, schema="public")

        assert "completeness" in results
        assert "consistency" in results

    def test_validate_schema_with_expected_counts(self):
        """Test validating schema with expected counts."""
        validator = StateValidator()

        # Use create_autospec to create a mock that passes isinstance checks
        table = Table(name="test_table", schema="public", columns=[], constraints=[])
        table.name = "test_table"
        table.schema = "public"
        table.columns = []
        table.constraints = []

        tables = [table]
        expected_counts = {"tables": 1}

        results = validator.validate_schema(
            tables, expected_counts=expected_counts, schema="public"
        )

        assert "completeness" in results

    def test_validate_schema_with_live_objects(self):
        """Test validating schema with live objects."""
        validator = StateValidator()

        # Use create_autospec to create a mock that passes isinstance checks
        table = Table(name="test_table", schema="public", columns=[], constraints=[])
        table.name = "test_table"
        table.schema = "public"
        table.columns = []
        table.constraints = []

        tables = [table]
        live_objects = {"tables": [table]}

        results = validator.validate_schema(tables, live_objects=live_objects, schema="public")

        assert "accuracy" in results
        assert isinstance(results["accuracy"], ValidationResult)

    def test_get_overall_status(self):
        """Test getting overall status."""
        validator = StateValidator()

        result1 = ValidationResult(validator_name="test1")
        result1.passed = True

        result2 = ValidationResult(validator_name="test2")
        result2.passed = True

        results = {"test1": result1, "test2": result2}

        status = validator.get_overall_status(results)

        assert status["passed"] is True
        assert status["total_errors"] == 0
        assert status["total_warnings"] == 0

    def test_get_overall_status_with_errors(self):
        """Test getting overall status with errors."""
        validator = StateValidator()

        result1 = ValidationResult(validator_name="test1")
        result1.passed = False
        result1.add_issue(ValidationSeverity.ERROR, "Error message")

        result2 = ValidationResult(validator_name="test2")
        result2.passed = True

        results = {"test1": result1, "test2": result2}

        status = validator.get_overall_status(results)

        assert status["passed"] is False
        assert status["total_errors"] == 1
        assert status["overall_severity"] == "error"

    def test_get_overall_status_with_warnings(self):
        """Test getting overall status with warnings."""
        validator = StateValidator()

        result1 = ValidationResult(validator_name="test1")
        result1.add_issue(ValidationSeverity.WARNING, "Warning message")

        result2 = ValidationResult(validator_name="test2")
        result2.passed = True

        results = {"test1": result1, "test2": result2}

        status = validator.get_overall_status(results)

        assert status["passed"] is True
        assert status["total_warnings"] == 1
        assert status["overall_severity"] == "warning"

    def test_get_overall_status_with_confidence(self):
        """Test getting overall status with confidence score."""
        validator = StateValidator()

        completeness_result = ValidationResult(validator_name="completeness")
        completeness_result.passed = True
        completeness_result.metadata["object_counts"] = {"tables": 5}

        consistency_result = ValidationResult(validator_name="consistency")
        consistency_result.passed = True

        results = {
            "completeness": completeness_result,
            "consistency": consistency_result,
        }

        status = validator.get_overall_status(results)

        assert "confidence" in status
        assert isinstance(status["confidence"], dict)
        assert "overall_score" in status["confidence"]

    def test_get_overall_status_with_accuracy(self):
        """Test getting overall status with accuracy result."""
        validator = StateValidator()

        completeness_result = ValidationResult(validator_name="completeness")
        completeness_result.passed = True
        completeness_result.metadata["object_counts"] = {"tables": 5}

        consistency_result = ValidationResult(validator_name="consistency")
        consistency_result.passed = True

        accuracy_result = ValidationResult(validator_name="accuracy")
        accuracy_result.passed = True

        results = {
            "completeness": completeness_result,
            "consistency": consistency_result,
            "accuracy": accuracy_result,
        }

        status = validator.get_overall_status(results)

        assert "confidence" in status
        assert "validator_results" in status
        assert "accuracy" in status["validator_results"]
