"""``from_sqlalchemy(connection=...)``: callbacks persist and a failed read leaves the connection usable."""

from __future__ import annotations

import uuid
from urllib.parse import quote

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

pytestmark = pytest.mark.integration

CALLBACKS = ["beforeMigrate", "afterEachMigrate", "afterMigrate"]


def _url(config: dict, user: str = "", password: str = "") -> str:
    return (
        f"postgresql+psycopg://{quote(user or config['username'], safe='')}"
        f":{quote(password or config['password'], safe='')}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )


def run_callback_scenario(callback: str, url: str, tmp_path) -> None:
    """The callback's table exists once the caller has committed, whatever ran first."""
    schema = f"q_a_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / callback
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")
    (migrations / f"{callback}__cb.sql").write_text("CREATE TABLE cb (id integer);")

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
    try:
        with create_engine(url).connect() as conn:
            conn.execute(text("SELECT 1"))  # the connection has autobegun
            client = DBLiftClient.from_sqlalchemy(
                connection=conn, schema=schema, migrations_dir=migrations, logger=NullLog()
            )
            result = client.migrate()
            client.close()
            conn.commit()
        assert result.success, getattr(result, "error", None)
        with admin.connect() as conn:
            tables = (
                conn.execute(
                    text("SELECT tablename FROM pg_tables WHERE schemaname = :s ORDER BY 1"),
                    {"s": schema},
                )
                .scalars()
                .all()
            )
        assert "cb" in tables and "t" in tables, tables
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
        admin.dispose()


def run_failed_read_scenario(url: str, tmp_path) -> None:
    """A role that cannot read the history gets the real cause every time, keeping its own work."""
    uid = uuid.uuid4().hex[:8]
    schema, role, password = f"q_a_{uid}", f"q_a_reader_{uid}", f"Qa{uid}x1"
    migrations = tmp_path / "failed_read"
    migrations.mkdir()
    (migrations / "V1__t.sql").write_text("CREATE TABLE t (id integer);")

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f"CREATE ROLE {role} LOGIN PASSWORD '{password}'"))
        conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO {role}'))
    try:
        DBLiftClient.from_sqlalchemy(
            engine=admin, schema=schema, migrations_dir=migrations, logger=NullLog()
        ).migrate()
        with admin.connect() as conn:
            conn.execute(text(f'CREATE TABLE "{schema}".mine (id integer)'))
            conn.execute(text(f'GRANT INSERT, SELECT ON "{schema}".mine TO {role}'))
        config = _config_of(url)
        with create_engine(_url(config, role, password)).connect() as conn:
            conn.execute(text(f'INSERT INTO "{schema}".mine VALUES (1)'))
            client = DBLiftClient.from_sqlalchemy(
                connection=conn, schema=schema, migrations_dir=migrations, logger=NullLog()
            )
            for _ in range(2):
                message = client.info().error_message
                assert "permission denied" in message, message
                assert "aborted" not in message, message
            assert conn.execute(text(f'SELECT count(*) FROM "{schema}".mine')).scalar() == 1
            conn.rollback()
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            conn.execute(text(f"DROP ROLE IF EXISTS {role}"))
        admin.dispose()


def _config_of(url: str) -> dict:
    parsed = create_engine(url).url
    return {
        "host": parsed.host,
        "port": parsed.port,
        "database": parsed.database,
        "username": parsed.username,
        "password": parsed.password,
    }


@pytest.mark.parametrize("callback", CALLBACKS)
def test_callback_persists_on_a_caller_owned_connection(callback, postgresql_container, tmp_path):
    run_callback_scenario(callback, _url(postgresql_container), tmp_path)


def test_failed_history_read_leaves_the_caller_connection_usable(postgresql_container, tmp_path):
    run_failed_read_scenario(_url(postgresql_container), tmp_path)
