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
    monkeypatch.setattr(validate_sql, "lint_files", lambda *args, **kwargs: [lint])
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


def test_dialect_option_is_canonicalised_and_wins_over_the_config(tmp_path):
    script = tmp_path / "V1__index.sql"
    script.write_text("CREATE INDEX idx_users_email ON users (email);")
    ctx = _ctx(_config(dialect="mysql"), files=[str(script)])
    ctx.args.dialect = "postgres"

    _, result = validate_sql._handle_validate_sql(ctx)

    assert result.data["dialect"] == "postgresql"
    codes = [f["code"] for f in result.data["scripts"][0]["findings"]]
    assert "pg-index-not-concurrent" in codes


@pytest.fixture
def new_table(tmp_path: Path) -> Path:
    folder = tmp_path / "delta"
    folder.mkdir()
    (folder / "V1__orders.sql").write_text("CREATE TABLE orders (id INT);")
    (folder / "V2__index.sql").write_text("CREATE INDEX idx_orders_id ON orders (id);")
    return folder


def test_migration_directories_lint_each_script_alone(new_table):
    ctx = _ctx(_config(), scripts_dir=new_table)

    _, result = validate_sql._handle_validate_sql(ctx)

    verdicts = {s["script"]: s["verdict"] for s in result.data["scripts"]}
    assert verdicts == {"V1__orders.sql": "SAFE", "V2__index.sql": "REVIEW"}


def test_named_files_are_one_delta_listed_in_apply_order(new_table):
    files = [str(new_table / "V2__index.sql"), str(new_table / "V1__orders.sql")]
    ctx = _ctx(_config(), files=files)

    _, result = validate_sql._handle_validate_sql(ctx)

    assert [(s["script"], s["verdict"]) for s in result.data["scripts"]] == [
        ("V1__orders.sql", "SAFE"),
        ("V2__index.sql", "SAFE"),
    ]
