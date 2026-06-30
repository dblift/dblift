"""PostgreSQL plugin-owned SQLAlchemy URL construction."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from db.plugins.postgresql.plugin import PLUGIN
from db.provider_registry import ProviderRegistry


@pytest.fixture
def _reset_registry():
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_discovered = ProviderRegistry._discovered
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._discovered = saved_discovered


def test_postgresql_plugin_declares_sqlalchemy_url_builder() -> None:
    """The PostgreSQL plugin owns its SQLAlchemy URL construction."""
    assert PLUGIN.sqlalchemy_url_builder is not None


def test_postgresql_registry_builds_psycopg_sqlalchemy_url(_reset_registry) -> None:
    """The registry delegates PostgreSQL SQLAlchemy URLs to the plugin."""
    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="postgresql",
        host="db.example.com",
        port=5433,
        database="app",
        username="pg user",
        password="p@ss/word",
        connection_timeout=12,
        ssl_mode="require",
        extra_params={"application_name": "dblift"},
        options={"target_session_attrs": "read-write"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "postgresql+psycopg"
    assert url.username == "pg user"
    assert url.password == "p@ss/word"
    assert url.host == "db.example.com"
    assert url.port == 5433
    assert url.database == "app"
    assert dict(url.query) == {
        "application_name": "dblift",
        "connect_timeout": "12",
        "sslmode": "require",
        "target_session_attrs": "read-write",
    }


def test_postgresql_bare_sqlalchemy_url_uses_psycopg_driver(_reset_registry) -> None:
    """Bare PostgreSQL URLs use the installed psycopg v3 driver."""
    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="postgresql",
        url="postgresql://db.example.com/app",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "db.example.com"
    assert url.database == "app"


def test_postgresql_postgres_alias_url_uses_psycopg_driver(_reset_registry) -> None:
    """Common postgres:// aliases normalize to the installed psycopg v3 driver."""
    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="postgresql",
        url="postgres://db.example.com/app",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "postgresql+psycopg"
    assert url.host == "db.example.com"
    assert url.database == "app"


def test_postgresql_url_merges_explicit_credentials(_reset_registry) -> None:
    """Split-secret configs keep username/password outside the URL."""
    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="postgresql",
        url="postgresql+psycopg://db.example.com/app",
        username="pg",
        password="secret",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.username == "pg"
    assert url.password == "secret"
    assert url.host == "db.example.com"
    assert url.database == "app"


def test_postgresql_url_prefers_explicit_credentials_over_url_userinfo(
    _reset_registry,
) -> None:
    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="postgresql",
        url="postgresql+psycopg://stale:old@db.example.com/app",
        username="pg",
        password="secret",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.username == "pg"
    assert url.password == "secret"


def test_postgresql_sqlalchemy_url_includes_schema_search_path(_reset_registry) -> None:
    """The plugin maps database.schema to PostgreSQL search_path options."""
    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="postgresql",
        host="db.example.com",
        port=5432,
        database="app",
        username="pg",
        password="secret",
        schema="tenant_a",
        extra_params={},
        options={},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert dict(url.query)["options"] == "-csearch_path=tenant_a"


def test_postgresql_raw_sqlalchemy_url_merges_schema_search_path(_reset_registry) -> None:
    """Raw PostgreSQL SQLAlchemy URLs still honor plugin config options."""
    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="postgresql",
        url="postgresql://db.example.com/app?options=-cexisting%3D1",
        username="pg",
        password="secret",
        schema="tenant_a",
        connection_timeout=12,
        ssl_mode="require",
        extra_params={"application_name": "dblift"},
        options={"target_session_attrs": "read-write"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "postgresql+psycopg"
    assert url.username == "pg"
    assert url.password == "secret"
    assert dict(url.query) == {
        "application_name": "dblift",
        "connect_timeout": "12",
        "options": "-cexisting=1 -csearch_path=tenant_a",
        "sslmode": "require",
        "target_session_attrs": "read-write",
    }


def test_postgresql_sqlalchemy_url_builder_rejects_database_url(_reset_registry) -> None:
    """PostgreSQL URLs must be native SQLAlchemy URLs."""
    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="postgresql",
        url="jdbc:postgresql://db.example.com:5432/app",
    )

    with pytest.raises(ValueError, match="SQLAlchemy URL"):
        ProviderRegistry.build_sqlalchemy_url(database_config)


