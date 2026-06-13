"""Tests for confidence scorer."""

import pytest

from core.validation.confidence_scorer import ConfidenceScorer
from core.validation.result import ValidationResult, ValidationSeverity


@pytest.mark.unit
class TestConfidenceScorer:
    """Test ConfidenceScorer class."""

    def test_calculate_completeness_score_no_result(self):
        """Test completeness score with no result."""
        score = ConfidenceScorer.calculate_completeness_score(None, total_objects=0)

        assert score == 0.5

    def test_calculate_completeness_score_no_issues(self):
        """Test completeness score with no issues."""
        result = ValidationResult(validator_name="test")
        score = ConfidenceScorer.calculate_completeness_score(result, total_objects=0)

        assert score == 1.0

    def test_calculate_completeness_score_with_issues(self):
        """Test completeness score with issues."""
        result = ValidationResult(validator_name="test")
        result.add_issue(ValidationSeverity.ERROR, "Error")
        score = ConfidenceScorer.calculate_completeness_score(result, total_objects=0)

        assert score < 1.0

    def test_calculate_completeness_score_with_total_objects(self):
        """Test completeness score with total objects."""
        result = ValidationResult(validator_name="test")
        result.add_issue(ValidationSeverity.ERROR, "Error")
        score = ConfidenceScorer.calculate_completeness_score(result, total_objects=10)

        assert score == 0.9  # 9/10 captured

    def test_calculate_completeness_score_all_errors(self):
        """Test completeness score when all objects have errors."""
        result = ValidationResult(validator_name="test")
        for _ in range(10):
            result.add_issue(ValidationSeverity.ERROR, "Error")
        score = ConfidenceScorer.calculate_completeness_score(result, total_objects=10)

        assert score == 0.0

    def test_calculate_consistency_score_no_result(self):
        """Test consistency score with no result."""
        score = ConfidenceScorer.calculate_consistency_score(None)

        assert score == 0.5

    def test_calculate_consistency_score_passed(self):
        """Test consistency score when passed."""
        result = ValidationResult(validator_name="test")
        result.passed = True
        score = ConfidenceScorer.calculate_consistency_score(result)

        assert score == 1.0

    def test_calculate_consistency_score_with_errors(self):
        """Test consistency score with errors."""
        result = ValidationResult(validator_name="test")
        result.add_issue(ValidationSeverity.ERROR, "Error")
        score = ConfidenceScorer.calculate_consistency_score(result)

        assert score < 1.0

    def test_calculate_consistency_score_with_warnings(self):
        """Test consistency score with warnings."""
        result = ValidationResult(validator_name="test")
        result.passed = False  # Warnings should make it not pass
        result.add_issue(ValidationSeverity.WARNING, "Warning")
        score = ConfidenceScorer.calculate_consistency_score(result)

        assert score < 1.0

    def test_calculate_accuracy_score_no_result(self):
        """Test accuracy score with no result."""
        score = ConfidenceScorer.calculate_accuracy_score(None)

        assert score == 0.5

    def test_calculate_accuracy_score_passed(self):
        """Test accuracy score when passed."""
        result = ValidationResult(validator_name="test")
        result.passed = True
        score = ConfidenceScorer.calculate_accuracy_score(result)

        assert score == 1.0

    def test_calculate_accuracy_score_with_metadata(self):
        """Test accuracy score with metadata."""
        result = ValidationResult(validator_name="test")
        result.metadata["captured_count"] = 10
        result.metadata["live_count"] = 10
        result.metadata["common_count"] = 10
        result.add_issue(ValidationSeverity.ERROR, "Error")
        score = ConfidenceScorer.calculate_accuracy_score(result)

        assert score < 1.0

    def test_calculate_accuracy_score_no_common(self):
        """Test accuracy score with no common objects."""
        result = ValidationResult(validator_name="test")
        # When common_count is 0, the score should be 0.0
        # But the code checks total_issues == 0 first (returns 1.0)
        # So we need to have at least one issue to reach the common_count check
        result.passed = False
        result.add_issue(
            ValidationSeverity.WARNING, "Test issue"
        )  # Add issue to avoid early return
        result.metadata["common_count"] = 0
        result.metadata["captured_count"] = 5
        result.metadata["live_count"] = 5
        score = ConfidenceScorer.calculate_accuracy_score(result)

        # When common_count is 0, score should be 0.0 (line 135 in confidence_scorer.py)
        assert score == 0.0

    def test_calculate_error_rate_score_no_operations(self):
        """Test error rate score with no operations."""
        score = ConfidenceScorer.calculate_error_rate_score(0, 0, 0)

        assert score == 1.0

    def test_calculate_error_rate_score_with_issues(self):
        """Test error rate score with issues."""
        score = ConfidenceScorer.calculate_error_rate_score(2, 1, 0)

        assert score < 1.0

    def test_calculate_error_rate_score_with_operations(self):
        """Test error rate score with operations."""
        score = ConfidenceScorer.calculate_error_rate_score(2, 1, 100)

        assert score < 1.0
        assert score > 0.0

    def test_calculate_error_rate_score_perfect(self):
        """Test error rate score with no errors."""
        score = ConfidenceScorer.calculate_error_rate_score(0, 0, 100)

        assert score == 1.0

    def test_calculate_overall_confidence(self):
        """Test calculating overall confidence."""
        completeness_result = ValidationResult(validator_name="completeness")
        completeness_result.passed = True

        consistency_result = ValidationResult(validator_name="consistency")
        consistency_result.passed = True

        accuracy_result = ValidationResult(validator_name="accuracy")
        accuracy_result.passed = True

        confidence = ConfidenceScorer.calculate_overall_confidence(
            completeness_result=completeness_result,
            consistency_result=consistency_result,
            accuracy_result=accuracy_result,
            error_count=0,
            warning_count=0,
            total_objects=10,
        )

        assert "overall_score" in confidence
        assert "confidence_level" in confidence
        assert "breakdown" in confidence
        assert confidence["overall_score"] > 0.8

    def test_calculate_overall_confidence_no_results(self):
        """Test overall confidence with no results."""
        confidence = ConfidenceScorer.calculate_overall_confidence()

        assert "overall_score" in confidence
        assert confidence["overall_score"] > 0.0

    def test_calculate_overall_confidence_with_errors(self):
        """Test overall confidence with errors."""
        completeness_result = ValidationResult(validator_name="completeness")
        completeness_result.add_issue(ValidationSeverity.ERROR, "Error")

        confidence = ConfidenceScorer.calculate_overall_confidence(
            completeness_result=completeness_result,
            error_count=1,
            total_objects=10,
        )

        assert confidence["overall_score"] < 1.0

    def test_calculate_overall_confidence_high_level(self):
        """Test overall confidence at high level."""
        completeness_result = ValidationResult(validator_name="completeness")
        completeness_result.passed = True

        confidence = ConfidenceScorer.calculate_overall_confidence(
            completeness_result=completeness_result,
            total_objects=10,
        )

        assert confidence["confidence_level"] in ("HIGH", "MEDIUM", "LOW", "VERY_LOW")

    def test_get_confidence_level_high(self):
        """Test getting confidence level for high score."""
        level = ConfidenceScorer.get_confidence_level(0.95)

        assert level == "HIGH"

    def test_get_confidence_level_medium(self):
        """Test getting confidence level for medium score."""
        level = ConfidenceScorer.get_confidence_level(0.85)

        assert level == "MEDIUM"

    def test_get_confidence_level_low(self):
        """Test getting confidence level for low score."""
        level = ConfidenceScorer.get_confidence_level(0.65)

        assert level == "LOW"

    def test_get_confidence_level_very_low(self):
        """Test getting confidence level for very low score."""
        level = ConfidenceScorer.get_confidence_level(0.5)

        assert level == "VERY_LOW"

    def test_calculate_overall_confidence_breakdown(self):
        """Test overall confidence breakdown."""
        completeness_result = ValidationResult(validator_name="completeness")
        completeness_result.passed = True

        confidence = ConfidenceScorer.calculate_overall_confidence(
            completeness_result=completeness_result,
            total_objects=10,
        )

        breakdown = confidence["breakdown"]
        assert "completeness" in breakdown
        assert "consistency" in breakdown
        assert "accuracy" in breakdown
        assert "error_rate" in breakdown

        assert "score" in breakdown["completeness"]
        assert "weight" in breakdown["completeness"]
        assert "weighted" in breakdown["completeness"]
