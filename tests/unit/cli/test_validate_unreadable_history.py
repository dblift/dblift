"""``validate`` fails when the schema history table cannot be read.

A history table damaged after migrating (here a renamed ``checksum`` column)
used to leave ``validate`` reporting success with an exit code of 0, while
``info`` and ``undo`` on the same database failed.
"""

from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

pytestmark = [pytest.mark.unit]


def _run(args: List[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
    env = {key: value for key, value in os.environ.items() if not key.startswith("DBLIFT_")}
    env["DBLIFT_DISABLE_CLI_EXTENSIONS"] = "1"
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


@pytest.fixture(scope="module")
def broken_history(tmp_path_factory) -> Path:
    project = tmp_path_factory.mktemp("unreadable_history")
    scripts = project / "migrations"
    scripts.mkdir()
    (scripts / "V1__init.sql").write_text("CREATE TABLE t (id INTEGER);\n", encoding="utf-8")
    migrate = _run(["--db-url", "sqlite:///app.db", "--scripts", "migrations", "migrate"], project)
    assert migrate.returncode == 0, f"migrate failed:\n{migrate.stdout}\n{migrate.stderr}"
    connection = sqlite3.connect(project / "app.db")
    try:
        connection.execute("ALTER TABLE dblift_schema_history RENAME COLUMN checksum TO renamed")
        connection.commit()
    finally:
        connection.close()
    return project


def _validate(project: Path, *flags: str) -> "subprocess.CompletedProcess[str]":
    return _run(
        ["--db-url", "sqlite:///app.db", "--scripts", "migrations", "validate", *flags], project
    )


@pytest.mark.parametrize("strict", [False, True])
def test_validate_json_fails_on_unreadable_history(broken_history: Path, strict: bool) -> None:
    flags = ["--strict"] if strict else []
    result = _validate(broken_history, *flags, "--format", "json")
    assert result.returncode != 0, result.stdout
    payload = json.loads(result.stdout)
    assert payload["success"] is False
    assert "could not read migration history" in payload["error"]
    assert "checksum" in payload["error"]


@pytest.mark.parametrize("strict", [False, True])
def test_validate_human_fails_on_unreadable_history(broken_history: Path, strict: bool) -> None:
    result = _validate(broken_history, *(["--strict"] if strict else []))
    output = result.stdout + result.stderr
    assert result.returncode != 0, output
    assert "validation passed" not in output.lower()
    assert "could not read migration history" in output
