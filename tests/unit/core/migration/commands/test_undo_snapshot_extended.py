"""Extended tests for undo_command.py."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch


def _make_context():
    """Create a minimal command context mock."""
    ctx = MagicMock()
    ctx.config = MagicMock()
    ctx.config.database.type = "postgresql"
    ctx.config.database.schema = "public"
    ctx.log = MagicMock()
    ctx.provider = MagicMock()
    ctx.script_manager = MagicMock()
    ctx.history_manager = MagicMock()
    ctx.validator = MagicMock()
    ctx.execution_engine = MagicMock()
    ctx.migration_helpers = MagicMock()
    ctx.state_manager = MagicMock()
    ctx.migration_ui = MagicMock()
    ctx.migration_rules = MagicMock()
    ctx.journal = MagicMock()
    ctx.placeholder_service = MagicMock()
    return ctx


class TestUndoCommandExecute(unittest.TestCase):
    def _make(self):
        from core.migration.commands.undo_command import UndoCommand

        ctx = _make_context()
        return UndoCommand(ctx), ctx

    def test_no_migrations_returns_success(self):
        cmd, ctx = self._make()
        # Empty applied migrations
        ctx.state_manager.build_state.return_value = MagicMock(applied=[])
        ctx.history_manager.get_applied_migrations.return_value = []
        scripts_dir = Path("/tmp")
        result = cmd.execute(scripts_dir=scripts_dir)
        self.assertIsNotNone(result)

    def test_build_state_exception_handled(self):
        cmd, ctx = self._make()
        ctx.state_manager.build_state.side_effect = Exception("State error")
        ctx.history_manager.get_applied_migrations.return_value = []
        scripts_dir = Path("/tmp")
        result = cmd.execute(scripts_dir=scripts_dir)
        self.assertIsNotNone(result)

    def test_get_current_version_exception_handled(self):
        cmd, ctx = self._make()
        ctx.state_manager.build_state.return_value = MagicMock(applied=[MagicMock()])
        ctx.state_manager.get_current_version.side_effect = Exception("Version error")
        ctx.history_manager.get_applied_migrations.return_value = [MagicMock()]
        scripts_dir = Path("/tmp")
        result = cmd.execute(scripts_dir=scripts_dir)
        self.assertIsNotNone(result)
