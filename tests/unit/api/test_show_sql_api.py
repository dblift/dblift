"""Show-SQL API propagation tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from dblift.api.events import EventType


def _make_client(result: MagicMock):
    from dblift.api.client import DBLiftClient

    client = DBLiftClient.__new__(DBLiftClient)
    client.config = MagicMock()
    client.provider = MagicMock()
    client.executor = MagicMock()
    client.executor.history_manager = MagicMock()
    client.executor.migrate.return_value = result
    client.executor.undo.return_value = result
    client.events = MagicMock()
    client.logger = MagicMock()
    client.dialect = "postgresql"
    client._get_scripts_dir = lambda: Path("migrations")
    return client


@pytest.mark.unit
class TestShowSqlApi:
    def test_migrate_started_event_and_executor_receive_show_sql(self):
        result = MagicMock()
        result.success = True
        client = _make_client(result)

        client.migrate(show_sql=True)

        started_call = client.events.emit.call_args_list[0]
        assert started_call.args[0] is EventType.MIGRATION_STARTED
        assert started_call.args[1]["show_sql"] is True
        assert client.executor.migrate.call_args.kwargs["show_sql"] is True

    def test_migrate_completed_event_carries_snapshot_context(self):
        result = MagicMock()
        result.success = True
        result.migrations_applied = ["1"]
        client = _make_client(result)

        client.migrate()

        completed_call = next(
            call
            for call in client.events.emit.call_args_list
            if call.args[0] is EventType.MIGRATION_COMPLETED
        )
        payload = completed_call.args[1]
        assert payload["operation"] == "migrate"
        assert payload["result"] is result
        assert payload["migrations_applied"] == ["1"]
        assert payload["config"] is client.config
        assert payload["provider"] is client.provider
        assert payload["history_manager"] is client.executor.history_manager
        assert payload["log"] is client.logger

    def test_undo_started_event_and_executor_receive_show_sql(self):
        result = MagicMock()
        result.success = True
        client = _make_client(result)

        client.undo(show_sql=True)

        started_call = client.events.emit.call_args_list[0]
        # Issue #823: undo() emits the dedicated UNDO_STARTED event instead
        # of the generic MIGRATION_STARTED with operation="undo".
        assert started_call.args[0] is EventType.UNDO_STARTED
        assert started_call.args[1]["operation"] == "undo"
        assert started_call.args[1]["show_sql"] is True
        assert client.executor.undo.call_args.kwargs["show_sql"] is True

    def test_migrate_events_include_dialect(self):
        result = MagicMock()
        result.success = True
        result.migrations_applied = []
        client = _make_client(result)

        client.migrate()

        started = client.events.emit.call_args_list[0]
        assert started.args[1]["dialect"] == "postgresql"
        completed = next(
            c
            for c in client.events.emit.call_args_list
            if c.args[0] is EventType.MIGRATION_COMPLETED
        )
        assert completed.args[1]["dialect"] == "postgresql"

    def test_migrate_failed_result_event_includes_dialect(self):
        result = MagicMock()
        result.success = False
        result.error_message = "boom"
        client = _make_client(result)

        client.migrate()

        failed = next(
            c for c in client.events.emit.call_args_list if c.args[0] is EventType.MIGRATION_FAILED
        )
        assert failed.args[1]["dialect"] == "postgresql"
        assert failed.args[1]["error"] == "boom"

    def test_validate_failed_event_includes_dialect(self):
        client = _make_client(MagicMock())
        client.executor.validate.side_effect = RuntimeError("bad sql")

        with pytest.raises(RuntimeError, match="bad sql"):
            client.validate()

        failed = next(
            c for c in client.events.emit.call_args_list if c.args[0] is EventType.VALIDATION_FAILED
        )
        assert failed.args[1]["dialect"] == "postgresql"
        assert "bad sql" in failed.args[1]["error"]
