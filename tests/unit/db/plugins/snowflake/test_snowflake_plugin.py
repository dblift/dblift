"""Snowflake provider plugin contract."""

import datetime
import tomllib
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
from packaging.requirements import Requirement
from sqlalchemy.engine import make_url

from dblift.config.database_config import BaseDatabaseConfig
from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.logger import NullLog
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.snowflake.config import SnowflakeConfig
from dblift.db.plugins.snowflake.plugin import PLUGIN as SNOWFLAKE_PLUGIN
from dblift.db.plugins.snowflake.provider import (
    SnowflakeProvider,
    _caller_identifier,
    _is_lock_timeout_error,
    _routine_argument_types,
)
from dblift.db.plugins.snowflake.quirks import SnowflakeQuirks
from dblift.db.provider_interfaces import DroppableObject
from dblift.db.provider_registry import ProviderRegistry
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider


def test_snowflake_extra_rejects_unqualified_sqlalchemy_21() -> None:
    project = tomllib.loads((Path(__file__).resolve().parents[5] / "pyproject.toml").read_text())
    requirements = {
        Requirement(text).name.lower(): Requirement(text)
        for text in project["project"]["optional-dependencies"]["snowflake"]
    }
    assert "2.0.54" in requirements["sqlalchemy"].specifier
    assert "2.1.3" not in requirements["sqlalchemy"].specifier


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
        self.session_lock_timeout: str | None = "43200"
        self.invalidated = False

    def exec_driver_sql(self, sql: str) -> Any:
        self.sql.append(sql)
        if self.fail_on and self.fail_on in sql:
            raise self.error
        if sql.startswith("SHOW PARAMETERS LIKE 'LOCK_TIMEOUT'"):
            rows = (
                [] if self.session_lock_timeout is None else [{"value": self.session_lock_timeout}]
            )
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: rows))
        return None

    def commit(self) -> None:
        self.committed = True

    def rollback(self) -> None:
        self.rolled_back = True

    def begin(self) -> _FakeTransaction:
        return self.transaction

    def invalidate(self) -> None:
        self.invalidated = True

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
        self.log = NullLog()

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
    assert quirks.introspector_class() is None
    assert quirks.vendor_queries_class() is None


def test_snowflake_history_table_uses_autoincrement_not_serial() -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    ddl = provider.create_history_table("APP", "DBLIFT_SCHEMA_HISTORY")

    assert '"APP"."DBLIFT_SCHEMA_HISTORY"' in ddl
    assert "AUTOINCREMENT" in ddl
    assert "SERIAL" not in ddl


def test_snowflake_locking_does_not_use_postgresql_advisory_locks() -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    create_sql = provider.create_migration_lock_table_sql("APP")
    acquire_sql = provider.acquire_migration_lock_sql("APP")

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


@pytest.mark.parametrize("setting,allowed", [("false", True), ("true", False)])
def test_snowflake_connection_rejects_case_insensitive_quoted_identifiers(
    monkeypatch, setting, allowed
) -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)
    queries: list[str] = []

    class Connection:
        active_transaction = False

        def in_transaction(self):
            return self.active_transaction

        def exec_driver_sql(self, sql):
            queries.append(sql)
            self.active_transaction = True
            value = "TIMESTAMP_NTZ" if "TIMESTAMP_TYPE_MAPPING" in sql else setting
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [{"value": value}]))

        def rollback(self):
            self.active_transaction = False

    connection = Connection()
    monkeypatch.setattr(SqlAlchemyProvider, "create_connection", lambda self: connection)

    if allowed:
        assert provider.create_connection() is connection
    else:
        with pytest.raises(RuntimeError, match="QUOTED_IDENTIFIERS_IGNORE_CASE"):
            provider.create_connection()
    assert queries == [
        "SHOW PARAMETERS LIKE 'QUOTED_IDENTIFIERS_IGNORE_CASE' IN SESSION",
        "SHOW PARAMETERS LIKE 'TIMESTAMP_TYPE_MAPPING' IN SESSION",
    ]
    assert connection.in_transaction() is False


def test_snowflake_migration_cannot_change_quoted_identifier_semantics(monkeypatch) -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)
    calls: list[str] = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: calls.append(sql) or 1,
    )

    with pytest.raises(RuntimeError, match="QUOTED_IDENTIFIERS_IGNORE_CASE"):
        provider.execute_statement("ALTER SESSION SET QUOTED_IDENTIFIERS_IGNORE_CASE = TRUE")
    with pytest.raises(RuntimeError, match="TIMESTAMP_TYPE_MAPPING"):
        provider.execute_statement("ALTER SESSION SET TIMESTAMP_TYPE_MAPPING = TIMESTAMP_TZ")
    assert calls == []
    assert provider.execute_statement("ALTER SESSION SET TIMEZONE = 'UTC'") == 1
    assert calls == ["ALTER SESSION SET TIMEZONE = 'UTC'"]


def test_snowflake_connection_rejects_timestamp_alias_rebinding(monkeypatch) -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    class Connection:
        def in_transaction(self):
            return False

        def exec_driver_sql(self, sql):
            value = "TIMESTAMP_TZ" if "TIMESTAMP_TYPE_MAPPING" in sql else "false"
            return SimpleNamespace(mappings=lambda: SimpleNamespace(all=lambda: [{"value": value}]))

    monkeypatch.setattr(SqlAlchemyProvider, "create_connection", lambda self: Connection())

    with pytest.raises(RuntimeError, match="TIMESTAMP_TYPE_MAPPING"):
        provider.create_connection()


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
    provider.set_current_schema("APP")

    schema_stmt = 'CREATE SCHEMA IF NOT EXISTS "mixed""schema"'
    qualified_name = provider.get_schema_qualified_name("APP", "EVENTS")

    assert provider.statements == [(schema_stmt, None, None)]
    assert base_calls == ['USE SCHEMA "APP"']
    assert qualified_name == '"APP"."EVENTS"'
    assert provider.supports_transactional_ddl() is False


def test_snowflake_set_current_schema_skips_reissue_for_same_schema(monkeypatch) -> None:
    """A second call for the same schema does not re-issue ``USE SCHEMA``.

    Otherwise dblift resets the current schema before every migration
    statement, silently overwriting a ``USE SCHEMA`` the migration itself
    runs as soon as the next statement fires.
    """
    base_calls: list[str] = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: base_calls.append(sql),
    )
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    provider.set_current_schema("APP")
    provider.set_current_schema("APP")

    assert base_calls == ['USE SCHEMA "APP"']


def test_snowflake_begin_transaction_alone_does_not_clear_the_schema_cache(monkeypatch) -> None:
    """``begin_transaction`` no longer clears the cache on its own.

    Invalidation is owned by ``ExecutionEngine.reset_schema_cache()``, called
    once at the start of every migration/callback before the transaction
    begins. A provider-level clear here as well would leave nothing between
    the two clears, so the migration's first statement reapplied the schema
    a second time — a duplicate ``USE SCHEMA`` per migration.
    """
    base_calls: list[str] = []
    monkeypatch.setattr(
        SqlAlchemyProvider,
        "execute_statement",
        lambda self, sql, schema=None, params=None: base_calls.append(sql),
    )
    monkeypatch.setattr(SqlAlchemyProvider, "begin_transaction", lambda self: None)
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    provider.set_current_schema("APP")
    SnowflakeProvider.begin_transaction(provider)
    provider.set_current_schema("APP")

    assert base_calls == ['USE SCHEMA "APP"']


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


