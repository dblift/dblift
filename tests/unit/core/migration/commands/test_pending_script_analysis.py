"""Pending scripts carry an ``analysis`` in ``info``, ``migrate --dry-run`` and ``validate`` payloads.

Driven through the real CLI against SQLite, like ``test_validate_reports_real_runs``.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

pytestmark = pytest.mark.unit


def _run(tmp_path: Path, *args: str, scripts: Path, db: Path) -> subprocess.CompletedProcess:
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "dblift.cli.main",
            "--scripts",
            str(scripts),
            "--log-dir",
            str(tmp_path / "logs"),
            "--db-url",
            f"sqlite:///{db}",
            *args,
        ],
        capture_output=True,
        text=True,
    )


def _payload(proc: subprocess.CompletedProcess) -> dict:
    assert proc.stdout, proc.stderr
    return json.loads(proc.stdout)


@pytest.fixture
def project(tmp_path: Path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    (scripts / "V1__a.sql").write_text("CREATE TABLE a (id INTEGER PRIMARY KEY);")
    db = tmp_path / "t.db"
    _run(tmp_path, "migrate", scripts=scripts, db=db)
    (scripts / "V2__drop.sql").write_text("DROP TABLE a;")
    (scripts / "V3__py.py").write_text("def migrate(ctx):\n    pass\n")
    return scripts, db


def test_info_fills_analysis_on_pending_sql_rows_only(tmp_path, project):
    scripts, db = project

    payload = _payload(_run(tmp_path, "info", "--format", "json", scripts=scripts, db=db))

    rows = {m["script"]: m for m in payload["migrations"]}
    assert rows["V1__a.sql"]["analysis"] is None
    assert rows["V3__py.py"]["analysis"] is None
    analysis = rows["V2__drop.sql"]["analysis"]
    assert analysis["statements"][0]["operation"] == "DROP"
    assert analysis["cautions"] == [
        {
            "level": "destroys",
            "statement": 0,
            "reason": analysis["cautions"][0]["reason"],
        }
    ]
    assert "a" in analysis["cautions"][0]["reason"]


def test_migrate_dry_run_fills_analysis_on_pending_rows(tmp_path, project):
    scripts, db = project

    payload = _payload(
        _run(tmp_path, "migrate", "--dry-run", "--format", "json", scripts=scripts, db=db)
    )

    rows = {m["script"]: m for m in payload["migrations"]}
    assert payload["dry_run"] is True
    assert rows["V2__drop.sql"]["analysis"]["cautions"][0]["level"] == "destroys"
    assert rows["V3__py.py"]["analysis"] is None
