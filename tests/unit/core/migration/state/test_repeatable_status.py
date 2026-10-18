"""The state layer alone decides a repeatable migration's status from its latest run."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.state.repeatable_status import (
    PENDING_REPEATABLE_STATUSES,
    RepeatableRun,
    RepeatableStatus,
    repeatable_runs,
)
from tests.unit._migration_factory import make_migration

pytestmark = [pytest.mark.unit]


def _script(name: str = "R__v.sql", content: str = "SELECT 1;") -> Migration:
    return make_migration(script_name=name, content=content, type=MigrationType.REPEATABLE)


def _row(
    name: str = "R__v.sql",
    *,
    checksum: Any = None,
    success: Any = True,
    rank: int = 1,
    type: Any = MigrationType.REPEATABLE,
) -> SimpleNamespace:
    return SimpleNamespace(
        script_name=name, checksum=checksum, success=success, installed_rank=rank, type=type
    )


def _only(scripts, history) -> RepeatableRun:
    runs = repeatable_runs(scripts, history)
    assert len(runs) == 1
    return next(iter(runs.values()))


def test_new_when_no_row():
    run = _only([_script()], [])
    assert run == RepeatableRun(RepeatableStatus.NEW, None, _script().checksum)


def test_failed_changed_when_file_differs_from_failed_run():
    script = _script(content="SELECT 2;")
    run = _only([script], [_row(checksum=_script().checksum, success=False)])
    assert run.status is RepeatableStatus.FAILED_CHANGED
    assert run.stored_checksum == _script().checksum
    assert run.current_checksum == script.checksum


def test_failed_unchanged_when_file_matches_failed_run():
    script = _script()
    run = _only([script], [_row(checksum=script.checksum, success=False)])
    assert run.status is RepeatableStatus.FAILED_UNCHANGED


def test_changed_when_success_checksum_differs():
    script = _script(content="SELECT 2;")
    run = _only([script], [_row(checksum=_script().checksum)])
    assert run.status is RepeatableStatus.CHANGED
    assert run.stored_checksum == _script().checksum


def test_unchanged_when_success_checksum_matches():
    script = _script()
    assert _only([script], [_row(checksum=script.checksum)]).status is RepeatableStatus.UNCHANGED


def test_basename_match_for_legacy_row():
    script = _script()
    run = _only([script], [_row("extra-migrations/R__v.sql", checksum=script.checksum)])
    assert run.status is RepeatableStatus.UNCHANGED


def test_exact_name_wins_over_basename_rows():
    script = _script()
    history = [
        _row("old/R__v.sql", checksum=script.checksum, rank=9, success=False),
        _row("R__v.sql", checksum=script.checksum, rank=1),
    ]
    assert _only([script], history).status is RepeatableStatus.UNCHANGED


def test_audit_rows_ignored():
    script = _script()
    history = [
        _row(checksum=script.checksum, rank=1),
        _row(rank=2, type=MigrationType.DELETE, success=False),
        _row(rank=3, type=MigrationType.UNDO_SQL, success=False),
        _row(rank=4, type=MigrationType.SQL, success=False),
    ]
    assert _only([script], history).status is RepeatableStatus.UNCHANGED


def test_latest_run_by_installed_rank():
    script = _script()
    failed_then_ok = [
        _row(checksum=script.checksum, success=False, rank=1),
        _row(checksum=script.checksum, success=True, rank=2),
    ]
    assert _only([script], failed_then_ok).status is RepeatableStatus.UNCHANGED
    assert _only([script], list(reversed(failed_then_ok))).status is RepeatableStatus.UNCHANGED
    ok_then_failed = [
        _row(checksum=script.checksum, success=True, rank=1),
        _row(checksum=script.checksum, success=False, rank=2),
    ]
    assert _only([script], ok_then_failed).status is RepeatableStatus.FAILED_UNCHANGED


def test_unsigned_stored_checksum_normalised():
    script = _script()
    unsigned = script.checksum & 0xFFFFFFFF
    run = _only([script], [_row(checksum=str(unsigned))])
    assert run.status is RepeatableStatus.UNCHANGED
    assert run.stored_checksum == script.checksum


def test_null_success_row_is_not_a_recorded_run():
    assert _only([_script()], [_row(success=None)]).status is RepeatableStatus.NEW


def test_only_repeatable_scripts_are_keyed_by_script_name():
    versioned = make_migration(
        script_name="V1__a.sql", content="SELECT 1;", version="1", type=MigrationType.SQL
    )
    runs = repeatable_runs([versioned, _script("R__a.sql"), _script("R__b.sql")], [])
    assert set(runs) == {"R__a.sql", "R__b.sql"}


@pytest.mark.parametrize(
    "status,pending",
    [
        (RepeatableStatus.NEW, True),
        (RepeatableStatus.CHANGED, True),
        (RepeatableStatus.FAILED_CHANGED, True),
        (RepeatableStatus.UNCHANGED, False),
        (RepeatableStatus.FAILED_UNCHANGED, False),
    ],
)
def test_pending_statuses(status: RepeatableStatus, pending: bool):
    assert (status in PENDING_REPEATABLE_STATUSES) is pending
