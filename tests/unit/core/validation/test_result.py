"""Tests for validation result classes."""

import pytest

from core.validation.result import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)


@pytest.mark.unit
class TestValidationSeverity:
    """Test ValidationSeverity enum."""

    def test_severity_values(self):
        """Test severity enum values."""
        assert ValidationSeverity.INFO.value == "info"
        assert ValidationSeverity.WARNING.value == "warning"
        assert ValidationSeverity.ERROR.value == "error"


@pytest.mark.unit
class TestValidationIssue:
    """Test ValidationIssue dataclass."""

    def test_issue_creation(self):
        """Test creating a validation issue."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            message="Test issue",
        )

        assert issue.severity == ValidationSeverity.ERROR
        assert issue.message == "Test issue"
        assert issue.object_type is None
        assert issue.object_name is None

    def test_issue_with_all_fields(self):
        """Test issue with all fields."""
        issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            message="Test issue",
            object_type="table",
            object_name="test_table",
            property_name="column_count",
            expected_value=5,
            actual_value=3,
        )

        assert issue.object_type == "table"
        assert issue.object_name == "test_table"
        assert issue.property_name == "column_count"
        assert issue.expected_value == 5
        assert issue.actual_value == 3

    def test_issue_str_representation(self):
        """Test string representation of issue."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            message="Test issue",
        )

        result = str(issue)
        assert "[ERROR]" in result
        assert "Test issue" in result

    def test_issue_str_with_object(self):
        """Test string representation with object info."""
        issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            message="Test issue",
            object_type="table",
            object_name="test_table",
        )

        result = str(issue)
        assert "table.test_table" in result

    def test_issue_str_with_property(self):
        """Test string representation with property."""
        issue = ValidationIssue(
            severity=ValidationSeverity.INFO,
            message="Test issue",
            object_type="table",
            object_name="test_table",
            property_name="column_count",
        )

        result = str(issue)
        assert "Property: column_count" in result

    def test_issue_str_with_values(self):
        """Test string representation with expected/actual values."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            message="Test issue",
            expected_value=5,
            actual_value=3,
        )

        result = str(issue)
        assert "Expected: 5" in result
        assert "Actual: 3" in result


@pytest.mark.unit
class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_result_creation(self):
        """Test creating a validation result."""
        result = ValidationResult(validator_name="TestValidator")

        assert result.validator_name == "TestValidator"
        assert result.passed is True
        assert result.issues == []
        assert result.metadata == {}

    def test_add_issue(self):
        """Test adding an issue."""
        result = ValidationResult(validator_name="TestValidator")

        result.add_issue(
            ValidationSeverity.WARNING,
            "Test warning",
            object_type="table",
            object_name="test_table",
        )

        assert len(result.issues) == 1
        assert result.issues[0].severity == ValidationSeverity.WARNING
        assert result.issues[0].message == "Test warning"

    def test_add_issue_error_sets_passed_false(self):
        """Test that adding an error issue sets passed to False."""
        result = ValidationResult(validator_name="TestValidator")
        assert result.passed is True

        result.add_issue(ValidationSeverity.ERROR, "Test error")

        assert result.passed is False

    def test_add_issue_warning_keeps_passed(self):
        """Test that adding a warning issue doesn't change passed."""
        result = ValidationResult(validator_name="TestValidator")
        assert result.passed is True

        result.add_issue(ValidationSeverity.WARNING, "Test warning")

        assert result.passed is True

    def test_has_issues(self):
        """Test has_issues method."""
        result = ValidationResult(validator_name="TestValidator")
        assert result.has_issues() is False

        result.add_issue(ValidationSeverity.INFO, "Test issue")
        assert result.has_issues() is True

    def test_get_error_count(self):
        """Test get_error_count method."""
        result = ValidationResult(validator_name="TestValidator")

        result.add_issue(ValidationSeverity.ERROR, "Error 1")
        result.add_issue(ValidationSeverity.WARNING, "Warning 1")
        result.add_issue(ValidationSeverity.ERROR, "Error 2")

        assert result.get_error_count() == 2

    def test_get_warning_count(self):
        """Test get_warning_count method."""
        result = ValidationResult(validator_name="TestValidator")

        result.add_issue(ValidationSeverity.WARNING, "Warning 1")
        result.add_issue(ValidationSeverity.INFO, "Info 1")
        result.add_issue(ValidationSeverity.WARNING, "Warning 2")

        assert result.get_warning_count() == 2

    def test_to_dict(self):
        """Test converting result to dictionary."""
        result = ValidationResult(validator_name="TestValidator")
        result.add_issue(ValidationSeverity.ERROR, "Error message")
        result.add_issue(ValidationSeverity.WARNING, "Warning message")
        result.metadata["test_key"] = "test_value"

        result_dict = result.to_dict()

        assert result_dict["validator_name"] == "TestValidator"
        assert result_dict["passed"] is False
        assert result_dict["issue_count"] == 2
        assert result_dict["error_count"] == 1
        assert result_dict["warning_count"] == 1
        assert len(result_dict["issues"]) == 2
        assert result_dict["metadata"]["test_key"] == "test_value"

    def test_str_representation(self):
        """Test string representation of result."""
        result = ValidationResult(validator_name="TestValidator")

        result_str = str(result)
        assert "TestValidator" in result_str
        assert "Passed: True" in result_str

    def test_str_with_issues(self):
        """Test string representation with issues."""
        result = ValidationResult(validator_name="TestValidator")
        result.add_issue(ValidationSeverity.ERROR, "Error message")
        result.add_issue(ValidationSeverity.WARNING, "Warning message")

        result_str = str(result)
        assert "Issues: 2" in result_str
        assert "Errors: 1" in result_str
        assert "Warnings: 1" in result_str
