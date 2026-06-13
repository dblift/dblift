"""Shared failure policy for validation-style command results."""

from __future__ import annotations

from typing import Any, Dict, Literal, Optional, cast

FindingSeverity = Literal["error", "warning", "info"]
FailOnLevel = Literal["never", "error", "warning", "info"]

_ALWAYS_FAIL_SOURCES = frozenset({"checksum_drift", "runtime"})
_SEVERITY_RANK: Dict[str, int] = {"info": 1, "warning": 2, "error": 3}
_FAIL_ON_RANK: Dict[FailOnLevel, int] = {
    "never": 4,
    "error": 3,
    "warning": 2,
    "info": 1,
}


def normalize_fail_on(value: Optional[str]) -> FailOnLevel:
    """Return a valid failure threshold."""
    if value in ("never", "error", "warning", "info"):
        return cast(FailOnLevel, value)
    return "error"


def is_always_fail_source(source: Any) -> bool:
    """Return True when a finding source must fail regardless of threshold."""
    if source is None:
        return False
    value = getattr(source, "value", source)
    return str(value) in _ALWAYS_FAIL_SOURCES


def severity_meets_threshold(severity: Any, fail_on: str) -> bool:
    """Return True when severity meets or exceeds the failure threshold."""
    threshold = normalize_fail_on(fail_on)
    if threshold == "never":
        return False
    value = getattr(severity, "value", severity)
    severity_rank = _SEVERITY_RANK.get(str(value), 1)
    return severity_rank >= _FAIL_ON_RANK[threshold]
