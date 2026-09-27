"""Every DBLiftClient command returns a failed result on a preflight failure.

A preflight failure is a connection that cannot be opened or a
schema-history table that cannot be created (``PreflightConnectionError``).
Each command method returns a failed result of its own type for it, emits
its ``*_FAILED`` event and neither warns nor raises. Any other exception
still propagates.
"""

from __future__ import annotations

import socket
import warnings
from unittest.mock import MagicMock, patch

import pytest

from dblift.api.client import DBLiftClient
from dblift.api.events import EventType
from dblift.config import DbliftConfig
from dblift.core.logger.results import (
    BaselineResult,
    CleanResult,
    InfoResult,
    MigrateResult,
    OperationResult,
    RepairResult,
    UndoResult,
    ValidateResult,
)
from dblift.core.migration.commands.base_command import PreflightConnectionError

_HISTORY = "Could not create the schema-history table: permission denied"
_CONNECTION = "Connection failed: refused"

# (client method, executor method, call kwargs, result type, failed event)
_COMMANDS = [
    ("migrate", "migrate", {}, MigrateResult, EventType.MIGRATION_FAILED),
    ("info", "info", {}, InfoResult, EventType.INFO_FAILED),
    ("validate", "validate", {}, ValidateResult, EventType.VALIDATION_FAILED),
    ("undo", "undo", {}, UndoResult, EventType.UNDO_FAILED),
    ("clean", "clean", {"clean_enabled": True}, CleanResult, EventType.CLEAN_FAILED),
    ("baseline", "baseline", {"version": "1"}, BaselineResult, EventType.BASELINE_FAILED),
    ("repair", "repair", {}, RepairResult, EventType.REPAIR_FAILED),
    ("import_flyway", "import_flyway", {}, OperationResult, EventType.MIGRATION_FAILED),
]
_IDS = [command[0] for command in _COMMANDS]


def _make_client(executor_method, outcome):
    client = DBLiftClient.__new__(DBLiftClient)
    client.config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    client.config.database.schema = "app"
    client.provider = MagicMock()
    client.executor = MagicMock()
    getattr(client.executor, executor_method).side_effect = outcome
    client.events = MagicMock()
    client.dialect = "postgresql"
    client._get_scripts_dir = lambda: "migrations"
    return client


def _emitted(client):
    return [call.args[0] for call in client.events.emit.call_args_list]


def _assert_failed_result(result, result_cls, message, schema):
    assert type(result) is result_cls
    assert result.success is False
    assert result.error_message == message
    assert result.target_schema == schema
    assert isinstance(result._preflight_error, PreflightConnectionError)
    assert result.end_time is not None


@pytest.mark.unit
class TestClientPreflightFailureMocked:
    @pytest.mark.parametrize("message", [_HISTORY, _CONNECTION])
    @pytest.mark.parametrize(
        "method,executor_method,kwargs,result_cls,failed_event", _COMMANDS, ids=_IDS
    )
    def test_returns_failed_result_and_emits_failed_event(
        self, method, executor_method, kwargs, result_cls, failed_event, message
    ):
        client = _make_client(executor_method, PreflightConnectionError(message))

        with warnings.catch_warnings():
            warnings.simplefilter("error")
            result = getattr(client, method)(**kwargs)

        _assert_failed_result(result, result_cls, message, "app")
        assert failed_event in _emitted(client)
        failed_payloads = [
            call.args[1]
            for call in client.events.emit.call_args_list
            if call.args[0] == failed_event
        ]
        assert failed_payloads[-1]["error"] == message

    @pytest.mark.parametrize(
        "method,executor_method,kwargs,result_cls,failed_event", _COMMANDS, ids=_IDS
    )
    def test_keeps_the_result_the_command_attached(
        self, method, executor_method, kwargs, result_cls, failed_event
    ):
        attached = result_cls()
        attached.target_schema = "kept"
        client = _make_client(executor_method, PreflightConnectionError(_CONNECTION, attached))

        result = getattr(client, method)(**kwargs)

        assert result is attached
        assert result.target_schema == "kept"
        assert result.error_message == _CONNECTION

    @pytest.mark.parametrize(
        "method,executor_method,kwargs,result_cls,failed_event", _COMMANDS, ids=_IDS
    )
    def test_non_preflight_connection_error_still_raises(
        self, method, executor_method, kwargs, result_cls, failed_event
    ):
        """Matching is on the type: a plain ConnectionError propagates."""
        client = _make_client(executor_method, ConnectionError(_HISTORY))

        with pytest.raises(ConnectionError, match="Could not create the schema-history table"):
            getattr(client, method)(**kwargs)

        assert failed_event in _emitted(client)

    @pytest.mark.parametrize(
        "method,executor_method,kwargs,result_cls,failed_event", _COMMANDS, ids=_IDS
    )
    def test_other_exceptions_still_raise(
        self, method, executor_method, kwargs, result_cls, failed_event
    ):
        client = _make_client(executor_method, RuntimeError("bad sql"))

        with pytest.raises(RuntimeError, match="bad sql"):
            getattr(client, method)(**kwargs)

        assert failed_event in _emitted(client)

    def test_validate_docstring_no_longer_announces_a_future_raise(self):
        doc = DBLiftClient.validate.__doc__ or ""
        assert "Deprecated" not in doc
        assert "next major release" not in doc


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


