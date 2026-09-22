"""Freeze what a user's database and scripts observe at runtime on SQLite.

Covers the history table columns, the keys of ``info --format json`` and the
process exit codes. SQLite needs no server, so this runs in the unit suite.
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

from ._snapshot import assert_matches_snapshot

pytestmark = [pytest.mark.unit]


def _run(args: List[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
    # The CLI reads its configuration from DBLIFT_* variables; a developer's
    # shell must not leak into the recorded contract. Only the extension
    # switch is set, so the result describes this distribution alone.
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


def test_sqlite_runtime_contract(tmp_path: Path) -> None:
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__create_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);\n", encoding="utf-8"
    )
    base = ["--db-url", "sqlite:///contract.db", "--scripts", "migrations"]

    migrate = _run([*base, "migrate"], tmp_path)
    info = _run([*base, "info", "--format", "json"], tmp_path)
    unknown = _run(["no-such-command"], tmp_path)
    # A script edited after it was applied is the canonical failure: validate refuses it.
    (scripts / "V1__create_users.sql").write_text(
        "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, email TEXT);\n", encoding="utf-8"
    )
    tampered = _run([*base, "validate"], tmp_path)

    assert migrate.returncode == 0, f"migrate failed:\n{migrate.stdout}\n{migrate.stderr}"
    assert info.returncode == 0, f"info failed:\n{info.stdout}\n{info.stderr}"

    facts = [
        f"exit_code :: migrate_ok={migrate.returncode}",
        f"exit_code :: info_ok={info.returncode}",
        f"exit_code :: unknown_command={unknown.returncode}",
        f"exit_code :: validate_checksum_mismatch={tampered.returncode}",
    ]
    payload = json.loads(info.stdout)
    facts += [f"info_json :: {key}" for key in payload]
    facts += [f"info_json.migrations[] :: {key}" for key in payload["migrations"][0]]

    connection = sqlite3.connect(tmp_path / "contract.db")
    try:
        rows = connection.execute("PRAGMA table_info(dblift_schema_history)").fetchall()
    finally:
        connection.close()
    assert rows, "dblift_schema_history not found in contract.db — did migrate write elsewhere?"
    facts += [f"history_column :: {row[1]}|{row[2].upper()}" for row in rows]

    assert_matches_snapshot("sqlite_runtime", facts)
