"""Snowflake provider plugin contract."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from config.database_config import BaseDatabaseConfig
from db.plugins.snowflake.config import SnowflakeConfig
from db.plugins.snowflake.plugin import PLUGIN as SNOWFLAKE_PLUGIN
from db.plugins.snowflake.provider import SnowflakeProvider
from db.plugins.snowflake.quirks import SnowflakeQuirks
from db.provider_registry import ProviderRegistry
from db.sqlalchemy_provider import SqlAlchemyProvider


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