def test_snowflake_quoted_identifiers_keep_catalog_case() -> None:
    provider = _SnowflakeProvider()

    assert provider.get_schema_qualified_name("MixedCase", 'order"items') == (
        '"MixedCase"."order""items"'
    )

    provider.table_exists("MixedCase", "order")
    sql, params = provider.queries[-1]
    assert "UPPER(?)" not in sql
    assert params == ["MixedCase", "order"]


def test_snowflake_sqlglot_parser_handles_ddl_for_lint_and_preflight() -> None:
    parser = SqlParserFactory("snowflake", parser_type="hybrid")

    result = parser.parse_sql('CREATE TABLE "QA"."Orders" ("Amount" NUMBER(18,4))')

    assert result.success
    assert len(result.statements) == 1
    assert result.statements[0].statement_type.value == "CREATE"
    assert result.statements[0].objects


def test_snowflake_migration_split_preserves_quoted_sql() -> None:
    sql = (
        "-- setup; comment\n"
        'CREATE TABLE "QA"."A;B" ("V" VARCHAR);\n'
        "INSERT INTO \"QA\".\"A;B\" VALUES ('one;two'), ('it''s;ok'), ('back\\'slash;ok');\n"
        "SELECT $$a; b$$;"
    )

    statements = StatementSplitter("snowflake").split_statements(sql)

    assert statements == [
        '-- setup; comment\nCREATE TABLE "QA"."A;B" ("V" VARCHAR)',
        "INSERT INTO \"QA\".\"A;B\" VALUES ('one;two'), ('it''s;ok'), ('back\\'slash;ok')",
        "SELECT $$a; b$$",
    ]


def test_snowflake_migration_split_refuses_unquoted_scripting_block() -> None:
    sql = "BEGIN LET x INT := 1; RETURN x; END;"

    with pytest.raises(UnsafeStatementSplitError, match="Snowflake Scripting"):
        StatementSplitter("snowflake").split_statements(
            sql, fallback=lambda value: value.split(";")
        )


def test_snowflake_clean_schema_and_droppable_objects_use_catalogs() -> None:
    def handler(sql, params):
        if "INFORMATION_SCHEMA.SCHEMATA" in sql:
            return [{"present": 1}]
        if "INFORMATION_SCHEMA.VIEWS" in sql:
            return [{"object_name": "active_events"}]
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"OBJECT_NAME": "EVENTS"}]
        if "INFORMATION_SCHEMA.SEQUENCES" in sql:
            return [{"object_name": "event_seq"}, {"object_name": ""}]
        return []

    provider = _SnowflakeProvider(handler)

    summary = provider.clean_schema("ANALYTICS")
    objects = provider.list_droppable_objects("ANALYTICS")

    queried_sql = "\n".join(sql for sql, _params in provider.queries)
    executed_sql = [sql for sql, _schema, _params in provider.statements]

    assert "INFORMATION_SCHEMA.VIEWS" in queried_sql
    assert "INFORMATION_SCHEMA.TABLES" in queried_sql
    assert "INFORMATION_SCHEMA.SEQUENCES" in queried_sql
    assert summary.statements == [
        'DROP VIEW IF EXISTS "ANALYTICS"."active_events"',
        'DROP TABLE IF EXISTS "ANALYTICS"."EVENTS" CASCADE',
        'DROP SEQUENCE IF EXISTS "ANALYTICS"."event_seq"',
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
            'DROP VIEW IF EXISTS "ANALYTICS"."active_events"',
        ),
        (
            "table",
            "EVENTS",
            'DROP TABLE IF EXISTS "ANALYTICS"."EVENTS" CASCADE',
        ),
        (
            "sequence",
            "event_seq",
            'DROP SEQUENCE IF EXISTS "ANALYTICS"."event_seq"',
        ),
    ]


def test_snowflake_migration_lock_table_creation_is_seeded() -> None:
    provider = _SnowflakeProvider()

    provider.create_migration_lock_table_if_not_exists("APP")

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

    acquired = provider.acquire_migration_lock("APP", wait_timeout_seconds=-5)

    assert acquired is True
    assert provider.acquire_migration_lock("APP") is True

    assert connection.sql[1] == "ALTER SESSION SET LOCK_TIMEOUT = 0"
    assert connection.sql[-1] == (
        'UPDATE "APP"."DBLIFT_MIGRATION_LOCK" '
        "SET locked_at = CURRENT_TIMESTAMP() WHERE lock_name = 'migration'"
    )
    assert connection.committed is True
    assert provider._migration_lock_connection is connection
    assert provider._migration_lock_transaction is transaction


def test_snowflake_lock_table_seed_runs_under_the_requested_lock_timeout() -> None:
    """Every statement that can wait on the lock table follows ALTER SESSION.

    The seeding MERGE blocks behind the session holding the lock row, so it
    must run on the lock session after ``LOCK_TIMEOUT`` is set; on the main
    session it would wait for the 12 hour default.
    """
    connection = _FakeConnection()
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=5) is True

    set_timeout = connection.sql.index("ALTER SESSION SET LOCK_TIMEOUT = 5")
    merge = next(i for i, sql in enumerate(connection.sql) if "MERGE INTO" in sql)
    update = next(i for i, sql in enumerate(connection.sql) if sql.startswith("UPDATE"))
    assert set_timeout < merge < update
    assert all(i > set_timeout for i, sql in enumerate(connection.sql) if "CREATE " in sql)
    main_session_sql = "\n".join(sql for sql, _schema, _params in provider.statements)
    assert "MERGE" not in main_session_sql
    assert "LOCK_TIMEOUT" not in main_session_sql


def test_snowflake_lock_timeout_while_seeding_returns_false_and_restores_the_session() -> None:
    connection = _FakeConnection(fail_on="MERGE", error=RuntimeError("lock timeout"))
    connection.session_lock_timeout = "600"
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))

    acquired = provider.acquire_migration_lock("APP", wait_timeout_seconds=1)

    assert acquired is False
    assert connection.rolled_back is True
    assert connection.sql[-1] == "ALTER SESSION SET LOCK_TIMEOUT = 600"
    assert connection.closed is True
    assert provider._migration_lock_connection is None


def test_snowflake_release_restores_the_session_lock_timeout_before_closing() -> None:
    transaction = _FakeTransaction()
    connection = _FakeConnection(transaction)
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))
    provider.acquire_migration_lock("APP", wait_timeout_seconds=5)

    assert provider.release_migration_lock("APP") is True

    assert transaction.committed is True
    assert connection.sql[-1] == "ALTER SESSION SET LOCK_TIMEOUT = 43200"
    assert connection.closed is True


def test_snowflake_unknown_session_lock_timeout_is_unset_on_release() -> None:
    connection = _FakeConnection()
    connection.session_lock_timeout = None
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))
    provider.acquire_migration_lock("APP", wait_timeout_seconds=5)

    assert provider.release_migration_lock("APP") is True

    assert connection.sql[-1] == "ALTER SESSION UNSET LOCK_TIMEOUT"
    assert connection.invalidated is False
    assert connection.closed is True


