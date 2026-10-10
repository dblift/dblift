"""``--format json`` helpers shared by info / validate / migrate handlers."""

from __future__ import annotations

import json
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.api.client import DBLiftClient
from dblift.cli.handlers._shared import (
    CliCommandContext,
    _migration_info_to_dict,
    run_json_guarded,
)
from dblift.config import DbliftConfig
from dblift.core.logger.log import FileLog, LogFormat
from dblift.core.logger.results import MigrationInfo, OperationResult, ValidateResult
from dblift.core.migration.commands.base_command import PreflightConnectionError


def _migration(**overrides):
    m = MagicMock()
    m.script = "V1__init.sql"
    m.version = "1"
    m.description = "init"
    m.type = SimpleNamespace(name="SQL")
    m.status = "PENDING"
    m.checksum = 42
    m.installed_on = None
    m.installed_by = None
    m.execution_time = 0
    m.error = None
    for k, v in overrides.items():
        setattr(m, k, v)
    return m


@pytest.mark.unit
def test_migration_info_to_dict_uses_enum_names_and_isoformat():
    from datetime import datetime

    m = _migration(
        installed_on=datetime(2026, 9, 7, 12, 0, 0), status=SimpleNamespace(name="SUCCESS")
    )

    data = _migration_info_to_dict(m)

    assert data["type"] == "SQL"
    assert data["status"] == "SUCCESS"
    assert data["installed_on"] == "2026-09-07T12:00:00"
    assert data["version"] == "1"


@pytest.mark.unit
def test_run_json_guarded_emits_payload_and_swallows_client_stdout(capsys):
    result = SimpleNamespace(success=True)
    ctx = CliCommandContext(args=SimpleNamespace(format="json"), log=MagicMock())

    def call():
        print("BANNER THAT MUST NOT LEAK")
        return result

    ok, returned = run_json_guarded(ctx, "VALIDATE", call, lambda r: {"success": True, "x": 1})

    out = capsys.readouterr().out
    assert ok is True and returned is result
    assert json.loads(out) == {"success": True, "x": 1}
    assert "BANNER" not in out


@pytest.mark.unit
def test_run_json_guarded_turns_exception_into_error_payload(capsys):
    ctx = CliCommandContext(args=SimpleNamespace(format="json"), log=MagicMock())

    def call():
        raise RuntimeError("boom")

    ok, returned = run_json_guarded(ctx, "VALIDATE", call, lambda r: {})

    assert (ok, returned) == (False, None)
    assert json.loads(capsys.readouterr().out) == {"success": False, "error": "RuntimeError: boom"}


@pytest.mark.unit
@pytest.mark.parametrize("log_format", [LogFormat.JSON, LogFormat.HTML])
def test_run_json_guarded_records_failed_result_in_file_report(tmp_path, capsys, log_format):
    log = FileLog("test", tmp_path, log_format, schema="main", database_name="db")
    ctx = CliCommandContext(args=SimpleNamespace(format="json"), log=log)
    result = OperationResult(success=False, error_message="checksum mismatch")
    result.complete()

    ok, returned = run_json_guarded(
        ctx, "VALIDATE", lambda: result, lambda r: {"success": r.success}
    )
    log.close()

    assert ok is False and returned is result
    assert json.loads(capsys.readouterr().out) == {"success": False}
    report = log.log_file.read_text(encoding="utf-8")
    if log_format == LogFormat.JSON:
        document = json.loads(report)
        assert document["status"] == "FAILED"
        assert document["error"] == "checksum mismatch"
    else:
        assert "VALIDATE" in report
        assert "Failed" in report
        assert "checksum mismatch" in report


