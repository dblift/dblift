"""Console text for a connection or schema-history preflight failure.

The console reports it as ``ConnectionError: <message>``, the same text as
``--format json`` and MCP, with no ``Unexpected error`` line and no
duplicate ``Exception:`` line. Any other unexpected error keeps both lines.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest

pytestmark = [pytest.mark.unit]


def _env() -> dict:
    env = {key: value for key, value in os.environ.items() if not key.startswith("DBLIFT_")}
    env["DBLIFT_DISABLE_CLI_EXTENSIONS"] = "1"
    return env


def _run(args: List[str], cwd: Path) -> "subprocess.CompletedProcess[str]":
    return subprocess.run(
        [sys.executable, "-m", "dblift.cli.main", *args],
        cwd=cwd,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )


def _closed_port() -> int:
    sock = socket.socket()
    sock.bind(("127.0.0.1", 0))
    port = sock.getsockname()[1]
    sock.close()
    return port


@pytest.fixture
def project(tmp_path: Path) -> Path:
    (tmp_path / "migrations").mkdir()
    (tmp_path / "migrations" / "V1__init.sql").write_text(
        "CREATE TABLE t (id INTEGER);\n", encoding="utf-8"
    )
    return tmp_path


@pytest.fixture
def unopenable_sqlite(project: Path):
    locked = project / "locked"
    locked.mkdir()
    locked.chmod(0o500)
    yield f"sqlite:///{locked / 'app.db'}"
    locked.chmod(0o700)


def _assert_console_connection_error(completed: "subprocess.CompletedProcess[str]") -> None:
    output = completed.stdout + completed.stderr
    assert completed.returncode == 1, output
    assert "ConnectionError: Connection failed: " in output
    assert "Unexpected error" not in output
    assert "Exception:" not in output
    assert "Traceback" not in output


@pytest.mark.parametrize("command", ["info", "migrate", "clean"])
def test_console_reports_closed_port_as_connection_error(project: Path, command: str) -> None:
    url = f"postgresql://user:pw@127.0.0.1:{_closed_port()}/db"
    args = ["--db-url", url, "--scripts", "migrations", command]
    if command == "clean":
        args.append("--clean-enabled")
    _assert_console_connection_error(_run(args, project))


@pytest.mark.parametrize("dry_run", [False, True])
def test_sqlite_migrate_unopenable_path_console(
    project: Path, unopenable_sqlite: str, dry_run: bool
) -> None:
    flags = ["--dry-run"] if dry_run else []
    completed = _run(
        ["--db-url", unopenable_sqlite, "--scripts", "migrations", *flags, "migrate"], project
    )
    _assert_console_connection_error(completed)


def test_sqlite_migrate_unopenable_path_json(project: Path, unopenable_sqlite: str) -> None:
    completed = _run(
        ["--db-url", unopenable_sqlite, "--scripts", "migrations", "migrate", "--format", "json"],
        project,
    )
    assert completed.returncode == 1, completed.stdout + completed.stderr
    payload = json.loads(completed.stdout)
    assert payload["success"] is False
    assert payload["error"].startswith("ConnectionError: Connection failed: ")


def test_other_unexpected_errors_keep_both_lines(project: Path) -> None:
    script = (
        "import sys\n"
        "import dblift.cli.main as cli_main\n"
        "def boom(**kwargs):\n"
        "    raise RuntimeError('boom')\n"
        "cli_main.execute_single_command = boom\n"
        "sys.argv = ['dblift', '--db-url', 'sqlite:///app.db', '--scripts', 'migrations', 'info']\n"
        "sys.exit(cli_main.main())\n"
    )
    completed = subprocess.run(
        [sys.executable, "-c", script],
        cwd=project,
        env=_env(),
        capture_output=True,
        text=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    assert completed.returncode == 1, output
    assert "Unexpected error: boom" in output
    assert "Exception: boom" in output
