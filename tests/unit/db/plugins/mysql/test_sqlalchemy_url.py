"""MySQL-family plugin-owned SQLAlchemy URL construction."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from dblift.config.dblift_config import DbliftConfig
from dblift.db.plugins.mariadb.plugin import PLUGIN as MARIADB_PLUGIN
from dblift.db.plugins.mysql.plugin import PLUGIN as MYSQL_PLUGIN
from dblift.db.provider_registry import ProviderRegistry


@pytest.fixture
def _reset_registry():
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_discovered = ProviderRegistry._discovered
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._discovered = saved_discovered


def test_mysql_plugin_declares_sqlalchemy_url_builder() -> None:
    assert MYSQL_PLUGIN.sqlalchemy_url_builder is not None


def test_mariadb_plugin_declares_sqlalchemy_url_builder() -> None:
    assert MARIADB_PLUGIN.sqlalchemy_url_builder is not None


def test_mysql_registry_builds_pymysql_sqlalchemy_url(_reset_registry) -> None:
    ProviderRegistry._plugins["mysql"] = MYSQL_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="mysql",
        host="db.example.com",
        port=3307,
        database="app",
        username="mysql user",
        password="p@ss/word",
        connection_timeout=12,
        ssl_enabled=True,
        options={"charset": "utf8mb4"},
        extra_params={"local_infile": "1"},
        session_variables={"wait_timeout": "28800"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "mysql+pymysql"
    assert url.username == "mysql user"
    assert url.password == "p@ss/word"
    assert url.host == "db.example.com"
    assert url.port == 3307
    assert url.database == "app"
    assert dict(url.query) == {
        "charset": "utf8mb4",
        "connect_timeout": "12",
        "init_command": "SET SESSION wait_timeout=28800",
        "local_infile": "1",
        "ssl": "true",
    }


def test_mysql_bare_sqlalchemy_url_uses_pymysql_driver(_reset_registry) -> None:
    ProviderRegistry._plugins["mysql"] = MYSQL_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(type="mysql", url="mysql://db.example.com/app")

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "mysql+pymysql"
    assert url.host == "db.example.com"
    assert url.database == "app"


def test_mysql_sqlalchemy_url_merges_explicit_credentials(_reset_registry) -> None:
    ProviderRegistry._plugins["mysql"] = MYSQL_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="mysql",
        url="mysql+pymysql://db.example.com/app",
        username="mysql",
        password="secret",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.username == "mysql"
    assert url.password == "secret"
    assert url.host == "db.example.com"
    assert url.database == "app"


def test_mysql_sqlalchemy_url_prefers_explicit_credentials_over_url_userinfo(
    _reset_registry,
) -> None:
    ProviderRegistry._plugins["mysql"] = MYSQL_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="mysql",
        url="mysql+pymysql://stale:old@db.example.com/app",
        username="mysql",
        password="secret",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.username == "mysql"
    assert url.password == "secret"


def test_mariadb_registry_builds_pymysql_sqlalchemy_url(_reset_registry) -> None:
    ProviderRegistry._plugins["mariadb"] = MARIADB_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="mariadb",
        host="db.example.com",
        port=3306,
        database="app",
        username="maria",
        password="secret",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "mysql+pymysql"
    assert url.username == "maria"
    assert url.password == "secret"
    assert url.host == "db.example.com"
    assert url.database == "app"


def test_mysql_sqlalchemy_url_builder_rejects_database_url(_reset_registry) -> None:
    ProviderRegistry._plugins["mysql"] = MYSQL_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="mysql",
        url="jdbc:mysql://db.example.com:3306/app",
    )

    with pytest.raises(ValueError, match="SQLAlchemy URL"):
        ProviderRegistry.build_sqlalchemy_url(database_config)


def test_mysql_field_based_native_config_passes_validation() -> None:
    config = DbliftConfig.from_dict(
        {
            "database": {
                "type": "mysql",
                "host": "db.example.com",
                "database": "app",
                "username": "mysql",
                "password": "secret",
            }
        }
    )

    assert config.database.type == "mysql"
    assert config.database.host == "db.example.com"
    assert config.database.database == "app"


def test_mariadb_field_based_native_config_passes_validation() -> None:
    config = DbliftConfig.from_dict(
        {
            "database": {
                "type": "mariadb",
                "host": "db.example.com",
                "database": "app",
                "username": "maria",
                "password": "secret",
            }
        }
    )

    assert config.database.type == "mariadb"
    assert config.database.host == "db.example.com"
    assert config.database.database == "app"


def test_mysql_session_variables_string_values_are_quoted() -> None:
    """String session variable values must be SQL-quoted to avoid parse errors."""
    from dblift.db.plugins.mysql.sqlalchemy_url import build_sqlalchemy_url

    db = SimpleNamespace(
        type="mysql",
        host="h",
        port=3306,
        database="app",
        username="u",
        password="p",
        ssl_enabled=False,
        connection_timeout=None,
        options=None,
        extra_params=None,
        session_variables={
            "time_zone": "+00:00",
            "sql_mode": "ANSI_QUOTES",
            "wait_timeout": "28800",
        },
        url=None,
    )
    url = make_url(build_sqlalchemy_url(db))
    init_cmd = dict(url.query)["init_command"]

    # Numeric value unquoted; string values single-quoted
    assert "wait_timeout=28800" in init_cmd
    assert "time_zone='+00:00'" in init_cmd
    assert "sql_mode='ANSI_QUOTES'" in init_cmd