@pytest.mark.unit
@pytest.mark.parametrize("log_format", [LogFormat.JSON, LogFormat.HTML])
def test_run_json_guarded_records_exception_in_file_report(tmp_path, capsys, log_format):
    log = FileLog("test", tmp_path, log_format, schema="main", database_name="db")
    ctx = CliCommandContext(args=SimpleNamespace(format="json"), log=log)

    def fail():
        raise RuntimeError("boom")

    ok, returned = run_json_guarded(ctx, "VALIDATE", fail, lambda r: {})
    log.close()

    assert (ok, returned) == (False, None)
    assert json.loads(capsys.readouterr().out) == {"success": False, "error": "RuntimeError: boom"}
    report = log.log_file.read_text(encoding="utf-8")
    if log_format == LogFormat.JSON:
        document = json.loads(report)
        assert document["status"] == "FAILED"
        assert document["error"] == "RuntimeError: boom"
    else:
        assert "VALIDATE" in report
        assert "Failed" in report
        assert "RuntimeError: boom" in report


@pytest.mark.unit
@pytest.mark.parametrize("log_format", [LogFormat.JSON, LogFormat.HTML])
def test_validate_report_keeps_every_drift_and_validated_script(tmp_path, capsys, log_format):
    log = FileLog("test", tmp_path, log_format, schema="main", database_name="db")
    ctx = CliCommandContext(args=SimpleNamespace(format="json"), log=log)
    result = ValidateResult()
    result.add_failed_migration(MigrationInfo("V1__first.sql", status="FAILED"))
    result.add_failed_migration(MigrationInfo("V2__second.sql", status="FAILED"))
    result.add_validated_migration(MigrationInfo("V3__good.sql", status="SUCCESS"))
    result.issues = ["V1__first.sql checksum mismatch", "V2__second.sql checksum mismatch"]
    result.error_message = result.issues[0]
    result.complete()

    ok, returned = run_json_guarded(
        ctx, "VALIDATE", lambda: result, lambda r: {"success": r.success}
    )
    log.close()

    assert ok is False and returned is result
    assert json.loads(capsys.readouterr().out) == {"success": False}
    report = log.log_file.read_text(encoding="utf-8")
    if log_format == LogFormat.JSON:
        validation = json.loads(report)["commands"][0]
        assert validation["error_count"] == 2
        assert validation["issues"] == result.issues
        assert [m["script"] for m in validation["failed_migrations"]] == [
            "V1__first.sql",
            "V2__second.sql",
        ]
        assert [m["script"] for m in validation["validated_migrations"]] == ["V3__good.sql"]
    else:
        assert "V1__first.sql checksum mismatch" in report
        assert "V2__second.sql checksum mismatch" in report
        assert "V3__good.sql" in report


@pytest.mark.unit
def test_run_json_guarded_lets_systemexit_propagate():
    ctx = CliCommandContext(args=SimpleNamespace(format="json"), log=MagicMock())

    def call():
        raise SystemExit(4)

    with pytest.raises(SystemExit):
        run_json_guarded(ctx, "VALIDATE", call, lambda r: {})


@pytest.mark.unit
def test_run_json_guarded_human_mode_reraises_and_reports_completion():
    log = MagicMock()
    ctx = CliCommandContext(args=SimpleNamespace(format="console"), log=log)
    result = SimpleNamespace(success=True, execution_time=lambda: 3)

    ok, returned = run_json_guarded(ctx, "VALIDATE", lambda: result, lambda r: {})

    assert ok is True and returned is result
    log.set_command_completed.assert_called_once()

    def raising():
        raise RuntimeError("x")

    with pytest.raises(RuntimeError):
        run_json_guarded(ctx, "VALIDATE", raising, lambda r: {})


@pytest.mark.unit
def test_info_result_to_dict_payload_is_unchanged():
    from dblift.cli.handlers.info import _info_result_to_dict

    result = SimpleNamespace(
        success=True,
        error_message=None,
        current_schema_version="1",
        target_schema="main",
        db_version="3.45",
        database_url_masked="sqlite:///x",
        native_driver="sqlite3",
        migrations=[_migration()],
    )

    data = _info_result_to_dict(result)

    assert list(data) == [
        "success",
        "error",
        "current_schema_version",
        "target_schema",
        "db_version",
        "database_url_masked",
        "native_driver",
        "migrations",
    ]
    assert list(data["migrations"][0]) == [
        "script",
        "version",
        "description",
        "type",
        "status",
        "checksum",
        "installed_on",
        "installed_by",
        "execution_time",
        "error",
        "analysis",
    ]


