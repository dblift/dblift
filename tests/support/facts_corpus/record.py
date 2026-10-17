"""Record statement facts and the frozen text extraction for every family statement."""

from __future__ import annotations

from typing import Any, Dict, List


def check_arm(arm: str, installed: str, versions: Dict[str, Any]) -> None:
    """Raise unless the installed sqlglot is the one recorded for ``arm``."""


def record_statement(family: str, sql: str) -> Dict[str, Any]:
    """Return ``facts`` and ``old`` for one statement on the running sqlglot."""
    return {}


def record_family(
    family: str,
    arm: str,
    inputs: List[Dict[str, Any]],
    existing: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Return the rows of a family after recording one sqlglot arm."""
    return []
