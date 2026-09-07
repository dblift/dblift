"""``--format json`` helpers shared by info / validate / migrate handlers."""

from __future__ import annotations

import io
import json
from contextlib import redirect_stdout
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.cli.handlers._shared import (
    CliCommandContext,
    _migration_info_to_dict,
    run_json_guarded,
)


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
    ]


@pytest.mark.unit
def test_validate_result_to_dict_shape():
    from dblift.cli.handlers.validate import _validate_result_to_dict

    result = SimpleNamespace(
        success=False,
        error_message="checksum mismatch",
        target_schema="main",
        error_count=1,
        validated_migrations=[_migration()],
        failed_migrations=[_migration(status="FAILED")],
    )

    data = _validate_result_to_dict(result)

    assert data == {
        "success": False,
        "error": "checksum mismatch",
        "target_schema": "main",
        "error_count": 1,
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
    )
    ctx = CliCommandContext(client=client, args=SimpleNamespace(format="json"), log=MagicMock())

    ok, _ = _handle_validate(ctx)

    assert ok is True
    payload = json.loads(capsys.readouterr().out)
    assert payload["success"] is True and payload["validated_migrations"] == []


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
    )
    args = SimpleNamespace(format="json", dry_run=False, validate_only=True)

    _handle_migrate(CliCommandContext(client=client, args=args, log=MagicMock()))

    assert "validated_migrations" in json.loads(capsys.readouterr().out)