@pytest.mark.unit
def test_validate_result_to_dict_shape():
    from dblift.cli.handlers.validate import _validate_result_to_dict

    result = SimpleNamespace(
        success=False,
        error_message="checksum mismatch",
        target_schema="main",
        error_count=1,
        issues=["checksum mismatch", "Validation failed. Detected modified migration scripts."],
        validated_migrations=[_migration()],
        failed_migrations=[_migration(status="FAILED")],
    )

    data = _validate_result_to_dict(result)

    assert data == {
        "success": False,
        "error": "checksum mismatch",
        "target_schema": "main",
        "error_count": 1,
        # ``error`` is only the first issue; the console logs every one of them.
        "issues": [
            "checksum mismatch",
            "Validation failed. Detected modified migration scripts.",
        ],
        "validated_migrations": [_migration_info_to_dict(result.validated_migrations[0])],
        "failed_migrations": [_migration_info_to_dict(result.failed_migrations[0])],
    }


@pytest.mark.unit
def test_handle_validate_json_emits_payload_only(capsys):
    from dblift.cli.handlers.validate import _handle_validate

    client = MagicMock()
    client.validate.return_value = SimpleNamespace(
        success=True,
        error_message=None,
        target_schema="main",
        error_count=0,
        validated_migrations=[],
        failed_migrations=[],
        _preflight_error=None,
    )
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="json"), log=MagicMock())

    ok, _ = _handle_validate(ctx)

    assert ok is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True and payload["validated_migrations"] == []


_HISTORY = "Could not create the schema-history table: permission denied"
_CONNECTION = "Connection failed: connection refused"


def _preflight_failure_result(message):
    return SimpleNamespace(
        success=False,
        error_message=message,
        target_schema="public",
        error_count=1,
        issues=[],
        validated_migrations=[],
        failed_migrations=[],
        execution_time=lambda: 0,
        _preflight_error=PreflightConnectionError(message),
    )


def _history_failure_result():
    return _preflight_failure_result(_HISTORY)


def _real_preflight_client(message):
    """A real client whose validate() hits a preflight failure."""
    client = DBLiftClient.__new__(DBLiftClient)
    client.config = DbliftConfig.from_dict({"database": {"type": "sqlite", "path": ":memory:"}})
    client.provider = MagicMock()
    client.executor = MagicMock()
    client.executor.validate.side_effect = PreflightConnectionError(message)
    client.events = MagicMock()
    client.dialect = "sqlite"
    return client


@pytest.mark.unit
def test_handle_validate_json_history_table_failure_stays_an_error_payload(capsys):
    """JSON validate keeps the #416 error document for this failure."""
    from dblift.cli.handlers.validate import _handle_validate

    client = MagicMock()
    client.validate.return_value = _history_failure_result()
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="json"), log=MagicMock())

    ok, returned = _handle_validate(ctx)

    assert ok is False
    assert returned is None
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": False, "error": f"ConnectionError: {_HISTORY}"}


@pytest.mark.unit
def test_handle_validate_human_history_table_failure_still_raises():
    from dblift.cli.handlers.validate import _handle_validate

    client = MagicMock()
    client.validate.return_value = _history_failure_result()
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="console"), log=MagicMock())

    with pytest.raises(
        ConnectionError, match="Could not create the schema-history table"
    ) as excinfo:
        _handle_validate(ctx)

    assert type(excinfo.value) is ConnectionError


@pytest.mark.unit
def test_handle_validate_json_connection_failure_stays_an_error_payload(capsys):
    """A refused connection keeps the same JSON error document as history DDL."""
    from dblift.cli.handlers.validate import _handle_validate

    client = MagicMock()
    client.validate.return_value = _preflight_failure_result(_CONNECTION)
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="json"), log=MagicMock())

    ok, returned = _handle_validate(ctx)

    assert ok is False
    assert returned is None
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": False, "error": f"ConnectionError: {_CONNECTION}"}


