"""The strict-ordering rule: pending versions at or below the current version are out of order."""

from __future__ import annotations

import pytest

from dblift.core.migration.migration import MigrationType
from dblift.core.migration.state.ordering import OutOfOrder, out_of_order
from tests.unit._migration_factory import make_migration

pytestmark = pytest.mark.unit


def _pending(version):
    return make_migration(
        script_name=f"V{version}__m.sql",
        version=version,
        description="m",
        type=MigrationType.SQL,
        content="SELECT 1;",
    )


@pytest.mark.parametrize("current", [None, ""])
def test_nothing_is_out_of_order_without_a_current_version(current):
    assert out_of_order([_pending("1"), _pending("2")], current) == ()


def test_lower_version_is_out_of_order():
    lower = _pending("2")
    assert out_of_order([lower], "3") == (OutOfOrder(lower, "3"),)


def test_equal_version_is_out_of_order():
    equal = _pending("3")
    assert out_of_order([equal], "3") == (OutOfOrder(equal, "3"),)


def test_higher_version_is_in_order():
    assert out_of_order([_pending("4")], "3") == ()


def test_numeric_not_lexical_comparison():
    assert out_of_order([_pending("10")], "9") == ()
    assert [e.migration.version for e in out_of_order([_pending("9")], "10")] == ["9"]


def test_input_order_is_kept_and_in_order_entries_dropped():
    pending = [_pending("5"), _pending("1"), _pending("7"), _pending("3")]
    found = out_of_order(pending, "5")
    assert [e.migration for e in found] == [pending[0], pending[1], pending[3]]
    assert {e.current_version for e in found} == {"5"}


def test_migration_without_a_version_is_never_out_of_order():
    unversioned = make_migration(
        script_name="R__view.sql",
        description="view",
        type=MigrationType.REPEATABLE,
        content="SELECT 1;",
    )
    assert out_of_order([unversioned], "3") == ()
