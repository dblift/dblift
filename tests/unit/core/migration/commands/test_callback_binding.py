"""Callback dispatch binds its directory arguments once per command."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.base_command import BaseCommand


def _make_command() -> BaseCommand:
    command = BaseCommand.__new__(BaseCommand)
    command.log = MagicMock()
    command.state_manager = MagicMock()
    command._execute_callbacks = MagicMock()
    return command


@pytest.mark.unit
class TestCallbackBinding:
    def test_fire_delegates_with_bound_arguments(self):
        command = _make_command()
        result = MagicMock()
        command._bind_callbacks(Path("/m"), False, [Path("/x")], {Path("/m"): True}, result)

        command._fire("beforeMigrate")

        command._execute_callbacks.assert_called_once_with(
            Path("/m"), "beforeMigrate", False, [Path("/x")], {Path("/m"): True}, result=result
        )

    def test_fire_without_scripts_dir_does_not_scan(self):
        command = _make_command()
        command._bind_callbacks(None, False, None, None, None)

        command._fire("beforeClean")

        command._execute_callbacks.assert_not_called()
        assert command.state_manager.mock_calls == []

    def test_fire_before_binding_raises(self):
        command = _make_command()

        with pytest.raises(RuntimeError, match="callbacks are not bound"):
            command._fire("beforeMigrate")

    def test_callbacks_for_uses_one_snapshot_in_event_order(self):
        command = _make_command()
        command._bind_callbacks(Path("/m"), True, [Path("/x")], {Path("/m"): False}, None)
        snapshot = object()
        command.state_manager.new_callback_snapshot.return_value = snapshot
        command.state_manager.get_callbacks_by_event.side_effect = [["a", "b"], ["c"]]

        callbacks = command._callbacks_for(["beforeUndo", "afterUndo"])

        assert callbacks == ["a", "b", "c"]
        command.state_manager.new_callback_snapshot.assert_called_once_with()
        calls = command.state_manager.get_callbacks_by_event.call_args_list
        assert [c.args[1] for c in calls] == ["beforeUndo", "afterUndo"]
        for call in calls:
            assert call.args[0] == Path("/m")
            assert call.kwargs == {
                "read_snapshot": snapshot,
                "recursive": True,
                "additional_dirs": [Path("/x")],
                "dir_recursive_map": {Path("/m"): False},
            }
