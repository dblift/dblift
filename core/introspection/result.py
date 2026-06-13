"""
Introspection result tracking for schema introspection.

This module provides result classes to track introspection success/failure,
warnings, errors, and completeness metrics.
"""

import logging
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ResultSeverity(Enum):
    """Severity levels for introspection issues."""

    INFO = "info"
    WARNING = "warning"
    ERROR = "error"
    CRITICAL = "critical"


@dataclass
class IntrospectionIssue:
    """Represents a single introspection issue (warning or error)."""

    severity: ResultSeverity
    message: str
    object_type: Optional[str] = None
    object_name: Optional[str] = None
    property_name: Optional[str] = None
    exception: Optional[Exception] = None

    def __str__(self) -> str:
        """String representation of the issue."""
        parts = [f"[{self.severity.value.upper()}] {self.message}"]
        if self.object_type and self.object_name:
            parts.append(f"Object: {self.object_type}.{self.object_name}")
        if self.property_name:
            parts.append(f"Property: {self.property_name}")
        if self.exception:
            parts.append(f"Exception: {type(self.exception).__name__}: {self.exception}")
        return " | ".join(parts)


@dataclass
class ObjectCaptureStatus:
    """Tracks capture status for a single object."""

    object_type: str
    object_name: str
    schema: Optional[str] = None
    captured: bool = True
    properties_captured: Dict[str, bool] = field(default_factory=dict)
    issues: List[IntrospectionIssue] = field(default_factory=list)

    def add_property_status(
        self, property_name: str, captured: bool, issue: Optional[IntrospectionIssue] = None
    ) -> None:
        """Track whether a property was successfully captured."""
        self.properties_captured[property_name] = captured
        if issue:
            self.issues.append(issue)

    def get_completeness_score(self) -> float:
        """Calculate completeness score (0.0 to 1.0)."""
        if not self.properties_captured:
            return 1.0 if self.captured else 0.0
        captured_count = sum(1 for captured in self.properties_captured.values() if captured)
        total_count = len(self.properties_captured)
        return captured_count / total_count if total_count > 0 else 1.0


@dataclass
class IntrospectionResult:
    """
    Result of schema introspection operation.

    Tracks success/failure, warnings, errors, and completeness metrics.
    """

    success: bool = True
    warnings: List[IntrospectionIssue] = field(default_factory=list)
    errors: List[IntrospectionIssue] = field(default_factory=list)
    object_statuses: List[ObjectCaptureStatus] = field(default_factory=list)
    missing_objects: List[Dict[str, Any]] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    def add_warning(
        self,
        message: str,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        property_name: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Add a warning to the result."""
        issue = IntrospectionIssue(
            severity=ResultSeverity.WARNING,
            message=message,
            object_type=object_type,
            object_name=object_name,
            property_name=property_name,
            exception=exception,
        )
        self.warnings.append(issue)
        logger.warning(str(issue))

    def add_error(
        self,
        message: str,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        property_name: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Add an error to the result."""
        issue = IntrospectionIssue(
            severity=ResultSeverity.ERROR,
            message=message,
            object_type=object_type,
            object_name=object_name,
            property_name=property_name,
            exception=exception,
        )
        self.errors.append(issue)
        self.success = False
        logger.error(str(issue))

    def add_critical(
        self,
        message: str,
        object_type: Optional[str] = None,
        object_name: Optional[str] = None,
        exception: Optional[Exception] = None,
    ) -> None:
        """Add a critical error to the result."""
        issue = IntrospectionIssue(
            severity=ResultSeverity.CRITICAL,
            message=message,
            object_type=object_type,
            object_name=object_name,
            exception=exception,
        )
        self.errors.append(issue)
        self.success = False
        logger.critical(str(issue))

    def has_warnings(self) -> bool:
        """Check if there are any warnings."""
        return len(self.warnings) > 0

    def has_errors(self) -> bool:
        """Check if there are any errors."""
        return len(self.errors) > 0

    def get_completeness_score(self) -> float:
        """Calculate overall completeness score (0.0 to 1.0)."""
        if not self.object_statuses:
            return 1.0 if self.success else 0.0

        total_score = sum(status.get_completeness_score() for status in self.object_statuses)
        return total_score / len(self.object_statuses) if self.object_statuses else 1.0

    def get_confidence_level(self) -> str:
        """Get confidence level based on completeness and errors."""
        completeness = self.get_completeness_score()
        has_errors = self.has_errors()
        has_warnings = self.has_warnings()

        if completeness >= 0.95 and not has_errors and not has_warnings:
            return "HIGH"
        elif completeness >= 0.80 and not has_errors:
            return "MEDIUM"
        elif completeness >= 0.60:
            return "LOW"
        else:
            return "VERY_LOW"

    def to_dict(self) -> Dict[str, Any]:
        """Convert result to dictionary."""
        return {
            "success": self.success,
            "warnings": [str(w) for w in self.warnings],
            "errors": [str(e) for e in self.errors],
            "completeness_score": self.get_completeness_score(),
            "confidence_level": self.get_confidence_level(),
            "object_count": len(self.object_statuses),
            "missing_object_count": len(self.missing_objects),
            "metadata": self.metadata,
        }

    def __str__(self) -> str:
        """String representation of the result."""
        parts = [f"Success: {self.success}"]
        if self.warnings:
            parts.append(f"Warnings: {len(self.warnings)}")
        if self.errors:
            parts.append(f"Errors: {len(self.errors)}")
        parts.append(f"Completeness: {self.get_completeness_score():.2%}")
        parts.append(f"Confidence: {self.get_confidence_level()}")
        return " | ".join(parts)
