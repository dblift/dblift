"""Parity: Python versioned migrations undo via a separate U*.py, like SQL."""

from __future__ import annotations

from pathlib import Path

import pytest

from api import DBLiftClient

V1_PY = """\
def migrate(context):
    context.execute("CREATE TABLE items (id INTEGER PRIMARY KEY, name TEXT)")
"""

U1_PY = """\
def migrate(context):
    context.execute("DROP TABLE IF EXISTS items")
"""


def _table_exists(engine, name: str) -> bool:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchall()
    return bool(rows)


def _client(tmp_path: Path):
    from sqlalchemy import create_engine

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    return engine, migrations


def test_python_undo_uses_separate_undo_script(tmp_path):
    engine, migrations = _client(tmp_path)
    (migrations / "V1__create_items.py").write_text(V1_PY)
    (migrations / "U1__drop_items.py").write_text(U1_PY)

    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    assert client.migrate().success
    assert _table_exists(engine, "items")

    undo_result = client.undo()
    assert undo_result.success, undo_result
    assert not _table_exists(engine, "items")
    client.close()


def test_python_undo_without_undo_script_fails_cleanly(tmp_path):
    engine, migrations = _client(tmp_path)
    (migrations / "V1__create_items.py").write_text(V1_PY)  # no U1__*.py

    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    assert client.migrate().success

    undo_result = client.undo()
    assert not undo_result.success
    assert "No undo script found" in (undo_result.error_message or "")
    client.close()


def test_python_undo_dry_run_show_sql_has_no_sql_statements(tmp_path):
    engine, migrations = _client(tmp_path)
    (migrations / "V1__create_items.py").write_text(V1_PY)
    (migrations / "U1__drop_items.py").write_text(U1_PY)

    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    assert client.migrate().success

    undo_result = client.undo(dry_run=True, show_sql=True)
    assert undo_result.success, undo_result
    assert _table_exists(engine, "items")  # dry run: nothing actually rolled back
    assert len(undo_result.sql) == 1
    assert undo_result.sql[0].statements == []
    client.close()


def test_inline_undo_in_versioned_py_is_ignored(tmp_path):
    engine, migrations = _client(tmp_path)
    # Versioned file carries a leftover inline undo() — must be ignored (hard break).
    (migrations / "V1__create_items.py").write_text(
        V1_PY + "\n\ndef undo(context):\n    context.execute('DROP TABLE items')\n"
    )
    # No U1__*.py present, so undo must fail rather than call the inline undo().
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    assert client.migrate().success

    undo_result = client.undo()
    assert not undo_result.success
    assert "No undo script found" in (undo_result.error_message or "")
    assert _table_exists(engine, "items")  # inline undo() did NOT run
    client.close()


def test_python_undo_dry_run_show_sql_requires_undo_script(tmp_path):
    engine, migrations = _client(tmp_path)
    (migrations / "V1__create_items.py").write_text(V1_PY)  # no U1__*.py

    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    assert client.migrate().success

    result = client.undo(dry_run=True, show_sql=True)
    assert not result.success
    assert "No undo script found" in (result.error_message or "")
    client.close()
