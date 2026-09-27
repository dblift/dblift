"""undo must plan one entry per version after an undo -> migrate cycle.

After migrate V1-V4, undo (V4), migrate (V4 re-applied), history holds two
successful SQL rows for V4. ``undo --target-version 1`` used to plan every
successful row above the target, so it ran U4 twice (the second run failed
on the already-dropped table) and never reached V3 and V2. Only the latest
successful row of each version is the currently applied one.
"""

from __future__ import annotations

import re
import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List

import pytest
import yaml
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

REPO_ROOT = Path(__file__).resolve().parents[5]


def _write_migrations(migrations: Path) -> None:
    migrations.mkdir()
    for v in range(1, 5):
        (migrations / f"V{v}__create_t{v}.sql").write_text(
            f"CREATE TABLE t{v} (id INTEGER PRIMARY KEY);"
        )
        (migrations / f"U{v}__drop_t{v}.sql").write_text(f"DROP TABLE t{v};")


def _client(tmp_path: Path, migrations: Path) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        create_engine(f"sqlite:///{tmp_path / 'app.db'}"), migrations_dir=str(migrations)
    )


def _tables(db_file: Path) -> List[str]:
    with sqlite3.connect(db_file) as conn:
        return [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 't_' "
                "ORDER BY name"
            )
        ]


def _failed_rows(db_file: Path) -> int:
    with sqlite3.connect(db_file) as conn:
        return conn.execute(
            "SELECT COUNT(*) FROM dblift_schema_history WHERE success = 0"
        ).fetchone()[0]


def test_target_version_after_undo_and_reapply_undoes_each_version_once(tmp_path):
    migrations = tmp_path / "migrations"
    _write_migrations(migrations)
    client = _client(tmp_path, migrations)
    assert client.migrate().success
    assert client.undo().success
    assert client.migrate().success

    result = client.undo(target_version="1")
    client.close()

    assert result.success, result.error_message
    assert [m.version for m in result.undone_migrations] == ["4", "3", "2"]
    assert _tables(tmp_path / "app.db") == ["t1"]
    assert _failed_rows(tmp_path / "app.db") == 0


def test_repeated_undo_migrate_cycles_keep_target_version_plan_distinct(tmp_path):
    migrations = tmp_path / "migrations"
    _write_migrations(migrations)
    client = _client(tmp_path, migrations)
    assert client.migrate().success
    for _ in range(3):
        assert client.undo().success
        assert client.migrate().success

    result = client.undo(target_version="1")
    client.close()

    assert result.success, result.error_message
    assert [m.version for m in result.undone_migrations] == ["4", "3", "2"]
    assert _tables(tmp_path / "app.db") == ["t1"]
    assert _failed_rows(tmp_path / "app.db") == 0


def test_plain_undo_after_cycle_undoes_latest_version_once(tmp_path):
    migrations = tmp_path / "migrations"
    _write_migrations(migrations)
    client = _client(tmp_path, migrations)
    assert client.migrate().success
    assert client.undo().success
    assert client.migrate().success

    result = client.undo()
    client.close()

    assert result.success, result.error_message
    assert [m.version for m in result.undone_migrations] == ["4"]
    assert _tables(tmp_path / "app.db") == ["t1", "t2", "t3"]


def test_tag_filtered_undo_after_cycle_plans_each_version_once(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for v in range(1, 4):
        (migrations / f"V{v}__create_t{v}[grp].sql").write_text(
            f"CREATE TABLE t{v} (id INTEGER PRIMARY KEY);"
        )
        (migrations / f"U{v}__drop_t{v}.sql").write_text(f"DROP TABLE t{v};")
    client = _client(tmp_path, migrations)
    assert client.migrate().success
    assert client.undo().success
    assert client.migrate().success

    result = client.undo(tags="grp")
    client.close()

    assert result.success, result.error_message
    versions = [m.version for m in result.undone_migrations]
    assert sorted(versions) == ["1", "2", "3"]
    assert _failed_rows(tmp_path / "app.db") == 0


def test_cli_dry_run_plan_matches_real_run_after_cycle(tmp_path):
    db_file = tmp_path / "app.db"
    migrations = tmp_path / "migrations"
    _write_migrations(migrations)
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(db_file)},
                "migrations": {"directory": str(migrations)},
            }
        )
    )

    def run(*argv: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            [sys.executable, "-m", "dblift.cli.main", "--config", str(config), *argv],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=False,
        )

    def planned(proc: subprocess.CompletedProcess) -> int:
        match = re.search(r"Found (\d+) migration\(s\) to undo", proc.stdout + proc.stderr)
        assert match, proc.stdout + proc.stderr
        return int(match.group(1))

    assert run("migrate").returncode == 0
    assert run("undo").returncode == 0
    assert run("migrate").returncode == 0

    dry = run("--dry-run", "undo", "--target-version", "1")
    real = run("undo", "--target-version", "1")

    assert dry.returncode == 0, dry.stdout + dry.stderr
    assert real.returncode == 0, real.stdout + real.stderr
    assert planned(dry) == planned(real) == 3
    assert _tables(db_file) == ["t1"]
    assert _failed_rows(db_file) == 0