def test_snowflake_lock_connection_is_invalidated_when_the_timeout_cannot_be_restored() -> None:
    """A connection still carrying the short LOCK_TIMEOUT must not return to the pool."""
    connection = _FakeConnection(fail_on="= 43200", error=RuntimeError("session gone"))
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))
    provider.acquire_migration_lock("APP", wait_timeout_seconds=5)

    assert provider.release_migration_lock("APP") is True

    assert connection.invalidated is True
    assert connection.closed is True
    assert provider._migration_lock_connection is None


def test_snowflake_lock_connection_is_kept_poolable_when_the_timeout_is_restored() -> None:
    connection = _FakeConnection()
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))
    provider.acquire_migration_lock("APP", wait_timeout_seconds=5)
    provider.release_migration_lock("APP")

    assert connection.invalidated is False


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


# ---------------------------------------------------------------------------
# History rank ordering
# ---------------------------------------------------------------------------


class _RecordingLog:
    def __init__(self) -> None:
        self.warnings: list[str] = []
        self.infos: list[str] = []

    def warning(self, message: str) -> None:
        self.warnings.append(message)

    def info(self, message: str, console_only: bool = False, *, dedupe: bool = True) -> None:
        self.infos.append(message)

    def debug(self, message: str, exc_info: bool = False) -> None:
        pass


def _history_provider(identity_ordered: str | None) -> _SnowflakeProvider:
    """Provider whose history table exists and reports the given IDENTITY_ORDERED."""

    def handler(sql, params):
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"present": 1}]
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            if identity_ordered is None:
                return []
            return [{"identity_ordered": identity_ordered}]
        return []

    provider = _SnowflakeProvider(handler)
    provider.log = _RecordingLog()
    return provider


def _history_inserts(provider: _SnowflakeProvider) -> list[tuple[str, object]]:
    return [
        (sql, params)
        for sql, _schema, params in provider.statements
        if "INSERT INTO" in sql and "DBLIFT_SCHEMA_HISTORY" in sql
    ]


_MIGRATION = {"version": "1", "description": "init", "script": "V1__init.sql", "checksum": "abc"}


def test_snowflake_history_table_ddl_orders_the_rank_identity() -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    ddl = " ".join(provider.create_history_table("APP", "DBLIFT_SCHEMA_HISTORY").split())

    assert "installed_rank INTEGER AUTOINCREMENT START 1 INCREMENT 1 ORDER PRIMARY KEY" in ddl


def test_snowflake_ordered_history_identity_uses_implicit_rank() -> None:
    provider = _history_provider("YES")

    provider.record_migration("app", _MIGRATION)

    ((sql, params),) = _history_inserts(provider)
    assert "installed_rank" not in sql
    assert len(params) == 8
    assert provider.log.warnings == []


@pytest.mark.parametrize("identity_ordered", ["YES", "NO", None])
def test_snowflake_history_inserts_never_assign_the_rank_explicitly(identity_ordered) -> None:
    """Ranks always come from the identity: an explicit MAX+1 can collide, since
    Snowflake does not enforce the primary key."""
    provider = _history_provider(identity_ordered)

    provider.record_migration("app", _MIGRATION)
    provider.record_undo("app", "1")

    inserts = _history_inserts(provider)
    assert len(inserts) == 2
    for sql, params in inserts:
        assert "MAX(installed_rank)" not in sql
        assert "installed_rank" not in sql
        assert len(params) == 8


def test_snowflake_unordered_history_identity_warns_once_with_detection_hint() -> None:
    provider = _history_provider("NO")

    provider.record_migration("app", _MIGRATION)
    provider.record_migration("app", {**_MIGRATION, "version": "2", "script": "V2__next.sql"})

    assert len(provider.log.warnings) == 1
    warning = provider.log.warnings[0]
    assert '"app"."DBLIFT_SCHEMA_HISTORY"' in warning
    assert "unique but may not follow application order" in warning
    assert "ORDER BY installed_on" in warning


@pytest.mark.parametrize("identity_ordered", ["YES", None])
def test_snowflake_ordered_or_unknown_history_identity_does_not_warn(identity_ordered) -> None:
    provider = _history_provider(identity_ordered)

    provider.record_migration("app", _MIGRATION)

    assert provider.log.warnings == []


def test_snowflake_rank_identity_is_checked_once_per_history_table() -> None:
    provider = _history_provider("YES")

    provider.record_migration("app", _MIGRATION)
    provider.record_migration("app", {**_MIGRATION, "version": "2"})

    column_queries = [sql for sql, _ in provider.queries if "INFORMATION_SCHEMA.COLUMNS" in sql]
    assert len(column_queries) == 1


def test_snowflake_failing_rank_identity_check_does_not_block_the_insert() -> None:
    def handler(sql, params):
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"present": 1}]
        if "INFORMATION_SCHEMA.COLUMNS" in sql:
            raise RuntimeError("catalog unavailable")
        return []

    provider = _SnowflakeProvider(handler)
    provider.log = _RecordingLog()

    provider.record_migration("app", _MIGRATION)

    assert len(_history_inserts(provider)) == 1
    assert provider.log.warnings == []


# ---------------------------------------------------------------------------
# Flyway source table (quoted lowercase)
# ---------------------------------------------------------------------------


def _flyway_source_provider(existing_tables: set[str], rows: list[dict[str, Any]] | None = None):
    def handler(sql, params):
        if "INFORMATION_SCHEMA.TABLES" in sql:
            return [{"present": 1}] if params[1] in existing_tables else []
        if sql.startswith("SELECT * FROM"):
            return list(rows or [])
        return []

    provider = _SnowflakeProvider(handler)
    provider.config = SimpleNamespace(database=SimpleNamespace(type="snowflake"))
    provider._quirks = SnowflakeQuirks()
    return provider


def _flyway_row(rank: int, script: str) -> dict[str, Any]:
    return {
        "installed_rank": rank,
        "version": str(rank),
        "description": script,
        "type": "SQL",
        "script": script,
        "checksum": rank,
        "installed_by": "flyway",
        "installed_on": None,
        "execution_time": 1,
        "success": True,
    }


def test_snowflake_quirks_treat_flyway_source_table_case_as_significant() -> None:
    assert SnowflakeQuirks().flyway_source_table_case_sensitive is True


def test_snowflake_table_helpers_accept_a_name_quoted_by_the_caller() -> None:
    provider = _flyway_source_provider({"flyway_schema_history"})

    assert provider.table_exists("S", '"flyway_schema_history"') is True
    assert provider.queries[-1][1] == ["S", "flyway_schema_history"]
    assert provider.get_schema_qualified_name("S", '"flyway_schema_history"') == (
        '"S"."flyway_schema_history"'
    )


def test_snowflake_import_finds_quoted_lowercase_flyway_table_and_reads_it_quoted() -> None:
    from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager

    provider = _flyway_source_provider(
        {"flyway_schema_history"}, [_flyway_row(2, "V2__b.sql"), _flyway_row(1, "V1__a.sql")]
    )
    manager = MigrationHistoryManager(provider, "S", "dblift")

    table = manager.resolve_flyway_source_table("S", "flyway_schema_history")
    rows = manager.read_history_rows("S", table, flyway_source=True)

    assert table == '"flyway_schema_history"'
    assert provider.queries[-1][0] == 'SELECT * FROM "S"."flyway_schema_history"'
    assert [row["script"] for row in rows] == ["V1__a.sql", "V2__b.sql"]
    assert all("ORDER BY" not in sql for sql, _ in provider.queries)