@pytest.mark.unit
def test_handle_validate_human_connection_failure_still_raises():
    from dblift.cli.handlers.validate import _handle_validate

    client = MagicMock()
    client.validate.return_value = _preflight_failure_result(_CONNECTION)
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="console"), log=MagicMock())

    with pytest.raises(ConnectionError, match="Connection failed: connection refused") as excinfo:
        _handle_validate(ctx)

    assert type(excinfo.value) is ConnectionError


@pytest.mark.unit
@pytest.mark.filterwarnings("error::DeprecationWarning")
def test_handle_validate_json_preflight_stays_connection_error_when_warnings_are_errors(capsys):
    """The CLI must not turn the deprecation into the JSON error text."""
    from dblift.cli.handlers.validate import _handle_validate

    client = _real_preflight_client(_CONNECTION)
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="json"), log=MagicMock())

    ok, returned = _handle_validate(ctx)

    assert ok is False
    assert returned is None
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": False, "error": f"ConnectionError: {_CONNECTION}"}


@pytest.mark.unit
@pytest.mark.filterwarnings("error::DeprecationWarning")
def test_handle_validate_human_preflight_stays_connection_error_when_warnings_are_errors():
    from dblift.cli.handlers.validate import _handle_validate

    client = _real_preflight_client(_HISTORY)
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="console"), log=MagicMock())

    with pytest.raises(
        ConnectionError, match="Could not create the schema-history table"
    ) as raised:
        _handle_validate(ctx)

    assert type(raised.value) is ConnectionError


@pytest.mark.unit
@pytest.mark.filterwarnings("error::DeprecationWarning")
def test_migrate_validate_only_json_preflight_stays_connection_error_when_warnings_are_errors(
    capsys,
):
    from dblift.cli.handlers.migrate import _handle_migrate

    client = _real_preflight_client(_CONNECTION)
    args = SimpleNamespace(format="json", dry_run=False, validate_only=True)

    ok, returned = _handle_migrate(CliCommandContext(client=client, args=args, log=MagicMock()))

    assert ok is False
    assert returned is None
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": False, "error": f"ConnectionError: {_CONNECTION}"}


# (handler module, handler, executor method, args, has --format json)
_PREFLIGHT_HANDLERS = [
    ("info", "_handle_info", "info", {}, True),
    ("validate", "_handle_validate", "validate", {}, True),
    ("migrate", "_handle_migrate", "migrate", {"dry_run": False, "validate_only": False}, True),
    ("undo", "_handle_undo", "undo", {"dry_run": False}, False),
    ("baseline", "_handle_baseline", "baseline", {"baseline_version": "1"}, False),
    ("clean", "_handle_clean", "clean", {"dry_run": False}, False),
    ("repair", "_handle_repair", "repair", {"dry_run": False}, False),
    ("import_flyway", "_handle_import_flyway", "import_flyway", {"dry_run": False}, False),
]


def _run_preflight_handler(module, handler, executor_method, args, message):
    import importlib

    client = _real_preflight_client(message)
    client.executor.validate.side_effect = None
    getattr(client.executor, executor_method).side_effect = PreflightConnectionError(message)
    handle = getattr(importlib.import_module(f"dblift.cli.handlers.{module}"), handler)
    return handle(CliCommandContext(client=client, args=SimpleNamespace(**args), log=MagicMock()))


@pytest.mark.unit
@pytest.mark.filterwarnings("error::DeprecationWarning")
@pytest.mark.parametrize("message", [_CONNECTION, _HISTORY])
@pytest.mark.parametrize(
    "module,handler,executor_method,args,has_json",
    _PREFLIGHT_HANDLERS,
    ids=[entry[0] for entry in _PREFLIGHT_HANDLERS],
)
def test_every_handler_reraises_a_preflight_failure_as_connection_error(
    module, handler, executor_method, args, has_json, message
):
    """The client returns a failed result; every CLI command still fails
    with the same plain ``ConnectionError`` the outer runner reports."""
    with pytest.raises(ConnectionError) as raised:
        _run_preflight_handler(
            module, handler, executor_method, {"format": "console", **args}, message
        )

    assert type(raised.value) is ConnectionError
    assert str(raised.value) == message


