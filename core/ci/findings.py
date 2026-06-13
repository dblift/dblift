"""Normalized CI findings shared by validation-style commands."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from core.validation.failure_policy import (
    FailOnLevel,
    FindingSeverity,
    normalize_fail_on,
    severity_meets_threshold,
)


@dataclass(frozen=True)
class Finding:
    """One normalized validation or planning finding."""

    severity: FindingSeverity
    code: str
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    details: Dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        if self.severity not in ("error", "warning", "info"):
            object.__setattr__(self, "severity", "warning")

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the finding without empty optional fields."""
        payload: Dict[str, Any] = {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
        }
        if self.file:
            payload["file"] = self.file
        if self.line is not None:
            payload["line"] = self.line
        if self.column is not None:
            payload["column"] = self.column
        if self.details:
            payload["details"] = dict(self.details)
        return payload


@dataclass
class FindingReport:
    """Normalized command report used by CI formatters and exit policies."""

    command: str
    fail_on: FailOnLevel = "error"
    checked_count: int = 0
    findings: List[Finding] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)

    @property
    def summary(self) -> Dict[str, int]:
        """Count findings by severity."""
        counts = {"error": 0, "warning": 0, "info": 0}
        for finding in self.findings:
            counts[finding.severity] += 1
        return counts

    def to_dict(self) -> Dict[str, Any]:
        """Serialize the report to the stable JSON contract."""
        return {
            "command": self.command,
            "fail_on": self.fail_on,
            "checked_count": self.checked_count,
            "summary": self.summary,
            "metadata": dict(self.metadata),
            "findings": [finding.to_dict() for finding in self.findings],
            "success": not should_fail_for_threshold(self, self.fail_on),
        }


def should_fail_for_threshold(report: FindingReport, fail_on: str) -> bool:
    """Return True when report findings meet or exceed the configured threshold."""
    if any(finding.details.get("blocking") is True for finding in report.findings):
        return True
    threshold = normalize_fail_on(fail_on)
    return any(severity_meets_threshold(finding.severity, threshold) for finding in report.findings)
