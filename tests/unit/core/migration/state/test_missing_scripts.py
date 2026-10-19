"""The missing-script rule: applied migrations whose script is gone from the catalog."""

from __future__ import annotations

from typing import List, Optional

import pytest

from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.state.missing_scripts import missing_applied
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit


def _script(name: str) -> Migration:
    return make_migration(script_name=name, content="x", type=MigrationType.SQL)


def _row(
    name: str,
    *,
    type_: MigrationType = MigrationType.SQL,
    success: bool = True,
    version: Optional[str] = "1",
    rank: int = 1,
) -> Migration:
    row = make_migration(script_name=name, content="x", type=MigrationType.SQL)
    row.type = type_
    row.success = success
    row.version = version
    row.installed_rank = rank
    return row


def _names(rows) -> List[str]:
    return [row.script_name for row in rows]


def test_script_absent_from_catalog_is_missing():
    history = [_row("V1__a.sql"), _row("V2__b.sql", version="2", rank=2)]

    missing = missing_applied([_script("V1__a.sql")], history)

    assert _names(missing) == ["V2__b.sql"]
    assert missing[0] is history[1]


def test_delete_marker_excludes_the_script():
    history = [
        _row("V1__a.sql"),
        _row("V1__a.sql", type_=MigrationType.DELETE, rank=2),
        _row("V2__b.sql", version="2", rank=3),
    ]

    assert _names(missing_applied([], history)) == ["V2__b.sql"]


def test_file_name_matches_a_directory_qualified_row():
    history = [_row("extra/V1__a.sql")]

    assert missing_applied([_script("V1__a.sql")], history) == ()


def test_file_name_matches_a_directory_qualified_catalog_script():
    history = [_row("V1__a.sql")]

    assert missing_applied([_script("extra/V1__a.sql")], history) == ()


def test_audit_and_baseline_rows_are_never_missing():
    history = [
        _row("B1__baseline.sql", type_=MigrationType.BASELINE),
        _row("V0__legacy.sql", version="baseline"),
        _row("U1__a.sql", type_=MigrationType.UNDO_SQL),
        _row("V9__gone.sql", type_=MigrationType.DELETE, version="9"),
    ]

    assert missing_applied([], history) == ()


def test_script_is_listed_once_by_its_latest_successful_row():
    history = [
        _row("V1__a.sql", rank=1),
        _row("V2__b.sql", version="2", rank=2),
        _row("V1__a.sql", rank=3),
    ]

    missing = missing_applied([], history)

    assert _names(missing) == ["V2__b.sql", "V1__a.sql"]
    assert missing[1] is history[2]


def test_script_with_only_failed_rows_is_not_missing():
    history = [_row("V1__a.sql", success=False)]

    assert missing_applied([], history) == ()


def test_failed_retry_after_success_does_not_hide_the_script():
    history = [_row("V1__a.sql", rank=1), _row("V1__a.sql", success=False, rank=2)]

    assert _names(missing_applied([], history)) == ["V1__a.sql"]