@pytest.mark.unit
@pytest.mark.filterwarnings("error::DeprecationWarning")
@pytest.mark.parametrize("message", [_CONNECTION, _HISTORY])
@pytest.mark.parametrize(
    "module,handler,executor_method,args",
    [entry[:4] for entry in _PREFLIGHT_HANDLERS if entry[4]],
    ids=[entry[0] for entry in _PREFLIGHT_HANDLERS if entry[4]],
)
def test_every_json_handler_reports_a_preflight_failure_as_connection_error(
    capsys, module, handler, executor_method, args, message
):
    ok, returned = _run_preflight_handler(
        module, handler, executor_method, {"format": "json", **args}, message
    )

    assert ok is False
    assert returned is None
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": False, "error": f"ConnectionError: {message}"}


@pytest.mark.unit
def test_handle_validate_json_keeps_a_normal_failure_as_a_verdict(capsys):
    from dblift.cli.handlers.validate import _handle_validate

    client = MagicMock()
    client.validate.return_value = SimpleNamespace(
        success=False,
        error_message="checksum mismatch",
        target_schema="main",
        error_count=1,
        issues=["checksum mismatch"],
        validated_migrations=[],
        failed_migrations=[],
        _preflight_error=None,
    )
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="json"), log=MagicMock())

    ok, returned = _handle_validate(ctx)

    assert ok is False
    assert returned is not None
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is False
    assert payload["error"] == "checksum mismatch"
    assert "ConnectionError" not in payload["error"]


@pytest.mark.unit
def test_handle_migrate_validate_only_json_history_table_failure_stays_an_error(capsys):
    from dblift.cli.handlers.migrate import _handle_migrate

    client = MagicMock()
    client.validate.return_value = _history_failure_result()
    args = SimpleNamespace(format="json", dry_run=False, validate_only=True)

    ok, returned = _handle_migrate(CliCommandContext(client=client, args=args, log=MagicMock()))

    assert ok is False
    assert returned is None
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": False, "error": f"ConnectionError: {_HISTORY}"}
    client.migrate.assert_not_called()


@pytest.mark.unit
def test_validate_parser_accepts_format_json():
    from dblift.cli._parser_setup import create_parser

    args = create_parser(exit_on_error=False).parse_args(["validate", "--format", "json"])

    assert args.format == "json"
    assert create_parser(exit_on_error=False).parse_args(["validate"]).format == "console"


@pytest.mark.unit
def test_migrate_result_to_dict_shape():
    from dblift.cli.handlers.migrate import _migrate_result_to_dict

    result = SimpleNamespace(
        success=True,
        error_message=None,
        target_schema="main",
        current_schema_version="1",
        dry_run_count=2,
        migrations=[_migration(status="SUCCESS")],
        migrations_applied=["1"],
    )

    data = _migrate_result_to_dict(result, dry_run=True)

    assert data == {
        "success": True,
        "error": None,
        "dry_run": True,
        "target_schema": "main",
        "current_schema_version": "1",
        "dry_run_count": 2,
        "migrations": [_migration_info_to_dict(result.migrations[0])],
        "migrations_applied": ["1"],
    }


