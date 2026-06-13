"""
Validation metrics collection and reporting.

This module tracks validation test results and generates confidence scores
and reports showing which features work reliably.
"""

import json
import warnings
from dataclasses import asdict, dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional


@dataclass
class TestResult:
    """Result of a single validation test."""

    test_name: str
    dialect: str
    feature_type: str  # "data_type", "constraint", "index", etc.
    feature_name: str  # "INTEGER", "PRIMARY_KEY", etc.
    success: bool
    error_message: Optional[str] = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return asdict(self)


@dataclass
class DialectMetrics:
    """Metrics for a single dialect."""

    dialect: str
    total_tests: int = 0
    passed_tests: int = 0
    failed_tests: int = 0
    feature_coverage: Dict[str, Dict[str, int]] = field(default_factory=dict)

    @property
    def pass_rate(self) -> float:
        """Calculate pass rate."""
        if self.total_tests == 0:
            return 0.0
        return (self.passed_tests / self.total_tests) * 100

    @property
    def confidence_score(self) -> float:
        """
        Calculate confidence score (1-10 scale).

        Based on pass rate:
        - 100% = 10/10
        - 95%+ = 9/10
        - 90%+ = 8/10
        - 85%+ = 7/10
        - 80%+ = 6/10
        - etc.
        """
        pass_rate = self.pass_rate
        if pass_rate >= 100:
            return 10.0
        elif pass_rate >= 95:
            return 9.0 + (pass_rate - 95) / 5
        elif pass_rate >= 90:
            return 8.0 + (pass_rate - 90) / 5
        elif pass_rate >= 85:
            return 7.0 + (pass_rate - 85) / 5
        elif pass_rate >= 80:
            return 6.0 + (pass_rate - 80) / 5
        else:
            return pass_rate / 13.33  # Scale 0-80% to 0-6

    def to_dict(self) -> Dict:
        """Convert to dictionary."""
        return {
            "dialect": self.dialect,
            "total_tests": self.total_tests,
            "passed_tests": self.passed_tests,
            "failed_tests": self.failed_tests,
            "pass_rate": round(self.pass_rate, 2),
            "confidence_score": round(self.confidence_score, 1),
            "feature_coverage": self.feature_coverage,
        }


