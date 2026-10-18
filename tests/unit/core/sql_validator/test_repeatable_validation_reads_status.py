"""The validator reports what the state layer decided for each repeatable migration."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from dblift.core.logger import NullLog
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.state.repeatable_status import (
    RepeatableRun,
    RepeatableStatus,
    repeatable_runs,
)
from dblift.core.sql_validator.migration_validator import MigrationValidator, ValidationResult
from tests.unit._migration_factory import make_migration

pytestmark = [pytest.mark.unit]

FAILED_MESSAGE = (
    "Repeatable migration R__v.sql previously failed and has not changed. "
    "Please fix the script before retrying."
)


def _validator() -> MigrationValidator:
    instance = MigrationValidator.__new__(MigrationValidator)
    instance.log = NullLog()
    return instance


def _script(content: str = "SELECT 1;", name: str = "R__v.sql") -> Migration:
    return make_migration(script_name=name, content=content, type=MigrationType.REPEATABLE)


def _row(name="R__v.sql", *, checksum=None, success=True, rank=1, execution_time=10):
    return SimpleNamespace(
        script_name=name,
        type=MigrationType.REPEATABLE,
        checksum=checksum,
        success=success,
        installed_rank=rank,
        execution_time=execution_time,
    )


def _check(scripts, rows, **kwargs) -> ValidationResult:
    result = ValidationResult()
    _validator()._check_repeatable_migrations(scripts, rows, result, "validate", **kwargs)
    return result


def test_failed_changed_is_reapplied_with_failed_checksum():
    script = _script("SELECT 2;")
    result = _check([script], [_row(checksum=_script().checksum, success=False)])
    assert result.success
    assert [
        (r["script"], r["database_checksum"]) for r in result.repeatable_migrations_to_reapply
    ] == [("R__v.sql", str(_script().checksum))]


def test_failed_unchanged_with_zero_execution_time_is_refused():
    """A failed run is a failed run, whatever execution time was recorded."""
    script = _script()
    result = _check([script], [_row(checksum=script.checksum, success=False, execution_time=0)])
    assert result.success is False
    assert result.error_message == FAILED_MESSAGE


def test_failed_messages_accumulate_per_script():
    scripts = [_script(name="R__a.sql"), _script(name="R__b.sql")]
    rows = [_row(s.script_name, checksum=s.checksum, success=False) for s in scripts]
    result = _check(scripts, rows)
    assert result.error_message.count("previously failed and has not changed") == 2
    assert "\n" in result.error_message


def test_legacy_qualified_history_row_matched_by_file_name():
    script = _script()
    result = _check([script], [_row("extra/R__v.sql", checksum=script.checksum)])
    assert result.repeatable_migrations_to_reapply == []


def test_changed_repeatable_is_reapplied():
    result = _check([_script("SELECT 2;")], [_row(checksum=_script().checksum)])
    assert [r["script"] for r in result.repeatable_migrations_to_reapply] == ["R__v.sql"]


def test_supplied_runs_are_used_without_reading_history():
    script = _script()
    runs = {
        "R__v.sql": RepeatableRun(RepeatableStatus.CHANGED, 7, script.checksum),
        "R__other.sql": RepeatableRun(RepeatableStatus.CHANGED, 7, 8),
    }
    result = _check([script], [_row(checksum=script.checksum)], runs=runs)
    assert result.repeatable_migrations_to_reapply == [
        {"script": "R__v.sql", "database_checksum": "7", "filesystem_checksum": script.checksum}
    ]


def test_script_missing_from_supplied_runs_is_skipped():
    assert _check([_script()], [], runs={}).repeatable_migrations_to_reapply == []


def test_supplied_runs_match_derived_runs():
    script = _script()
    rows = [_row(checksum=script.checksum, success=False)]
    derived = _check([script], rows)
    supplied = _check([script], rows, runs=repeatable_runs([script], rows))
    assert derived.error_message == supplied.error_message == FAILED_MESSAGE


def test_supplied_checksum_drift_replaces_the_comparison():
    from unittest.mock import patch

    from dblift.core.migration.state.checksum_drift import ChecksumDrift
    from dblift.core.sql_validator._checksum_validator import validate_checksums

    script = make_migration(script_name="V1__a.sql", content="SELECT 1;", type=MigrationType.SQL)
    row = SimpleNamespace(
        script_name="V1__a.sql",
        version="1",
        type=MigrationType.SQL,
        checksum=script.checksum,
        success=True,
        installed_rank=1,
    )
    drift = [ChecksumDrift("V1__a.sql", 1, 2, False)]
    result, issues = ValidationResult(), []
    with patch(
        "dblift.core.sql_validator._checksum_validator.find_checksum_drift",
        side_effect=AssertionError("drift was supplied"),
    ):
        validate_checksums(_validator(), [script], [row], result, issues, drift=drift)
    assert any("V1__a.sql has been modified since it was applied" in i for i in issues)

    # Without a supplied answer the same rule is derived from the inputs.
    result, issues = ValidationResult(), []
    validate_checksums(_validator(), [script], [row], result, issues)
    assert not issues