def test_postgresql_field_based_config_validates(_reset_registry) -> None:
    """Native PostgreSQL accepts host/database credentials without database.url."""
    from config import DbliftConfig
    from db.plugins.postgresql.config import PostgreSqlConfig

    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    config = DbliftConfig(
        database=PostgreSqlConfig(
            type="postgresql",
            host="db.example.com",
            port=5432,
            database="app",
            username="pg",
            password="secret",
        )
    )

    assert ProviderRegistry.validate_database_configuration(config) == (True, None)


def test_dblift_config_accepts_field_based_postgresql_without_url(_reset_registry) -> None:
    """Top-level config validation honors PostgreSQL native identifiers."""
    from config import DbliftConfig

    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True

    config = DbliftConfig.from_dict(
        {
            "database": {
                "type": "postgresql",
                "host": "db.example.com",
                "database": "app",
                "username": "pg",
                "password": "secret",
            }
        }
    )

    assert config.database.type == "postgresql"
    assert config.database.host == "db.example.com"
    assert config.database.database == "app"
    assert config.database.schema == "public"


def test_dblift_config_infers_postgresql_from_sqlalchemy_url(_reset_registry) -> None:
    """A native PostgreSQL SQLAlchemy URL does not require database.type."""
    from config import DbliftConfig

    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True

    config = DbliftConfig.from_dict(
        {"database": {"url": "postgresql+psycopg://pg:secret@db.example.com/app"}}
    )

    assert config.database.type == "postgresql"
    assert config.database.url == "postgresql+psycopg://pg:secret@db.example.com/app"


def test_dblift_config_rejects_postgresql_database_url(_reset_registry) -> None:
    """PostgreSQL v2 native configs fail fast on legacy URLs."""
    from config import DbliftConfig
    from config.errors import ConfigurationError

    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True

    with pytest.raises(ConfigurationError, match="Legacy database URLs are no longer supported"):
        DbliftConfig.from_dict(
            {
                "database": {
                    "type": "postgresql",
                    "url": "jdbc:postgresql://db.example.com:5432/app",
                }
            }
        )


def test_dblift_config_rejects_inferred_postgresql_database_url(_reset_registry) -> None:
    """A JDBC PostgreSQL URL is rejected even when database.type is omitted."""
    from config import DbliftConfig
    from config.errors import ConfigurationError

    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True

    with pytest.raises(ConfigurationError, match="Legacy database URLs are no longer supported"):
        DbliftConfig.from_dict({"database": {"url": "jdbc:postgresql://db.example.com:5432/app"}})


def test_dblift_config_rejects_postgresql_host_without_database(_reset_registry) -> None:
    """PostgreSQL field configs require host and database together."""
    from config import DbliftConfig
    from config.errors import ConfigurationError

    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True

    with pytest.raises(ConfigurationError, match="host/database"):
        DbliftConfig.from_dict({"database": {"type": "postgresql", "host": "db.example.com"}})


def test_postgresql_registry_rejects_host_without_database(_reset_registry) -> None:
    """Registry validation uses the plugin-owned PostgreSQL identifier rules."""
    from config import DbliftConfig
    from db.plugins.postgresql.config import PostgreSqlConfig

    ProviderRegistry._plugins["postgresql"] = PLUGIN
    ProviderRegistry._discovered = True
    config = DbliftConfig(database=PostgreSqlConfig(type="postgresql", host="db.example.com"))

    assert ProviderRegistry.validate_database_configuration(config) == (
        False,
        "PostgreSQL connection requires url or host/database fields",
    )
