"""``undo`` reports what ``plan_undo`` decided with the same log lines as before."""

from __future__ import annotations

from unittest.mock import MagicMock, call, patch

import pytest

from dblift.core.migration.rules.migration_rules import GROUP_TAG_PREFIX, MigrationRules
from tests.unit.core.migration.commands.test_undo_command_group_tag import (
    _make_command,
    _make_migration,
)


@pytest.fixture(autouse=True)
def _stop_undo_script_lookup_patches():
    yield
    patch.stopall()


def _group():
    tag = f"{GROUP_TAG_PREFIX}V9"
    return [_make_migration(f"9_{n}", tags=[tag]) for n in (1, 2, 3)]


def test_widening_a_plain_undo_to_its_group_is_logged() -> None:
    cmd = _make_command(_group())

    cmd.execute(scripts_dir=MagicMock(), dry_run=True)

    messages = [c.args[0] for c in cmd.log.info.call_args_list]
    assert any(
        m.startswith("Undoing 2 additional migration(s) written as one group with V9_1__test.sql: ")
        for m in messages
    )
    assert call.info("Found 3 migration(s) to undo") in cmd.log.mock_calls


def test_widening_a_target_version_undo_to_its_group_is_logged() -> None:
    cmd = _make_command(_group())

    cmd.execute(scripts_dir=MagicMock(), target_version="9_2", dry_run=True)

    messages = [c.args[0] for c in cmd.log.info.call_args_list]
    assert any(
        m.startswith(
            "--target-version 9_2 falls inside a group of migrations written as one unit; "
            "undoing 2 additional migration(s) too: "
        )
        for m in messages
    )


def test_a_missing_undo_script_is_logged_as_an_error_after_the_count() -> None:
    v1, v2 = _make_migration(1), _make_migration(2)
    cmd = _make_command([v1, v2], undo_scripts=[MagicMock(version=1)])

    result = cmd.execute(scripts_dir=MagicMock(), target_version=0)

    assert not result.success
    assert result.error_message == "No undo script found for V2__test.sql"
    calls = cmd.log.mock_calls
    found = calls.index(call.info("Found 2 migration(s) to undo"))
    assert calls[found + 1] == call.error("No undo script found for V2__test.sql")


def test_a_rules_refusal_sets_the_error_without_an_error_log() -> None:
    cmd = _make_command([_make_migration(1), _make_migration(2)])
    cmd.migration_rules = MagicMock(spec=MigrationRules)
    cmd.migration_rules._is_currently_undone.return_value = False
    cmd.migration_rules.should_undo_version.return_value = (False, "Version 2 is refused.")

    result = cmd.execute(scripts_dir=MagicMock(), target_version=0)

    assert not result.success
    assert result.error_message == "Version 2 is refused."
    cmd.log.error.assert_not_called()


def test_nothing_to_undo_is_logged_and_completes() -> None:
    cmd = _make_command([_make_migration(1)])

    result = cmd.execute(scripts_dir=MagicMock(), target_version=1)

    assert result.success
    assert call.info("No migrations to undo") in cmd.log.mock_calls