def test_snowflake_import_falls_back_to_folded_uppercase_flyway_table() -> None:
    from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager

    provider = _flyway_source_provider({"FLYWAY_SCHEMA_HISTORY"})
    manager = MigrationHistoryManager(provider, "S", "dblift")

    assert manager.resolve_flyway_source_table("S", "flyway_schema_history") == (
        "FLYWAY_SCHEMA_HISTORY"
    )


def test_snowflake_compatibility_snapshot_reads_quoted_lowercase_flyway_table() -> None:
    from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager

    provider = _flyway_source_provider(
        {"flyway_schema_history", "DBLIFT_SCHEMA_HISTORY"}, [_flyway_row(1, "V1__a.sql")]
    )
    manager = MigrationHistoryManager(provider, "S", "dblift")

    snapshot = manager.collect_flyway_compatibility_snapshot()

    assert snapshot.collection_error == ""
    assert snapshot.flyway_exists is True
    assert [row["script"] for row in snapshot.flyway_migrations] == ["V1__a.sql"]
    flyway_selects = [sql for sql, _ in provider.queries if "flyway_schema_history" in sql]
    assert flyway_selects == ['SELECT * FROM "S"."flyway_schema_history"']


# ---------------------------------------------------------------------------
# Clean coverage
# ---------------------------------------------------------------------------


def _clean_catalog_handler(extra: dict[str, list[dict[str, Any]]] | None = None):
    catalog: dict[str, list[dict[str, Any]]] = {
        "INFORMATION_SCHEMA.SCHEMATA": [{"present": 1}],
        "SELECT CURRENT_DATABASE()": [{"db": "ANALYTICS"}],
        "SHOW PIPES": [{"name": "LOAD_PIPE"}],
        "SHOW TASKS": [{"name": "NIGHTLY"}],
        "SHOW ALERTS": [{"name": "LOW_STOCK"}],
        "SHOW STREAMS": [{"name": "ORDERS_STREAM"}],
        "SHOW DYNAMIC TABLES": [{"name": "DAILY_TOTALS"}],
        "SHOW MATERIALIZED VIEWS": [{"name": "ORDER_COUNTS"}],
        "SHOW EVENT TABLES": [{"name": "APP_EVENTS"}],
        "SHOW EXTERNAL TABLES": [{"name": "LAKE_ORDERS"}],
        "SHOW TAGS": [{"name": "PII"}],
        "SHOW MASKING POLICIES": [{"name": "MASK_EMAIL"}],
        "SHOW ROW ACCESS POLICIES": [{"name": "REGION_ONLY"}],
        "SHOW PASSWORD POLICIES": [{"name": "STRONG_PW"}],
        "SHOW SESSION POLICIES": [{"name": "IDLE_LIMIT"}],
        "SHOW SECRETS": [{"name": "API_KEY"}],
        "SHOW NETWORK RULES": [{"name": "EGRESS"}],
        "INFORMATION_SCHEMA.VIEWS": [
            {"object_name": "active_orders"},
            {"object_name": "ORDER_COUNTS"},
        ],
        "INFORMATION_SCHEMA.TABLES": [
            {"object_name": "ORDERS"},
            {"object_name": "DAILY_TOTALS"},
            {"object_name": "APP_EVENTS"},
        ],
        "INFORMATION_SCHEMA.SEQUENCES": [{"object_name": "order_seq"}],
        "SHOW USER FUNCTIONS": [
            {"name": "ADD_TAX", "arguments": "ADD_TAX(NUMBER, VARCHAR) RETURN NUMBER"},
            {"NAME": "NOW_UTC", "ARGUMENTS": "NOW_UTC() RETURN TIMESTAMP_NTZ"},
        ],
        "SHOW USER PROCEDURES": [{"name": "REFRESH", "arguments": "REFRESH(NUMBER) RETURN NUMBER"}],
        "SHOW STAGES": [{"name": "LANDING"}],
        "SHOW FILE FORMATS": [{"name": "CSV_FMT"}],
    }
    catalog.update(extra or {})

    def handler(sql, params):
        for marker, rows in catalog.items():
            if marker in sql:
                return rows
        return []

    return handler


def test_snowflake_clean_preview_covers_every_schema_object_kind_in_drop_order() -> None:
    provider = _SnowflakeProvider(_clean_catalog_handler())

    summary = provider.get_clean_preview("S")

    assert summary.statements == [
        'DROP PIPE IF EXISTS "S"."LOAD_PIPE"',
        'DROP TASK IF EXISTS "S"."NIGHTLY"',
        'DROP ALERT IF EXISTS "S"."LOW_STOCK"',
        'DROP STREAM IF EXISTS "S"."ORDERS_STREAM"',
        'DROP DYNAMIC TABLE IF EXISTS "S"."DAILY_TOTALS"',
        'DROP MATERIALIZED VIEW IF EXISTS "S"."ORDER_COUNTS"',
        'DROP VIEW IF EXISTS "S"."active_orders"',
        'DROP TABLE IF EXISTS "S"."ORDERS" CASCADE',
        'DROP EXTERNAL TABLE IF EXISTS "S"."LAKE_ORDERS"',
        'DROP EVENT TABLE IF EXISTS "S"."APP_EVENTS"',
        'DROP SEQUENCE IF EXISTS "S"."order_seq"',
        'DROP TAG IF EXISTS "S"."PII"',
        'DROP MASKING POLICY IF EXISTS "S"."MASK_EMAIL"',
        'DROP ROW ACCESS POLICY IF EXISTS "S"."REGION_ONLY"',
        'DROP PASSWORD POLICY IF EXISTS "S"."STRONG_PW"',
        'DROP SESSION POLICY IF EXISTS "S"."IDLE_LIMIT"',
        'DROP FUNCTION IF EXISTS "S"."ADD_TAX"(NUMBER, VARCHAR)',
        'DROP FUNCTION IF EXISTS "S"."NOW_UTC"()',
        'DROP PROCEDURE IF EXISTS "S"."REFRESH"(NUMBER)',
        'DROP STAGE IF EXISTS "S"."LANDING"',
        'DROP FILE FORMAT IF EXISTS "S"."CSV_FMT"',
        'DROP SECRET IF EXISTS "S"."API_KEY"',
        'DROP NETWORK RULE IF EXISTS "S"."EGRESS"',
    ]
    assert [obj.object_type for obj in summary.objects] == [
        "pipe",
        "task",
        "alert",
        "stream",
        "dynamic_table",
        "materialized_view",
        "view",
        "table",
        "external_table",
        "event_table",
        "sequence",
        "tag",
        "masking_policy",
        "row_access_policy",
        "password_policy",
        "session_policy",
        "function",
        "function",
        "procedure",
        "stage",
        "file_format",
        "secret",
        "network_rule",
    ]


