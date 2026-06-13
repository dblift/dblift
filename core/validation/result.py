"""
Validation result classes for schema validation.
"""

from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional


class ValidationSeverity(Enum):
    """Severity levels for validation issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"


@dataclass
class ValidationIssue:
    """Represents a single validation issue."""

    severity: ValidationSeverity
    message: str
    object_type: Optional[str] = None
    object_name: Optional[str] = None
    property_name: Optional[str] = None
    expected_value: Optional[Any] = None
    actual_value: Optional[Any] = None

    def __str__(self) -> str:
        """String representation of the issue."""
        parts = [f"[{self.severity.value.upper()}] {self.message}"]
        if self.object_type and self.object_name:
            parts.append(f"Object: {self.object_type}.{self.object_name}")
        if self.property_name:
            parts.append(f"Property: {self.property_name}")
        if self.expected_value is not None and self.actual_value is not None:
            parts.append(f"Expected: {self.expected_value}, Actual: {self.actual_value}")
        return " | ".join(parts)


@dataclass
class ValidationResult:
    """Result of a validation operation."""

    validator_name: str
    passed: bool = True
    issues: List[ValidationIssue] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_issue(
        self,
        severity: ValidationSeverity,
        message: str,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        property_name: Optional[str] = None,
        expected_value: Optional[Any] = None,
        actual_value: Optional[Any] = None,
    ) -> None:
        """Add a validation issue."""
        issue = ValidationIssue(
            severity=severity,
            message=message,
            object_type=object_type,
            object_name=object_name,
            property_name=property_name,
            expected_value=expected_value,
            actual_value=actual_value,
        )
        self.issues.append(issue)
        if severity == ValidationSeverity.ERROR:
            self.passed = False

    def has_issues(self) -> bool:
        """Check if there are any issues."""
        return len(self.issues) > 0

    def get_error_count(self) -> int:
        """Get count of error-level issues."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.ERROR)

    def get_warning_count(self) -> int:
        """Get count of warning-level issues."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.WARNING)

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "validator_name": self.validator_name,
            "passed": self.passed,
            "issue_count": len(self.issues),
            "error_count": self.get_error_count(),
            "warning_count": self.get_warning_count(),
            "issues": [str(issue) for issue in self.issues],
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        """String representation of the result."""
        parts = [f"Validator: {self.validator_name}", f"Passed: {self.passed}"]
        if self.issues:
            parts.append(
                f"Issues: {len(self.issues)} (Errors: {self.get_error_count()}, Warnings: {self.get_warning_count()})"
            )
        return " | ".join(parts)
