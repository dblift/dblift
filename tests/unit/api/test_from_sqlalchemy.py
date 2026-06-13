"""End-to-end tests for DBLiftClient.from_sqlalchemy (python-native integration)."""

import tempfile
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient
from config.errors import ConfigurationError


def test_from_sqlalchemy_migrate_sqlite(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'test.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    result = client.migrate()
    assert result.success
    client.close()
    # Engine still usable
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")


def test_from_sqlalchemy_in_memory_shares_database(tmp_path):
    """Regression: in-memory sqlite must migrate the caller's engine, not a copy.

    A native sqlite3 provider that opens its own ``sqlite3.connect(":memory:")``
    would migrate a *separate* database, so ``migrate()`` could report success
    while the caller's engine saw no schema changes.
    """
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine("sqlite:///:memory:")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    result = client.migrate()
    assert result.success
    client.close()
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='t'"
        ).fetchall()
        assert rows, "migration must be visible to the caller's engine"


def test_from_sqlalchemy_in_memory_context_manager_shares_database(tmp_path):
    """Regression: the ``with DBLiftClient.from_sqlalchemy(...)`` path.

    ``__enter__`` calls ``provider.create_connection()`` when ``is_connected()``
    is false; the native sqlite3 provider must not open a fresh connection that
    discards the injected engine (separate in-memory DB otherwise).
    """
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine("sqlite:///:memory:")
    with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations) as client:
        result = client.migrate()
        assert result.success
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='t'"
        ).fetchall()
        assert rows, "migration must be visible to the caller's engine"


def test_from_sqlalchemy_in_memory_connection_shares_database(tmp_path):
    """Regression: the ``connection=`` path must migrate the caller's connection."""
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine("sqlite:///:memory:")
    conn = engine.connect()
    client = DBLiftClient.from_sqlalchemy(connection=conn, migrations_dir=migrations)
    result = client.migrate()
    assert result.success
    rows = conn.exec_driver_sql(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='t'"
    ).fetchall()
    assert rows, "migration must be visible on the caller's connection"
    client.close()
    # Caller's connection is untouched by client.close()
    assert conn.exec_driver_sql("SELECT 1").scalar() == 1
    conn.close()


def test_from_sqlalchemy_engine_not_disposed(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'a.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=tmp_path)
    client.close()
    with engine.connect() as conn:
        conn.exec_driver_sql("SELECT 1")


def test_from_sqlalchemy_rejects_both_engine_and_connection():
    engine = create_engine("sqlite:///:memory:")
    conn = engine.connect()
    with pytest.raises(ConfigurationError):
        DBLiftClient.from_sqlalchemy(engine=engine, connection=conn)


def test_from_sqlalchemy_accepts_list_migrations_dir(tmp_path):
    """Regression: migrations_dir as a list must not raise during construction.

    config_from_engine previously wrote the raw value into migrations.directory,
    which DbliftConfig.from_dict parses as a string (TypeError on a list).
    """
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path / 'list.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=[migrations])
    result = client.migrate()
    assert result.success
    client.close()
    with engine.connect() as conn:
        rows = conn.exec_driver_sql(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='t'"
        ).fetchall()
        assert rows


def test_from_sqlalchemy_in_memory_rebinds_after_close(tmp_path):
    """Regression: reconnecting an external-connection provider must re-bind.

    After close() clears provider.connection (but keeps _external_connection),
    a later create_connection() must re-bind to the caller's engine rather than
    silently opening a fresh in-memory database.
    """
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__init.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine("sqlite:///:memory:")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations)
    client.close()
    with engine.connect() as conn:
        conn.exec_driver_sql("CREATE TABLE marker (x INTEGER)")
        conn.commit()
    client.provider.create_connection()
    rows = client.provider.execute_query(
        "SELECT name FROM sqlite_master WHERE type='table' AND name='marker'"
    )
    assert rows, "reconnected provider must see the caller engine's database"
