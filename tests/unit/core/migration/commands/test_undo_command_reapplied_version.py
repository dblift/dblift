"""Undo after a version has been undone and then re-applied.

The history keeps the ``UNDO_SQL`` row forever; a re-apply supersedes it by
recording the versioned migration again with a higher ``installed_rank``. If
that supersession is not recognised, ``undo`` treats the live version as still
undone and walks past it to an *older* version — undoing a migration the
operator never asked for.

These tests assert observable state: which table actually disappeared.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from api import DBLiftClient

V1_PY = """\
def migrate(context):
    context.execute("CREATE TABLE items (id INTEGER PRIMARY KEY)")
"""

U1_PY = """\
def migrate(context):
    context.execute("DROP TABLE items")
"""

V2_PY = """\
def migrate(context):
    context.execute("CREATE TABLE widgets (id INTEGER PRIMARY KEY)")
"""

U2_PY = """\
def migrate(context):
    context.execute("DROP TABLE widgets")
"""

V1_SQL = "CREATE TABLE items (id INTEGER PRIMARY KEY);"
U1_SQL = "DROP TABLE items;"
V2_SQL = "CREATE TABLE widgets (id INTEGER PRIMARY KEY);"
U2_SQL = "DROP TABLE widgets;"


def _table_exists(engine, name: str) -> bool:
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (name,)
        ).fetchall()
    return bool(rows)


def _setup(tmp_path: Path, suffix: str, bodies):
    from sqlalchemy import create_engine

    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for name, body in bodies.items():
        (migrations / f"{name}.{suffix}").write_text(body)
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    return engine, migrations


def _py_project(tmp_path: Path):
    return _setup(
        tmp_path,
        "py",
        {
            "V1__create_items": V1_PY,
            "U1__drop_items": U1_PY,
            "V2__create_widgets": V2_PY,
            "U2__drop_widgets": U2_PY,
        },
    )


def _sql_project(tmp_path: Path):
    return _setup(
        tmp_path,
        "sql",
        {
            "V1__create_items": V1_SQL,
            "U1__drop_items": U1_SQL,
            "V2__create_widgets": V2_SQL,
            "U2__drop_widgets": U2_SQL,
        },
    )


@pytest.mark.unit
@pytest.mark.parametrize("project", [_py_project, _sql_project], ids=["python", "sql"])
def test_reapplied_version_is_undone_again_not_the_previous_one(tmp_path, project):
    """apply -> undo -> re-apply -> undo must undo V2 again, never V1."""
    engine, migrations = project(tmp_path)
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        assert client.migrate().success
        assert client.undo().success
        assert not _table_exists(engine, "widgets")

        assert client.migrate().success
        assert _table_exists(engine, "widgets")

        result = client.undo()
        assert result.success, result.error_message

        # V2 was undone again; V1 was left alone.
        assert not _table_exists(engine, "widgets")
        assert _table_exists(engine, "items")
    finally:
        client.close()


@pytest.mark.unit
def test_genuinely_undone_version_falls_through_to_the_previous_one(tmp_path):
    """Without a re-apply, a second ``undo`` steps back to V1.

    This is the documented "undo the latest still-applied migration"
    behaviour and must survive the re-apply fix — the fall-through is only
    wrong when the eligibility verdict itself is wrong.
    """
    engine, migrations = _py_project(tmp_path)
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        assert client.migrate().success
        assert client.undo().success
        assert not _table_exists(engine, "widgets")
        assert _table_exists(engine, "items")

        assert client.undo().success
        assert not _table_exists(engine, "items")
    finally:
        client.close()


@pytest.mark.unit
def test_target_version_never_undoes_below_the_target(tmp_path):
    """``--target-version`` must never retarget a version at or below the target.

    Unlike the no-target scan, this path is bounded: it only considers
    versions strictly newer than the target, and refuses outright when one of
    them cannot be undone. With V2 already undone there is nothing left above
    V1, so V1 must survive.
    """
    engine, migrations = _py_project(tmp_path)
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    try:
        assert client.migrate().success
        assert client.undo().success  # V2 genuinely undone

        result = client.undo(target_version="1")
        assert result.undone_count == 0
        assert _table_exists(engine, "items")
    finally:
        client.close()