def test_snowflake_clean_preview_lists_function_overloads_by_signature() -> None:
    provider = _SnowflakeProvider(_clean_catalog_handler())

    objects = provider.list_droppable_objects("S")

    names = {obj.object_type: [] for obj in objects}
    for obj in objects:
        names[obj.object_type].append(obj.name)
    assert names["function"] == ["ADD_TAX(NUMBER, VARCHAR)", "NOW_UTC()"]
    assert names["procedure"] == ["REFRESH(NUMBER)"]
    assert [obj.drop_sql for obj in objects] == provider.get_clean_preview("S").statements


def test_snowflake_clean_preview_scopes_show_commands_to_the_database_and_schema() -> None:
    provider = _SnowflakeProvider(_clean_catalog_handler())

    provider.get_clean_preview("My Schema")

    shows = [sql.strip() for sql, _ in provider.queries if sql.strip().startswith("SHOW")]
    assert shows == [
        'SHOW PIPES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW TASKS IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW ALERTS IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW STREAMS IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW DYNAMIC TABLES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW MATERIALIZED VIEWS IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW EVENT TABLES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW EXTERNAL TABLES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW TAGS IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW MASKING POLICIES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW ROW ACCESS POLICIES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW PASSWORD POLICIES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW SESSION POLICIES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW USER FUNCTIONS IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW USER PROCEDURES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW STAGES IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW FILE FORMATS IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW SECRETS IN SCHEMA "ANALYTICS"."My Schema"',
        'SHOW NETWORK RULES IN SCHEMA "ANALYTICS"."My Schema"',
    ]


def test_snowflake_clean_preview_does_not_drop_materialized_views_and_dynamic_tables_twice() -> (
    None
):
    """Both kinds also appear in the view/table catalogs but need their own DROP."""
    provider = _SnowflakeProvider(_clean_catalog_handler())

    statements = provider.get_clean_preview("S").statements

    assert 'DROP VIEW IF EXISTS "S"."ORDER_COUNTS"' not in statements
    assert 'DROP TABLE IF EXISTS "S"."DAILY_TOTALS" CASCADE' not in statements
    assert 'DROP TABLE IF EXISTS "S"."APP_EVENTS" CASCADE' not in statements


@pytest.mark.parametrize(
    "failing",
    ["INFORMATION_SCHEMA.VIEWS", "INFORMATION_SCHEMA.TABLES", "INFORMATION_SCHEMA.SEQUENCES"],
)
def test_snowflake_clean_preview_propagates_core_catalog_failures(failing) -> None:
    full = _clean_catalog_handler()

    def handler(sql, params):
        if failing in sql:
            raise RuntimeError("insufficient privileges")
        return full(sql, params)

    provider = _SnowflakeProvider(handler)

    with pytest.raises(RuntimeError, match="insufficient privileges"):
        provider.get_clean_preview("S")


def test_snowflake_clean_of_a_missing_schema_is_a_no_op() -> None:
    full = _clean_catalog_handler()

    def handler(sql, params):
        return [] if "INFORMATION_SCHEMA.SCHEMATA" in sql else full(sql, params)

    provider = _SnowflakeProvider(handler)
    provider.log = _RecordingLog()

    assert provider.get_clean_preview("GONE").statements == []
    assert provider.list_droppable_objects("GONE") == []
    assert provider.clean_schema("GONE").statements == []

    assert provider.statements == []
    assert provider.log.warnings == []
    assert all(not sql.strip().startswith("SHOW") for sql, _ in provider.queries)
    schema_checks = [p for sql, p in provider.queries if "INFORMATION_SCHEMA.SCHEMATA" in sql]
    assert schema_checks and all(params == ["GONE"] for params in schema_checks)


_OPTIONAL_KINDS = [
    "PIPES",
    "TASKS",
    "ALERTS",
    "STREAMS",
    "DYNAMIC TABLES",
    "MATERIALIZED VIEWS",
    "EVENT TABLES",
    "EXTERNAL TABLES",
    "TAGS",
    "MASKING POLICIES",
    "ROW ACCESS POLICIES",
    "PASSWORD POLICIES",
    "SESSION POLICIES",
    "USER FUNCTIONS",
    "USER PROCEDURES",
    "STAGES",
    "FILE FORMATS",
    "SECRETS",
    "NETWORK RULES",
]


@pytest.mark.parametrize("kind", _OPTIONAL_KINDS)
def test_snowflake_clean_preview_skips_an_optional_kind_it_cannot_list(kind) -> None:
    full = _clean_catalog_handler()

    def handler(sql, params):
        if f"SHOW {kind} IN SCHEMA" in sql:
            raise RuntimeError("feature not enabled")
        return full(sql, params)

    provider = _SnowflakeProvider(handler)
    provider.log = _RecordingLog()

    objects = provider.list_droppable_objects("S")

    expected = (
        f"could not list {kind.lower()}; objects of this kind were not cleaned: feature not enabled"
    )
    assert [w for w in provider.log.warnings if expected in w] != []
    assert len([w for w in provider.log.warnings if "could not list" in w]) == 1
    assert objects  # the remaining kinds are still listed


def test_snowflake_clean_residual_warning_lists_kinds_that_could_not_be_listed() -> None:
    provider = _residue_provider([], failing_show="SHOW STAGES")

    provider.clean_schema("S")

    residual = [w for w in provider.log.warnings if "after clean" in w]
    assert len(residual) == 1
    assert "stages" in residual[0]


def test_snowflake_clean_schema_executes_the_extended_drops_in_order() -> None:
    provider = _SnowflakeProvider(_clean_catalog_handler())

    summary = provider.clean_schema("S")

    assert [sql for sql, _schema, _params in provider.statements] == summary.statements
    assert summary.statements[0].startswith("DROP PIPE")
    assert summary.statements[-1].startswith("DROP NETWORK RULE")


# ---------------------------------------------------------------------------
# Statement splitting without a caller-supplied fallback
# ---------------------------------------------------------------------------


def test_snowflake_statement_splitter_splits_without_a_fallback() -> None:
    statements = StatementSplitter("snowflake", logger=NullLog()).split_statements(
        "SELECT 1; SELECT 2;"
    )

    assert statements == ["SELECT 1", "SELECT 2"]


def test_snowflake_sql_analyzer_splits_statements() -> None:
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

    statements = SqlAnalyzer(dialect="snowflake").split_statements("SELECT 1; SELECT 2;")

    assert statements == ["SELECT 1", "SELECT 2"]


def test_snowflake_statement_splitter_fails_explicitly_on_unterminated_string() -> None:
    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter("snowflake", logger=NullLog()).split_statements("SELECT 'open; SELECT 2;")


def test_snowflake_sql_analyzer_fails_explicitly_on_unterminated_string() -> None:
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

    with pytest.raises(UnsafeStatementSplitError):
        SqlAnalyzer(dialect="snowflake").split_statements("SELECT 'open; SELECT 2;")


# ---------------------------------------------------------------------------
# installed_on supplied by the caller
# ---------------------------------------------------------------------------

_FLYWAY_INSTALLED_ON = datetime.datetime(2023, 4, 15, 9, 12, 0)


