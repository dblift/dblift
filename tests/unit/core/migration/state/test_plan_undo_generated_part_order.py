"""``plan_undo`` refuses a generated part set whose application order it cannot trust."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.unit.core.migration.state.test_plan_undo import (
    GROUP_TAG_PREFIX,
    _applied,
    _legacy_generated_part,
    _manager,
    _paired_manager,
    _paired_parts,
    _plan,
)

pytestmark = pytest.mark.unit


def _parts():
    return [_legacy_generated_part(1, 2), _legacy_generated_part(2, 2)]


def test_parts_applied_in_reverse_part_order_are_refused() -> None:
    parts = _parts()
    second, first = _applied("9.2", 1), _applied("9.1", 2)
    first.script_name, second.script_name = (part.script_name for part in parts)
    manager, _, _ = _manager([second, first], ["9.1", "9.2"], forward_parts=parts)

    plan = _plan(manager)

    assert plan.steps == ()
    assert plan.refusal == (
        "Cannot undo a generated part set applied out of part order. "
        "Check migration history and recover this set manually."
    )


def test_a_part_sharing_its_install_rank_with_a_selected_migration_is_refused() -> None:
    parts = _parts()
    first, unrelated, last = _applied("9.1", 1), _applied("10", 1), _applied("9.2", 2)
    first.script_name, last.script_name = (part.script_name for part in parts)
    manager, _, _ = _manager([first, unrelated, last], ["9.1", "9.2", "10"], forward_parts=parts)

    plan = _plan(manager, target_version="0", exclude_versions=["9.1"])

    assert plan.steps == ()
    assert plan.refusal == "Cannot undo a generated part set with ambiguous application order."


def test_history_read_out_of_install_rank_order_is_refused() -> None:
    parts = _parts()
    first, second = _applied("9.1", 1), _applied("9.2", 2)
    first.script_name, second.script_name = (part.script_name for part in parts)
    manager, _, _ = _manager([second, first], ["9.1", "9.2"], forward_parts=parts)

    plan = _plan(manager, target_version="0")

    assert plan.steps == ()
    assert [migration.version for migration in plan.selected] == ["9.1", "9.2"]
    assert plan.refusal == "Cannot undo a generated part set out of part order."


def test_an_applied_part_whose_file_was_renamed_is_refused() -> None:
    tag = f"{GROUP_TAG_PREFIX}split"
    forwards, undos = _paired_parts()
    for forward in forwards:
        forward.tags = [tag]
    forwards[1].script_name = "V9_2__renamed.sql"
    forwards[1].path = Path("V9_2__renamed.sql")
    first, second = _applied("9.1", 1), _applied("9.2", 2)
    first.script_name, second.script_name = "V9_1__change.sql", "V9_2__change.sql"

    plan = _plan(_paired_manager([first, second], forwards, undos))

    assert plan.steps == ()
    assert plan.refusal == (
        "Cannot undo a partially applied generated part set: a generated part is absent "
        "from applied history: V9_2__change.sql. Check migration history and recover "
        "this set manually."
    )
