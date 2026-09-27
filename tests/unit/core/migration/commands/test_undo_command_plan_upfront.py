"""undo --target-version must validate the whole rollback plan before any write.

With V1-V4 applied, U4 present and U3 missing, ``undo --target-version 2``
used to execute U4 and only then refuse on the missing U3, leaving the
database half rolled back, while ``--dry-run`` refused up front. The real
run must reach the dry-run's verdict before executing anything.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
from pathlib import Path
from typing import List, Tuple

import pytest
import yaml
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

REPO_ROOT = Path(__file__).resolve().parents[5]


def _write_migrations(migrations: Path, undo_versions: List[int]) -> None:
    migrations.mkdir()
    for v in range(1, 5):
        (migrations / f"V{v}__create_t{v}.sql").write_text(
            f"CREATE TABLE t{v} (id INTEGER PRIMARY KEY);"
        )
    for v in undo_versions:
        (migrations / f"U{v}__drop_t{v}.sql").write_text(f"DROP TABLE t{v};")


def _client(tmp_path: Path, migrations: Path) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        create_engine(f"sqlite:///{tmp_path / 'app.db'}"), migrations_dir=str(migrations)
    )


def _snapshot(db_file: Path) -> Tuple[List[tuple], List[str]]:
    with sqlite3.connect(db_file) as conn:
        history = conn.execute(
            "SELECT * FROM dblift_schema_history ORDER BY installed_rank"
        ).fetchall()
        tables = [
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name LIKE 't_' "
                "ORDER BY name"
            )
        ]
    return history, tables


def test_missing_undo_script_below_top_refuses_before_executing_anything(tmp_path):
    migrations = tmp_path / "migrations"
    _write_migrations(migrations, undo_versions=[4])  # U3 missing
    client = _client(tmp_path, migrations)
    assert client.migrate().success
    before = _snapshot(tmp_path / "app.db")

    dry_run_result = client.undo(target_version="2", dry_run=True)
    real_result = client.undo(target_version="2")
    client.close()

    assert not dry_run_result.success
    assert not real_result.success
    assert real_result.error_message == dry_run_result.error_message
    assert "No undo script found for V3__create_t3.sql" in real_result.error_message
    assert not real_result.undone_migrations
    # U4 must not have run: t4 still exists and history is unchanged.
    assert _snapshot(tmp_path / "app.db") == before


def test_target_version_still_skips_already_undone_versions(tmp_path):
    migrations = tmp_path / "migrations"
    _write_migrations(migrations, undo_versions=[3, 4])
    client = _client(tmp_path, migrations)
    assert client.migrate().success
    assert client.undo().success  # undoes V4 only

    result = client.undo(target_version="2")
    client.close()

    assert result.success, result.error_message
    assert [m.version for m in result.undone_migrations] == ["3"]
    _, tables = _snapshot(tmp_path / "app.db")
    assert tables == ["t1", "t2"]


def test_cli_undo_target_version_refuses_without_partial_rollback(tmp_path):
    db_file = tmp_path / "app.db"
    migrations = tmp_path / "migrations"
    _write_migrations(migrations, undo_versions=[4])
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

    assert run("migrate").returncode == 0
    before = _snapshot(db_file)

    dry = run("--dry-run", "undo", "--target-version", "2")
    real = run("undo", "--target-version", "2")

    assert dry.returncode != 0
    assert real.returncode != 0
    message = "No undo script found for V3__create_t3.sql"
    assert message in dry.stdout + dry.stderr
    assert message in real.stdout + real.stderr
    assert _snapshot(db_file) == before
