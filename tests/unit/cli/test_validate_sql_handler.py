"""``_handle_validate_sql`` called in process, with no database."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.cli.handlers import validate_sql
from dblift.cli.handlers._shared import CliCommandContext, ConfigOnlyClient
from dblift.core.migration.sql.lint import REVIEW, ScriptLint
from dblift.core.migration.sql.lint_rules import ERROR, Finding

pytestmark = pytest.mark.unit


def _config(dialect: str = "postgresql", directory: str = "") -> SimpleNamespace:
    return SimpleNamespace(
        database=SimpleNamespace(type=dialect), migrations=SimpleNamespace(directory=directory)
    )


def _ctx(config: SimpleNamespace, files=None, fmt: str = "console", **kwargs) -> CliCommandContext:
    return CliCommandContext(
        client=ConfigOnlyClient(config=config),
        args=argparse.Namespace(files=files, format=fmt),
        log=MagicMock(),
        **kwargs,
    )


def _logged(log: MagicMock) -> str:
    return "\n".join(str(call.args[0]) for call in log.info.call_args_list)


@pytest.fixture
def scripts(tmp_path: Path) -> Path:
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "V1__users.sql").write_text("CREATE TABLE users (id INT PRIMARY KEY, email TEXT);")
    (folder / "V2__drop_email.sql").write_text("ALTER TABLE users DROP COLUMN email;")
    (folder / "U2__drop_email.sql").write_text("ALTER TABLE users ADD COLUMN email TEXT;")
    (folder / "notes.sql").write_text("DROP TABLE users;")
    nested = folder / "later"
    nested.mkdir()
    (nested / "V3__drop_users.sql").write_text("DROP TABLE users;")
    return folder


def test_scripts_dir_lints_v_and_r_scripts_and_prints_findings(scripts):
    ctx = _ctx(_config(), scripts_dir=scripts)

    ok, result = validate_sql._handle_validate_sql(ctx)

    assert ok is False and result.success is False
    assert [s["script"] for s in result.data["scripts"]] == ["V1__users.sql", "V2__drop_email.sql"]
    assert result.data["summary"] == {"SAFE": 1, "REVIEW": 0, "UNSAFE": 1}
    logged = _logged(ctx.log)
    assert "V2__drop_email.sql: UNSAFE" in logged
    assert "drop-column, statement 1" in logged
    assert "2 script(s): 1 SAFE, 0 REVIEW, 1 UNSAFE" in logged


def test_recursive_directory_from_config_includes_nested_scripts(scripts):
    ctx = _ctx(_config(directory=str(scripts)), recursive=True)

    _, result = validate_sql._handle_validate_sql(ctx)

    assert [s["script"] for s in result.data["scripts"]] == [
        "V1__users.sql",
        "V2__drop_email.sql",
        "V3__drop_users.sql",
    ]


def test_per_directory_recursion_overrides_the_default(scripts):
    ctx = _ctx(_config(), scripts_dir=scripts, recursive=True, dir_recursive_map={scripts: False})

    _, result = validate_sql._handle_validate_sql(ctx)

    assert "V3__drop_users.sql" not in [s["script"] for s in result.data["scripts"]]


def test_missing_file_fails_and_is_reported(scripts):
    missing = scripts / "V9__gone.sql"
    ctx = _ctx(_config(), files=[str(scripts / "V1__users.sql"), str(missing)])

    ok, result = validate_sql._handle_validate_sql(ctx)

    assert ok is False
    assert result.error_message == f"File not found: {missing}"
    ctx.log.error.assert_called_once_with(result.error_message)
    assert [s["script"] for s in result.data["scripts"]] == ["V1__users.sql"]


def test_allowed_finding_and_unread_statement_are_printed(monkeypatch, scripts):
    finding = Finding("drop-table", ERROR, 0, "drops a table", "DROP TABLE users", allowed=True)
    lint = ScriptLint("V1__users.sql", REVIEW, (finding,), ("parser error: boom",))
    monkeypatch.setattr(validate_sql, "lint_files", lambda *args: [lint])
    ctx = _ctx(_config(), files=[str(scripts / "V1__users.sql")])

    ok, _ = validate_sql._handle_validate_sql(ctx)

    assert ok is True
    logged = _logged(ctx.log)
    assert "drops a table (allowed)" in logged
    assert "DROP TABLE users" in logged
    assert "not read: parser error: boom" in logged


def test_json_format_writes_only_the_payload(capsys, scripts):
    ctx = _ctx(_config(), files=[str(scripts / "V2__drop_email.sql")], fmt="json")

    ok, _ = validate_sql._handle_validate_sql(ctx)

    payload = json.loads(capsys.readouterr().out)
    assert ok is False
    assert payload["success"] is False and payload["error"] is None
    assert payload["dialect"] == "postgresql"
    assert payload["scripts"][0]["verdict"] == "UNSAFE"
    ctx.log.info.assert_not_called()
