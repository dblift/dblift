"""A brand-new command whose *first* provider interaction is ``undo()`` must
establish the provider connection itself, the same way ``migrate``/``info``
do via ``_ensure_connected()`` / ``_run_preflight()``.

Reproduces a provider shape like CosmosDB's: no ``_ensure_connection`` hook
(unlike the SQLAlchemy/SQLite providers, which lazily reconnect on demand),
so any read attempted before ``connect()``/``create_connection()`` raises.
``UndoCommand.execute()`` never called ``_ensure_connected()`` and instead
relied on ``create_schema_and_history_table()`` to establish the connection
as a side effect -- which does not hold for a provider whose history-table
creation talks to a lower-level connection manager without touching the
provider's own connection state.

The broad ``except Exception`` around ``state_manager.build_state()``
(added to tolerate mocked dependencies in tests) then swallowed that
connection failure into an empty applied-migrations list, so the command
reported "No migrations to undo" / ``success=True`` even though a real
migration was applied and undoable.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from core.migration.commands.undo_command import UndoCommand
from core.migration.migration import MigrationType


class _ColdStartProvider:
    """Stand-in for a provider with no ``_ensure_connection`` hook.

    Mirrors ``CosmosDbProvider``: reads before ``connect()`` fail, and
    ``connect()`` is the only thing that flips the connected state.
    """

    def __init__(self) -> None:
        self.connected = False
        self.connect_calls = 0

    def is_connected(self) -> bool:
        return self.connected

    def connect(self) -> None:
        self.connect_calls += 1
        self.connected = True


def _make_migration(version: str, mtype=MigrationType.SQL, success: bool = True):
    m = MagicMock()
    m.version = version
    m.type = mtype
    m.success = success
    m.script_name = f"V{version}__test.sql"
    m.description = "test"
    m.checksum = "abc"
    m.content = None
    return m


def _make_command(applied_migrations):
    provider = _ColdStartProvider()

    state_manager = MagicMock()

    def _build_state(*args, **kwargs):
        if not provider.connected:
            # Exactly the error CosmosDbProvider._get_connection_or_raise()
            # raises when a query runs before create_connection().
            raise RuntimeError(
                "CosmosDB provider has no active connection. "
                "Ensure create_connection() was called before executing queries."
            )
        migration_state = MagicMock()
        migration_state.applied_objects = applied_migrations
        return migration_state

    state_manager.build_state.side_effect = _build_state
    state_manager.get_current_version.return_value = None

    migration_rules = MagicMock()
    migration_rules.should_undo_version.return_value = (True, None)

    executor_factory = MagicMock()
    executor_factory.get_executor.return_value = None

    execution_engine = MagicMock()
    execution_engine.executor_factory = executor_factory

    history_manager = MagicMock()
    script_manager = MagicMock()
    script_manager.get_migration_scripts.return_value = []

    config = MagicMock()
    config.database.schema = "test"

    cmd = UndoCommand(
        config=config,
        log=MagicMock(),
        provider=provider,
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

    return cmd, provider


@pytest.mark.unit
def test_cold_start_undo_connects_before_deciding_nothing_to_undo():
    """First-ever call is undo() -- a real migration is applied and undoable.

    The command must connect the provider before it can know whether there
    is anything to undo. It must not silently report "no migrations to
    undo" just because it never tried to connect.
    """
    v1 = _make_migration("1")
    cmd, provider = _make_command([v1])

    result = cmd.execute(scripts_dir=MagicMock())

    assert provider.connect_calls >= 1, (
        "undo() must establish the provider connection itself (like "
        "migrate()/info() do) instead of assuming one already exists"
    )

    checked_versions = [
        call.args[0] for call in cmd.migration_rules.should_undo_version.call_args_list
    ]
    assert checked_versions == ["1"], (
        "the applied migration must be found once connected, not silently "
        "dropped because the state build failed before any connection was made"
    )

    logged_info = [call.args[0] for call in cmd.log.info.call_args_list]
    assert not any("No migrations to undo" in msg for msg in logged_info), (
        f"got a false 'nothing to undo' result even though V1 was applied "
        f"and undoable: {result.__dict__}"
    )
