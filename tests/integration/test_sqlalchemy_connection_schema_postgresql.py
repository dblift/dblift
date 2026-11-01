"""``from_sqlalchemy(connection=...)`` migrates the configured PostgreSQL schema.

dblift never commits on a caller-owned connection, so its own rollback undoes the
``SET search_path``. Scenarios vary the first unit: DDL, CIC, Python, a query.
"""

from __future__ import annotations

import uuid

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog

pytestmark = pytest.mark.integration

SCENARIOS = ["ddl_then_cic", "cic_first", "python_first", "select_first"]


def _url(config: dict) -> str:
    return (
        f"postgresql+psycopg://{config['username']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )


def _write_migrations(name: str, migrations, table: str, index: str) -> list:
    """Write the scenario's files; return the versions expected in the history."""
    if name == "ddl_then_cic":
        (migrations / "V1__table.sql").write_text(f"CREATE TABLE {table} (id integer);")
        (migrations / "V2__index.sql").write_text(
            f"CREATE INDEX CONCURRENTLY {index} ON {table} (id);"
        )
        return ["1", "2"]
    if name == "cic_first":
        (migrations / "V1__index.sql").write_text(
            f"CREATE INDEX CONCURRENTLY {index} ON {table} (id);"
        )
    elif name == "python_first":
        (migrations / "V1__table.py").write_text(
            f'def migrate(context):\n    context.execute("CREATE TABLE {table} (id integer)")\n'
        )
    else:
        (migrations / "V1__select_then_table.sql").write_text(
            f"SELECT count(*) FROM {table} WHERE id = 1;\nCREATE TABLE {table}_new (id integer);"
        )
    return ["1"]


def run_scenario(name: str, url: str, tmp_path) -> None:
    uid = uuid.uuid4().hex[:8]
    schema, table, index = f"q_conn_{uid}", f"w_{uid}", f"ix_{uid}"
    migrations = tmp_path / name
    migrations.mkdir()
    versions = _write_migrations(name, migrations, table, index)

    admin = create_engine(url, isolation_level="AUTOCOMMIT")
    with admin.connect() as conn:
        conn.execute(text(f'CREATE SCHEMA "{schema}"'))
        if name in ("cic_first", "select_first"):
            conn.execute(text(f'CREATE TABLE "{schema}".{table} (id integer)'))
        if name == "select_first":
            conn.execute(text(f'INSERT INTO "{schema}".{table} VALUES (1)'))
        if name != "cic_first":
            # A same-named table on the default path makes a misresolved name
            # loud: its columns differ from the configured schema's table.
            conn.execute(text(f"CREATE TABLE public.{table} (other integer)"))
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
            tables = (
                conn.execute(
                    text("SELECT schemaname FROM pg_tables WHERE tablename LIKE :p ORDER BY 1"),
                    {"p": f"{table}%"},
                )
                .scalars()
                .all()
            )
            indexes = (
                conn.execute(
                    text("SELECT schemaname FROM pg_indexes WHERE indexname = :i"), {"i": index}
                )
                .scalars()
                .all()
            )
            history = (
                conn.execute(
                    text(
                        f'SELECT version FROM "{schema}".dblift_schema_history '
                        "WHERE success ORDER BY installed_rank"
                    )
                )
                .scalars()
                .all()
            )
        assert history == versions, history
        expected_tables = {
            "ddl_then_cic": [schema, "public"],
            "cic_first": [schema],
            "python_first": [schema, "public"],
            "select_first": [schema, "public", schema],
        }[name]
        assert sorted(tables) == sorted(expected_tables), tables
        if name in ("ddl_then_cic", "cic_first"):
            assert indexes == [schema], indexes
        if name == "select_first":
            with admin.connect() as conn:
                new_schema = (
                    conn.execute(
                        text("SELECT schemaname FROM pg_tables WHERE tablename = :t"),
                        {"t": f"{table}_new"},
                    )
                    .scalars()
                    .all()
                )
            assert new_schema == [schema], new_schema
    finally:
        with admin.connect() as conn:
            conn.execute(text(f'DROP SCHEMA "{schema}" CASCADE'))
            conn.execute(text(f"DROP TABLE IF EXISTS public.{table}"))
        admin.dispose()


def run_scenarios(url: str, tmp_path) -> None:
    for name in SCENARIOS:
        run_scenario(name, url, tmp_path)


@pytest.mark.parametrize("name", SCENARIOS)
def test_from_sqlalchemy_connection_migrates_configured_schema(
    name, postgresql_container, tmp_path
):
    run_scenario(name, _url(postgresql_container), tmp_path)
