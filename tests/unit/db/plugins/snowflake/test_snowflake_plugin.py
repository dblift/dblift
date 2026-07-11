"""Snowflake provider plugin contract."""

from types import SimpleNamespace
from typing import Any

import pytest
from sqlalchemy.engine import make_url

from config.database_config import BaseDatabaseConfig
from db.plugins.snowflake.config import SnowflakeConfig
from db.plugins.snowflake.plugin import PLUGIN as SNOWFLAKE_PLUGIN
from db.plugins.snowflake.provider import (
    SnowflakeProvider,
    _is_lock_timeout_error,
)
from db.plugins.snowflake.quirks import SnowflakeQuirks
from db.provider_registry import ProviderRegistry
from db.sqlalchemy_provider import SqlAlchemyProvider


class _DriverError(Exception):
    def __init__(self, message: str, raw_msg: str | None = None) -> None:
        super().__init__(message)
        self.raw_msg = raw_msg


class _FakeTransaction:
    def __init__(
        self,
        commit_error: Exception | None = None,
        rollback_error: Exception | None = None,
    ) -> None:
        self.commit_error = commit_error
        self.rollback_error = rollback_error
        self.committed = False
        self.rolled_back = False

    def commit(self) -> None:
        self.committed = True
        if self.commit_error:
            raise self.commit_error

    def rollback(self) -> None:
        self.rolled_back = True
        if self.rollback_error:
            raise self.rollback_error


class _FakeConnection:
    def __init__(
        self,
        transaction: _FakeTransaction | None = None,
        fail_on: str | None = None,
        error: Exception | None = None,
    ) -> None:
        self.transaction = transaction or _FakeTransaction()
        self.fail_on = fail_on
        self.error = error or RuntimeError("lock timeout")
        self.sql: list[str] = []
        self.committed = False
        self.rolled_back = False
        self.closed = False

    def exec_driver_sql(self, sql: str) -> None:
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise self.error

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def begin(self) -> _FakeTransaction:
        return self.transaction

    def close(self) -> None:
        self.closed = True


