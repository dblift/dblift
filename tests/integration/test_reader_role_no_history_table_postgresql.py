"""A role that cannot create the history table is told it does not exist.

With USAGE on the schema and no history table, ``info`` and ``migrate --dry-run`` listed
every migration as Pending and a schema version of none, with nothing to say that no
migration was ever applied there.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

pytestmark = pytest.mark.integration


def _url(config: dict, username: str | None = None, password: str | None = None) -> str:
    return (
        f"postgresql+psycopg://{username or config['username']}:{password or config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )


def _client(url: str, schema: str, migrations):
    return DBLiftClient.from_sqlalchemy(
        create_engine(url), schema=schema, migrations_dir=migrations, logger=NullLog()
    )


def run_scenario(url: str, reader_url_for, tmp_path) -> None:
    """``url`` is an admin URL; ``reader_url_for(role, password)`` the same server as ``role``."""
    uid = uuid.uuid4().hex[:8]
    schema, role, password = f"q_nohist_{uid}", f"q_reader_{uid}", "ReaderPass123"
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__t1.sql").write_text(f'CREATE TABLE "{schema}".t1 (id integer);')

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'"))
        conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
    try:
        reader_url = reader_url_for(role, password)

        for operation in ("info", "migrate"):
            client = _client(reader_url, schema, migrations)
            try:
                result = client.info() if operation == "info" else client.migrate(dry_run=True)
            finally:
                client.close()
            assert result.success, result.error_message
            assert result.history_table_exists is False
            assert [m.status for m in result.migrations] == ["PENDING"]

        # The reads created nothing.
        with admin.connect() as conn:
            assert (
                conn.execute(
                    text("SELECT to_regclass(:name)"), {"name": f'"{schema}".dblift_schema_history'}
                ).scalar()
                is None
            )

        # Once the history table exists, the same role is no longer told it is missing.
        applied = _client(url, schema, migrations)
        try:
            assert applied.migrate().success
        finally:
            applied.close()
        with admin.connect() as conn:
            conn.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
        client = _client(reader_url, schema, migrations)
        try:
            info = client.info()
        finally:
            client.close()
        assert info.success, info.error_message
        assert info.history_table_exists is True
        assert {m.status for m in info.migrations} == {"SUCCESS"}
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        admin.dispose()


def test_role_without_create_is_told_the_history_table_is_missing(postgresql_container, tmp_path):
    run_scenario(
        _url(postgresql_container),
        lambda role, password: _url(postgresql_container, role, password),
        tmp_path,
    )
