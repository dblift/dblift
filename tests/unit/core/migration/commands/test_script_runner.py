"""Tests for the per-script runner shared by ``migrate`` and ``undo``."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dblift.core.exceptions import CallbackExecutionError
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.commands._script_runner import ScriptRunner
from dblift.core.migration.commands.migrate_command import MIGRATE_POLICY
from dblift.core.migration.commands.undo_command import UNDO_POLICY

EMIT = "dblift.core.migration.commands._script_runner.emit_script_event"


def _script() -> SimpleNamespace:
    return SimpleNamespace(
        script_name="V1__init.sql",
        version="1",
        description="init",
        type=SimpleNamespace(value="SQL"),
    )


def _command(calls: list, *, fire_raises=None):
    """A stub command whose collaborators all append to ``calls``."""
    command = MagicMock()

    def fire(event):
        calls.append(event)
        if fire_raises and fire_raises[0] == event:
            raise fire_raises[1]

    command._fire.side_effect = fire
    command.journal.start_migration.side_effect = lambda *a, **k: calls.append("journal.start")
    command.journal.end_migration.side_effect = lambda *a, **k: calls.append(
        "journal.end:ok" if k.get("success") else "journal.end:fail"
    )
    command.execution_engine.execute_migration.side_effect = lambda *a, **k: calls.append("execute")
    return command


def _emit_into(calls: list):
    return patch(EMIT, side_effect=lambda event, data: calls.append(event))


def _run(command, policy, result, on_success):
    return ScriptRunner(command, policy).run(
        _script(),
        result,
        event_data={"script": "V1__init.sql"},
        on_success=on_success,
    )


@pytest.mark.unit
def test_success_order():
    calls: list = []
    command = _command(calls)
    result = MigrateResult()

    with _emit_into(calls):
        ok = _run(command, MIGRATE_POLICY, result, lambda ms: calls.append("on_success"))

    assert ok is True
    assert calls == [
        "beforeEach",
        "beforeEachMigrate",
        "journal.start",
        "migration.script.started",
        "execute",
        "journal.end:ok",
        "on_success",
        "migration.script.completed",
        "afterEachMigrate",
        "afterEach",
    ]


@pytest.mark.unit
def test_reported_failure_order():
    calls: list = []
    command = _command(calls)
    result = MigrateResult()
    on_success = MagicMock()

    def fail(script, res):
        calls.append("execute")
        res.set_error("boom")

    command.execution_engine.execute_migration.side_effect = fail

    with _emit_into(calls):
        ok = _run(command, MIGRATE_POLICY, result, on_success)

    assert ok is False
    assert calls[-3:] == ["journal.end:fail", "migration.script.failed", "afterMigrateError"]
    on_success.assert_not_called()


@pytest.mark.unit
def test_raising_script_emits_failed_event():
    calls: list = []
    command = _command(calls)
    result = MigrateResult()
    command.execution_engine.execute_migration.side_effect = RuntimeError("driver")

    with patch(EMIT) as emit:
        ok = _run(command, MIGRATE_POLICY, result, MagicMock())

    assert ok is False
    failed = [c for c in emit.call_args_list if c.args[0] == "migration.script.failed"]
    assert len(failed) == 1
    assert failed[0].args[1]["error"] == "driver"
    assert result.error_message == "Migration failed: driver"
    command.journal.end_migration.assert_called_once()
    assert command.journal.end_migration.call_args.kwargs["success"] is False
    assert calls.count("afterMigrateError") == 1


@pytest.mark.unit
def test_raising_script_keeps_existing_error_message():
    command = _command([])
    result = MigrateResult()
    result.set_error("original error")
    command.execution_engine.execute_migration.side_effect = RuntimeError("new error")

    with patch(EMIT) as emit:
        ok = _run(command, MIGRATE_POLICY, result, MagicMock())

    assert ok is False
    assert result.error_message == "original error"
    failed = [c for c in emit.call_args_list if c.args[0] == "migration.script.failed"]
    assert failed[0].args[1]["error"] == "original error"


@pytest.mark.unit
def test_before_each_failure_fires_error_callback_once():
    calls: list = []
    command = _command(calls, fire_raises=("beforeEach", CallbackExecutionError("cb")))
    result = MigrateResult()

    with patch(EMIT) as emit:
        ok = _run(command, MIGRATE_POLICY, result, MagicMock())

    assert ok is False
    command.journal.start_migration.assert_not_called()
    command.journal.end_migration.assert_not_called()
    emit.assert_not_called()
    assert calls.count("afterMigrateError") == 1
    assert result.error_message == "Migration failed: cb"


@pytest.mark.unit
def test_undo_policy_emits_rolled_back():
    calls: list = []
    command = _command(calls)
    result = MigrateResult()

    with _emit_into(calls):
        ok = _run(command, UNDO_POLICY, result, lambda ms: None)

    assert ok is True
    assert calls == [
        "beforeEach",
        "journal.start",
        "migration.script.started",
        "execute",
        "journal.end:ok",
        "migration.script.completed",
        "undo.script.rolled_back",
        "afterEach",
    ]


@pytest.mark.unit
def test_execution_time_includes_before_callbacks():
    command = _command([])
    result = MigrateResult()
    on_success = MagicMock()

    with (
        patch(EMIT),
        patch(
            "dblift.core.migration.commands._script_runner.time.time", side_effect=[100.0, 100.5]
        ),
    ):
        ok = _run(command, MIGRATE_POLICY, result, on_success)

    assert ok is True
    on_success.assert_called_once_with(500)


@pytest.mark.unit
def test_after_each_failure_emits_single_terminal_event():
    calls: list = []
    command = _command(calls, fire_raises=("afterEach", CallbackExecutionError("after")))
    result = MigrateResult()

    with _emit_into(calls):
        ok = _run(command, MIGRATE_POLICY, result, MagicMock())

    assert ok is False
    assert calls.count("migration.script.completed") == 1
    assert "migration.script.failed" not in calls
    command.journal.end_migration.assert_called_once()
    assert command.journal.end_migration.call_args.kwargs["success"] is True
    assert calls.count("afterMigrateError") == 1
    assert result.error_message == "Migration failed: after"


@pytest.mark.unit
def test_error_event_failure_does_not_duplicate_terminal_event():
    calls: list = []
    command = _command(calls, fire_raises=("afterMigrateError", RuntimeError("scan")))
    result = MigrateResult()

    def fail(script, res):
        calls.append("execute")
        res.set_error("boom")

    command.execution_engine.execute_migration.side_effect = fail

    with _emit_into(calls):
        with pytest.raises(RuntimeError, match="scan"):
            _run(command, MIGRATE_POLICY, result, MagicMock())

    assert calls.count("migration.script.failed") == 1
    command.journal.end_migration.assert_called_once()
    assert calls.count("afterMigrateError") == 1