class _FakeEngine:
    def __init__(self, connection: _FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> _FakeConnection:
        return self.connection


class _SnowflakeProvider(SnowflakeProvider):
    def __init__(
        self,
        query_handler: Any | None = None,
        statement_result: int = 1,
        engine: _FakeEngine | None = None,
    ) -> None:
        self.query_handler = query_handler
        self.statement_result = statement_result
        self.fake_engine = engine
        self.queries: list[tuple[str, object]] = []
        self.statements: list[tuple[str, object, object]] = []
        self._migration_lock_connection = None
        self._migration_lock_transaction = None

    @property
    def engine(self) -> _FakeEngine:
        if self.fake_engine is None:
            raise AssertionError("engine is not configured")
        return self.fake_engine

    def execute_query(self, sql, params=None):
        self.queries.append((sql, params))
        if self.query_handler:
            return self.query_handler(sql, params)
        return []

    def execute_statement(self, sql, schema=None, params=None):
        self.statements.append((sql, schema, params))
        return self.statement_result


@pytest.fixture
def _reset_registry():
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_quirks_cache = dict(ProviderRegistry._quirks_cache)
    saved_discovered = ProviderRegistry._discovered
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._quirks_cache.clear()
    ProviderRegistry._quirks_cache.update(saved_quirks_cache)
    ProviderRegistry._discovered = saved_discovered


def test_snowflake_plugin_metadata() -> None:
    assert SNOWFLAKE_PLUGIN.name == "snowflake"
    assert SNOWFLAKE_PLUGIN.dialects == ["snowflake"]
    assert SNOWFLAKE_PLUGIN.config_class is SnowflakeConfig
    assert SNOWFLAKE_PLUGIN.quirks_class is SnowflakeQuirks
    assert SNOWFLAKE_PLUGIN.native_driver_module == "snowflake.connector"
    assert SNOWFLAKE_PLUGIN.sqlalchemy_url_builder is not None
    assert issubclass(SNOWFLAKE_PLUGIN.provider_class, SqlAlchemyProvider)
    assert SNOWFLAKE_PLUGIN.provider_class is SnowflakeProvider


def test_snowflake_config_preserves_session_context(_reset_registry) -> None:
    ProviderRegistry._plugins["snowflake"] = SNOWFLAKE_PLUGIN
    ProviderRegistry._discovered = True

    cfg = BaseDatabaseConfig.create(
        {
            "type": "snowflake",
            "account": "xy12345.us-east-1",
            "username": "tempuser",
            "password": "TempUser!2026",
            "database": "ANALYTICS",
            "schema": "PUBLIC",
            "warehouse": "COMPUTE_WH",
            "role": "ANALYST",
        }
    )

    assert isinstance(cfg, SnowflakeConfig)
    assert cfg.type == "snowflake"
    assert cfg.account == "xy12345.us-east-1"
    assert cfg.database == "ANALYTICS"
    assert cfg.schema == "PUBLIC"
    assert cfg.warehouse == "COMPUTE_WH"
    assert cfg.role == "ANALYST"


def test_snowflake_config_hydrates_account_and_schema_from_url_path(
    _reset_registry,
) -> None:
    ProviderRegistry._plugins["snowflake"] = SNOWFLAKE_PLUGIN
    ProviderRegistry._discovered = True
    snowflake_url = "snowflake://tempuser:TempUser%212026@xy12345.us-east-1"

    cfg = SnowflakeConfig(
        type="snowflake",
        url=f"{snowflake_url}/ANALYTICS/PUBLIC",
        host="xy12345.us-east-1",
        username="tempuser",
        password="TempUser!2026",
        database="ANALYTICS/PUBLIC",
        warehouse="COMPUTE_WH",
        role="ANALYST",
        authenticator="externalbrowser",
        extra_params={"client_session_keep_alive": "true"},
    )

    assert cfg.account == "xy12345.us-east-1"
    assert cfg.database == "ANALYTICS"
    assert cfg.schema == "PUBLIC"
    assert cfg.build_connection_string() == cfg.build_database_url()

    data = cfg.to_dict()
    assert data["account"] == "xy12345.us-east-1"
    assert data["warehouse"] == "COMPUTE_WH"
    assert data["role"] == "ANALYST"
    assert data["authenticator"] == "externalbrowser"

    props = cfg.get_connection_props()
    assert props["loginTimeout"] == "30"
    assert props["client_session_keep_alive"] == "true"
    assert props["account"] == "xy12345.us-east-1"
    assert props["warehouse"] == "COMPUTE_WH"
    assert props["role"] == "ANALYST"
    assert props["authenticator"] == "externalbrowser"


def test_snowflake_config_requires_account_or_url(_reset_registry) -> None:
    ProviderRegistry._plugins["snowflake"] = SNOWFLAKE_PLUGIN
    ProviderRegistry._discovered = True

    with pytest.raises(ValueError, match="Snowflake requires url or account"):
        BaseDatabaseConfig.create(
            {
                "type": "snowflake",
                "username": "tempuser",
                "password": "TempUser!2026",
                "database": "ANALYTICS",
                "schema": "PUBLIC",
            }
        )


def test_snowflake_builds_url_from_account_fields(_reset_registry) -> None:
    ProviderRegistry._plugins["snowflake"] = SNOWFLAKE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="snowflake",
        account="xy12345.us-east-1",
        username="tempuser",
        password="TempUser!2026",
        database="ANALYTICS",
        schema="PUBLIC",
        warehouse="COMPUTE_WH",
        role="ANALYST",
        authenticator=None,
        extra_params={},
        options={},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "snowflake"
    assert url.username == "tempuser"
    assert url.password == "TempUser!2026"
    assert url.host == "xy12345.us-east-1"
    assert url.database == "ANALYTICS/PUBLIC"
    assert dict(url.query) == {
        "warehouse": "COMPUTE_WH",
        "role": "ANALYST",
    }


def test_snowflake_builds_url_from_host_and_query_options(
    _reset_registry,
) -> None:
    ProviderRegistry._plugins["snowflake"] = SNOWFLAKE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="snowflake",
        account=None,
        host="xy12345.us-east-1",
        username="tempuser",
        password="TempUser!2026",
        database="ANALYTICS",
        schema="",
        warehouse=None,
        role=None,
        authenticator="externalbrowser",
        extra_params=None,
        options={"client_session_keep_alive": True},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.host == "xy12345.us-east-1"
    assert url.database == "ANALYTICS"
    assert dict(url.query) == {
        "authenticator": "externalbrowser",
        "client_session_keep_alive": "True",
    }


def test_snowflake_url_overrides_credentials(_reset_registry) -> None:
    ProviderRegistry._plugins["snowflake"] = SNOWFLAKE_PLUGIN
    ProviderRegistry._discovered = True
    raw_url = "snowflake://stale:old@xy12345.us-east-1/ANALYTICS/PUBLIC"
    database_config = SimpleNamespace(
        type="snowflake",
        url=raw_url,
        username="tempuser",
        password="TempUser!2026",
        warehouse="COMPUTE_WH",
        role="ANALYST",
        authenticator=None,
        extra_params={},
        options={},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "snowflake"
    assert url.username == "tempuser"
    assert url.password == "TempUser!2026"
    assert url.host == "xy12345.us-east-1"
    assert url.database == "ANALYTICS/PUBLIC"
    assert dict(url.query) == {
        "warehouse": "COMPUTE_WH",
        "role": "ANALYST",
    }


def test_snowflake_rejects_non_snowflake_raw_url(_reset_registry) -> None:
    ProviderRegistry._plugins["snowflake"] = SNOWFLAKE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="snowflake",
        url="postgresql://user:password@localhost/app",
        username="tempuser",
        password="TempUser!2026",
        account="xy12345.us-east-1",
        warehouse=None,
        role=None,
        authenticator=None,
        extra_params={},
        options={},
    )

    with pytest.raises(ValueError, match="snowflake:// URL"):
        ProviderRegistry.build_sqlalchemy_url(database_config)


def test_snowflake_quirks_connection_identifier_variants() -> None:
    quirks = SnowflakeQuirks()

    assert quirks.has_connection_identifier({"host": "xy12345.us-east-1"})
    assert quirks.has_connection_identifier(
        SimpleNamespace(url="", account=None, host="xy12345.us-east-1")
    )
    assert not quirks.has_connection_identifier({"url": " ", "account": ""})
    assert quirks.ddl_generator_class() is None
    assert quirks.alter_generator_class() is None
    assert quirks.introspector_class() is None
    assert quirks.vendor_queries_class() is None


def test_snowflake_history_table_uses_autoincrement_not_serial() -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    ddl = provider.create_history_table("app", "dblift_schema_history")

    assert '"APP"."DBLIFT_SCHEMA_HISTORY"' in ddl
    assert "AUTOINCREMENT" in ddl
    assert "SERIAL" not in ddl


def test_snowflake_locking_does_not_use_postgresql_advisory_locks() -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    create_sql = provider.create_migration_lock_table_sql("app")
    acquire_sql = provider.acquire_migration_lock_sql("app")

    assert "pg_try_advisory_lock" not in create_sql
    assert "pg_try_advisory_lock" not in acquire_sql
    assert "pg_advisory_unlock" not in acquire_sql
    assert "UPDATE" in acquire_sql
    assert '"APP"."DBLIFT_MIGRATION_LOCK"' in acquire_sql


def test_snowflake_provider_initializes_sqlalchemy_base(monkeypatch) -> None:
    calls: list[tuple[object, object]] = []
    config = object()
    log = object()

    def fake_base_init(self, config_arg, log_arg=None):
        calls.append((config_arg, log_arg))

    monkeypatch.setattr(SqlAlchemyProvider, "__init__", fake_base_init)

    provider = SnowflakeProvider(config, log)

    assert isinstance(provider, SnowflakeProvider)
    assert calls == [(config, log)]


def test_snowflake_execute_statement_prepares_schema(monkeypatch) -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)
    schema_calls: list[str] = []
    base_calls: list[tuple[str, object, object]] = []

    def fake_base_execute_statement(self, sql, schema=None, params=None):
        base_calls.append((sql, schema, params))
        return 7

    provider.create_schema_if_not_exists = schema_calls.append

    def fake_set_schema(schema):
        schema_calls.append(f"use:{schema}")

    provider.set_current_schema = fake_set_schema
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        fake_base_execute_statement,
    )

    rowcount = SnowflakeProvider.execute_statement(
        provider,
        "SELECT 1",
        schema="app",
        params=["value"],
    )

    assert rowcount == 7
    assert schema_calls == ["app", "use:app"]
    assert base_calls == [("SELECT 1", "app", ["value"])]