@pytest.mark.parametrize("identity_ordered", ["YES", "NO"])
def test_snowflake_record_migration_binds_a_supplied_installed_on(identity_ordered) -> None:
    provider = _history_provider(identity_ordered)

    provider.record_migration("app", {**_MIGRATION, "installed_on": _FLYWAY_INSTALLED_ON})

    ((sql, params),) = _history_inserts(provider)
    normalized = " ".join(sql.split())
    assert "execution_time, success, installed_on)" in normalized
    assert params == [
        "1",
        "init",
        "SQL",
        "V1__init.sql",
        "abc",
        "dblift",
        0,
        True,
        _FLYWAY_INSTALLED_ON,
    ]
    assert normalized.count("?") == len(params)
    assert "MAX(installed_rank)" not in normalized


@pytest.mark.parametrize("identity_ordered", ["YES", "NO"])
@pytest.mark.parametrize("blank", [None, "", "   "])
def test_snowflake_record_migration_keeps_the_default_timestamp_without_installed_on(
    identity_ordered, blank
) -> None:
    provider = _history_provider(identity_ordered)

    provider.record_migration("app", {**_MIGRATION, "installed_on": blank})
    provider.record_migration("app", _MIGRATION)

    for sql, params in _history_inserts(provider):
        assert "installed_on" not in sql
        assert len(params) == 8
        assert " ".join(sql.split()).count("?") == 8


def test_snowflake_import_flyway_passes_the_flyway_installed_on_to_the_provider() -> None:
    from unittest.mock import Mock

    from dblift.core.migration.commands.import_flyway_command import ImportFlywayCommand
    from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager
    from dblift.core.migration.state.migration_state_manager import MigrationStateManager

    flyway_row = {**_flyway_row(1, "V1__a.sql"), "installed_on": _FLYWAY_INSTALLED_ON}
    provider = _flyway_source_provider(
        {"flyway_schema_history", "DBLIFT_SCHEMA_HISTORY"}, [flyway_row]
    )
    base_handler = provider.query_handler
    provider.query_handler = lambda sql, params: (
        [{"identity_ordered": "YES"}]
        if "INFORMATION_SCHEMA.COLUMNS" in sql
        else base_handler(sql, params)
    )
    provider.log = NullLog()
    config = Mock()
    config.database.schema = "S"
    config.history_table = None
    history = MigrationHistoryManager(provider, "S", "dblift")
    state = MigrationStateManager(Mock(), history, Mock(), Mock())
    command = ImportFlywayCommand(
        config=config,
        log=Mock(),
        provider=provider,
        script_manager=Mock(),
        history_manager=history,
        validator=Mock(),
        execution_engine=Mock(),
        migration_helpers=Mock(),
        state_manager=state,
        migration_ui=Mock(),
        migration_rules=Mock(),
    )

    command._run_preflight = lambda *args, **kwargs: None
    provider.commit_transaction = lambda: None

    result = command.execute(scripts_dir=Path("/scripts"), dry_run=False)

    assert result.success is True, result.error_message
    ((sql, params),) = _history_inserts(provider)
    assert "installed_on" in sql
    assert params[-1] == _FLYWAY_INSTALLED_ON


# ---------------------------------------------------------------------------
# Catalog-derived names are used exactly as the catalog reports them
# ---------------------------------------------------------------------------


def test_snowflake_clean_drops_objects_by_their_literal_catalog_names() -> None:
    handler = _clean_catalog_handler(
        {
            "INFORMATION_SCHEMA.TABLES": [
                {"object_name": '"foo"'},
                {"object_name": " padded "},
            ],
            "SHOW STAGES": [{"name": '"stage"'}],
            "SHOW USER FUNCTIONS": [{"name": '"fn"', "arguments": '"fn"(NUMBER) RETURN NUMBER'}],
        }
    )
    statements = _SnowflakeProvider(handler).get_clean_preview("S").statements

    assert 'DROP TABLE IF EXISTS "S"."""foo""" CASCADE' in statements
    assert 'DROP TABLE IF EXISTS "S"." padded " CASCADE' in statements
    assert 'DROP STAGE IF EXISTS "S"."""stage"""' in statements
    assert 'DROP FUNCTION IF EXISTS "S"."""fn"""(NUMBER)' in statements


def test_snowflake_caller_quote_stripping_never_touches_whitespace_or_partial_quotes() -> None:
    provider = SnowflakeProvider.__new__(SnowflakeProvider)

    assert provider.get_schema_qualified_name("S", " padded ") == '"S"." padded "'
    assert provider.get_schema_qualified_name("S", '"half') == '"S"."""half"'
    assert provider.get_schema_qualified_name("S", 'a"b"') == '"S"."a""b"""'
    assert provider.get_schema_qualified_name("S", '"a""b"') == '"S"."a""b"'


# ---------------------------------------------------------------------------
# Function and procedure signatures
# ---------------------------------------------------------------------------


def test_snowflake_clean_builds_drop_signatures_from_show_arguments() -> None:
    handler = _clean_catalog_handler(
        {
            "SHOW USER FUNCTIONS": [
                {"name": "FD", "arguments": "FD(NUMBER, DEFAULT NUMBER) RETURN NUMBER"},
                {"name": "FD", "arguments": "FD(VARCHAR) RETURN VARCHAR"},
                {"name": "FT", "arguments": "FT(NUMBER) RETURN TABLE (X NUMBER)"},
                {"name": "a RETURN b", "arguments": "a RETURN b(NUMBER) RETURN NUMBER"},
                {"name": "Fn X", "arguments": "Fn X(NUMBER, VARCHAR, ARRAY) RETURN NUMBER"},
                {
                    "name": "G",
                    "arguments": "G(NUMBER(38, 0), DEFAULT VARCHAR) RETURN NUMBER",
                },
            ],
            "SHOW USER PROCEDURES": [
                {"name": "P", "arguments": "P(DEFAULT NUMBER) RETURN TABLE (Y NUMBER)"}
            ],
        }
    )

    statements = _SnowflakeProvider(handler).get_clean_preview("S").statements

    assert [s for s in statements if "FUNCTION" in s or "PROCEDURE" in s] == [
        'DROP FUNCTION IF EXISTS "S"."FD"(NUMBER, NUMBER)',
        'DROP FUNCTION IF EXISTS "S"."FD"(VARCHAR)',
        'DROP FUNCTION IF EXISTS "S"."FT"(NUMBER)',
        'DROP FUNCTION IF EXISTS "S"."a RETURN b"(NUMBER)',
        'DROP FUNCTION IF EXISTS "S"."Fn X"(NUMBER, VARCHAR, ARRAY)',
        'DROP FUNCTION IF EXISTS "S"."G"(NUMBER(38, 0), VARCHAR)',
        'DROP PROCEDURE IF EXISTS "S"."P"(NUMBER)',
    ]


def test_snowflake_clean_refuses_arguments_that_do_not_start_with_the_routine_name() -> None:
    handler = _clean_catalog_handler(
        {"SHOW USER FUNCTIONS": [{"name": "F", "arguments": "OTHER(NUMBER) RETURN NUMBER"}]}
    )

    with pytest.raises(RuntimeError, match="argument types"):
        _SnowflakeProvider(handler).get_clean_preview("S")


# ---------------------------------------------------------------------------
# Residual check after clean
# ---------------------------------------------------------------------------


