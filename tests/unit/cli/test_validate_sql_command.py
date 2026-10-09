"""``dblift validate-sql`` through the real CLI, with no database."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _run(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", "--log-dir", str(tmp_path / "logs"), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "DBLIFT_DISABLE_CLI_EXTENSIONS": "1"},
    )


@pytest.fixture
def scripts(tmp_path: Path) -> Path:
    folder = tmp_path / "migrations"
    folder.mkdir()
    (folder / "V1__users.sql").write_text("CREATE TABLE users (id INT PRIMARY KEY, email TEXT);")
    (folder / "V2__drop_email.sql").write_text("ALTER TABLE users DROP COLUMN email;")
    (folder / "U2__drop_email.sql").write_text("ALTER TABLE users ADD COLUMN email TEXT;")
    (folder / "notes.sql").write_text("DROP TABLE users;")
    return folder


def test_json_lists_v_and_r_scripts_with_verdicts_and_fails_on_unsafe(tmp_path, scripts):
    proc = _run(
        tmp_path,
        "--scripts",
        str(scripts),
        "validate-sql",
        "--dialect",
        "postgresql",
        "--format",
        "json",
    )

    payload = json.loads(proc.stdout)
    assert proc.returncode == 1, proc.stderr
    assert payload["success"] is False
    assert [s["script"] for s in payload["scripts"]] == ["V1__users.sql", "V2__drop_email.sql"]
    assert [s["verdict"] for s in payload["scripts"]] == ["SAFE", "UNSAFE"]
    assert payload["summary"] == {"SAFE": 1, "REVIEW": 0, "UNSAFE": 1}


def test_files_option_lints_exactly_the_files_given(tmp_path, scripts):
    proc = _run(
        tmp_path,
        "validate-sql",
        "--dialect",
        "mysql",
        "--format",
        "json",
        "--files",
        str(scripts / "V1__users.sql"),
    )

    payload = json.loads(proc.stdout)
    assert proc.returncode == 0, proc.stderr
    assert [s["script"] for s in payload["scripts"]] == ["V1__users.sql"]


def test_allow_directive_turns_unsafe_into_safe(tmp_path, scripts):
    target = scripts / "V2__drop_email.sql"
    target.write_text("-- dblift:allow drop-column, pg-missing-lock-timeout\n" + target.read_text())

    proc = _run(
        tmp_path,
        "validate-sql",
        "--dialect",
        "postgresql",
        "--format",
        "json",
        "--files",
        str(target),
    )

    assert proc.returncode == 0, proc.stderr
    assert json.loads(proc.stdout)["scripts"][0]["verdict"] == "SAFE"


@pytest.mark.parametrize("dialect", ["snowflake", "oracle"])
def test_dialect_alone_lints_offline_without_a_config(tmp_path, scripts, dialect):
    proc = _run(
        tmp_path,
        "validate-sql",
        "--dialect",
        dialect,
        "--format",
        "json",
        "--files",
        str(scripts / "notes.sql"),
    )

    payload = json.loads(proc.stdout)
    assert proc.returncode == 1, proc.stderr
    assert [f["code"] for f in payload["scripts"][0]["findings"]] == ["drop-table"]


def test_placeholders_option_is_substituted_before_linting(tmp_path):
    script = tmp_path / "V1__drop.sql"
    script.write_text("DROP TABLE ${table};")

    proc = _run(
        tmp_path,
        "validate-sql",
        "--dialect",
        "mysql",
        "--format",
        "json",
        "--placeholders",
        "table=users",
        "--files",
        str(script),
    )

    payload = json.loads(proc.stdout)
    assert proc.returncode == 1, proc.stderr
    assert [f["snippet"] for f in payload["scripts"][0]["findings"]] == ["DROP TABLE users"]


def test_missing_file_fails(tmp_path):
    proc = _run(
        tmp_path,
        "validate-sql",
        "--dialect",
        "mysql",
        "--format",
        "json",
        "--files",
        str(tmp_path / "V9__nope.sql"),
    )

    payload = json.loads(proc.stdout)
    assert proc.returncode == 1
    assert "V9__nope.sql" in payload["error"]


def test_console_prints_each_finding_and_a_summary(tmp_path, scripts):
    proc = _run(tmp_path, "--scripts", str(scripts), "validate-sql", "--dialect", "postgresql")

    output = proc.stdout + proc.stderr
    assert proc.returncode == 1
    assert "V2__drop_email.sql: UNSAFE" in output
    assert "drop-column" in output
    assert "1 SAFE, 0 REVIEW, 1 UNSAFE" in output


def test_console_prints_the_statement_under_every_finding_on_it(tmp_path, scripts):
    # drop-column and pg-missing-lock-timeout both point at the one statement:
    # the logger's repeated-message filter must not swallow the second copy.
    proc = _run(
        tmp_path,
        "validate-sql",
        "--dialect",
        "postgresql",
        "--files",
        str(scripts / "V2__drop_email.sql"),
    )

    output = proc.stdout + proc.stderr
    assert output.count("ALTER TABLE users DROP COLUMN email;") == 2, output


def test_without_a_dialect_or_config_the_command_explains_what_it_needs(tmp_path, scripts):
    proc = _run(tmp_path, "--scripts", str(scripts), "validate-sql")

    assert proc.returncode != 0
    assert "--dialect" in proc.stdout + proc.stderr


def test_an_installed_extension_replaces_the_default_parser(monkeypatch):
    import dblift.cli.extensions as extensions
    from dblift.cli._parser_setup import create_parser

    def _extension(parser):
        sub = next(a for a in parser._actions if a.__class__.__name__ == "_SubParsersAction")
        sub.add_parser("validate-sql").add_argument("--marker", action="store_true")

    monkeypatch.setattr(extensions, "load_command_extensions", _extension)
    args = create_parser().parse_args(["validate-sql", "--marker"])
    assert args.marker is True


def test_default_handler_is_registered_and_no_stub_remains():
    from dblift.cli._command_handlers import _COMMAND_HANDLERS, PREMIUM_STUB_COMMANDS
    from dblift.cli.handlers.validate_sql import _handle_validate_sql

    assert _COMMAND_HANDLERS["validate-sql"] is _handle_validate_sql
    assert "validate-sql" not in PREMIUM_STUB_COMMANDS