def test_snowflake_schema_helpers_quote_identifiers(monkeypatch) -> None:
    provider = _SnowflakeProvider()
    base_calls: list[str] = []

    def fake_base_execute_statement(self, sql, schema=None, params=None):
        base_calls.append(sql)
        return 1

    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        fake_base_execute_statement,
    )

    provider.create_schema_if_not_exists('mixed"schema')
    provider.set_current_schema("app")

    schema_stmt = 'CREATE SCHEMA IF NOT EXISTS "MIXED""SCHEMA"'
    qualified_name = provider.get_schema_qualified_name("app", "events")

    assert provider.statements == [(schema_stmt, None, None)]
    assert base_calls == ['USE SCHEMA "APP"']
    assert qualified_name == '"APP"."EVENTS"'
    assert provider.supports_transactional_ddl() is False


def test_snowflake_table_exists_and_version_queries() -> None:
    table_rows = [{"present": 1}]

    def handler(sql, params):
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return table_rows
        if "CURRENT_VERSION" in sql:
            return [{"version": "8.20.1"}]
        return []

    provider = _SnowflakeProvider(handler)

    assert provider.table_exists("app", "events") is True
    table_rows.clear()
    assert provider.table_exists("app", "events") is False
    assert provider.get_database_version() == "Snowflake 8.20.1"

    empty_provider = _SnowflakeProvider()
    assert empty_provider.get_database_version() == "Unknown Snowflake Version"


