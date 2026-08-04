"""Tests for per-migration callback dispatch."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.logger.results import MigrateResult
from core.migration.commands.migrate_command import MigrateCommand


@pytest.mark.unit
def test_migrate_dispatches_generic_and_command_specific_each_callbacks():
    command = MigrateCommand.__new__(MigrateCommand)
    command.journal = None
    command.execution_engine = MagicMock()
    command.log = MagicMock()
    command._execute_callbacks = MagicMock()
    migration = SimpleNamespace(
        script_name="V1__init.sql",
        version="1",
        description="init",
        type=SimpleNamespace(value="SQL"),
        checksum=123,
    )
    result = MigrateResult()

    assert command._execute_single_migration(
        migration=migration,
        scripts_dir=Path("migrations"),
        use_recursive=True,
        use_additional_dirs=None,
        dir_recursive_map=None,
        result=result,
    )

    events = [call.args[1] for call in command._execute_callbacks.call_args_list]
    assert events == ["beforeEach", "beforeEachMigrate", "afterEachMigrate", "afterEach"]


@pytest.mark.unit
def test_failing_beforeEachMigrate_callback_surfaces_its_own_error():
    """A beforeEachMigrate callback that raises must report its own failure.

    Regression test: start_time was assigned after the beforeEach/beforeEachMigrate
    callback dispatch, but read in the except block that a callback failure unwinds
    through, so a failing callback surfaced as UnboundLocalError instead of the
    callback's real error.
    """
    command = MigrateCommand.__new__(MigrateCommand)
    command.journal = None
    command.execution_engine = MagicMock()
    command.log = MagicMock()

    def _execute_callbacks(scripts_dir, event, *args, **kwargs):
        if event == "beforeEachMigrate":
            raise RuntimeError("no such table: err_log")

    command._execute_callbacks = MagicMock(side_effect=_execute_callbacks)
    migration = SimpleNamespace(
        script_name="V1__init.sql",
        version="1",
        description="init",
        type=SimpleNamespace(value="SQL"),
        checksum=123,
    )
    result = MigrateResult()

    success = command._execute_single_migration(
        migration=migration,
        scripts_dir=Path("migrations"),
        use_recursive=True,
        use_additional_dirs=None,
        dir_recursive_map=None,
        result=result,
    )

    assert success is False
    assert result.error_message is not None
    assert "no such table: err_log" in result.error_message
    assert "start_time" not in result.error_message


@pytest.mark.unit
def test_each_callback_banner_logs_once_per_migration_in_a_batch():
    """The "Executing N <event> callback(s)" banner must log once per
    migration in a batch, not just for the first migration.

    Regression test for issue #829: the banner is emitted via
    ``self.log.info()`` with the logger's default ``dedupe=True``. Because the
    same callback set (and therefore the identical message text) is
    dispatched before every migration in a batch, the logger's time-window
    deduplication silently swallowed the banner for every migration but the
    first, even though the callbacks themselves executed correctly for each
    migration (confirmed via a side-effect log table in the original report).
    """
    from core.logger.log import AbstractLog

    logged_messages: list[str] = []

    class _RecordingLog(AbstractLog):
        def _write_log_event(self, event, console_only=False):
            logged_messages.append(event.message)

    command = MigrateCommand.__new__(MigrateCommand)
    command.log = _RecordingLog("test")
    command.execution_engine = MagicMock()

    callback = SimpleNamespace(script_name="beforeEachMigrate__mark.sql")
    command.script_manager = MagicMock()
    command.script_manager.get_callbacks_by_event.return_value = [callback]

    scripts_dir = Path("migrations")

    # Simulate the per-migration dispatch that _execute_single_migration does
    # for a 2-migration batch, each with a matching beforeEachMigrate callback.
    for _ in range(2):
        command._execute_callbacks(
            scripts_dir,
            "beforeEachMigrate",
            True,
            None,
            None,
        )

    banner_lines = [m for m in logged_messages if m.startswith("Executing") and "callback(s)" in m]
    assert len(banner_lines) == 2, (
        "expected one banner line per migration in the batch, got "
        f"{len(banner_lines)}: {logged_messages}"
    )


@pytest.mark.unit
def test_each_callback_banner_falls_back_when_len_raises():
    """A callbacks collection that declares ``__len__`` but raises on call
    (a malformed/duck-typed collection) must still log a banner line,
    falling back to a plain "callback(s)" message instead of propagating."""

    class _BrokenLen:
        def __len__(self):
            raise TypeError("len() not actually supported")

        def __iter__(self):
            return iter([SimpleNamespace(script_name="beforeEachMigrate__mark.sql")])

        def __bool__(self):
            return True

    command = MigrateCommand.__new__(MigrateCommand)
    command.log = MagicMock()
    command.execution_engine = MagicMock()
    command.script_manager = MagicMock()
    command.script_manager.get_callbacks_by_event.return_value = _BrokenLen()

    command._execute_callbacks(Path("migrations"), "beforeEachMigrate", True, None, None)

    banner_calls = [
        call.args[0]
        for call in command.log.info.call_args_list
        if call.args[0].startswith("Executing") and "callback(s)" in call.args[0]
    ]
    assert banner_calls == ["Executing beforeEachMigrate callback(s)"]
