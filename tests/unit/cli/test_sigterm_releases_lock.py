"""SIGTERM during ``migrate`` unwinds like SIGINT and releases the migration lock."""

from __future__ import annotations

import os
import signal
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

pytestmark = [
    pytest.mark.unit,
    pytest.mark.skipif(sys.platform == "win32", reason="POSIX signal semantics"),
]

LOCK_TABLE = "dblift_migration_lock"
STATEMENTS = 20000


def _lock_rows(db: Path) -> "int | None":
    """Row count of the lock table, or None while it is absent or unreadable."""
    try:
        connection = sqlite3.connect(db, timeout=0.05)
        try:
            return int(connection.execute(f'SELECT COUNT(*) FROM "{LOCK_TABLE}"').fetchone()[0])
        finally:
            connection.close()
    except sqlite3.Error:
        return None


def _wait_for(condition, timeout: float) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if condition():
            return True
        time.sleep(0.02)
    return False


def test_sigterm_releases_migration_lock(tmp_path: Path) -> None:
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    body = "CREATE TABLE t (id INTEGER);\n" + "".join(
        f"INSERT INTO t VALUES ({i});\n" for i in range(STATEMENTS)
    )
    (scripts / "V1__slow.sql").write_text(body, encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    env["DBLIFT_DISABLE_CLI_EXTENSIONS"] = "1"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    db = tmp_path / "app.db"

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "dblift.cli.main",
            "--db-url",
            "sqlite:///app.db",
            "--scripts",
            "migrations",
            "migrate",
        ],
        cwd=tmp_path,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    try:
        assert _wait_for(lambda: _lock_rows(db) == 1, timeout=30), "lock never acquired"
        assert proc.poll() is None, "migration finished before SIGTERM could be sent"
        proc.send_signal(signal.SIGTERM)
        code = proc.wait(timeout=30)
    finally:
        if proc.poll() is None:
            proc.kill()
            proc.wait()

    assert code == 128 + signal.SIGTERM
    assert _lock_rows(db) == 0


@pytest.mark.parametrize("point", ["after_commit", "entry", "after_held", "before_thread_start"])
def test_sigterm_during_lease_registration_releases_lock(tmp_path: Path, point: str) -> None:
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__create.sql").write_text("CREATE TABLE t (id INTEGER);\n", encoding="utf-8")
    env = {k: v for k, v in os.environ.items() if not k.startswith("DBLIFT_")}
    env["DBLIFT_DISABLE_CLI_EXTENSIONS"] = "1"
    env["PYTHONPATH"] = str(Path(__file__).resolve().parents[3])
    env["SIGNAL_POINT"] = point

    child = """
import os
import runpy
import signal
import sys

point = os.environ["SIGNAL_POINT"]
fired = False

def trace(frame, event, _arg):
    global fired
    if fired:
        return None
    if point == "after_commit" and (
        frame.f_code.co_filename.endswith("dblift/db/plugins/sql_lease_store.py")
        and frame.f_code.co_name == "try_acquire"
    ):
        if event == "return" and _arg is True:
            fired = True
            print("SIGNAL_AT_REGISTRATION", flush=True)
            os.kill(os.getpid(), signal.SIGTERM)
        return trace
    if not frame.f_code.co_filename.endswith("dblift/db/plugins/lease_lock.py"):
        return None
    if frame.f_code.co_name != "_on_acquired":
        return None
    lease = frame.f_locals.get("self")
    if (point == "entry" and event == "call") or (
        point == "after_held" and event == "line" and lease._held
    ) or (
        point == "before_thread_start"
        and event == "line"
        and lease._thread is not None
        and not lease._thread.is_alive()
    ):
        fired = True
        print("SIGNAL_AT_REGISTRATION", flush=True)
        os.kill(os.getpid(), signal.SIGTERM)
    return trace

sys.settrace(trace)
sys.argv = ["-m", "--db-url", "sqlite:///app.db", "--scripts", "migrations", "migrate"]
runpy.run_module("dblift.cli.main", run_name="__main__")
"""
    result = subprocess.run(
        [sys.executable, "-c", child],
        cwd=tmp_path,
        env=env,
        text=True,
        capture_output=True,
        timeout=30,
    )

    assert "SIGNAL_AT_REGISTRATION" in result.stdout
    assert result.returncode == 128 + signal.SIGTERM
    assert _lock_rows(tmp_path / "app.db") == 0