def test_snowflake_clean_schema_and_droppable_objects_use_catalogs() -> None:
    def handler(sql, params):
        if "INFORMATION_SCHEMA.VIEWS" in sql:
            return [{"object_name": "active_events"}]
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"OBJECT_NAME": "EVENTS"}]
        if "INFORMATION_SCHEMA.SEQUENCES" in sql:
            return [{"object_name": "event_seq"}, {"object_name": ""}]
        return []

    provider = _SnowflakeProvider(handler)

    summary = provider.clean_schema("analytics")
    objects = provider.list_droppable_objects("analytics")

    queried_sql = "\n".join(sql for sql, _params in provider.queries)
    executed_sql = [sql for sql, _schema, _params in provider.statements]

    assert "INFORMATION_SCHEMA.VIEWS" in queried_sql
    assert "INFORMATION_SCHEMA.TABLES" in queried_sql
    assert "INFORMATION_SCHEMA.SEQUENCES" in queried_sql
    assert summary.statements == [
        'DROP VIEW IF EXISTS "ANALYTICS"."ACTIVE_EVENTS"',
        'DROP TABLE IF EXISTS "ANALYTICS"."EVENTS" CASCADE',
        'DROP SEQUENCE IF EXISTS "ANALYTICS"."EVENT_SEQ"',
    ]
    assert executed_sql == summary.statements
    assert [(obj.object_type, obj.name) for obj in summary.objects] == [
        ("view", "active_events"),
        ("table", "EVENTS"),
        ("sequence", "event_seq"),
    ]
    assert [(obj.object_type, obj.name, obj.drop_sql) for obj in objects] == [
        (
            "view",
            "active_events",
            'DROP VIEW IF EXISTS "ANALYTICS"."ACTIVE_EVENTS"',
        ),
        (
            "table",
            "EVENTS",
            'DROP TABLE IF EXISTS "ANALYTICS"."EVENTS" CASCADE',
        ),
        (
            "sequence",
            "event_seq",
            'DROP SEQUENCE IF EXISTS "ANALYTICS"."EVENT_SEQ"',
        ),
    ]


