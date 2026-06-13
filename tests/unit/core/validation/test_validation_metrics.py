"""Tests for validation metrics."""

import json
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from core.validation.validation_metrics import DialectMetrics, TestResult, ValidationMetrics


@pytest.mark.unit
class TestTestResult:
    """Test TestResult dataclass."""

    def test_test_result_creation(self):
        """Test creating a test result."""
        result = TestResult(
            test_name="test1",
            dialect="postgresql",
            feature_type="data_type",
            feature_name="INTEGER",
            success=True,
        )

        assert result.test_name == "test1"
        assert result.dialect == "postgresql"
        assert result.feature_type == "data_type"
        assert result.feature_name == "INTEGER"
        assert result.success is True
        assert result.error_message is None

    def test_test_result_with_error(self):
        """Test test result with error message."""
        result = TestResult(
            test_name="test1",
            dialect="postgresql",
            feature_type="constraint",
            feature_name="PRIMARY_KEY",
            success=False,
            error_message="Test error",
        )

        assert result.success is False
        assert result.error_message == "Test error"

    def test_test_result_to_dict(self):
        """Test converting test result to dictionary."""
        result = TestResult(
            test_name="test1",
            dialect="postgresql",
            feature_type="data_type",
            feature_name="INTEGER",
            success=True,
        )

        result_dict = result.to_dict()

        assert result_dict["test_name"] == "test1"
        assert result_dict["dialect"] == "postgresql"
        assert result_dict["success"] is True


@pytest.mark.unit
class TestDialectMetrics:
    """Test DialectMetrics dataclass."""

    def test_dialect_metrics_creation(self):
        """Test creating dialect metrics."""
        metrics = DialectMetrics(dialect="postgresql")

        assert metrics.dialect == "postgresql"
        assert metrics.total_tests == 0
        assert metrics.passed_tests == 0
        assert metrics.failed_tests == 0

    def test_pass_rate_zero_tests(self):
        """Test pass rate with zero tests."""
        metrics = DialectMetrics(dialect="postgresql")

        assert metrics.pass_rate == 0.0

    def test_pass_rate(self):
        """Test pass rate calculation."""
        metrics = DialectMetrics(dialect="postgresql")
        metrics.total_tests = 10
        metrics.passed_tests = 8

        assert metrics.pass_rate == 80.0

    def test_confidence_score_100_percent(self):
        """Test confidence score at 100%."""
        metrics = DialectMetrics(dialect="postgresql")
        metrics.total_tests = 10
        metrics.passed_tests = 10

        assert metrics.confidence_score == 10.0

    def test_confidence_score_95_percent(self):
        """Test confidence score at 95%."""
        metrics = DialectMetrics(dialect="postgresql")
        metrics.total_tests = 100
        metrics.passed_tests = 95

        assert metrics.confidence_score >= 9.0

    def test_confidence_score_90_percent(self):
        """Test confidence score at 90%."""
        metrics = DialectMetrics(dialect="postgresql")
        metrics.total_tests = 100
        metrics.passed_tests = 90

        assert metrics.confidence_score >= 8.0

    def test_confidence_score_low(self):
        """Test confidence score at low pass rate."""
        metrics = DialectMetrics(dialect="postgresql")
        metrics.total_tests = 100
        metrics.passed_tests = 50

        assert metrics.confidence_score < 6.0

    def test_to_dict(self):
        """Test converting metrics to dictionary."""
        metrics = DialectMetrics(dialect="postgresql")
        metrics.total_tests = 10
        metrics.passed_tests = 8
        metrics.failed_tests = 2  # Set explicitly
        metrics.feature_coverage = {"data_type": {"passed": 5, "failed": 2}}

        metrics_dict = metrics.to_dict()

        assert metrics_dict["dialect"] == "postgresql"
        assert metrics_dict["total_tests"] == 10
        assert metrics_dict["passed_tests"] == 8
        assert metrics_dict["failed_tests"] == 2
        assert metrics_dict["pass_rate"] == 80.0
        assert "confidence_score" in metrics_dict


