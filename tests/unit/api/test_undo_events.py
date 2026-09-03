"""BUG-09 regression: undo() emits UNDO_FAILED when result.success=False.

Before this fix, api.Client.undo() only emitted a failure event on Python
exceptions; a soft failure (executor returns result.success=False) silently
emitted only the completed event, leaving listeners unable to distinguish
success from failure.

Cursor-bot follow-up: the completed event must NOT be emitted on failure
(success=False), consistent with the exception path which also omits it.
Emitting both events on soft failure would trigger post-success workflows.

Issue #823: undo() used to emit the generic ``MIGRATION_STARTED`` /
``MIGRATION_COMPLETED`` / ``MIGRATION_FAILED`` events (with
``operation="undo"``) instead of the dedicated ``UNDO_STARTED`` /
``UNDO_COMPLETED`` / ``UNDO_FAILED`` members that ``EventType`` already
declares. Updated here to assert the dedicated events fire.
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from dblift.api.events import EventType


def _make_client(undo_result):
    """Build a minimal Client stub for event-emission tests."""
    from dblift.api.client import DBLiftClient

    provider = MagicMock()
    provider.supports_transactions.return_value = False

    executor = MagicMock()
    executor.undo.return_value = undo_result

    client = DBLiftClient.__new__(DBLiftClient)
    client.provider = provider
    client.executor = executor
    client.events = MagicMock()
    client._scripts_dir = None

    def _get_scripts_dir():
        return "migrations"

    client._get_scripts_dir = _get_scripts_dir
    return client


@pytest.mark.unit
class TestUndoEvents:
    def test_undo_success_emits_completed_only(self):
        result = MagicMock()
        result.success = True
        result.error_message = None

        client = _make_client(result)
        client.undo(target_version="1")

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.UNDO_COMPLETED in emitted
        assert EventType.UNDO_FAILED not in emitted

    def test_undo_failure_emits_failed_not_completed(self):
        result = MagicMock()
        result.success = False
        result.error_message = "No undo script for V2"

        client = _make_client(result)
        client.undo(target_version="1")

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.UNDO_FAILED in emitted
        assert EventType.UNDO_COMPLETED not in emitted

    def test_undo_failure_event_carries_error_message(self):
        result = MagicMock()
        result.success = False
        result.error_message = "No undo script for V2"

        client = _make_client(result)
        client.undo(target_version="1")

        failed_calls = [
            call
            for call in client.events.emit.call_args_list
            if call.args[0] == EventType.UNDO_FAILED
        ]
        assert len(failed_calls) == 1
        assert failed_calls[0].args[1]["error"] == "No undo script for V2"

    def test_undo_exception_still_emits_failed(self):
        from dblift.api.client import DBLiftClient

        provider = MagicMock()
        provider.supports_transactions.return_value = False

        executor = MagicMock()
        executor.undo.side_effect = RuntimeError("DB gone")

        client = DBLiftClient.__new__(DBLiftClient)
        client.provider = provider
        client.executor = executor
        client.events = MagicMock()
        client._get_scripts_dir = lambda: "migrations"

        with pytest.raises(RuntimeError):
            client.undo(target_version="1")

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.UNDO_FAILED in emitted
        assert EventType.UNDO_COMPLETED not in emitted
