"""Oracle plugin-owned SQLAlchemy URL construction."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from dblift.db.plugins.oracle.plugin import PLUGIN as ORACLE_PLUGIN
from dblift.db.provider_registry import ProviderRegistry


@pytest.fixture
def _reset_registry():
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_discovered = ProviderRegistry._discovered
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._discovered = saved_discovered


def test_oracle_plugin_declares_sqlalchemy_url_builder() -> None:
    assert ORACLE_PLUGIN.sqlalchemy_url_builder is not None
    assert ORACLE_PLUGIN.transport == "native"


def test_oracle_registry_builds_oracledb_service_name_url(_reset_registry) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        host="ora.example.com",
        port=1522,
        username="system",
        password="p@ss/word",
        service_name="XEPDB1",
        sid=None,
        extra_params={"mode": "thin"},
        options={"encoding": "UTF-8"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "oracle+oracledb"
    assert url.username == "system"
    assert url.password == "p@ss/word"
    assert url.host == "ora.example.com"
    assert url.port == 1522
    assert url.database is None
    assert dict(url.query) == {
        "encoding": "UTF-8",
        "mode": "thin",
        "service_name": "XEPDB1",
    }


def test_oracle_registry_builds_sid_url(_reset_registry) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        host="localhost",
        port=1521,
        username="system",
        password="oracle",
        service_name=None,
        sid="XE",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "oracle+oracledb"
    assert dict(url.query) == {"sid": "XE"}


def test_oracle_service_name_removes_stale_sid_query(_reset_registry) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        host="localhost",
        port=1521,
        username="system",
        password="oracle",
        service_name="XEPDB1",
        sid=None,
        extra_params={"sid": "XE"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert dict(url.query) == {"service_name": "XEPDB1"}


def test_oracle_sid_removes_stale_service_name_query(_reset_registry) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        host="localhost",
        port=1521,
        username="system",
        password="oracle",
        service_name=None,
        sid="XE",
        options={"service_name": "XEPDB1"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert dict(url.query) == {"sid": "XE"}


def test_oracle_bare_sqlalchemy_url_uses_oracledb_driver(_reset_registry) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        url="oracle://ora.example.com:1521/?service_name=XEPDB1",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "oracle+oracledb"
    assert url.host == "ora.example.com"
    assert dict(url.query) == {"service_name": "XEPDB1"}


def test_oracle_raw_sqlalchemy_url_merges_extra_params_and_options(
    _reset_registry,
) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        url="oracle+oracledb://ora.example.com:1521/?service_name=XEPDB1",
        extra_params={"encoding": "UTF-8"},
        options={"mode": "thin"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert dict(url.query) == {
        "encoding": "UTF-8",
        "mode": "thin",
        "service_name": "XEPDB1",
    }


def test_oracle_sqlalchemy_url_merges_explicit_credentials(_reset_registry) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        url="oracle+oracledb://ora.example.com:1521/?service_name=XEPDB1",
        username="system",
        password="oracle",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.username == "system"
    assert url.password == "oracle"


def test_oracle_sqlalchemy_url_explicit_credentials_override_url_credentials(
    _reset_registry,
) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        url="oracle+oracledb://stale:old@ora.example.com:1521/?service_name=XEPDB1",
        username="system",
        password="oracle",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.username == "system"
    assert url.password == "oracle"


def test_oracle_sqlalchemy_url_builder_rejects_database_url(_reset_registry) -> None:
    ProviderRegistry._plugins["oracle"] = ORACLE_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="oracle",
        url="jdbc:oracle:thin:@localhost:1521/XEPDB1",
    )

    with pytest.raises(ValueError, match="SQLAlchemy URL"):
        ProviderRegistry.build_sqlalchemy_url(database_config)
