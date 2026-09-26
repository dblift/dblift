"""DBLiftClient.validate() stays compatible on preflight connection failures."""

from __future__ import annotations

import warnings
from unittest.mock import MagicMock

import pytest

from dblift.api.client import DBLiftClient
from dblift.api.events import EventType
from dblift.config import DbliftConfig
from dblift.core.logger.results import ValidateResult
from dblift.core.migration.commands.base_command import PreflightConnectionError

_HISTORY = "Could not create the schema-history table: permission denied"
_CONNECTION = "Connection failed: refused"


def _make_client(outcome):
    client = DBLiftClient.__new__(DBLiftClient)
    client.config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    client.config.database.schema = "app"
    client.provider = MagicMock()
    client.executor = MagicMock()
    client.executor.validate.side_effect = outcome
    client.events = MagicMock()
    client.dialect = "postgresql"
    client._get_scripts_dir = lambda: "migrations"
    return client


def _emitted(client):
    return [call.args[0] for call in client.events.emit.call_args_list]


def _deprecations(caught):
    return [item for item in caught if issubclass(item.category, DeprecationWarning)]


@pytest.mark.unit
class TestValidateHistoryTableClient:
    def test_history_table_failure_returns_result_and_emits_failed(self):
        client = _make_client(PreflightConnectionError(_HISTORY))

        result = client.validate()

        assert isinstance(result, ValidateResult)
        assert result.success is False
        assert result.error_message == _HISTORY
        assert result.error_count == 1
        assert result.target_schema == "app"
        assert isinstance(result.preflight_error, PreflightConnectionError)
        assert EventType.VALIDATION_FAILED in _emitted(client)
        assert EventType.VALIDATION_COMPLETED not in _emitted(client)
        client.events.emit.assert_any_call(
            EventType.VALIDATION_FAILED,
            {"error": _HISTORY, "dialect": "postgresql"},
        )

    def test_preflight_connection_failure_returns_failed_result(self):
        """An unreachable database is a preflight failure, same as history DDL."""
        client = _make_client(PreflightConnectionError(_CONNECTION))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            result = client.validate()

        assert isinstance(result, ValidateResult)
        assert result.success is False
        assert result.error_message == _CONNECTION
        assert result.error_count == 1
        assert result.target_schema == "app"
        assert isinstance(result.preflight_error, PreflightConnectionError)
        assert EventType.VALIDATION_FAILED in _emitted(client)
        assert EventType.VALIDATION_COMPLETED not in _emitted(client)
        assert len(_deprecations(caught)) == 1

    def test_preflight_failure_keeps_target_schema_from_the_command_result(self):
        attached = ValidateResult()
        attached.target_schema = "kept"
        client = _make_client(PreflightConnectionError(_CONNECTION, attached))
        client.config.database.schema = "other"

        result = client.validate()

        assert result is attached
        assert result.target_schema == "kept"
        assert result.error_message == _CONNECTION
        assert result.preflight_error is not None

    def test_non_preflight_connection_error_still_raises(self):
        """A ConnectionError that is not a preflight failure still propagates.

        Matching is on the type. The history-table wording on a plain
        ConnectionError is not enough to turn it into a result.
        """
        client = _make_client(ConnectionError(_HISTORY))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(ConnectionError, match="Could not create the schema-history table"):
                client.validate()

        assert EventType.VALIDATION_FAILED in _emitted(client)
        assert EventType.VALIDATION_COMPLETED not in _emitted(client)
        assert _deprecations(caught) == []

    def test_other_exceptions_still_raise(self):
        client = _make_client(RuntimeError("bad sql"))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            with pytest.raises(RuntimeError, match="bad sql"):
                client.validate()

        assert EventType.VALIDATION_FAILED in _emitted(client)
        assert _deprecations(caught) == []

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

    @pytest.mark.parametrize("message", [_HISTORY, _CONNECTION])
    def test_preflight_failure_warns_once_about_the_future_raise(self, message):
        """The deprecation warning is for these two failures, not every validate()."""
        client = _make_client(PreflightConnectionError(message))

        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            client.validate()

        deprecations = _deprecations(caught)
        assert len(deprecations) == 1
        text = str(deprecations[0].message)
        assert "ConnectionError" in text
        assert "next major" in text
        assert "Deprecated since 4.9.0" in text

    def test_docstring_marks_the_future_connection_error(self):
        doc = DBLiftClient.validate.__doc__ or ""
        assert "Raises:" in doc
        assert "ConnectionError" in doc
        assert "Future behavior" in doc
        assert "next major" in doc
        assert "Deprecated since 4.9.0" in doc