def test_snowflake_migration_lock_table_creation_is_seeded() -> None:
    provider = _SnowflakeProvider()

    provider.create_migration_lock_table_if_not_exists("app")

    statement_values = [sql for sql, _schema, _params in provider.statements]
    statement_sql = "\n".join(statement_values)

    assert 'CREATE SCHEMA IF NOT EXISTS "APP"' in statement_sql
    assert "CREATE TABLE IF NOT EXISTS" in statement_sql
    assert '"APP"."DBLIFT_MIGRATION_LOCK"' in statement_sql
    assert "MERGE INTO" in statement_sql
    assert "WHEN NOT MATCHED THEN" in statement_sql
    assert "WHERE NOT EXISTS" not in statement_sql


def test_snowflake_acquire_migration_lock_holds_transaction() -> None:
    transaction = _FakeTransaction()
    connection = _FakeConnection(transaction)
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))

    acquired = provider.acquire_migration_lock("app", wait_timeout_seconds=-5)

    assert acquired is True
    assert provider.acquire_migration_lock("app") is True

    assert connection.sql == [
        "ALTER SESSION SET LOCK_TIMEOUT = 0",
        (
            'UPDATE "APP"."DBLIFT_MIGRATION_LOCK" '
            "SET locked_at = CURRENT_TIMESTAMP() WHERE lock_name = 'migration'"
        ),
    ]
    assert connection.committed is True
    assert provider._migration_lock_connection is connection
    assert provider._migration_lock_transaction is transaction


def test_snowflake_lock_timeout_detection_is_lock_specific() -> None:
    raw_message = " ".join(
        [
            "Your statement was aborted because waiting for this lock is",
            "currently not allowed",
        ]
    )
    driver_error = _DriverError("SQL execution failed", raw_msg=raw_message)
    network_timeout = RuntimeError("network timeout while connecting")

    assert _is_lock_timeout_error(RuntimeError("lock timeout exceeded"))
    assert _is_lock_timeout_error(driver_error)
    assert not _is_lock_timeout_error(network_timeout)
    assert not _is_lock_timeout_error(RuntimeError("statement timeout"))


def test_snowflake_acquire_migration_lock_returns_false_on_timeout() -> None:
    connection = _FakeConnection(
        fail_on="UPDATE",
        error=RuntimeError("lock timeout"),
    )
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))

    acquired = provider.acquire_migration_lock("app", wait_timeout_seconds=1)

    assert acquired is False
    assert connection.rolled_back is True
    assert connection.closed is True


def test_snowflake_acquire_migration_lock_reraises_non_timeout_error() -> None:
    connection = _FakeConnection(
        fail_on="ALTER",
        error=RuntimeError("network down"),
    )
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))

    with pytest.raises(RuntimeError, match="network down"):
        provider.acquire_migration_lock("app", wait_timeout_seconds=1)

    assert connection.rolled_back is True
    assert connection.closed is True


def test_snowflake_release_migration_lock_commit_and_failure_paths() -> None:
    provider = _SnowflakeProvider()
    assert provider.release_migration_lock("app") is True

    success_tx = _FakeTransaction()
    success_conn = _FakeConnection(success_tx)
    provider._migration_lock_transaction = success_tx
    provider._migration_lock_connection = success_conn

    assert provider.release_migration_lock("app") is True
    assert success_tx.committed is True
    assert success_conn.closed is True
    assert provider._migration_lock_transaction is None
    assert provider._migration_lock_connection is None

    failed_tx = _FakeTransaction(
        commit_error=RuntimeError("commit failed"),
        rollback_error=RuntimeError("rollback failed"),
    )
    failed_conn = _FakeConnection(failed_tx)
    provider._migration_lock_transaction = failed_tx
    provider._migration_lock_connection = failed_conn

    assert provider.release_migration_lock("app") is False
    assert failed_tx.rolled_back is True
    assert failed_conn.closed is True
    assert provider._migration_lock_transaction is None
    assert provider._migration_lock_connection is None


