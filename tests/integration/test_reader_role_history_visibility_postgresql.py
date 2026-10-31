"""A role that cannot read the history table gets an error, not an empty history.

``information_schema.tables`` lists only tables the role holds a privilege on, so
a history table without SELECT used to read as absent: ``info`` exited 0 with
every migration Pending and ``migrate --dry-run`` offered to apply them all.
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


def _reader_client(url: str, schema: str, migrations):
    return DBLiftClient.from_sqlalchemy(
        create_engine(url), schema=schema, migrations_dir=migrations, logger=NullLog()
    )


def run_scenario(url: str, reader_url_for, tmp_path) -> None:
    """``url`` is an admin URL; ``reader_url_for(role, password)`` the same server as ``role``."""
    uid = uuid.uuid4().hex[:8]
    schema, role, password = f"q_hist_{uid}", f"q_reader_{uid}", "ReaderPass123"
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    for version in (1, 2, 3):
        (migrations / f"V{version}__t{version}.sql").write_text(
            f'CREATE TABLE "{schema}".t{version} (id integer);'
        )

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        conn.execute(text(f"CREATE ROLE \"{role}\" LOGIN PASSWORD '{password}'"))
        conn.execute(text(f'GRANT USAGE ON SCHEMA "{schema}" TO "{role}"'))
    try:
        applied = DBLiftClient.from_sqlalchemy(
            create_engine(url), schema=schema, migrations_dir=migrations, logger=NullLog()
        )
        assert applied.migrate().success
        applied.close()

        reader_url = reader_url_for(role, password)

        # Usage on the schema, but no SELECT on the history table.
        reader = _reader_client(reader_url, schema, migrations)
        try:
            info = reader.info()
            dry_run = reader.migrate(dry_run=True)
        finally:
            reader.close()
        for result in (info, dry_run):
            assert not result.success
            assert "permission denied" in result.error_message
        assert not getattr(dry_run, "migrations", None)

        # With SELECT, the same role reads the real history.
        with admin.connect() as conn:
            conn.execute(text(f'GRANT SELECT ON ALL TABLES IN SCHEMA "{schema}" TO "{role}"'))
        reader = _reader_client(reader_url, schema, migrations)
        try:
            info = reader.info()
        finally:
            reader.close()
        assert info.success, info.error_message
        assert {m.status for m in info.migrations} == {"SUCCESS"}
        assert info.current_schema_version == "3"
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            conn.execute(text(f'DROP OWNED BY "{role}"'))
            conn.execute(text(f'DROP ROLE IF EXISTS "{role}"'))
        admin.dispose()


def test_role_without_select_on_history_table_gets_an_error(postgresql_container, tmp_path):
    run_scenario(
        _url(postgresql_container),
        lambda role, password: _url(postgresql_container, role, password),
        tmp_path,
    )
