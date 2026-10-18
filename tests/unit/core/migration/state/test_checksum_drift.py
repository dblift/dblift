"""Versioned checksum drift: the one comparison shared by ``validate`` and ``repair``."""

from __future__ import annotations

from typing import Optional

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.checksum_drift import ChecksumDrift, find_checksum_drift
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit


def _script(name: str, checksum: Optional[int], type_: MigrationType = MigrationType.SQL):
    script = make_migration(script_name=name, content="x", type=type_)
    script.checksum = checksum
    return script


def _row(
    name: str,
    checksum: Optional[int],
    *,
    type_=MigrationType.SQL,
    success=True,
    rank: int = 1,
):
    row = make_migration(script_name=name, content="x", type=MigrationType.SQL)
    row.type = type_
    row.checksum = checksum
    row.success = success
    row.installed_rank = rank
    return row


def test_versioned_change_is_drift():
    drift = find_checksum_drift([_script("V1__a.sql", 200)], [_row("V1__a.sql", 100)])

    assert drift == [
        ChecksumDrift(
            script_name="V1__a.sql", applied_checksum=100, current_checksum=200, repeatable=False
        )
    ]


def test_unsigned_stored_checksum_is_not_drift():
    scripts = [_script("V1__a.sql", -1022714467)]

    assert find_checksum_drift(scripts, [_row("V1__a.sql", 3272252829)]) == []


@pytest.mark.parametrize("stored,current", [(None, 5), (5, None), (None, None)])
def test_none_on_either_side_is_drift(stored, current):
    drift = find_checksum_drift([_script("V1__a.sql", current)], [_row("V1__a.sql", stored)])

    assert [d.script_name for d in drift] == ["V1__a.sql"]
    assert drift[0].applied_checksum == stored
    assert drift[0].current_checksum == current


def test_latest_successful_row_wins():
    applied = [_row("V1__a.sql", 100, rank=1), _row("V1__a.sql", 200, rank=2)]

    assert find_checksum_drift([_script("V1__a.sql", 200)], applied) == []
    drift = find_checksum_drift([_script("V1__a.sql", 100)], applied)
    assert [d.applied_checksum for d in drift] == [200]


def test_failed_row_ignored():
    applied = [_row("V1__a.sql", 100, rank=1), _row("V1__a.sql", 999, success=False, rank=2)]

    assert find_checksum_drift([_script("V1__a.sql", 100)], applied) == []
    # Only a failed row: there is no successful checksum to compare.
    assert find_checksum_drift([_script("V1__a.sql", 100)], [applied[1]]) == []


@pytest.mark.parametrize(
    "audit_type",
    [MigrationType.DELETE, MigrationType.UNDO_SQL, MigrationType.BASELINE, MigrationType.UNKNOWN],
)
def test_audit_rows_ignored(audit_type):
    scripts = [_script("V1__a.sql", 100)]

    assert find_checksum_drift(scripts, [_row("V1__a.sql", 999, type_=audit_type)]) == []


@pytest.mark.parametrize("audit_type", [MigrationType.DELETE, MigrationType.UNDO_SQL])
def test_delete_and_undo_rows_never_replace_the_applied_checksum(audit_type):
    applied = [_row("V1__a.sql", 100, rank=1), _row("V1__a.sql", 999, type_=audit_type, rank=2)]

    assert find_checksum_drift([_script("V1__a.sql", 100)], applied) == []


@pytest.mark.parametrize("audit_type", ["DELETE", "UNDO_SQL", "BASELINE", "UNKNOWN"])
def test_audit_rows_ignored_as_strings(audit_type):
    applied = [_row("V1__a.sql", 999, type_=audit_type)]

    assert find_checksum_drift([_script("V1__a.sql", 100)], applied) == []


def test_legacy_qualified_row_matches_basename():
    drift = find_checksum_drift([_script("V1__a.sql", 200)], [_row("extra/V1__a.sql", 100)])

    assert [d.script_name for d in drift] == ["extra/V1__a.sql"]
    assert (drift[0].applied_checksum, drift[0].current_checksum) == (100, 200)
    assert find_checksum_drift([_script("V1__a.sql", 100)], [_row("extra/V1__a.sql", 100)]) == []


def test_out_of_scope_and_missing_scripts_excluded():
    applied = [_row("V1__a.sql", 1), _row("V2__b.sql", 2, rank=2), _row("V3__c.sql", 3, rank=3)]
    scripts = [_script("V1__a.sql", 10)]  # V2 filtered out of scope, V3 missing from disk

    assert [d.script_name for d in find_checksum_drift(scripts, applied)] == ["V1__a.sql"]


def test_repeatable_flagged():
    applied = [_row("R__views.sql", 1, type_=MigrationType.REPEATABLE)]
    drift = find_checksum_drift([_script("R__views.sql", 2, MigrationType.REPEATABLE)], applied)

    assert [(d.script_name, d.repeatable) for d in drift] == [("R__views.sql", True)]


def test_one_entry_per_script_in_history_order():
    applied = [
        _row("V2__b.sql", 1, rank=1),
        _row("V1__a.sql", 1, rank=2),
        _row("V2__b.sql", 1, rank=3),
    ]
    scripts = [_script("V1__a.sql", 9), _script("V2__b.sql", 9)]

    assert [d.script_name for d in find_checksum_drift(scripts, applied)] == [
        "V2__b.sql",
        "V1__a.sql",
    ]
