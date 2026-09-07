"""Spawn ``dblift mcp`` and prove every stdout line is a JSON-RPC frame, even with debug logs."""

from __future__ import annotations

import json
import queue
import subprocess
import sys
import threading
import time
from pathlib import Path

import pytest
import yaml

pytest.importorskip("mcp")

ROOT = Path(__file__).resolve().parents[2]


def _frame(msg_id, method, params=None):
    body = {"jsonrpc": "2.0", "id": msg_id, "method": method}
    if params is not None:
        body["params"] = params
    return json.dumps(body) + "\n"


@pytest.mark.integration
def test_stdio_round_trip_keeps_stdout_pure(tmp_path: Path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE widgets (id INTEGER PRIMARY KEY);")
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(tmp_path / "t.sqlite")},
                "migrations": {"directory": str(migrations)},
            }
        )
    )

    # A single `input=`/`communicate()` write with an immediate stdin close
    # races the server's shutdown: closing stdin signals EOF while the
    # `tools/call` handler (the slowest of the three — it opens the SQLite
    # connection and creates the history table) is still running, and the
    # server can exit before flushing that last response. Driving the
    # handshake frame-by-frame — write, flush, wait for that frame's
    # response — avoids the race; stdin is closed only once every response
    # has arrived.
    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "dblift.cli.main",
            "--config",
            str(config),
            "--log-dir",
            str(tmp_path / "logs"),
            "--log-level",
            "debug",
            "mcp",
        ],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        cwd=ROOT,
        bufsize=1,
    )

    lines: list[str] = []
    line_queue: "queue.Queue[str | None]" = queue.Queue()

    def _pump_stdout() -> None:
        for line in iter(proc.stdout.readline, ""):
            lines.append(line)
            line_queue.put(line)
        line_queue.put(None)

    reader = threading.Thread(target=_pump_stdout, daemon=True)
    reader.start()

    deadline = time.monotonic() + 60

    def _next_line() -> str:
        remaining = deadline - time.monotonic()
        try:
            item = line_queue.get(timeout=max(remaining, 0))
        except queue.Empty:
            item = None
        if item is None:
            proc.kill()
            proc.wait(timeout=5)
            raise AssertionError(
                f"stdout closed/timed out before expected frame; stderr={proc.stderr.read()!r}"
            )
        return item

    try:
        proc.stdin.write(
            _frame(
                1,
                "initialize",
                {
                    "protocolVersion": "2025-06-18",
                    "capabilities": {},
                    "clientInfo": {"name": "smoke", "version": "0"},
                },
            )
        )
        proc.stdin.flush()
        _next_line()

        proc.stdin.write(
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}) + "\n"
        )
        proc.stdin.flush()

        proc.stdin.write(_frame(2, "tools/list"))
        proc.stdin.flush()
        _next_line()

        proc.stdin.write(_frame(3, "tools/call", {"name": "info", "arguments": {}}))
        proc.stdin.flush()
        _next_line()
    finally:
        proc.stdin.close()

    returncode = proc.wait(timeout=60)
    reader.join(timeout=5)
    stderr = proc.stderr.read()

    non_blank = [line for line in lines if line.strip()]
    assert non_blank, f"no frames on stdout; returncode={returncode}; stderr={stderr!r}"
    assert returncode == 0, f"dblift mcp exited {returncode}; stderr={stderr!r}"
    frames = [json.loads(line) for line in non_blank]  # raises if anything non-JSON leaked
    by_id = {f.get("id"): f for f in frames}
    assert {t["name"] for t in by_id[2]["result"]["tools"]} >= {
        "info",
        "validate",
        "migrate_dry_run",
    }
    assert by_id[3]["result"]["isError"] is False
    assert by_id[3]["result"]["structuredContent"]["migrations"][0]["script"] == "V1__init.sql"
