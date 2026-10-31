"""``from_sqlalchemy(connection=...)`` must migrate the configured PostgreSQL schema.

A ``SET search_path`` issued on a caller-owned connection is never committed
by dblift, so the provider's defensive rollback before each migration undoes
it. Objects then land on the server's default path (``public``) while the
history table, which is schema-qualified, lands in the configured schema.
Both the transactional path and the autocommit path (``CREATE INDEX
CONCURRENTLY``) are pinned: each resolves names on its own connection state.
"""

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


def run_connection_schema_scenario(url: str, tmp_path) -> None:
    """Shared body so the same scenario can run against any PostgreSQL."""
    schema = f"q_conn_{uuid.uuid4().hex[:8]}"
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__table.sql").write_text("CREATE TABLE widgets (id integer);")
    (migrations / "V2__index.sql").write_text(
        "CREATE INDEX CONCURRENTLY ix_widgets_id ON widgets (id);"
    )

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        # A decoy on the default path: an unqualified name that resolves
        # there instead of in the configured schema is the defect.
        conn.execute(text("CREATE TABLE IF NOT EXISTS public.widgets (id integer)"))
    try:
        engine = create_engine(url)
        with engine.connect() as conn:
            client = DBLiftClient.from_sqlalchemy(
                connection=conn, schema=schema, migrations_dir=migrations, logger=NullLog()
            )
            result = client.migrate()
            client.close()
        assert result.success, getattr(result, "error", None)

        with admin.connect() as conn:
            table_schemas = (
                conn.execute(text("SELECT schemaname FROM pg_tables WHERE tablename = 'widgets'"))
                .scalars()
                .all()
            )
            index_schemas = (
                conn.execute(
                    text("SELECT schemaname FROM pg_indexes WHERE indexname = 'ix_widgets_id'")
                )
                .scalars()
                .all()
            )
            history = conn.execute(
                text(
                    f'SELECT version, success FROM "{schema}".dblift_schema_history '
                    "ORDER BY installed_rank"
                )
            ).all()
        assert sorted(table_schemas) == sorted(["public", schema]), table_schemas
        assert index_schemas == [schema], index_schemas
        assert [(row[0], row[1]) for row in history] == [("1", True), ("2", True)], history
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            conn.execute(text("DROP TABLE IF EXISTS public.widgets"))
        admin.dispose()


def test_from_sqlalchemy_connection_migrates_configured_schema(postgresql_container, tmp_path):
    run_connection_schema_scenario(_url(postgresql_container), tmp_path)
