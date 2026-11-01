"""The CLI resolves paths written in the configuration file against the file's folder."""

import os
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _run(args, cwd: Path) -> "subprocess.CompletedProcess[str]":
    env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        timeout=120,
    )


@pytest.fixture
def project(tmp_path):
    root = tmp_path / "proj"
    (root / "migrations").mkdir(parents=True)
    (root / "migrations" / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER);\n")
    (root / "dblift.yaml").write_text(
        "database:\n  url: sqlite:///rel.db\n"
        "migrations:\n  directory: migrations\n"
        "logging:\n  directory: logs\n"
    )
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    return root, elsewhere


def test_migrate_from_another_directory(project):
    root, elsewhere = project

    result = _run(["--config", str(root / "dblift.yaml"), "migrate"], elsewhere)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert "not found" not in output
    with sqlite3.connect(root / "rel.db") as conn:
        tables = {row[0] for row in conn.execute("SELECT name FROM sqlite_master")}
    assert "t" in tables
    assert list((root / "logs").glob("*.log"))
    assert list(elsewhere.iterdir()) == []


def test_info_from_another_directory_lists_the_pending_migration(project):
    root, elsewhere = project

    result = _run(["--config", str(root / "dblift.yaml"), "info"], elsewhere)

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert re.search(r"│ 1\s+│ t\s+│", output), output


def test_command_line_values_stay_relative_to_the_working_directory(project):
    root, elsewhere = project
    (elsewhere / "cli_migrations").mkdir()
    (elsewhere / "cli_migrations" / "V2__u.sql").write_text("CREATE TABLE u (id INTEGER);\n")

    result = _run(
        ["--config", str(root / "dblift.yaml"), "--scripts", "cli_migrations", "info"],
        elsewhere,
    )

    output = result.stdout + result.stderr
    assert result.returncode == 0, output
    assert re.search(r"│ 2\s+│ u\s+│", output), output
    assert not re.search(r"│ 1\s+│ t\s+│", output), output
