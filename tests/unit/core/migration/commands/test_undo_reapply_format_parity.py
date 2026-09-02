"""Undo after re-apply must behave identically for every versioned format.

``migrate -> undo -> migrate -> undo`` undoes the same version twice. The
second undo is legal: the version was re-applied after the first undo, so it
is applied again and undoable again.

The rank bookkeeping that decides this counted only migrations whose recorded
type was ``SQL``. Versioned Python scripts are recorded as ``PYTHON``, so the
re-apply was invisible: the version looked permanently undone, the second undo
refused it and walked down to the previous version instead.

These tests run the real client against SQLite and are parametrised over the
script format, asserting identical outcomes.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

_BODIES = {
    "sql": {
        "V1__create_a.sql": "CREATE TABLE a (id INTEGER PRIMARY KEY);",
        "U1__drop_a.sql": "DROP TABLE a;",
        "V2__create_b.sql": "CREATE TABLE b (id INTEGER PRIMARY KEY);",
        "U2__drop_b.sql": "DROP TABLE b;",
    },
    "py": {
        "V1__create_a.py": 'def migrate(context):\n    context.execute("CREATE TABLE a (id INTEGER PRIMARY KEY)")\n',
        "U1__drop_a.py": 'def migrate(context):\n    context.execute("DROP TABLE a")\n',
        "V2__create_b.py": 'def migrate(context):\n    context.execute("CREATE TABLE b (id INTEGER PRIMARY KEY)")\n',
        "U2__drop_b.py": 'def migrate(context):\n    context.execute("DROP TABLE b")\n',
    },
}


def _write_migrations(tmp_path: Path, fmt: str) -> Path:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for name, body in _BODIES[fmt].items():
        (migrations / name).write_text(body)
    return migrations


def _client(tmp_path: Path, migrations: Path) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        create_engine(f"sqlite:///{tmp_path / 'app.db'}"), migrations_dir=str(migrations)
    )


def _tables(tmp_path: Path) -> set:
    with sqlite3.connect(tmp_path / "app.db") as conn:
        rows = conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
    return {r[0] for r in rows}


@pytest.mark.parametrize("fmt", ["sql", "py"])
def test_undo_after_reapply_undoes_the_reapplied_version(tmp_path: Path, fmt: str) -> None:
    migrations = _write_migrations(tmp_path, fmt)

    assert _client(tmp_path, migrations).migrate().success
    assert {"a", "b"} <= _tables(tmp_path)

    assert _client(tmp_path, migrations).undo().success
    assert "b" not in _tables(tmp_path)
    assert "a" in _tables(tmp_path)

    # Re-apply V2, then undo it again. The version is applied, so it is undoable.
    assert _client(tmp_path, migrations).migrate().success
    assert "b" in _tables(tmp_path)

    second_undo = _client(tmp_path, migrations).undo()
    assert second_undo.success, second_undo

    tables = _tables(tmp_path)
    assert "b" not in tables, "second undo did not undo the re-applied version"
    assert "a" in tables, "second undo walked past the re-applied version to V1"