@pytest.mark.unit
class TestValidationMetrics:
    """Test ValidationMetrics class."""

    def test_metrics_creation(self):
        """Test creating validation metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            assert metrics.storage_path == storage_path
            assert metrics.test_results == []
            assert metrics.dialect_metrics == {}

    def test_metrics_creation_default_path(self):
        """Test creating metrics with default path."""
        metrics = ValidationMetrics()

        assert metrics.storage_path == Path("validation_metrics.json")

    def test_record_test_result(self):
        """Test recording a test result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            assert len(metrics.test_results) == 1
            assert "postgresql" in metrics.dialect_metrics
            assert metrics.dialect_metrics["postgresql"].total_tests == 1
            assert metrics.dialect_metrics["postgresql"].passed_tests == 1

    def test_record_test_result_failed(self):
        """Test recording a failed test result."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=False,
                error_message="Test error",
            )

            assert metrics.dialect_metrics["postgresql"].failed_tests == 1
            assert metrics.dialect_metrics["postgresql"].passed_tests == 0

    def test_record_test_result_feature_coverage(self):
        """Test feature coverage tracking."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            assert "data_type" in metrics.dialect_metrics["postgresql"].feature_coverage
            assert (
                metrics.dialect_metrics["postgresql"].feature_coverage["data_type"]["passed"] == 1
            )

    def test_get_confidence_score(self):
        """Test getting confidence score for dialect."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            score = metrics.get_confidence_score("postgresql")
            assert score > 0

    def test_get_confidence_score_nonexistent(self):
        """Test getting confidence score for nonexistent dialect."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            score = metrics.get_confidence_score("nonexistent")
            assert score == 0.0

    def test_get_overall_confidence(self):
        """Test getting overall confidence."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            metrics.record_test_result(
                test_name="test2",
                dialect="mysql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            overall = metrics.get_overall_confidence()
            assert overall > 0

    def test_get_overall_confidence_no_metrics(self):
        """Test overall confidence with no metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            overall = metrics.get_overall_confidence()
            assert overall == 0.0

    def test_generate_report(self):
        """Test generating report."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            report = metrics.generate_report()

            assert "# Validation Test Report" in report
            assert "postgresql" in report.lower()

    def test_generate_report_with_output_path(self):
        """Test generating report with output path."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            output_path = Path(tmpdir) / "report.md"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            report = metrics.generate_report(output_path=output_path)

            assert output_path.exists()
            assert "# Validation Test Report" in report

    def test_generate_report_with_failed_tests(self):
        """Test generating report with failed tests."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=False,
                error_message="Test error",
            )

            report = metrics.generate_report()

            assert "Failed Tests" in report
            assert "test1" in report

    def test_save_metrics(self):
        """Test saving metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            assert storage_path.exists()

    def test_load_metrics(self):
        """Test loading metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"

            # Create initial metrics and save
            metrics1 = ValidationMetrics(storage_path=storage_path)
            metrics1.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            # Create new metrics instance and load
            metrics2 = ValidationMetrics(storage_path=storage_path)

            assert len(metrics2.test_results) >= 1
            assert "postgresql" in metrics2.dialect_metrics

    def test_load_metrics_nonexistent(self):
        """Test loading metrics from nonexistent file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "nonexistent.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            assert metrics.test_results == []
            assert metrics.dialect_metrics == {}

    def test_load_metrics_invalid_json(self):
        """Test loading metrics from invalid JSON."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            storage_path.write_text("invalid json")

            metrics = ValidationMetrics(storage_path=storage_path)

            # Should handle gracefully
            assert isinstance(metrics, ValidationMetrics)

    def test_reset_metrics(self):
        """Test resetting metrics."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            metrics.reset_metrics()

            assert metrics.test_results == []
            assert metrics.dialect_metrics == {}
            assert not storage_path.exists()

    def test_generate_report_recommendations(self):
        """Test report generation with recommendations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            # Add tests with low pass rate
            for i in range(10):
                metrics.record_test_result(
                    test_name=f"test{i}",
                    dialect="postgresql",
                    feature_type="data_type",
                    feature_name="INTEGER",
                    success=(i < 7),  # 70% pass rate
                )

            report = metrics.generate_report()

            assert "Recommendations" in report

    def test_generate_report_feature_coverage(self):
        """Test report generation with feature coverage."""
        with tempfile.TemporaryDirectory() as tmpdir:
            storage_path = Path(tmpdir) / "metrics.json"
            metrics = ValidationMetrics(storage_path=storage_path)

            metrics.record_test_result(
                test_name="test1",
                dialect="postgresql",
                feature_type="data_type",
                feature_name="INTEGER",
                success=True,
            )

            metrics.record_test_result(
                test_name="test2",
                dialect="postgresql",
                feature_type="constraint",
                feature_name="PRIMARY_KEY",
                success=True,
            )

            report = metrics.generate_report()

            assert "Feature Coverage" in report
            assert "data_type" in report
            assert "constraint" in report