def _residue_provider(
    leftover: list[dict[str, Any]],
    failing_show: str | None = None,
    catalog: dict[str, list[dict[str, Any]]] | None = None,
) -> _SnowflakeProvider:
    """Catalog that lists objects until the drops ran, then only ``leftover``."""
    full = _clean_catalog_handler(catalog)
    holder: dict[str, _SnowflakeProvider] = {}

    def handler(sql, params):
        if failing_show and failing_show in sql:
            raise RuntimeError("feature not enabled")
        dropped = bool(holder["p"].statements) or bool(holder["p"].dropped)
        if "SHOW OBJECTS" in sql:
            return leftover if dropped else []
        if dropped and "INFORMATION_SCHEMA.SCHEMATA" not in sql and "CURRENT_DATABASE" not in sql:
            return []
        return full(sql, params)

    provider = _SnowflakeProvider(handler)
    provider.log = _RecordingLog()
    provider.dropped = []
    holder["p"] = provider
    return provider


def _drop_all(provider: _SnowflakeProvider, schema: str = "S") -> None:
    for obj in provider.list_droppable_objects(schema):
        provider.drop_object(obj)
        provider.dropped.append(obj)


def test_snowflake_clean_schema_warns_about_objects_that_survive() -> None:
    provider = _residue_provider([{"name": "STUCK", "kind": "TABLE"}])

    provider.clean_schema("S")

    (warning,) = [w for w in provider.log.warnings if "after clean" in w]
    assert "table STUCK" in warning
    assert '"S"' in warning
    assert "drop errors above" not in warning


def test_snowflake_clean_through_drop_object_warns_once_after_the_last_drop() -> None:
    provider = _residue_provider([{"name": "STUCK", "kind": "VIEW"}])

    objects = provider.list_droppable_objects("My Schema")
    for obj in objects[:-1]:
        provider.drop_object(obj)
    assert provider.log.warnings == []
    provider.drop_object(objects[-1])

    (warning,) = provider.log.warnings
    assert "view STUCK" in warning
    assert '"My Schema"' in warning
    shows = [sql for sql, _ in provider.queries if "SHOW OBJECTS" in sql]
    assert shows == ['SHOW OBJECTS IN SCHEMA "ANALYTICS"."My Schema"']


def test_snowflake_clean_reports_enumerated_survivors_not_listed_by_show_objects() -> None:
    full = _clean_catalog_handler()

    def handler(sql, params):
        return [] if "SHOW OBJECTS" in sql else full(sql, params)

    provider = _SnowflakeProvider(handler)
    provider.log = _RecordingLog()

    provider.clean_schema("S")

    (warning,) = provider.log.warnings
    assert "pipe LOAD_PIPE" in warning


def test_snowflake_clean_of_an_emptied_schema_does_not_warn() -> None:
    provider = _residue_provider([])

    provider.clean_schema("S")

    assert provider.log.warnings == []


def test_snowflake_residual_check_failure_does_not_fail_clean() -> None:
    full = _clean_catalog_handler()
    holder: dict[str, _SnowflakeProvider] = {}

    def handler(sql, params):
        if holder["p"].statements:
            raise RuntimeError("catalog unavailable")
        return full(sql, params)

    provider = _SnowflakeProvider(handler)
    provider.log = _RecordingLog()
    holder["p"] = provider

    summary = provider.clean_schema("S")

    assert summary.statements
    assert provider.log.warnings == []


def test_snowflake_survivors_are_keyed_by_kind_and_name() -> None:
    provider = _residue_provider(
        [],
        catalog={
            **{
                marker: [] for marker in ("SHOW PIPES", "SHOW TASKS", "SHOW ALERTS", "SHOW STREAMS")
            },
            "INFORMATION_SCHEMA.VIEWS": [{"object_name": "SAME"}],
            "INFORMATION_SCHEMA.TABLES": [],
            "INFORMATION_SCHEMA.SEQUENCES": [],
            "SHOW DYNAMIC TABLES": [],
            "SHOW MATERIALIZED VIEWS": [],
            "SHOW EVENT TABLES": [],
            "SHOW EXTERNAL TABLES": [],
            "SHOW TAGS": [],
            "SHOW MASKING POLICIES": [],
            "SHOW ROW ACCESS POLICIES": [],
            "SHOW PASSWORD POLICIES": [],
            "SHOW SESSION POLICIES": [],
            "SHOW USER FUNCTIONS": [],
            "SHOW USER PROCEDURES": [],
            "SHOW STAGES": [{"name": "SAME"}],
            "SHOW FILE FORMATS": [],
            "SHOW SECRETS": [],
            "SHOW NETWORK RULES": [],
        },
    )
    survivors, _temporary, _unlisted = provider._clean_residue("S")

    assert survivors == [("view", "SAME"), ("stage", "SAME")]


def test_snowflake_show_objects_rows_already_enumerated_are_not_reported_twice() -> None:
    full = _clean_catalog_handler()

    def handler(sql, params):
        if "SHOW OBJECTS" in sql:
            return [
                {"name": "ORDERS", "kind": "TABLE"},
                {"name": "DAILY_TOTALS", "kind": "TABLE"},
                {"name": "ORDER_COUNTS", "kind": "VIEW"},
            ]
        return full(sql, params)

    provider = _SnowflakeProvider(handler)

    survivors, _temporary, _unlisted = provider._clean_residue("S")

    names = [name for _kind, name in survivors]
    assert names.count("ORDERS") == 1
    assert names.count("DAILY_TOTALS") == 1
    assert names.count("ORDER_COUNTS") == 1


def test_snowflake_residual_report_leaves_session_temporary_tables_out() -> None:
    provider = _residue_provider(
        [
            {"name": "TMP", "kind": "TEMPORARY TABLE"},
            {"name": "TMP2", "kind": "TABLE", "is_temporary": "Y"},
        ]
    )

    provider.clean_schema("S")

    assert provider.log.warnings == []
    (info,) = provider.log.infos
    assert "TMP" in info and "TMP2" in info
    assert "not managed by clean" in info


def test_snowflake_drop_object_outside_a_listed_clean_never_runs_the_check() -> None:
    provider = _residue_provider([{"name": "STUCK", "kind": "TABLE"}])

    provider.drop_object(DroppableObject("X", "table", 'DROP TABLE IF EXISTS "S"."X"'))

    assert provider.log.warnings == []
    assert all("SHOW OBJECTS" not in sql for sql, _ in provider.queries)


def test_snowflake_dry_run_listing_and_empty_listing_arm_nothing() -> None:
    provider = _residue_provider([{"name": "STUCK", "kind": "TABLE"}])
    provider.list_droppable_objects("S")  # dry run: listed, never dropped

    provider.drop_object(DroppableObject("X", "table", 'DROP TABLE IF EXISTS "S"."X"'))

    assert provider.log.warnings == []

    empty = _SnowflakeProvider(lambda sql, params: [])
    empty.log = _RecordingLog()
    assert empty.list_droppable_objects("S") == []
    empty.drop_object(DroppableObject("X", "table", 'DROP TABLE IF EXISTS "S"."X"'))
    assert empty.log.warnings == []
    assert all("SHOW OBJECTS" not in sql for sql, _ in empty.queries)