def _real_client(tmp_path, url, schema):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    config = DbliftConfig.from_dict(
        {
            "database": {"url": url, "schema": schema},
            "migrations": {"directory": str(migrations)},
        }
    )
    return DBLiftClient.from_config(config)


@pytest.mark.unit
class TestClientPreflightFailureRealCommands:
    """The real commands raise the preflight error and the client converts it."""

    @pytest.mark.parametrize(
        "method,executor_method,kwargs,result_cls,failed_event", _COMMANDS, ids=_IDS
    )
    def test_closed_localhost_port(
        self, tmp_path, monkeypatch, method, executor_method, kwargs, result_cls, failed_event
    ):
        monkeypatch.chdir(tmp_path)
        client = _real_client(
            tmp_path, f"postgresql://user:pw@127.0.0.1:{_closed_port()}/db", "app"
        )
        events = []
        client.events.on(failed_event, lambda data: events.append(data))
        try:
            with warnings.catch_warnings():
                warnings.simplefilter("error", DeprecationWarning)
                result = getattr(client, method)(**kwargs)
        finally:
            client.close()

        assert type(result) is result_cls
        assert result.success is False
        assert result.error_message.startswith("Connection failed: ")
        assert result.target_schema == "app"
        assert isinstance(result._preflight_error, PreflightConnectionError)
        assert events and events[-1].error == result.error_message

    @pytest.mark.parametrize("nested", [False, True], ids=["read-only-dir", "uncreatable-dir"])
    @pytest.mark.parametrize(
        "method,executor_method,kwargs,result_cls,failed_event",
        _COMMANDS + [("migrate", "migrate", {"dry_run": True}, MigrateResult, None)],
        ids=_IDS + ["migrate-dry-run"],
    )
    def test_unopenable_sqlite_path(
        self,
        tmp_path,
        monkeypatch,
        method,
        executor_method,
        kwargs,
        result_cls,
        failed_event,
        nested,
    ):
        """A SQLite file that cannot be opened (OperationalError) or whose
        directory cannot be created (PermissionError) is a connection failure."""
        monkeypatch.chdir(tmp_path)
        locked = tmp_path / "locked"
        locked.mkdir()
        db_path = locked / "sub" / "app.db" if nested else locked / "app.db"
        client = _real_client(tmp_path, f"sqlite:///{db_path}", "main")
        locked.chmod(0o500)
        try:
            result = getattr(client, method)(**kwargs)
        finally:
            locked.chmod(0o700)
            client.close()

        assert type(result) is result_cls
        assert result.success is False
        assert result.error_message.startswith("Connection failed: ")
        assert isinstance(result._preflight_error, PreflightConnectionError)

    # clean does not need the schema-history table, so it has no such failure.
    @pytest.mark.parametrize(
        "method,executor_method,kwargs,result_cls,failed_event",
        [command for command in _COMMANDS if command[0] != "clean"],
        ids=[name for name in _IDS if name != "clean"],
    )
    def test_history_table_creation_failure(
        self, tmp_path, monkeypatch, method, executor_method, kwargs, result_cls, failed_event
    ):
        monkeypatch.chdir(tmp_path)
        client = _real_client(tmp_path, f"sqlite:///{tmp_path / 'app.db'}", "main")
        events = []
        client.events.on(failed_event, lambda data: events.append(data))
        try:
            with patch(
                "dblift.core.migration.history.migration_history_manager."
                "MigrationHistoryManager.create_schema_and_history_table",
                side_effect=RuntimeError("permission denied for schema main"),
            ):
                with warnings.catch_warnings():
                    warnings.simplefilter("error", DeprecationWarning)
                    result = getattr(client, method)(**kwargs)
        finally:
            client.close()

        assert type(result) is result_cls
        assert result.success is False
        assert result.error_message.startswith("Could not create the schema-history table: ")
        assert "permission denied for schema main" in result.error_message
        assert result.target_schema == "main"
        assert isinstance(result._preflight_error, PreflightConnectionError)
        assert events and events[-1].error == result.error_message