@pytest.mark.unit
def test_migrate_result_to_dict_carries_sql_only_when_show_sql_is_true():
    from dblift.cli.handlers.migrate import _migrate_result_to_dict
    from dblift.core.logger.results import MigrationSqlInfo

    result_with_sql = SimpleNamespace(
        success=True,
        error_message=None,
        target_schema="main",
        current_schema_version="1",
        dry_run_count=1,
        migrations=[],
        migrations_applied=[],
        show_sql=True,
        sql=[
            MigrationSqlInfo(
                script="V1__x.sql", version="1", description="x", statements=["CREATE TABLE ..."]
            )
        ],
    )

    data = _migrate_result_to_dict(result_with_sql, dry_run=True)

    # Both keys, matching the log-format JSON shape.
    assert data["show_sql"] is True
    assert data["sql"] == [
        {
            "script": "V1__x.sql",
            "version": "1",
            "description": "x",
            "statements": ["CREATE TABLE ..."],
        }
    ]

    result_without_sql = SimpleNamespace(
        success=True,
        error_message=None,
        target_schema="main",
        current_schema_version="1",
        dry_run_count=1,
        migrations=[],
        migrations_applied=[],
        show_sql=False,
    )

    without = _migrate_result_to_dict(result_without_sql, dry_run=True)
    assert "sql" not in without
    assert "show_sql" not in without


@pytest.mark.unit
@pytest.mark.parametrize("message", [_CONNECTION, _HISTORY])
@pytest.mark.parametrize("dry_run", [False, True])
def test_handle_migrate_json_preflight_failure_is_a_connection_error(capsys, message, dry_run):
    """`migrate --format json` reports a preflight failure with the same
    `ConnectionError: ...` document info and validate produce: the client
    lets it propagate rather than returning a failed migrate result."""
    from dblift.cli.handlers.migrate import _handle_migrate

    client = _real_preflight_client(message)
    client.executor.migrate.side_effect = PreflightConnectionError(message)
    args = SimpleNamespace(format="json", dry_run=dry_run, validate_only=False)

    ok, returned = _handle_migrate(CliCommandContext(client=client, args=args, log=MagicMock()))

    assert ok is False
    assert returned is None
    payload = json.loads(capsys.readouterr().out)
    assert payload == {"success": False, "error": f"ConnectionError: {message}"}


@pytest.mark.unit
def test_handle_migrate_dry_run_json(capsys):
    from dblift.cli.handlers.migrate import _handle_migrate

    client = MagicMock()
    client.migrate.return_value = SimpleNamespace(
        success=True,
        error_message=None,
        target_schema="main",
        current_schema_version=None,
        dry_run_count=1,
        migrations=[],
        migrations_applied=[],
    )
    args = SimpleNamespace(format="json", dry_run=True, validate_only=False)
    ctx = CliCommandContext(client=client, args=args, log=MagicMock())

    ok, _ = _handle_migrate(ctx)

    assert ok is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["dry_run"] is True and payload["dry_run_count"] == 1
    assert client.migrate.call_args.kwargs["dry_run"] is True


@pytest.mark.unit
def test_handle_migrate_validate_only_json_uses_validate_payload(capsys):
    from dblift.cli.handlers.migrate import _handle_migrate

    client = MagicMock()
    client.validate.return_value = SimpleNamespace(
        success=True,
        error_message=None,
        target_schema="main",
        error_count=0,
        validated_migrations=[],
        failed_migrations=[],
        _preflight_error=None,
    )
    args = SimpleNamespace(format="json", dry_run=False, validate_only=True)

    _handle_migrate(CliCommandContext(client=client, args=args, log=MagicMock()))

    assert "validated_migrations" in json.loads(capsys.readouterr().out)


@pytest.mark.unit
def test_validate_result_to_dict_error_is_null_on_success_like_info_and_migrate():
    """A clean validate leaves ``error_message`` empty; the JSON ``error`` must
    be ``null`` (as info/migrate emit), not ``""`` — one contract across the
    three read tools."""
    from dblift.cli.handlers.validate import _validate_result_to_dict

    result = SimpleNamespace(
        success=True,
        error_message="",
        target_schema="main",
        error_count=0,
        issues=[],
        validated_migrations=[],
        failed_migrations=[],
    )

    assert _validate_result_to_dict(result)["error"] is None


@pytest.mark.unit
def test_migration_info_to_dict_carries_analysis_or_null():
    analysis = {"statements": [], "cautions": [], "errors": []}

    assert _migration_info_to_dict(_migration(analysis=analysis))["analysis"] == analysis
    assert _migration_info_to_dict(_migration(analysis=None))["analysis"] is None