class ValidationMetrics:
    """Collects and analyzes validation test metrics."""

    def __init__(self, storage_path: Optional[Path] = None):
        """
        Initialize metrics collector.

        Args:
            storage_path: Path to store metrics data (JSON file)
        """
        self.storage_path = storage_path or Path("validation_metrics.json")
        self.test_results: List[TestResult] = []
        self.dialect_metrics: Dict[str, DialectMetrics] = {}

        # Load existing metrics if available
        self._load_metrics()

    def record_test_result(
        self,
        test_name: str,
        dialect: str,
        feature_type: str,
        feature_name: str,
        success: bool,
        error_message: Optional[str] = None,
    ) -> None:
        """
        Record a test result.

        Args:
            test_name: Name of the test
            dialect: Database dialect
            feature_type: Type of feature being tested
            feature_name: Specific feature name
            success: Whether test passed
            error_message: Error message if failed
        """
        result = TestResult(
            test_name=test_name,
            dialect=dialect,
            feature_type=feature_type,
            feature_name=feature_name,
            success=success,
            error_message=error_message,
        )

        self.test_results.append(result)

        # Update dialect metrics
        if dialect not in self.dialect_metrics:
            self.dialect_metrics[dialect] = DialectMetrics(dialect=dialect)

        metrics = self.dialect_metrics[dialect]
        metrics.total_tests += 1
        if success:
            metrics.passed_tests += 1
        else:
            metrics.failed_tests += 1

        # Update feature coverage
        if feature_type not in metrics.feature_coverage:
            metrics.feature_coverage[feature_type] = {"passed": 0, "failed": 0}

        if success:
            metrics.feature_coverage[feature_type]["passed"] += 1
        else:
            metrics.feature_coverage[feature_type]["failed"] += 1

        # Auto-save after each result
        self._save_metrics()

    def get_confidence_score(self, dialect: str) -> float:
        """
        Get confidence score for a dialect.

        Args:
            dialect: Database dialect

        Returns:
            Confidence score (1-10 scale)
        """
        if dialect not in self.dialect_metrics:
            return 0.0
        return self.dialect_metrics[dialect].confidence_score

    def get_overall_confidence(self) -> float:
        """Get overall confidence score across all dialects."""
        if not self.dialect_metrics:
            return 0.0

        scores = [m.confidence_score for m in self.dialect_metrics.values()]
        return sum(scores) / len(scores)

    def generate_report(self, output_path: Optional[Path] = None) -> str:
        """
        Generate a comprehensive validation report.

        Args:
            output_path: Optional path to write report to

        Returns:
            Report as markdown string
        """
        report_lines = [
            "# Validation Test Report",
            "",
            f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            "",
            "## Overall Summary",
            "",
        ]

        # Overall statistics
        total_tests = sum(m.total_tests for m in self.dialect_metrics.values())
        total_passed = sum(m.passed_tests for m in self.dialect_metrics.values())
        overall_pass_rate = (total_passed / total_tests * 100) if total_tests > 0 else 0
        overall_confidence = self.get_overall_confidence()

        report_lines.extend(
            [
                f"- **Total Tests**: {total_tests}",
                f"- **Passed**: {total_passed}",
                f"- **Failed**: {total_tests - total_passed}",
                f"- **Pass Rate**: {overall_pass_rate:.1f}%",
                f"- **Overall Confidence**: {overall_confidence:.1f}/10",
                "",
            ]
        )

        # Per-dialect summary
        report_lines.extend(
            [
                "## Dialect Summary",
                "",
                "| Dialect | Tests | Passed | Failed | Pass Rate | Confidence |",
                "|---------|-------|--------|--------|-----------|------------|",
            ]
        )

        for dialect, metrics in sorted(self.dialect_metrics.items()):
            report_lines.append(
                f"| {dialect} | {metrics.total_tests} | {metrics.passed_tests} | "
                f"{metrics.failed_tests} | {metrics.pass_rate:.1f}% | "
                f"{metrics.confidence_score:.1f}/10 |"
            )

        report_lines.append("")

        # Feature coverage per dialect
        for dialect, metrics in sorted(self.dialect_metrics.items()):
            report_lines.extend(
                [
                    f"## {dialect.upper()} Feature Coverage",
                    "",
                    "| Feature Type | Passed | Failed | Pass Rate |",
                    "|--------------|--------|--------|-----------|",
                ]
            )

            for feature_type, counts in sorted(metrics.feature_coverage.items()):
                passed = counts["passed"]
                failed = counts["failed"]
                total = passed + failed
                pass_rate = (passed / total * 100) if total > 0 else 0
                report_lines.append(f"| {feature_type} | {passed} | {failed} | {pass_rate:.1f}% |")

            report_lines.append("")

        # Failed tests details
        failed_results = [r for r in self.test_results if not r.success]
        if failed_results:
            report_lines.extend(
                [
                    "## Failed Tests",
                    "",
                ]
            )

            for result in failed_results[-20:]:  # Last 20 failures
                report_lines.extend(
                    [
                        f"### {result.test_name}",
                        f"- **Dialect**: {result.dialect}",
                        f"- **Feature**: {result.feature_type} / {result.feature_name}",
                        f"- **Error**: {result.error_message or 'No error message'}",
                        f"- **Time**: {result.timestamp}",
                        "",
                    ]
                )

        # Recommendations
        report_lines.extend(
            [
                "## Recommendations",
                "",
            ]
        )

        for dialect, metrics in sorted(self.dialect_metrics.items()):
            if metrics.confidence_score < 9.0:
                report_lines.append(
                    f"### {dialect.upper()} (Confidence: {metrics.confidence_score:.1f}/10)"
                )

                # Find weakest features
                weak_features = []
                for feature_type, counts in metrics.feature_coverage.items():
                    passed = counts["passed"]
                    failed = counts["failed"]
                    total = passed + failed
                    if total > 0:
                        pass_rate = passed / total * 100
                        if pass_rate < 90:
                            weak_features.append((feature_type, pass_rate, failed))

                if weak_features:
                    report_lines.append("**Areas needing improvement:**")
                    for feature, pass_rate, failed_count in sorted(
                        weak_features, key=lambda x: x[1]
                    ):
                        report_lines.append(
                            f"- {feature}: {pass_rate:.1f}% pass rate ({failed_count} failures)"
                        )
                    report_lines.append("")

        report = "\n".join(report_lines)

        # Write to file if requested
        if output_path:
            output_path.write_text(report)

        return report

    def _save_metrics(self) -> None:
        """Save metrics to storage."""
        data = {
            "last_updated": datetime.now().isoformat(),
            "test_results": [r.to_dict() for r in self.test_results[-1000:]],  # Keep last 1000
            "dialect_metrics": {
                dialect: metrics.to_dict() for dialect, metrics in self.dialect_metrics.items()
            },
        }

        try:
            self.storage_path.write_text(json.dumps(data, indent=2))
        except Exception as e:
            warnings.warn(f"Could not save metrics: {e}", UserWarning)

    def _load_metrics(self) -> None:
        """Load metrics from storage."""
        if not self.storage_path.exists():
            return

        try:
            data = json.loads(self.storage_path.read_text())

            # Load test results
            for result_data in data.get("test_results", []):
                self.test_results.append(TestResult(**result_data))

            # Load dialect metrics
            for dialect, metrics_data in data.get("dialect_metrics", {}).items():
                self.dialect_metrics[dialect] = DialectMetrics(
                    dialect=metrics_data["dialect"],
                    total_tests=metrics_data["total_tests"],
                    passed_tests=metrics_data["passed_tests"],
                    failed_tests=metrics_data["failed_tests"],
                    feature_coverage=metrics_data["feature_coverage"],
                )
        except Exception as e:
            warnings.warn(f"Could not load metrics: {e}", UserWarning)

    def reset_metrics(self) -> None:
        """Reset all metrics."""
        self.test_results = []
        self.dialect_metrics = {}
        if self.storage_path.exists():
            self.storage_path.unlink()
