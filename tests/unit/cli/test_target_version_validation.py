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


@pytest.mark.parametrize("bad", ["v1", "abc", ""])
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


@pytest.mark.parametrize("bad", ["99", "1a", "1.5"])
def test_undo_target_unknown_to_disk_and_history_is_refused_with_both_listed(project, bad):
    assert _run(project, "migrate").returncode == 0
    (project / "m" / "V1__t.sql").unlink()
    (project / "m" / "U1__t.sql").unlink()
    proc = _run(project, "undo", "--target-version", bad)
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Available versions: 1, 2, 3" in proc.stderr
    assert _applied(project) == ["1", "2", "3"]


def test_undo_to_an_applied_version_whose_scripts_were_deleted(project):
    assert _run(project, "migrate").returncode == 0
    (project / "m" / "V1__t.sql").unlink()
    (project / "m" / "U1__t.sql").unlink()
    proc = _run(project, "undo", "--target-version", "1")
    assert proc.returncode == 0, proc.stdout + proc.stderr
    with sqlite3.connect(project / "tv.db") as conn:
        tables = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "t1" in tables and not tables & {"t2", "t3"}


def test_migrate_to_a_version_without_a_script_stays_refused(project):
    assert _run(project, "migrate", "--target-version", "1").returncode == 0
    (project / "m" / "V1__t.sql").unlink()
    (project / "m" / "U1__t.sql").unlink()
    assert _run(project, "migrate", "--target-version", "1").returncode == 2


@pytest.mark.parametrize("bad", ["99", "zzz"])
def test_target_version_from_config_is_refused_before_connecting(project, bad):
    config = project / "c.yaml"
    config.write_text(config.read_text() + f"target_version: {bad}\n")
    proc = _run(project, "migrate")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Available versions: 1, 2, 3" in proc.stderr
    assert not (project / "tv.db").exists()


_UNREACHABLE = "database:\n  url: postgresql://u:p@127.0.0.1:1/x\n  type: postgresql\n"


@pytest.mark.parametrize("command", ["migrate", "validate", "info"])
def test_refusal_precedes_an_unreachable_database(project, command):
    (project / "c.yaml").write_text(_UNREACHABLE + "migrations:\n  directory: m\n")
    proc = _run(project, command, "--target-version", "99")
    assert proc.returncode == 2, proc.stdout + proc.stderr
    assert "Available versions: 1, 2, 3" in proc.stderr


def test_non_string_config_target_is_refused_by_the_cli_check(project, monkeypatch, capsys):
    import argparse
    from pathlib import Path

    from dblift.cli._command_handlers import _validate_target_version_option

    class Parser(argparse.ArgumentParser):
        def error(self, message):
            raise SystemExit(message)

    with pytest.raises(SystemExit) as raised:
        _validate_target_version_option(
            "migrate",
            argparse.Namespace(target_version=99),
            Parser(),
            None,
            project / "m",
            [],
            True,
            {},
        )
    assert "Available versions: 1, 2, 3" in str(raised.value)
