"""DBLiftClient.validate() stays compatible when history-table DDL fails."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from dblift.api.client import DBLiftClient
from dblift.api.events import EventType
from dblift.config import DbliftConfig
from dblift.core.logger.results import ValidateResult

_HISTORY = "Could not create the schema-history table: permission denied"


def _make_client(outcome):
    client = DBLiftClient.__new__(DBLiftClient)
    client.config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    client.provider = MagicMock()
    client.executor = MagicMock()
    client.executor.validate.side_effect = outcome
    client.events = MagicMock()
    client.dialect = "postgresql"
    client._get_scripts_dir = lambda: "migrations"
    return client


def _emitted(client):
    return [call.args[0] for call in client.events.emit.call_args_list]


@pytest.mark.unit
class TestValidateHistoryTableClient:
    def test_history_table_failure_returns_result_and_emits_failed(self):
        client = _make_client(ConnectionError(_HISTORY))

        result = client.validate()

        assert isinstance(result, ValidateResult)
        assert result.success is False
        assert result.error_message == _HISTORY
        assert result.error_count == 1
        assert EventType.VALIDATION_FAILED in _emitted(client)
        assert EventType.VALIDATION_COMPLETED not in _emitted(client)
        client.events.emit.assert_any_call(
            EventType.VALIDATION_FAILED,
            {"error": _HISTORY, "dialect": "postgresql"},
        )

    def test_other_connection_error_still_raises(self):
        client = _make_client(ConnectionError("Connection failed: refused"))

        with pytest.raises(ConnectionError, match="Connection failed: refused"):
            client.validate()

        assert EventType.VALIDATION_FAILED in _emitted(client)
        assert EventType.VALIDATION_COMPLETED not in _emitted(client)

    def test_other_exceptions_still_raise(self):
        client = _make_client(RuntimeError("bad sql"))

        with pytest.raises(RuntimeError, match="bad sql"):
            client.validate()

        assert EventType.VALIDATION_FAILED in _emitted(client)

    def test_success_emits_completed_and_does_not_warn(self):
        ok = ValidateResult()
        client = _make_client(None)
        client.executor.validate.side_effect = None
        client.executor.validate.return_value = ok

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = client.validate()

        assert result is ok
        assert EventType.VALIDATION_COMPLETED in _emitted(client)
        assert EventType.VALIDATION_FAILED not in _emitted(client)
        assert not any(issubclass(item.category, DeprecationWarning) for item in caught)

    def test_history_table_failure_warns_once_about_the_future_raise(self):
        """The deprecation warning is for this failure, not every validate()."""
        client = _make_client(ConnectionError(_HISTORY))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client.validate()

        deprecations = [item for item in caught if issubclass(item.category, DeprecationWarning)]
        assert len(deprecations) == 1
        text = str(deprecations[0].message)
        assert "ConnectionError" in text
        assert "next major" in text

    def test_docstring_marks_the_future_connection_error(self):
        doc = DBLiftClient.validate.__doc__ or ""
        assert "Raises:" in doc
        assert "ConnectionError" in doc
        assert "Future behavior" in doc
        assert "next major" in doc