def test_snowflake_close_releases_held_lock(monkeypatch) -> None:
    provider = _SnowflakeProvider()
    transaction = _FakeTransaction()
    connection = _FakeConnection(transaction)
    base_close_calls: list[SnowflakeProvider] = []

    def fake_base_close(self):
        base_close_calls.append(self)

    monkeypatch.setattr(SqlAlchemyProvider, "close", fake_base_close)
    provider._migration_lock_transaction = transaction
    provider._migration_lock_connection = connection

    provider.close()

    assert transaction.committed is True
    assert connection.closed is True
    assert provider._migration_lock_transaction is None
    assert provider._migration_lock_connection is None
    assert base_close_calls == [provider]


def test_snowflake_applied_migrations_require_history_table() -> None:
    def handler(sql, params):
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"present": 1}]
        if "ORDER BY installed_rank" in sql:
            return [{"version": "1", "script": "V1__init.sql"}]
        return []

    provider = _SnowflakeProvider(handler)
    missing_provider = _SnowflakeProvider()
    expected_rows = [{"version": "1", "script": "V1__init.sql"}]

    assert missing_provider.get_applied_migrations("app") == []
    assert provider.get_applied_migrations("app") == expected_rows


def test_snowflake_history_table_creation_and_baseline_safety() -> None:
    table_present = False
    migration_count = 0

    def handler(sql, params):
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"present": 1}] if table_present else []
        if "COUNT(1)" in sql:
            return [{"COUNT": migration_count}]
        return []

    def has_create_history_sql(statements):
        create_history_sql = "CREATE TABLE IF NOT EXISTS"
        return any(create_history_sql in sql for sql in statements)

    provider = _SnowflakeProvider(handler)

    provider.create_migration_history_table_if_not_exists(
        "app",
        create_schema=True,
    )
    statement_values = [sql for sql, *_ in provider.statements]
    history_table_created = has_create_history_sql(statement_values)
    assert history_table_created

    provider.statements.clear()
    table_present = True
    provider.create_migration_history_table_if_not_exists(
        "app",
        create_schema=True,
    )
    statement_values = [sql for sql, *_ in provider.statements]
    history_table_created = has_create_history_sql(statement_values)
    assert not history_table_created

    migration_count = 2
    with pytest.raises(RuntimeError, match="2 migration"):
        provider.create_migration_history_table_if_not_exists(
            "app",
            create_schema=True,
        )


def test_snowflake_record_migration_and_undo_insert_expected_rows() -> None:
    provider = _SnowflakeProvider()

    provider.record_migration(
        "app",
        {
            "version": "1",
            "description": "init",
            "script": "V1__init.sql",
            "checksum": "abc",
            "execution_time": 12,
        },
    )
    provider.record_undo("app", "1")

    insert_calls = [
        (sql, params)
        for sql, _schema, params in provider.statements
        if "INSERT INTO" in sql and "DBLIFT_SCHEMA_HISTORY" in sql
    ]
    assert insert_calls[0][1] == [
        "1",
        "init",
        "SQL",
        "V1__init.sql",
        "abc",
        "dblift",
        12,
        True,
    ]
    assert insert_calls[1][1] == [
        "1",
        "Undo migration 1",
        "UNDO_SQL",
        "UNDO_1.sql",
        0,
        "dblift",
        0,
        True,
    ]


def test_snowflake_repair_migration_history_updates_existing_rows() -> None:
    def missing_table(sql, params):
        return []

    def existing_table(sql, params):
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"present": 1}]
        return []

    assert (
        _SnowflakeProvider(missing_table).repair_migration_history(
            "app",
            "V1__init.sql",
            "abc",
        )
        is False
    )

    updated_provider = _SnowflakeProvider(existing_table, statement_result=1)
    assert (
        updated_provider.repair_migration_history(
            "app",
            "V1__init.sql",
            "def",
            success_value=True,
        )
        is True
    )
    assert updated_provider.statements[-1][2] == [
        "def",
        True,
        "V1__init.sql",
    ]

    unchanged_provider = _SnowflakeProvider(existing_table, statement_result=0)
    assert (
        unchanged_provider.repair_migration_history(
            "app",
            "V1__init.sql",
            "def",
        )
        is False
    )