def test_snowflake_finished_clean_is_disarmed() -> None:
    provider = _residue_provider([{"name": "STUCK", "kind": "TABLE"}])
    objects = provider.list_droppable_objects("S")
    for obj in objects:
        provider.drop_object(obj)
    assert len(provider.log.warnings) == 1

    provider.drop_object(objects[0])

    assert len(provider.log.warnings) == 1


def test_snowflake_failing_last_drop_still_completes_and_disarms_the_clean() -> None:
    provider = _residue_provider([{"name": "STUCK", "kind": "TABLE"}])
    objects = provider.list_droppable_objects("S")
    for obj in objects[:-1]:
        provider.drop_object(obj)
    original = provider.execute_statement

    def failing(sql, schema=None, params=None):
        raise RuntimeError("drop failed")

    provider.execute_statement = failing
    with pytest.raises(RuntimeError, match="drop failed"):
        provider.drop_object(objects[-1])
    provider.execute_statement = original

    assert len([w for w in provider.log.warnings if "after clean" in w]) == 1
    provider.drop_object(objects[-1])
    assert len([w for w in provider.log.warnings if "after clean" in w]) == 1


# ---------------------------------------------------------------------------
# Review follow-ups: names, signatures, lock, rank check
# ---------------------------------------------------------------------------


def test_snowflake_caller_identifier_unwraps_only_one_whole_quoted_identifier() -> None:
    assert _caller_identifier('"a"') == "a"
    assert _caller_identifier('"a""b"') == 'a"b'
    assert _caller_identifier('"a"."b"') == '"a"."b"'
    assert _caller_identifier('"a" "b"') == '"a" "b"'
    assert _caller_identifier('"') == '"'
    assert _caller_identifier("a") == "a"


def test_snowflake_routine_argument_types_edge_cases() -> None:
    assert _routine_argument_types("F", "F() RETURN NUMBER") == "()"
    assert _routine_argument_types("f(x)", "f(x)(NUMBER) RETURN NUMBER") == "(NUMBER)"
    assert _routine_argument_types("F", "F(NUMBER(38, 0), VARCHAR) RETURN NUMBER") == (
        "(NUMBER(38, 0), VARCHAR)"
    )
    assert _routine_argument_types("F", "F(DEFAULT NUMBER) RETURN NUMBER") == "(NUMBER)"
    with pytest.raises(RuntimeError, match="argument types"):
        _routine_argument_types("F", "G(NUMBER) RETURN NUMBER")
    with pytest.raises(RuntimeError, match="argument types"):
        _routine_argument_types("F", "F(NUMBER RETURN NUMBER")
    with pytest.raises(RuntimeError, match="argument types"):
        _routine_argument_types("F", "F RETURN NUMBER")


class _SequencedEngine:
    def __init__(self, *connections: _FakeConnection) -> None:
        self.connections = list(connections)

    def connect(self) -> _FakeConnection:
        return self.connections.pop(0)


def test_snowflake_each_lock_acquire_reads_the_session_timeout_again() -> None:
    first, second = _FakeConnection(), _FakeConnection()
    first.session_lock_timeout = "600"
    second.session_lock_timeout = None
    provider = _SnowflakeProvider(engine=_SequencedEngine(first, second))

    provider.acquire_migration_lock("APP", wait_timeout_seconds=5)
    provider.release_migration_lock("APP")
    provider.acquire_migration_lock("APP", wait_timeout_seconds=5)
    provider.release_migration_lock("APP")

    assert first.sql[-1] == "ALTER SESSION SET LOCK_TIMEOUT = 600"
    assert second.sql[-1] == "ALTER SESSION UNSET LOCK_TIMEOUT"


class _RollbackFails(_FakeConnection):
    def rollback(self) -> None:
        raise RuntimeError("rollback failed")


def test_snowflake_failed_rollback_does_not_mask_a_lock_timeout() -> None:
    connection = _RollbackFails(fail_on="UPDATE", error=RuntimeError("lock timeout"))
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))
    provider.log = _RecordingLog()

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=1) is False

    assert connection.closed is True
    assert connection.sql[-1] == "ALTER SESSION SET LOCK_TIMEOUT = 43200"


def test_snowflake_failed_rollback_does_not_mask_the_original_error() -> None:
    connection = _RollbackFails(fail_on="UPDATE", error=RuntimeError("network down"))
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))

    with pytest.raises(RuntimeError, match="network down"):
        provider.acquire_migration_lock("APP", wait_timeout_seconds=1)

    assert connection.closed is True


def test_snowflake_rank_identity_check_uses_the_same_table_name_as_the_existence_check() -> None:
    provider = _history_provider("YES")

    provider.record_migration("app", _MIGRATION, '"my_hist"')

    exists = [p for sql, p in provider.queries if "INFORMATION_SCHEMA.TABLES" in sql]
    columns = [p for sql, p in provider.queries if "INFORMATION_SCHEMA.COLUMNS" in sql]
    assert exists[0] == ["app", "MY_HIST"]
    assert columns == [["app", "MY_HIST"]]


# ---------------------------------------------------------------------------
# Lock refusal as the user sees it
# ---------------------------------------------------------------------------

_LOCK_LIMIT_ERROR = (
    "000627 (57014): Statement '01c78a0e-3204-adf0-0008-380200118cb2' has locked table "
    "'DBLIFT_MIGRATION_LOCK' in transaction 1791253348403000000 and this lock has not yet "
    "been released. Your statement '01c78a0e-3204-ab41-0008-38020011b606' was aborted "
    "because waiting for this lock is limited to 5 s"
)


class _ProgrammingError(Exception):
    """Stands in for the driver's ProgrammingError (``str`` carries the message)."""


@pytest.mark.parametrize("blocked", ["MERGE", "UPDATE"])
def test_snowflake_lock_limit_error_from_the_driver_is_a_refusal(blocked) -> None:
    connection = _FakeConnection(
        fail_on=blocked, error=_ProgrammingError(f"ProgrammingError: {_LOCK_LIMIT_ERROR}")
    )
    provider = _SnowflakeProvider(engine=_FakeEngine(connection))

    assert provider.acquire_migration_lock("APP", wait_timeout_seconds=5) is False

    assert connection.closed is True
    assert provider._migration_lock_connection is None


def test_snowflake_lock_refusal_reaches_the_user_through_migrate() -> None:
    from pathlib import Path
    from unittest.mock import patch

    from tests.unit.core.migration.commands.test_migrate_command_repeatable_lock_race import (
        _cmd,
        _repeatable,
    )

    connection = _FakeConnection(
        fail_on="MERGE", error=_ProgrammingError(f"ProgrammingError: {_LOCK_LIMIT_ERROR}")
    )
    cmd = _cmd([_repeatable()], applied_after_lock=[])
    cmd.provider = _SnowflakeProvider(engine=_FakeEngine(connection))

    with (
        patch.object(cmd, "_run_preflight"),
        patch.object(cmd, "_log_command_header_update"),
        patch.object(cmd, "_log_current_schema_version"),
        patch.object(cmd, "_log_command_completion"),
    ):
        result = cmd.execute(Path("/migrations"))

    assert result.success is False
    cmd.log.error.assert_any_call(
        "Could not acquire migration lock - another migration may be running"
    )
