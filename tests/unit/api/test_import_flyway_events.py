"""Regression: ``import_flyway()`` must emit ``MIGRATION_FAILED`` (not
``MIGRATION_COMPLETED``) when the executor returns a soft failure
(``result.success is False``) without raising.

Before this fix ``DBLiftClient.import_flyway()`` unconditionally emitted
``MIGRATION_COMPLETED`` after a successful call to
``self.executor.import_flyway`` regardless of the returned result's
``success`` flag, unlike ``migrate()`` and ``undo()``, which both check
``result.success`` and emit the matching completed/failed event.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from dblift.api.events import EventType
from dblift.config import DbliftConfig


def _make_client(import_flyway_result):
    """Build a minimal Client stub for event-emission tests."""
    from dblift.api.client import DBLiftClient

    provider = MagicMock()
    provider.supports_transactions.return_value = False

    executor = MagicMock()
    executor.import_flyway.return_value = import_flyway_result

    client = DBLiftClient.__new__(DBLiftClient)
    client.config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    client.provider = provider
    client.executor = executor
    client.events = MagicMock()
    client._scripts_dir = None

    def _get_scripts_dir():
        return "migrations"

    client._get_scripts_dir = _get_scripts_dir
    return client


@pytest.mark.unit
class TestImportFlywayEvents:
    def test_import_flyway_success_emits_completed_only(self):
        result = MagicMock()
        result.success = True
        result.error_message = None

        client = _make_client(result)
        client.import_flyway()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.MIGRATION_COMPLETED in emitted
        assert EventType.MIGRATION_FAILED not in emitted

    def test_import_flyway_failure_emits_failed_not_completed(self):
        result = MagicMock()
        result.success = False
        result.error_message = "flyway_schema_history table not found"

        client = _make_client(result)
        client.import_flyway()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.MIGRATION_FAILED in emitted
        assert EventType.MIGRATION_COMPLETED not in emitted

    def test_import_flyway_failure_event_carries_error_message(self):
        result = MagicMock()
        result.success = False
        result.error_message = "flyway_schema_history table not found"

        client = _make_client(result)
        client.import_flyway()

        failed_calls = [
            call
            for call in client.events.emit.call_args_list
            if call.args[0] == EventType.MIGRATION_FAILED
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0].args[1]["error"] == "flyway_schema_history table not found"
