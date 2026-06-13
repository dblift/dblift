"""Shared CI reporting primitives."""

from core.ci.findings import Finding, FindingReport, normalize_fail_on, should_fail_for_threshold
from core.ci.sql_validation import validation_result_to_finding_report

__all__ = [
    "Finding",
    "FindingReport",
    "normalize_fail_on",
    "should_fail_for_threshold",
    "validation_result_to_finding_report",
]
