"""DB2 plugin-owned SQLAlchemy URL construction."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from db.plugins.db2.plugin import PLUGIN as DB2_PLUGIN
from db.provider_registry import ProviderRegistry


@pytest.fixture
def _reset_registry():
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_discovered = ProviderRegistry._discovered
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._discovered = saved_discovered


def test_db2_plugin_declares_sqlalchemy_url_builder() -> None:
    assert DB2_PLUGIN.sqlalchemy_url_builder is not None
    assert DB2_PLUGIN.transport == "native"


def test_db2_registry_builds_ibm_db_sa_url(_reset_registry) -> None:
    ProviderRegistry._plugins["db2"] = DB2_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="db2",
        host="db2.example.com",
        port=50001,
        database="SAMPLE",
        username="db2inst1",
        password="p@ss/word",
        schema="APP",
        collection="APP_COLL",
        connection_timeout=30,
        extra_params={"security": "ssl"},
        options={"currentSchema": "IGNORED_BY_SCHEMA_FIELD"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "ibm_db_sa"
    assert url.username == "db2inst1"
    assert url.password == "p@ss/word"
    assert url.host == "db2.example.com"
    assert url.port == 50001
    assert url.database == "SAMPLE"
    assert dict(url.query) == {
        "collection": "APP_COLL",
        "connectTimeout": "30",
        "currentSchema": "APP",
        "security": "ssl",
    }


def test_db2_raw_url_merges_query_options(_reset_registry) -> None:
    ProviderRegistry._plugins["db2"] = DB2_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="db2",
        url="db2://db2.example.com:50000/SAMPLE?security=ssl",
        username="db2inst1",
        password="secret",
        schema="APP",
        extra_params={"retrieveMessagesFromServerOnGetMessage": "true"},
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "ibm_db_sa"
    assert url.username == "db2inst1"
    assert url.password == "secret"
    assert dict(url.query) == {
        "currentSchema": "APP",
        "retrieveMessagesFromServerOnGetMessage": "true",
        "security": "ssl",
    }


def test_db2_sqlalchemy_url_explicit_credentials_override_url_credentials(
    _reset_registry,
) -> None:
    ProviderRegistry._plugins["db2"] = DB2_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="db2",
        url="ibm_db_sa://stale:old@db2.example.com:50000/SAMPLE",
        username="db2inst1",
        password="secret",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.username == "db2inst1"
    assert url.password == "secret"


def test_db2_sqlalchemy_url_builder_rejects_database_url(_reset_registry) -> None:
    ProviderRegistry._plugins["db2"] = DB2_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="db2",
        url="jdbc:db2://localhost:50000/SAMPLE",
    )

    with pytest.raises(ValueError, match="SQLAlchemy URL"):
        ProviderRegistry.build_sqlalchemy_url(database_config)
