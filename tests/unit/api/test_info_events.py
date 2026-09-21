from unittest.mock import MagicMock

import pytest

from dblift.api.client import DBLiftClient
from dblift.api.events import EventType
from dblift.config import DbliftConfig


def _make_client(info_result):
    client = DBLiftClient.__new__(DBLiftClient)
    client.config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    client.provider = MagicMock()
    client.executor = MagicMock()
    client.executor.info.return_value = info_result
    client.events = MagicMock()
    client._scripts_dir = None
    client._get_scripts_dir = lambda: "migrations"
    return client


@pytest.mark.unit
class TestInfoEvents:
    def test_info_success_emits_completed_only(self):
        result = MagicMock(success=True)
        client = _make_client(result)

        client.info()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.INFO_COMPLETED in emitted
        assert EventType.INFO_FAILED not in emitted

    def test_info_failure_emits_failed_not_completed(self):
        result = MagicMock(success=False, error_message="state unavailable")
        client = _make_client(result)

        client.info()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.INFO_FAILED in emitted
        assert EventType.INFO_COMPLETED not in emitted
        client.events.emit.assert_any_call(EventType.INFO_FAILED, {"error": "state unavailable"})
