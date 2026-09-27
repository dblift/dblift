"""A dry run applies nothing, so the ``command.pre_migrate`` runtime checks
that gate applying a migration must not run for ``--dry-run``.

The checks registered at that point abort the operation by raising; a dry run
that never applies anything should not be gated by them. This pins that a
sentinel check registered at ``command.pre_migrate`` fires for a real migrate
but is skipped for a dry run.
"""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.seams import runtime_checks


class _CheckFired(Exception):
    pass


@pytest.fixture(autouse=True)
def _reset_registry():
    runtime_checks.clear_checks()
    yield
    runtime_checks.clear_checks()


def _cmd():
    return MigrateCommand(
        config=MagicMock(),
        log=MagicMock(),
        provider=MagicMock(),
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=None,
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )


def _register_sentinel():
    def _boom() -> None:
        raise _CheckFired()

    runtime_checks.register_check("command.pre_migrate", _boom)


def test_real_migrate_runs_the_pre_migrate_checks(tmp_path):
    _register_sentinel()
    cmd = _cmd()
    with pytest.raises(_CheckFired):
        cmd.execute(tmp_path, dry_run=False)


def test_dry_run_skips_the_pre_migrate_checks(tmp_path):
    _register_sentinel()
    cmd = _cmd()
    # The dry-run body may raise for its own reasons against these mocks; the
    # only thing under test is that the pre-migrate check did NOT fire.
    try:
        cmd.execute(tmp_path, dry_run=True)
    except _CheckFired:
        pytest.fail("command.pre_migrate checks ran during a dry run")
    except Exception:
        pass
