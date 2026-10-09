"""An embedded client releases the migration lock it holds when it shuts down.

dblift used as a library installs no signal handlers in the host process, so
the client gives the lock back on every orderly path instead: ``close()``,
leaving a ``with`` block, and interpreter exit (``atexit``). Anything harder
(SIGKILL, SIGTERM with the default handler) is left to the lease expiry.
"""

from __future__ import annotations

import sqlite3
import subprocess
import sys
import textwrap
from pathlib import Path

import pytest
import yaml

from dblift.api.client import DBLiftClient

REPO_ROOT = Path(__file__).resolve().parents[3]

pytestmark = [pytest.mark.unit]

ENGINES = ["sqlite", "duckdb"]


def _config(tmp_path: Path, engine: str) -> tuple[Path, Path]:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    if engine == "sqlite":
        db_file = tmp_path / "app.db"
        database = {"type": "sqlite", "path": str(db_file)}
    else:
        pytest.importorskip("duckdb_engine")
        db_file = tmp_path / "app.duckdb"
        database = {"type": "duckdb", "url": f"duckdb:///{db_file}"}
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump({"database": database, "migrations": {"directory": str(migrations)}})
    )
    return config, db_file


def _lock_rows(engine: str, db_file: Path) -> int:
    if engine == "sqlite":
        with sqlite3.connect(db_file) as conn:
            return conn.execute("SELECT COUNT(*) FROM dblift_migration_lock").fetchone()[0]
    import duckdb

    conn = duckdb.connect(str(db_file))
    try:
        (schema,) = conn.execute(
            "SELECT table_schema FROM information_schema.tables "
            "WHERE table_name = 'dblift_migration_lock'"
        ).fetchone()
        return conn.execute(f'SELECT COUNT(*) FROM "{schema}".dblift_migration_lock').fetchone()[0]
    finally:
        conn.close()


@pytest.mark.parametrize("engine", ENGINES)
def test_close_releases_a_held_migration_lock(tmp_path, engine):
    config, db_file = _config(tmp_path, engine)
    client = DBLiftClient.from_config_file(str(config))
    assert client.provider.acquire_migration_lock(client.config.database.schema, 5) is True

    client.close()

    assert _lock_rows(engine, db_file) == 0


@pytest.mark.parametrize("engine", ENGINES)
def test_leaving_the_with_block_releases_a_held_migration_lock(tmp_path, engine):
    config, db_file = _config(tmp_path, engine)
    with DBLiftClient.from_config_file(str(config)) as client:
        assert client.provider.acquire_migration_lock(client.config.database.schema, 5) is True

    assert _lock_rows(engine, db_file) == 0


@pytest.mark.parametrize("engine", ENGINES)
def test_interpreter_exit_releases_a_held_migration_lock(tmp_path, engine):
    config, db_file = _config(tmp_path, engine)
    script = textwrap.dedent("""
        import sys
        from dblift.api.client import DBLiftClient
        client = DBLiftClient.from_config_file(sys.argv[1])
        assert client.provider.acquire_migration_lock(client.config.database.schema, 5)
        # no close(): the interpreter exits with the lock held
        """)

    result = subprocess.run(
        [sys.executable, "-c", script, str(config)],
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        timeout=60,
        check=False,
    )

    assert result.returncode == 0, result.stdout + result.stderr
    assert _lock_rows(engine, db_file) == 0
