"""Canonical encoding of corpus rows and compact facts."""

from __future__ import annotations

from typing import Any


def dumps(value: Any) -> str:
    """Encode one value as a single canonical JSON line."""
    return ""


def compact_facts(facts: Any) -> Any:
    """Reduce a ``StatementFacts`` to its comparable, JSON-ready form."""
    return None
