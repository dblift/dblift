"""Issue #821: ``baseline()`` as the *first* operation on a fresh client must
establish the provider connection itself, the same way ``info()`` /
``migrate()`` / ``undo()`` do via ``_ensure_connected()``.

Reproduces a provider shape like CosmosDB's: no ``_ensure_connection`` hook
(unlike the SQLAlchemy/SQLite providers, which lazily reconnect on demand),
so any provider call attempted before ``connect()``/``create_connection()``
raises. ``BaselineCommand.execute()`` never called ``_ensure_connected()``
and instead relied on ``create_schema_and_history_table()`` to establish the
connection as a side effect -- a comment that happened to be true for
providers whose history-table creation lazily reconnects, but false for
CosmosDB, whose ``create_schema_if_not_exists()`` requires a connection to
already exist and raises immediately instead of creating one.

This mirrors the fix already applied to ``undo_command.py`` for the same
class of bug (see ``test_undo_command_cold_start_connection.py``).
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.migration.commands.baseline_command import BaselineCommand
from dblift.core.migration.commands.info_command import InfoCommand
from dblift.core.migration.commands.repair_command import RepairCommand
from dblift.core.migration.commands.validate_command import ValidateCommand


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

    def begin_transaction(self) -> None:
        pass

    def commit_transaction(self) -> None:
        pass

    def rollback_transaction(self) -> None:
        pass


_NO_CONNECTION_ERROR = (
    "CosmosDB provider has no active connection. "
    "Ensure create_connection() was called before executing queries."
)


def _make_history_manager(provider: _ColdStartProvider, has_history_table: bool = False):
    """A history_manager whose schema-creation call fails until the provider
    connects -- but only when it is asked to create the schema too.

    Mirrors real CosmosDB behaviour: ``create_schema_and_history_table(...)``
    calls ``provider.create_schema_if_not_exists()`` only when
    ``create_schema=True`` (baseline). That call hard-requires a connection
    and raises immediately if there isn't one. The history-*table* creation
    that runs either way (``create_schema=False``, used by validate/repair)
    goes through a lower-level component that lazily reconnects on its own,
    which is why validate()/repair() have historically "recovered" as a
    first call even without the fix this test suite covers.
    """
    hm = MagicMock()
    hm.has_history_table = has_history_table
    hm.get_applied_migration_records.return_value = []

    def _create_schema_and_history_table(create_schema: bool = False) -> None:
        if create_schema and not provider.is_connected():
            raise RuntimeError(_NO_CONNECTION_ERROR)

    hm.create_schema_and_history_table.side_effect = _create_schema_and_history_table
    hm.get_applied_migrations.return_value = []
    return hm


def _make_config():
    return SimpleNamespace(database=SimpleNamespace(schema="test", type="cosmosdb"))


def _make_command(command_cls, provider, history_manager, **extra_ctx):
    ctx_kwargs = dict(
        config=_make_config(),
        log=MagicMock(),
        provider=provider,
        script_manager=MagicMock(),
        history_manager=history_manager,
        validator=MagicMock(),
        execution_engine=MagicMock(),
        migration_helpers=MagicMock(),
        state_manager=MagicMock(),
        migration_ui=MagicMock(),
        migration_rules=MagicMock(),
    )
    ctx_kwargs.update(extra_ctx)
    return command_cls(**ctx_kwargs)


@pytest.mark.unit
class TestBaselineColdStartConnection:
    """baseline() must connect before touching the provider, not just rely
    on create_schema_and_history_table() to do it as a side effect."""

    def test_baseline_as_first_call_succeeds(self):
        provider = _ColdStartProvider()
        history_manager = _make_history_manager(provider)
        cmd = _make_command(BaselineCommand, provider, history_manager)

        result = cmd.execute("1.0", "initial baseline")

        assert result.success, f"baseline() failed: {result.error_message}"
        assert result.baseline_version == "1.0"

    def test_baseline_as_first_call_connects_the_provider(self):
        provider = _ColdStartProvider()
        history_manager = _make_history_manager(provider)
        cmd = _make_command(BaselineCommand, provider, history_manager)

        cmd.execute("1.0", "initial baseline")

        assert provider.connect_calls >= 1, (
            "baseline() must establish the provider connection itself (like "
            "migrate()/info()/undo() do) instead of assuming "
            "create_schema_and_history_table() will do it as a side effect"
        )

    def test_baseline_as_first_call_does_not_surface_no_connection_error(self):
        provider = _ColdStartProvider()
        history_manager = _make_history_manager(provider)
        cmd = _make_command(BaselineCommand, provider, history_manager)

        result = cmd.execute("2.0")

        assert "no active connection" not in (result.error_message or "").lower()

    def test_dry_run_as_first_call_still_connects_and_succeeds(self):
        """dry-run already called _ensure_connected() directly before this fix;
        confirm the reordering didn't break it."""
        provider = _ColdStartProvider()
        history_manager = _make_history_manager(provider, has_history_table=False)
        cmd = _make_command(BaselineCommand, provider, history_manager)

        result = cmd.execute("1.0", "initial baseline", dry_run=True)

        assert result.success, f"dry-run baseline() failed: {result.error_message}"
        assert provider.connect_calls >= 1
        history_manager.create_schema_and_history_table.assert_not_called()


@pytest.mark.unit
class TestOtherCommandsColdStartRegression:
    """Regression guard: info()/validate()/repair() must keep working as a
    cold-start first call the way they did before the baseline() fix."""

    def test_info_as_first_call_connects_and_succeeds(self):
        provider = _ColdStartProvider()
        history_manager = _make_history_manager(provider)
        cmd = _make_command(InfoCommand, provider, history_manager)
        cmd.state_manager.build_state.return_value = SimpleNamespace(
            applied_objects=[], all_applied_objects=[]
        )
        cmd.migration_ui.get_migration_data.return_value = []

        result = cmd.execute(scripts_dir=MagicMock(), display_human=False)

        assert result.success, f"info() failed: {result.error_message}"
        assert provider.connect_calls >= 1

    def test_validate_as_first_call_succeeds(self):
        provider = _ColdStartProvider()
        history_manager = _make_history_manager(provider)
        validator = MagicMock()
        validation_result = MagicMock()
        validation_result.success = True
        validation_result.error_message = ""
        validation_result.issues = []
        validator.validate_migrations.return_value = validation_result

        cmd = _make_command(ValidateCommand, provider, history_manager, validator=validator)

        result = cmd.execute(scripts_dir=MagicMock())

        assert result.success, f"validate() failed: {result.error_message}"

    def test_repair_as_first_call_with_nothing_to_repair_succeeds(self):
        provider = _ColdStartProvider()
        history_manager = _make_history_manager(provider)
        cmd = _make_command(RepairCommand, provider, history_manager)
        cmd.state_manager.build_state.return_value = SimpleNamespace(
            checksum_changes=[],
            applied_objects=[],
            deleted_scripts=set(),
            failed_objects=[],
            all_applied_objects=[],
        )
        cmd.script_manager.load_migration_scripts.return_value = {}

        result = cmd.execute(scripts_dir=MagicMock())

        assert result.success, f"repair() failed: {result.error_message}"
