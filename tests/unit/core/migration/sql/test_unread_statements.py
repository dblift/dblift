"""A statement the facts reader leaves unread is reported, never rated SAFE by silence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest

from dblift.core.migration.sql.lint import lint_script

pytestmark = pytest.mark.unit

_UNKNOWN = "FROBNICATE the widgets;"
_ORACLE_BLOCK = "BEGIN\n  DELETE FROM emp;\nEND;\n/\n"
_ORACLE_EXECUTE = "EXECUTE IMMEDIATE 'DROP TABLE emp';\n"
_DB2_COMPOUND = "BEGIN ATOMIC\n  DELETE FROM emp;\nEND\n"

UNREAD = [
    ("postgresql", _UNKNOWN),
    ("mysql", _UNKNOWN),
    ("oracle", _UNKNOWN),
    ("db2", _UNKNOWN),
    ("sqlite", _UNKNOWN),
    ("sqlserver", _UNKNOWN),
    ("oracle", _ORACLE_BLOCK),
    ("oracle", _ORACLE_EXECUTE),
    ("db2", _DB2_COMPOUND),
]

ENVELOPES = [
    ("postgresql", "BEGIN;\nSET search_path = app;\nSAVEPOINT s;\nRELEASE SAVEPOINT s;\nCOMMIT;"),
    ("postgresql", "START TRANSACTION;\nROLLBACK;"),
    ("mysql", "USE app;\nSET foreign_key_checks = 0;\nSTART TRANSACTION;\nCOMMIT;"),
    ("sqlite", "BEGIN;\nSAVEPOINT s;\nRELEASE s;\nCOMMIT;"),
    ("db2", "SET CURRENT SCHEMA = app;\nCOMMIT;"),
    ("oracle", "SET TRANSACTION READ WRITE;\nCOMMIT;"),
    ("sqlserver", "SET NOCOUNT ON;\nUSE app;\nBEGIN TRANSACTION;\nCOMMIT TRANSACTION;"),
    ("postgresql", "-- only a comment\n"),
    ("mysql", "SHOW TABLES;\nDESCRIBE users;"),
]


@pytest.mark.parametrize("dialect, sql", UNREAD)
def test_unread_statement_is_review_not_safe(dialect, sql):
    result = lint_script(sql, dialect)

    assert result.verdict == "REVIEW", (result.verdict, result.findings, result.errors)
    assert [f.code for f in result.findings] == ["statement-not-analysed"]
    assert result.findings[0].severity == "info"


@pytest.mark.parametrize("dialect, sql", [c for c in UNREAD if c[1] != _UNKNOWN])
def test_procedural_block_message_says_effects_are_not_modelled(dialect, sql):
    finding = lint_script(sql, dialect).findings[0]

    assert "procedural block: effects not modelled" in finding.message


@pytest.mark.parametrize("dialect", ["postgresql", "mysql", "oracle", "db2", "sqlite"])
def test_unread_message_names_the_reason(dialect):
    finding = lint_script(_UNKNOWN, dialect).findings[0]

    assert "FROBNICATE" in finding.message
    assert "not modelled" in finding.message or "not classified" in finding.message


@pytest.mark.parametrize("dialect, sql", ENVELOPES)
def test_transaction_and_session_envelopes_stay_safe(dialect, sql):
    result = lint_script(sql, dialect)

    assert (result.verdict, result.findings, result.errors) == ("SAFE", (), ())


def test_unread_statement_beside_read_ones_flags_only_itself():
    sql = "CREATE TABLE t (id INT);\nFROBNICATE the widgets;\nSET x = 1;"

    result = lint_script(sql, "postgresql")

    assert [(f.code, f.statement) for f in result.findings] == [("statement-not-analysed", 1)]


def test_allow_directive_accepts_an_unread_statement():
    result = lint_script("-- dblift:allow statement-not-analysed\n" + _UNKNOWN, "postgresql")

    assert result.verdict == "SAFE"


def _cli(tmp_path: Path, *args: str) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", "--log-dir", str(tmp_path / "logs"), *args],
        capture_output=True,
        text=True,
        env={**os.environ, "DBLIFT_DISABLE_CLI_EXTENSIONS": "1"},
    )


@pytest.mark.parametrize("dialect, sql", UNREAD)
def test_cli_validate_sql_rates_unread_statement_review(tmp_path, dialect, sql):
    script = tmp_path / "V1__x.sql"
    script.write_text(sql)

    proc = _cli(
        tmp_path, "validate-sql", "--dialect", dialect, "--format", "json", "--files", str(script)
    )

    scripts = json.loads(proc.stdout)["scripts"]
    assert [s["verdict"] for s in scripts] == ["REVIEW"], proc.stdout
    assert [f["code"] for f in scripts[0]["findings"]] == ["statement-not-analysed"]
    assert proc.returncode == 0, proc.stderr


def test_cli_dry_run_analysis_marks_unread_statement(tmp_path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__x.sql").write_text(_UNKNOWN)

    proc = _cli(
        tmp_path,
        "--scripts",
        str(scripts),
        "--db-url",
        f"sqlite:///{tmp_path / 't.db'}",
        "migrate",
        "--dry-run",
        "--format",
        "json",
    )

    analysis = json.loads(proc.stdout)["migrations"][0]["analysis"]
    assert analysis["verdict"] == "REVIEW", proc.stdout
    assert [f["code"] for f in analysis["findings"]] == ["statement-not-analysed"]
