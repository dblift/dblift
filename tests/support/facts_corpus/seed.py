"""Harvest the SQL inputs of the parser tests into ``inputs.jsonl`` (append-only)."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List


def source_files(root: Path) -> List[str]:
    """List the test files that call ``parse_sql(`` or ``extract_objects(``."""
    return []


def harvest(root: Path) -> List[Dict[str, Any]]:
    """Return one input row per distinct SQL script found in the source files."""
    return []


def merge_inputs(existing: List[Dict[str, Any]], found: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Merge harvested inputs into the existing ones; nothing is ever removed."""
    return []


def assert_only_added(before: List[Dict[str, Any]], after: List[Dict[str, Any]]) -> None:
    """Raise when an input present before is missing after."""


def split(family: str, sql: str) -> List[str]:
    """Split a script into statements with the family's analysis splitter."""
    return []


def seed(root: Path, inputs_path: Path, sources_path: Path) -> int:
    """Write ``inputs.jsonl`` and ``SOURCES.md``; return the number of inputs."""
    return 0
