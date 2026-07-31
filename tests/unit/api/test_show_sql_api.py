"""Show-SQL API propagation tests."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from api.events import EventType


def _make_client(result: MagicMock):
    from api.client import DBLiftClient

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
        assert started_call.args[0] is EventType.MIGRATION_STARTED
        assert started_call.args[1]["operation"] == "undo"
        assert started_call.args[1]["show_sql"] is True
        assert client.executor.undo.call_args.kwargs["show_sql"] is True
