"""No-target-version undo: the auto-scan loop at the top of UndoCommand.execute()
must silently skip candidates that are already undone and fall through to the
next one, without logging the "please specify version X" message that
should_undo_version() produces for the explicit --target-version path (see
test_undo_command_missing_undo_script.py, which covers that path).
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.migration.commands.undo_command import UndoCommand
from core.migration.migration import MigrationType
from core.migration.rules.migration_rules import MigrationRules


def _make_migration(version, mtype=MigrationType.SQL, success=True, installed_rank=1):
    m = MagicMock()
    # A real MigrationRules instance compares versions by equality (not via
    # str()), so keep this consistent with how compare_versions() below
    # receives it: as a string.
    m.version = str(version)
    m.type = mtype
    m.success = success
    m.installed_rank = installed_rank
    m.script_name = f"V{version}__test.sql"
    m.description = "test"
    m.checksum = "abc"
    m.content = None
    return m


def _make_undo_script(version):
    s = MagicMock()
    s.version = str(version)
    s.type = MigrationType.UNDO_SQL
    s.script_name = f"U{version}__test.sql"
    s.description = "undo test"
    s.tags = []
    return s


def _make_command(applied_migrations, *, migration_rules, undo_scripts=None):
    state_manager = MagicMock()
    migration_state = MagicMock()
    migration_state.applied_objects = applied_migrations
    state_manager.build_state.return_value = migration_state
    state_manager.get_current_version.return_value = None

    executor_factory = MagicMock()
    executor_factory.get_executor.return_value = None

    execution_engine = MagicMock()
    execution_engine.executor_factory = executor_factory

    history_manager = MagicMock()
    history_manager.record_undo.return_value = True

    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = undo_scripts or []

    config = MagicMock()
    config.database.schema = "test"

    cmd = UndoCommand(
        config=config,
        log=MagicMock(),
        provider=MagicMock(),
        script_manager=script_manager,
        history_manager=history_manager,
        validator=MagicMock(),
        execution_engine=execution_engine,
        migration_helpers=MagicMock(),
        state_manager=state_manager,
        migration_ui=MagicMock(),
        migration_rules=migration_rules,
    )
    cmd.journal = None
    cmd.placeholder_service = MagicMock()
    cmd.migration_helpers.setup_migration_parameters.return_value = (True, None)

    return cmd


@pytest.mark.unit
def test_no_target_version_skips_past_undone_version_without_message():
    """V2 was already undone; the scan must fall through to V1 silently --
    no "already been undone" message, since that message is only meaningful
    when the user explicitly asked to undo the version that turned out to
    already be undone."""
    v2 = _make_migration(2, installed_rank=1)
    u2 = _make_migration(2, mtype=MigrationType.UNDO_SQL, installed_rank=2)
    v1 = _make_migration(1, installed_rank=3)

    migration_rules = MigrationRules(MagicMock())
    cmd = _make_command(
        [v2, u2, v1], migration_rules=migration_rules, undo_scripts=[_make_undo_script(1)]
    )
    result = cmd.execute(scripts_dir=MagicMock())

    logged = [call.args[0] for call in cmd.log.info.call_args_list]
    assert not any("already been undone" in msg for msg in logged)
    assert not result.error_message
    assert [m.version for m in result.undone_migrations] == ["1"]


@pytest.mark.unit
def test_explicit_target_version_still_logs_message_for_already_undone():
    """Sanity check: the explicit --target-version path (which routes through
    should_undo_version) keeps producing its message -- only the no-target
    auto-scan above became silent."""
    v2 = _make_migration(2, installed_rank=1)
    u2 = _make_migration(2, mtype=MigrationType.UNDO_SQL, installed_rank=2)

    migration_rules = MigrationRules(MagicMock())
    cmd = _make_command([v2, u2], migration_rules=migration_rules)
    result = cmd.execute(scripts_dir=MagicMock(), target_version=1)

    assert result.error_message
    assert "already been undone" in result.error_message
