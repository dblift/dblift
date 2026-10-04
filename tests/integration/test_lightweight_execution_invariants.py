"""Live execution invariants for migration SQL and explicit undo scripts."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.db.plugins.postgresql.config import PostgreSqlConfig
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.plugins.sqlite.provider import SQLiteProvider
from tests.integration.helpers.migration_helper import create_versioned_migration

pytestmark = pytest.mark.integration


@pytest.fixture
def unique_postgresql_schema(request):
    """Use a UUID schema on a supplied service or the integration PG container."""
    if os.environ.get("DBLIFT_D4_PG_PASSWORD"):
        connection = {
            "host": os.environ.get("DBLIFT_D4_PG_HOST", "127.0.0.1"),
            "port": int(os.environ.get("DBLIFT_D4_PG_PORT", "5432")),
            "database": os.environ.get("DBLIFT_D4_PG_DATABASE", "testdb"),
            "username": os.environ.get("DBLIFT_D4_PG_USER", "postgres"),
            "password": os.environ["DBLIFT_D4_PG_PASSWORD"],
        }
    else:
        container = request.getfixturevalue("postgresql_container")
        connection = {
            key: container[key] for key in ("host", "port", "database", "username", "password")
        }

    schema = f"d4_{uuid.uuid4().hex[:12]}"

    def config_for(target_schema):
        return DbliftConfig(
            database=PostgreSqlConfig(
                type="postgresql",
                **connection,
                schema=target_schema,
            )
        )

    admin = PostgreSqlProvider(config_for("public"), NullLog())
    admin.create_connection()
    admin.execute_statement(f'CREATE SCHEMA "{schema}"')
    try:
        yield schema, admin, config_for
    finally:
        admin.execute_statement(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE')
        admin.close()


def _postgres_client(migrations, schema, config_for):
    config = config_for(schema)
    config.migrations.directory = str(migrations)
    provider = PostgreSqlProvider(config, NullLog())
    provider.create_connection()
    return DBLiftClient(provider, migrations, config=config, logger=NullLog()), provider


def test_sqlite_dry_run_sql_matches_driver_for_migrate_and_explicit_undo(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1__create_t.sql").write_text(
        "CREATE TABLE ${table_name} (id INTEGER PRIMARY KEY);"
    )
    (migrations / "U1__drop_t.sql").write_text("DROP TABLE ${table_name};")
    (migrations / "afterMigrate__seed.sql").write_text("INSERT INTO ${table_name} (id) VALUES (7);")
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations, logger=NullLog())
    sent = []
    execute_statement = client.provider.execute_statement

    def record(sql, schema=None, params=None):
        sent.append((sql, params))
        return execute_statement(sql, schema=schema, params=params)

    monkeypatch.setattr(client.provider, "execute_statement", record)
    placeholders = {"table_name": "d4_items"}
    try:
        preview = client.migrate(dry_run=True, show_sql=True, placeholders=placeholders)
        assert preview.success, preview.error_message
        migrate_preview = [sql for migration in preview.sql for sql in migration.statements]
        assert migrate_preview == ["CREATE TABLE d4_items (id INTEGER PRIMARY KEY);"]
        assert not sent

        applied = client.migrate(show_sql=True, placeholders=placeholders)
        assert applied.success, applied.error_message
        assert [sql for sql, _ in sent] == [
            *migrate_preview,
            "INSERT INTO d4_items (id) VALUES (7);",
        ]

        sent.clear()
        undo_preview = client.undo(dry_run=True, show_sql=True, placeholders=placeholders)
        assert undo_preview.success, undo_preview.error_message
        undo_sql = [sql for migration in undo_preview.sql for sql in migration.statements]
        assert undo_sql == ["DROP TABLE d4_items;"]
        assert not sent

        undone = client.undo(show_sql=True, placeholders=placeholders)
        assert undone.success, undone.error_message
        assert sent == [(undo_sql[0], None)]
        assert (
            client.provider.execute_query("SELECT name FROM sqlite_master WHERE name='d4_items'")
            == []
        )
    finally:
        client.close()
        engine.dispose()


def test_sqlite_comment_prefixed_pragma_changes_live_connection_state(tmp_path, monkeypatch):
    migrations = tmp_path / "migrations"
    create_versioned_migration(
        migrations, "1", "create_parent", "CREATE TABLE parent (id INTEGER PRIMARY KEY);"
    )
    create_versioned_migration(
        migrations, "2", "disable_fk", "-- temporarily off\nPRAGMA foreign_keys = OFF;"
    )
    config = DbliftConfig.from_dict(
        {"database": {"type": "sqlite", "path": str(tmp_path / "app.db"), "schema": "main"}}
    )
    provider = SQLiteProvider(config, NullLog())
    provider.create_connection()
    provider.execute_statement("PRAGMA foreign_keys = ON")
    assert provider.execute_query("PRAGMA foreign_keys")[0]["foreign_keys"] == 1
    sent_autocommit = []
    execute_autocommit = provider.execute_autocommit_statement

    def record(sql, schema=None, params=None):
        sent_autocommit.append(sql)
        return execute_autocommit(sql, schema=schema, params=params)

    monkeypatch.setattr(provider, "execute_autocommit_statement", record)
    client = DBLiftClient(provider, migrations, config=config, logger=NullLog())
    try:
        result = client.migrate()
        assert result.success, result.error_message
        assert sent_autocommit == ["-- temporarily off\nPRAGMA foreign_keys = OFF;"]
        assert provider.execute_query("PRAGMA foreign_keys")[0]["foreign_keys"] == 0
        applied = provider.get_applied_migrations("main")
        assert [row["script"] for row in applied] == [
            "V1__create_parent.sql",
            "V2__disable_fk.sql",
        ]
    finally:
        client.close()


def test_postgresql_comment_prefixed_concurrent_index_reaches_autocommit(
    unique_postgresql_schema, tmp_path, monkeypatch
):
    schema, admin, config_for = unique_postgresql_schema
    migrations = tmp_path / "migrations"
    create_versioned_migration(
        migrations, "1", "create_docs", f'CREATE TABLE "{schema}"."docs" (id INT PRIMARY KEY);'
    )
    create_versioned_migration(
        migrations,
        "2",
        "index_docs",
        f'-- online build\nCREATE INDEX CONCURRENTLY "ix_docs" ON "{schema}"."docs" (id);',
    )
    create_versioned_migration(
        migrations,
        "3",
        "fail_second",
        f'CREATE TABLE "{schema}"."later_first" (id INT);\n'
        f'CREATE TABLE "{schema}"."later_first" (id INT);\n'
        f'CREATE TABLE "{schema}"."later_never" (id INT);',
    )
    client, provider = _postgres_client(migrations, schema, config_for)
    sent_autocommit = []
    sent = []
    execute_autocommit = provider.execute_autocommit_statement
    execute_statement = provider.execute_statement

    def record_autocommit(sql, schema=None, params=None):
        sent_autocommit.append((sql, params))
        return execute_autocommit(sql, schema=schema, params=params)

    def record_statement(sql, schema=None, params=None):
        sent.append(sql)
        return execute_statement(sql, schema=schema, params=params)

    monkeypatch.setattr(provider, "execute_autocommit_statement", record_autocommit)
    monkeypatch.setattr(provider, "execute_statement", record_statement)
    try:
        applied = client.migrate(target_version="2")
        assert applied.success, applied.error_message
        assert len(sent_autocommit) == 1
        assert sent_autocommit[0][0] == (
            f'CREATE INDEX CONCURRENTLY "ix_docs" ON "{schema}"."docs" (id);'
        )
        assert sent_autocommit[0][1] is None
        rows = admin.execute_query(
            "SELECT indexname FROM pg_indexes WHERE schemaname = ? AND indexname = ?",
            [schema, "ix_docs"],
        )
        assert rows == [{"indexname": "ix_docs"}]
        failed = client.migrate()
        assert not failed.success
        assert not any('"later_never"' in sql for sql in sent)
        tables = admin.execute_query(
            "SELECT tablename FROM pg_tables WHERE schemaname = ? AND tablename IN (?, ?)",
            [schema, "later_first", "later_never"],
        )
        assert tables == []
        assert admin.execute_query(
            "SELECT indexname FROM pg_indexes WHERE schemaname = ? AND indexname = ?",
            [schema, "ix_docs"],
        ) == [{"indexname": "ix_docs"}]
        history = admin.execute_query(
            f'SELECT script, success FROM "{schema}"."dblift_schema_history" ORDER BY installed_rank'
        )
        assert history == [
            {"script": "V1__create_docs.sql", "success": True},
            {"script": "V2__index_docs.sql", "success": True},
            {"script": "V3__fail_second.sql", "success": False},
        ]
        contender = PostgreSqlProvider(config_for(schema), NullLog())
        contender.create_connection()
        try:
            assert contender.acquire_migration_lock(schema, wait_timeout_seconds=1)
            assert contender.release_migration_lock(schema)
        finally:
            contender.close()
    finally:
        client.close()


def test_postgresql_failed_callback_rolls_back_and_skips_migration(
    unique_postgresql_schema, tmp_path, monkeypatch
):
    schema, admin, config_for = unique_postgresql_schema
    migrations = tmp_path / "migrations"
    create_versioned_migration(
        migrations, "1", "never_run", f'CREATE TABLE "{schema}"."user_never" (id INT);'
    )
    (migrations / "beforeMigrate__fail.sql").write_text(
        f'CREATE TABLE "{schema}"."callback_first" (id INT);\n'
        f'CREATE TABLE "{schema}"."callback_first" (id INT);\n'
        f'CREATE TABLE "{schema}"."callback_never" (id INT);'
    )
    client, provider = _postgres_client(migrations, schema, config_for)
    sent = []
    execute_statement = provider.execute_statement

    def record(sql, schema=None, params=None):
        sent.append(sql)
        return execute_statement(sql, schema=schema, params=params)

    monkeypatch.setattr(provider, "execute_statement", record)
    try:
        result = client.migrate()
        assert not result.success
        assert not any('"callback_never"' in sql or '"user_never"' in sql for sql in sent)
        tables = admin.execute_query(
            "SELECT tablename FROM pg_tables WHERE schemaname = ? AND tablename LIKE ?",
            [schema, "%never%"],
        )
        assert tables == []
        callback_first = admin.execute_query(
            "SELECT tablename FROM pg_tables WHERE schemaname = ? AND tablename = ?",
            [schema, "callback_first"],
        )
        assert callback_first == []
        contender = PostgreSqlProvider(config_for(schema), NullLog())
        contender.create_connection()
        try:
            assert contender.acquire_migration_lock(schema, wait_timeout_seconds=1)
            assert contender.release_migration_lock(schema)
        finally:
            contender.close()
    finally:
        client.close()
