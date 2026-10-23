"""``--target-version`` must name a migration script's version, or the command refuses."""

from __future__ import annotations

import sqlite3
import subprocess
import sys

import pytest

pytestmark = [pytest.mark.unit]

_LAUNCH = "import sys; from dblift.cli.main import main; sys.argv[0] = 'dblift'; main()"


@pytest.fixture
def project(tmp_path):
    scripts = tmp_path / "m"
    scripts.mkdir()
    for version in (1, 2, 3):
        (scripts / f"V{version}__t.sql").write_text(f"CREATE TABLE t{version} (id INTEGER);\n")
        (scripts / f"U{version}__t.sql").write_text(f"DROP TABLE t{version};\n")
    (tmp_path / "c.yaml").write_text(
        "database:\n  url: sqlite:///tv.db\n  type: sqlite\nmigrations:\n  directory: m\n"
    )
    return tmp_path


def _run(project, *args):
    return subprocess.run(
        [sys.executable, "-c", _LAUNCH, "--config", "c.yaml", *args],
        cwd=project,
        capture_output=True,
        text=True,
        timeout=120,
    )


def _applied(project):
    db = project / "tv.db"
    if not db.exists():
        return None
    with sqlite3.connect(db) as conn:
        try:
            return [r[0] for r in conn.execute("SELECT version FROM dblift_schema_history")]
        except sqlite3.OperationalError:
            return None


@pytest.mark.parametrize("bad", ["v1", "V1", "abc", "", "99", "-1", "1a", "1.5", "0"])
@pytest.mark.parametrize("command", ["migrate", "validate", "info"])
def test_bad_target_version_is_refused_before_connecting(project, command, bad):
    proc = _run(project, command, "--target-version", bad)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Available versions: 1, 2, 3" in proc.stderr
    assert not (project / "tv.db").exists(), "refused after connecting"


@pytest.mark.parametrize("bad", ["v1", "abc", "", "99", "1a"])
def test_bad_undo_target_version_is_refused_before_connecting(project, bad):
    proc = _run(project, "undo", "--target-version", bad)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Available versions: 1, 2, 3" in proc.stderr
    assert not (project / "tv.db").exists()


@pytest.mark.parametrize("good,expected", [("1", ["1"]), ("2", ["1", "2"]), ("2.0.0", ["1", "2"])])
def test_valid_target_version_applies_up_to_it(project, good, expected):
    proc = _run(project, "migrate", "--target-version", good)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert _applied(project) == expected


def test_target_at_or_below_head_applies_nothing_and_says_so(project):
    assert _run(project, "migrate", "--target-version", "3").returncode == 0
    proc = _run(project, "migrate", "--target-version", "2")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "nothing to apply" in (proc.stdout + proc.stderr).lower()
    assert _applied(project) == ["1", "2", "3"]


def test_undo_to_zero_and_to_a_known_version_still_work(project):
    assert _run(project, "migrate").returncode == 0
    assert _run(project, "undo", "--target-version", "2").returncode == 0
    assert _run(project, "undo", "--target-version", "0").returncode == 0
