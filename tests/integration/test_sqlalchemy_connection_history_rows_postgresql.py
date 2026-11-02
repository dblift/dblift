"""``from_sqlalchemy(connection=...)``: a history row dblift writes survives the next boundary."""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

pytestmark = pytest.mark.integration


def _url(config: dict) -> str:
    return (
        f"postgresql+psycopg://{config['username']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )


def _client(conn, schema, migrations):
    return DBLiftClient.from_sqlalchemy(
        connection=conn, schema=schema, migrations_dir=migrations, logger=NullLog()
    )


def _history(admin, schema: str) -> list:
    with admin.connect() as conn:
        rows = conn.execute(
            text(
                f'SELECT version, success FROM "{schema}".dblift_schema_history '
                "ORDER BY installed_rank"
            )
        ).all()
    return [(row[0], bool(row[1])) for row in rows]


def run_baseline_then_migrate_scenario(url: str, tmp_path) -> None:
    """``baseline`` then ``migrate`` on one connection, no commit between: both rows are kept."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "baseline_migrate"
    migrations.mkdir()
    (migrations / "V1__a.sql").write_text("CREATE TABLE a (id integer);")
    (migrations / "V2__b.sql").write_text("CREATE TABLE b (id integer);")
    (migrations / "V3__c.sql").write_text("CREATE TABLE c (id integer);")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with create_engine(url).connect() as conn:
            client = _client(conn, schema, migrations)
            baselined = client.baseline(version="2", description="bl")
            migrated = client.migrate()
            client.close()
            conn.commit()
        assert baselined.success and migrated.success, (baselined, migrated)
        assert _history(admin, schema) == [("2", True), ("3", True)], _history(admin, schema)
        with create_engine(url).connect() as conn:
            pending = _client(conn, schema, migrations).info().pending_migrations
            conn.rollback()
        assert not pending, pending
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def _full_history(admin, schema: str) -> list:
    with admin.connect() as conn:
        rows = conn.execute(
            text(
                f'SELECT version, type, success, checksum FROM "{schema}".dblift_schema_history '
                "ORDER BY installed_rank"
            )
        ).all()
    return [tuple(row) for row in rows]


def _sibling_history(url: str, tmp_path, name: str, commit_between: bool) -> list:
    """History after a command then ``migrate`` on one connection (``V3`` is added in between)."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / f"{name}_{int(commit_between)}"
    migrations.mkdir()
    (migrations / "V1__a.sql").write_text("CREATE TABLE a (id integer);")
    (migrations / "V2__b.sql").write_text(
        "CREATE TABLE b (id integer);" if name != "repair_failed" else "CREATE TABLE b (;"
    )
    (migrations / "U2__b.sql").write_text("DROP TABLE b;")
    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        if name != "mark_as_executed":
            DBLiftClient.from_sqlalchemy(
                engine=admin, schema=schema, migrations_dir=migrations, logger=NullLog()
            ).migrate()
        if name == "repair_failed":
            (migrations / "V2__b.sql").write_text("CREATE TABLE b (id integer);")
        elif name == "repair_checksum":
            (migrations / "V1__a.sql").write_text("CREATE TABLE a (id integer, v integer);")
        with create_engine(url).connect() as conn:
            client = _client(conn, schema, migrations)
            first = {
                "undo": lambda: client.undo(target_version="1"),
                "mark_as_executed": lambda: client.migrate(mark_as_executed=True),
                "clean": lambda: client.clean(clean_enabled=True),
            }.get(name, client.repair)()
            if commit_between:
                conn.commit()
            (migrations / "V3__c.sql").write_text("CREATE TABLE c (id integer);")
            migrated = client.migrate()
            client.close()
            conn.commit()
        assert first.success and migrated.success, (name, first, migrated)
        return _full_history(admin, schema)
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_sibling_scenario(name: str, url: str, tmp_path) -> None:
    """A command then ``migrate``: the same history with or without a commit between."""
    expected = _sibling_history(url, tmp_path, name, commit_between=True)
    history = _sibling_history(url, tmp_path, name, commit_between=False)
    assert history == expected, (history, expected)


def test_baseline_then_migrate_keeps_the_baseline_row(postgresql_container, tmp_path):
    run_baseline_then_migrate_scenario(_url(postgresql_container), tmp_path)


@pytest.mark.parametrize(
    "name", ["repair_failed", "repair_checksum", "undo", "mark_as_executed", "clean"]
)
def test_command_then_migrate_keeps_the_history(name, postgresql_container, tmp_path):
    run_sibling_scenario(name, _url(postgresql_container), tmp_path)
