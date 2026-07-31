"""Oracle's status derivation must not depend on the migration's *format*.

``OracleHistoryManager._normalize_migration_results`` is the only dialect that
derives the per-row ``status`` from raw string comparisons against ``"SQL"``.
``MigrationType.SQL`` means "versioned", not "SQL format" — a versioned ``.py``
migration is stored as ``PYTHON`` — so those comparisons silently exclude every
Python migration from the undone-version accounting.

Two comparisons are involved and they must be widened together:

* the one populating ``version_latest_success`` (which versioned attempt is
  the latest for a version), and
* the one selecting rows eligible for the ``UNDONE`` status.

Widening only the second would make Python migrations reach a *different*
conclusion than SQL ones for the same history shape, replacing one divergence
with another. These tests are therefore written as parity assertions: the same
history shape must derive the same statuses whichever versioned type it uses.

Scope note: Oracle's ``UNDONE`` branch fires only when the *latest* versioned
attempt for an undone version failed, so a plain undo is reported ``SUCCESS``
here while ``MigrationInfoDataCollector`` reports ``UNDONE``. That divergence
is format-independent — it is identical for ``SQL`` and ``PYTHON`` before and
after this change — and is out of scope for the type-conflation fix.
"""

from __future__ import annotations

from typing import Any, Dict, List
from unittest.mock import MagicMock

import pytest

from db.plugins.oracle.oracle.history_manager import OracleHistoryManager

VERSIONED_TYPES = ["SQL", "PYTHON"]


def _manager() -> OracleHistoryManager:
    return OracleHistoryManager(MagicMock(), MagicMock(), MagicMock(), MagicMock())


def _row(rank: int, version: str, type_: str, success: int = 1) -> Dict[str, Any]:
    # Oracle returns uppercase column names; _normalize_migration_results lowercases them.
    return {
        "INSTALLED_RANK": rank,
        "VERSION": version,
        "DESCRIPTION": "desc",
        "TYPE": type_,
        "SCRIPT": f"V{version}__desc",
        "SUCCESS": success,
    }


def _statuses(rows: List[Dict[str, Any]]) -> List[str]:
    return [r["status"] for r in _manager()._normalize_migration_results(rows)]


def _undo_then_failed_reapply(versioned_type: str) -> List[Dict[str, Any]]:
    """V1 applied, undone, then re-applied unsuccessfully."""
    return [
        _row(1, "1", versioned_type),
        _row(2, "1", "UNDO_SQL"),
        _row(3, "1", versioned_type, success=0),
    ]


@pytest.mark.unit
class TestOracleStatusFormatParity:
    def test_undone_version_with_failed_reapply_is_undone_for_either_format(self):
        """The one shape where the raw ``== "SQL"`` comparisons are observable."""
        for versioned_type in VERSIONED_TYPES:
            assert _statuses(_undo_then_failed_reapply(versioned_type)) == [
                "UNDONE",
                "SUCCESS",
                "FAILED",
            ], f"{versioned_type} derived the wrong statuses"

    @pytest.mark.parametrize("versioned_type", VERSIONED_TYPES)
    def test_plain_successful_versioned_row_is_success(self, versioned_type):
        assert _statuses([_row(1, "1", versioned_type)]) == ["SUCCESS"]

    @pytest.mark.parametrize("versioned_type", VERSIONED_TYPES)
    def test_failed_versioned_row_is_failed(self, versioned_type):
        assert _statuses([_row(1, "1", versioned_type, success=0)]) == ["FAILED"]

    @pytest.mark.parametrize("versioned_type", VERSIONED_TYPES)
    def test_delete_row_is_deleted(self, versioned_type):
        rows = [_row(1, "1", versioned_type), _row(2, "1", "DELETE")]
        assert _statuses(rows)[1] == "DELETED"

    @pytest.mark.parametrize(
        "shape",
        [
            "plain",
            "undo",
            "undo_then_failed_reapply",
            "undo_then_successful_reapply",
        ],
    )
    def test_sql_and_python_derive_identical_statuses(self, shape):
        def build(versioned_type: str) -> List[Dict[str, Any]]:
            base = [_row(1, "1", versioned_type)]
            if shape == "plain":
                return base
            base.append(_row(2, "1", "UNDO_SQL"))
            if shape == "undo":
                return base
            failed = shape == "undo_then_failed_reapply"
            base.append(_row(3, "1", versioned_type, success=0 if failed else 1))
            return base

        assert _statuses(build("SQL")) == _statuses(build("PYTHON"))
