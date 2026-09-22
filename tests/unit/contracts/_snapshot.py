"""Snapshot helper for public-contract tests.

A contract is a sorted list of plain-text facts. A fact that disappears is a
breaking change; a fact that appears is an addition that must be recorded.
Regenerate with ``DBLIFT_UPDATE_CONTRACTS=1 pytest tests/unit/contracts``.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Iterable

import pytest

SNAPSHOT_DIR = Path(__file__).parent / "snapshots"


def assert_matches_snapshot(name: str, facts: Iterable[str]) -> None:
    current = sorted(set(facts))
    path = SNAPSHOT_DIR / f"{name}.json"
    update = os.environ.get("DBLIFT_UPDATE_CONTRACTS") == "1"
    if update and os.environ.get("CI"):
        pytest.fail(
            "DBLIFT_UPDATE_CONTRACTS=1 must not be set under CI: snapshots are "
            "regenerated locally and committed"
        )
    if update:
        path.write_text(json.dumps(current, indent=2) + "\n", encoding="utf-8")
        return
    if not path.exists():
        pytest.fail(
            f"no snapshot at {path}; record it with DBLIFT_UPDATE_CONTRACTS=1 pytest "
            "tests/unit/contracts"
        )
    recorded = json.loads(path.read_text(encoding="utf-8"))
    removed = sorted(set(recorded) - set(current))
    added = sorted(set(current) - set(recorded))
    assert not removed, (
        f"BREAKING: {name} lost {len(removed)} public fact(s): {removed}. "
        "Removing public surface requires a MAJOR release and a deprecation "
        "cycle (docs/semver-policy.md section 3). Restore it, or deprecate first."
    )
    assert not added, (
        f"{name} gained {len(added)} public fact(s): {added}. Additions are a "
        "MINOR change: add a CHANGELOG entry, then regenerate with "
        "DBLIFT_UPDATE_CONTRACTS=1 pytest tests/unit/contracts"
    )
