"""Issue #849: undo() and baseline() must share the canonical
``BaseCommand._run_preflight()`` instead of hand-rolling the
connect / create-history-table / populate-info sequence themselves.

These tests pin the exact ``_run_preflight`` arguments each command now
uses, so a future edit can't silently drop back to hand-rolling (which is
exactly the shape bug #821 was) or drift the ``create_schema``/``dry_run``
values away from what the old inline code did.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from dblift.core.migration.commands.baseline_command import BaselineCommand
from dblift.core.migration.commands.undo_command import UndoCommand


class _OrderTrackingProvider:
    """Plain provider stand-in with no ``_ensure_connection`` hook, so
    ``_ensure_connected()`` falls through to ``connect()`` and the call is
    observable (a bare ``MagicMock`` auto-creates a truthy
    ``_ensure_connection`` attribute that short-circuits this path)."""

    def __init__(self, calls: list[str]):
        self._calls = calls
        self._connected = False

    def is_connected(self) -> bool:
        return self._connected

    def connect(self) -> None:
        self._calls.append("connect")
        self._connected = True

    def begin_transaction(self) -> None:
        pass

    def commit_transaction(self) -> None:
        pass

    def rollback_transaction(self) -> None:
        pass


def _make_undo_cmd(history_manager=None, provider=None):
    state_manager = MagicMock()
    migration_state = MagicMock()
    migration_state.applied_objects = []
    migration_state.all_applied_objects = []
    migration_state.pending_objects = []
    migration_state.pending = []
    state_manager.build_state.return_value = migration_state
    state_manager.get_current_version.return_value = None
    from dblift.core.migration.state.migration_state_manager import MigrationStateManager

    _filter_mgr = MigrationStateManager.__new__(MigrationStateManager)
    state_manager.apply_filters_to_migrations.side_effect = (
        lambda migrations, **kwargs: _filter_mgr.apply_filters_to_migrations(migrations, **kwargs)
    )

    config = MagicMock()
    config.database.schema = "test"

    cmd = UndoCommand(
        config=config,
        log=MagicMock(),
        provider=provider or MagicMock(),
        script_manager=MagicMock(get_migration_scripts=MagicMock(return_value=[])),
        history_manager=history_manager or MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    cmd.journal = None
    cmd.placeholder_service = MagicMock()
    cmd.migration_helpers.setup_migration_parameters.return_value = (True, None)
    return cmd


def _make_baseline_cmd(history_manager=None, provider=None):
    config = SimpleNamespace(database=SimpleNamespace(schema="public", type="postgresql"))
    return BaselineCommand(
        config=config,
        log=MagicMock(),
        provider=provider or MagicMock(),
        script_manager=MagicMock(),
        history_manager=history_manager or MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )


@pytest.mark.unit
class TestUndoUsesRunPreflight:
    """undo()'s old hand-rolled sequence always called
    ``create_schema_and_history_table(create_schema=False)`` unconditionally
    (regardless of undo's own --dry-run flag, which only skips *executing*
    undo scripts later). The shared preflight must reproduce that exactly.
    """

    def test_calls_run_preflight_with_ensure_history_and_create_schema_false(self):
        cmd = _make_undo_cmd()
        with patch.object(cmd, "_run_preflight", wraps=cmd._run_preflight) as spy:
            cmd.execute(scripts_dir=MagicMock())

        spy.assert_called_once()
        _, kwargs = spy.call_args
        assert kwargs.get("ensure_history") is True
        assert kwargs.get("create_schema") is False
        # undo never passes its own dry_run through to preflight: the history
        # table must always be ensured, dry-run or not.
        assert "dry_run" not in kwargs

    def test_history_table_created_with_create_schema_false(self):
        hm = MagicMock()
        cmd = _make_undo_cmd(history_manager=hm)
        cmd.execute(scripts_dir=MagicMock())

        hm.create_schema_and_history_table.assert_called_once_with(create_schema=False)

    def test_history_table_still_created_when_undo_itself_is_a_dry_run(self):
        """Parity with the old hand-rolled code: the connect/create-history
        sequence ran before the dry_run branch was ever inspected."""
        hm = MagicMock()
        cmd = _make_undo_cmd(history_manager=hm)
        cmd.execute(scripts_dir=MagicMock(), dry_run=True)

        hm.create_schema_and_history_table.assert_called_once_with(create_schema=False)

    def test_connects_before_creating_history_table(self):
        calls: list[str] = []
        provider = _OrderTrackingProvider(calls)
        hm = MagicMock()
        hm.create_schema_and_history_table.side_effect = lambda **_: calls.append("create_history")

        cmd = _make_undo_cmd(history_manager=hm, provider=provider)
        cmd.execute(scripts_dir=MagicMock())

        assert calls == ["connect", "create_history"]


@pytest.mark.unit
class TestBaselineUsesRunPreflight:
    """baseline()'s old hand-rolled sequence called
    ``create_schema_and_history_table(create_schema=True)`` only when not a
    dry-run. The shared preflight must reproduce both the True value and the
    dry-run skip.
    """

    def test_calls_run_preflight_with_ensure_history_and_create_schema_true(self):
        cmd = _make_baseline_cmd()
        with patch.object(cmd, "_run_preflight", wraps=cmd._run_preflight) as spy:
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    cmd.execute("1.0", "initial baseline")

        spy.assert_called_once()
        _, kwargs = spy.call_args
        assert kwargs.get("ensure_history") is True
        assert kwargs.get("create_schema") is True
        assert kwargs.get("dry_run") is False

    def test_real_run_creates_history_table_with_create_schema_true(self):
        hm = MagicMock()
        cmd = _make_baseline_cmd(history_manager=hm)
        with patch.object(cmd, "_log_command_header_update"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute("1.0", "initial baseline")

        hm.create_schema_and_history_table.assert_called_once_with(create_schema=True)

    def test_dry_run_skips_history_table_creation_entirely(self):
        """baseline's dry-run must not create the schema/history table as a
        side effect — this is the behavior _run_preflight's dry_run flag
        already provides and must be preserved after the migration."""
        hm = MagicMock()
        hm.has_history_table = False
        cmd = _make_baseline_cmd(history_manager=hm)
        with patch.object(cmd, "_log_command_header_update"):
            with patch.object(cmd, "_log_command_completion"):
                result = cmd.execute("1.0", "initial baseline", dry_run=True)

        hm.create_schema_and_history_table.assert_not_called()
        assert result.success

    def test_dry_run_still_connects_and_populates_info(self):
        provider = MagicMock()
        hm = MagicMock()
        hm.has_history_table = False
        cmd = _make_baseline_cmd(history_manager=hm, provider=provider)
        with patch.object(cmd, "_populate_database_info") as populate_spy:
            with patch.object(cmd, "_log_command_header_update"):
                with patch.object(cmd, "_log_command_completion"):
                    cmd.execute("1.0", "initial baseline", dry_run=True)

        populate_spy.assert_called_once()

    def test_connects_before_creating_history_table(self):
        calls: list[str] = []
        provider = _OrderTrackingProvider(calls)
        hm = MagicMock()
        hm.create_schema_and_history_table.side_effect = lambda **_: calls.append("create_history")

        cmd = _make_baseline_cmd(history_manager=hm, provider=provider)
        with patch.object(cmd, "_log_command_header_update"):
            with patch.object(cmd, "_log_command_completion"):
                cmd.execute("1.0", "initial baseline")

        assert calls == ["connect", "create_history"]
