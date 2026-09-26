"""``command.pre_migrate_dry_run`` runs before a dry-run migrate.

With nothing registered the point is a no-op, so a dry run is unchanged.
A check registered there runs only for a dry run and raises to abort, the
same way ``command.pre_migrate`` aborts a real migrate. A real migrate does
not run the dry-run point, and a dry run does not run ``command.pre_migrate``.

``DBLiftClient.migrate``, ``client.executor.migrate`` and
``MigrationExecutor.migrate`` all construct ``MigrateCommand`` and call
``execute``, so a dry run on any of them hits this point.
"""

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.api.client import DBLiftClient
from dblift.core.migration.commands.base_command import BaseCommandContext
from dblift.core.migration.commands.migrate_command import MigrateCommand
from dblift.core.migration.executor.migration_executor import MigrationExecutor
from dblift.core.seams import runtime_checks


class _CheckFired(Exception):
    pass


class _PastCheck(Exception):
    """Raised from the first statement after the check point."""


@pytest.fixture(autouse=True)
def _reset_registry():
    runtime_checks.clear_checks()
    yield
    runtime_checks.clear_checks()


def _context() -> BaseCommandContext:
    return BaseCommandContext(
        config=MagicMock(),
        log=MagicMock(),
        provider=MagicMock(),
        script_manager=MagicMock(),
        history_manager=MagicMock(),
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )


def _executor() -> MigrationExecutor:
    executor = MigrationExecutor.__new__(MigrationExecutor)
    executor._make_command_context = _context
    return executor


def _client(executor: MigrationExecutor, scripts_dir: Path) -> DBLiftClient:
    client = DBLiftClient.__new__(DBLiftClient)
    client.executor = executor
    client.events = MagicMock()
    client.dialect = "sqlite"
    client._guard_scripts_dir_kwarg = lambda kwargs: None
    client._get_scripts_dir = lambda: scripts_dir
    client._resolve_script_options = lambda recursive, additional_dirs, dir_recursive_map: (
        False,
        [],
        None,
    )
    return client


def _stop_after_check(monkeypatch: pytest.MonkeyPatch) -> None:
    def _stop(self: MigrateCommand) -> None:
        raise _PastCheck()

    monkeypatch.setattr(MigrateCommand, "_reset_callback_catalog", _stop)


def _register_recorder(point: str, calls: list[str]) -> None:
    def _check() -> None:
        calls.append(point)

    runtime_checks.register_check(point, _check)


def test_no_registered_check_leaves_dry_run_unchanged(tmp_path, monkeypatch, capsys):
    _stop_after_check(monkeypatch)
    assert runtime_checks.registered_checks("command.pre_migrate_dry_run") == ()

    with pytest.raises(_PastCheck):
        MigrateCommand(_context()).execute(tmp_path, dry_run=True)

    executor = _executor()
    with pytest.raises(_PastCheck):
        executor.migrate(tmp_path, dry_run=True)

    client = _client(executor, tmp_path)
    with pytest.raises(_PastCheck):
        client.migrate(dry_run=True)
    with pytest.raises(_PastCheck):
        client.executor.migrate(tmp_path, dry_run=True)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_dry_run_check_runs_and_exception_propagates(tmp_path):
    def _boom() -> None:
        raise _CheckFired()

    runtime_checks.register_check("command.pre_migrate_dry_run", _boom)

    with pytest.raises(_CheckFired):
        MigrateCommand(_context()).execute(tmp_path, dry_run=True)

    executor = _executor()
    with pytest.raises(_CheckFired):
        executor.migrate(tmp_path, dry_run=True)

    client = _client(executor, tmp_path)
    with pytest.raises(_CheckFired):
        client.migrate(dry_run=True)
    with pytest.raises(_CheckFired):
        client.executor.migrate(tmp_path, dry_run=True)


def test_dry_run_and_real_migrate_run_different_points(tmp_path, monkeypatch):
    _stop_after_check(monkeypatch)
    calls: list[str] = []
    _register_recorder("command.pre_migrate", calls)
    _register_recorder("command.pre_migrate_dry_run", calls)

    command_cases = (
        lambda: MigrateCommand(_context()).execute(tmp_path, dry_run=True),
        lambda: MigrateCommand(_context()).execute(tmp_path, dry_run=False),
    )
    executor = _executor()
    client = _client(executor, tmp_path)
    cases = (
        *command_cases,
        lambda: executor.migrate(tmp_path, dry_run=True),
        lambda: executor.migrate(tmp_path, dry_run=False),
        lambda: client.migrate(dry_run=True),
        lambda: client.migrate(dry_run=False),
        lambda: client.executor.migrate(tmp_path, dry_run=True),
        lambda: client.executor.migrate(tmp_path, dry_run=False),
    )
    expected = (
        ["command.pre_migrate_dry_run"],
        ["command.pre_migrate"],
    ) * 4

    for call, want in zip(cases, expected, strict=True):
        calls.clear()
        with pytest.raises(_PastCheck):
            call()
        assert calls == want
