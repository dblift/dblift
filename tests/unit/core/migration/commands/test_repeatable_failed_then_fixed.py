"""A repeatable migration whose last run failed is retried once its file is fixed."""

from __future__ import annotations

import sqlite3

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]

FAILING = "INSERT INTO missing_table VALUES (1);\n"
FIXED = "DROP VIEW IF EXISTS v;\nCREATE VIEW v AS SELECT * FROM t;\n"


@pytest.fixture
def env(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    database = tmp_path / "app.db"
    engines = []

    def new_client():
        engine = create_engine(f"sqlite:///{database}")
        engines.append(engine)
        return DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))

    def history():
        with sqlite3.connect(database) as conn:
            return conn.execute(
                "select script, success, checksum from dblift_schema_history "
                "order by installed_rank"
            ).fetchall()

    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER);\n")
    yield new_client, migrations, history
    for engine in engines:
        engine.dispose()


def _fail_first_run(new_client, migrations):
    (migrations / "R__v.sql").write_text(FAILING)
    client = new_client()
    try:
        assert client.migrate().success is False
    finally:
        client.close()


def test_failed_repeatable_runs_after_fix(env):
    new_client, migrations, history = env
    _fail_first_run(new_client, migrations)
    (migrations / "R__v.sql").write_text(FIXED)

    client = new_client()
    try:
        assert client.validate().success
    finally:
        client.close()

    client = new_client()
    try:
        result = client.migrate()
    finally:
        client.close()

    assert result.success, result.error_message
    assert "R__v.sql" in [m.script for m in result.migrations]
    latest = [row for row in history() if row[0] == "R__v.sql"][-1]
    assert bool(latest[1]) is True


def test_failed_unchanged_repeatable_refused(env):
    new_client, migrations, history = env
    _fail_first_run(new_client, migrations)
    rows_before = history()

    client = new_client()
    try:
        validation = client.validate()
    finally:
        client.close()
    assert validation.success is False
    assert (
        "Repeatable migration R__v.sql previously failed and has not changed. "
        "Please fix the script before retrying."
    ) in (validation.error_message or "")

    client = new_client()
    try:
        result = client.migrate()
    finally:
        client.close()
    assert [m.script for m in result.migrations if m.script == "R__v.sql"] == []
    assert history() == rows_before


def test_build_state_public_surface_unchanged(env):
    new_client, migrations, history = env
    (migrations / "V2__u.sql").write_text("CREATE TABLE u (id INTEGER);\n")
    (migrations / "R__unchanged.sql").write_text(
        "DROP VIEW IF EXISTS a;\nCREATE VIEW a AS SELECT 1;\n"
    )
    (migrations / "R__changed.sql").write_text(
        "DROP VIEW IF EXISTS b;\nCREATE VIEW b AS SELECT 1;\n"
    )
    client = new_client()
    try:
        assert client.migrate().success
    finally:
        client.close()

    # V3 and R__new have never run; R__changed was edited after it ran; R__unchanged was not.
    (migrations / "V3__w.sql").write_text("CREATE TABLE w (id INTEGER);\n")
    (migrations / "R__new.sql").write_text("DROP VIEW IF EXISTS c;\nCREATE VIEW c AS SELECT 1;\n")
    (migrations / "R__changed.sql").write_text(
        "DROP VIEW IF EXISTS b;\nCREATE VIEW b AS SELECT 2;\n"
    )

    client = new_client()
    try:
        executor = client.executor
        state = executor.state_manager.build_state(scripts_dir=migrations)
    finally:
        client.close()

    assert sorted(m.script_name for m in state.executable_pending_objects()) == [
        "R__changed.sql",
        "R__new.sql",
        "V3__w.sql",
    ]
