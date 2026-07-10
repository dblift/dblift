"""Redshift plugin-owned SQLAlchemy URL construction."""

from types import SimpleNamespace

import pytest
from sqlalchemy.engine import make_url

from db.plugins.redshift.plugin import PLUGIN as REDSHIFT_PLUGIN
from db.provider_registry import ProviderRegistry


@pytest.fixture
def _reset_registry():
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_discovered = ProviderRegistry._discovered
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._discovered = saved_discovered


def test_redshift_plugin_uses_redshift_connector_driver() -> None:
    assert REDSHIFT_PLUGIN.sqlalchemy_url_builder is not None
    assert REDSHIFT_PLUGIN.native_driver_module == "redshift_connector"


def test_redshift_registry_builds_redshift_connector_url(_reset_registry) -> None:
    ProviderRegistry._plugins["redshift"] = REDSHIFT_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="redshift",
        host="redshift.example.com",
        port=5439,
        database="dev",
        username="tempuser",
        password="TempUser!2026",
        connection_timeout=12,
        ssl_mode="require",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "redshift+redshift_connector"
    assert url.username == "tempuser"
    assert url.password == "TempUser!2026"
    assert url.host == "redshift.example.com"
    assert url.port == 5439
    assert url.database == "dev"
    assert dict(url.query) == {}


def test_redshift_postgresql_url_is_mapped_to_redshift_connector(_reset_registry) -> None:
    ProviderRegistry._plugins["redshift"] = REDSHIFT_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(
        type="redshift",
        url="postgresql://stale:old@redshift.example.com:5439/dev",
        username="tempuser",
        password="TempUser!2026",
    )

    url = make_url(ProviderRegistry.build_sqlalchemy_url(database_config))

    assert url.drivername == "redshift+redshift_connector"
    assert url.username == "tempuser"
    assert url.password == "TempUser!2026"
    assert url.host == "redshift.example.com"
    assert url.database == "dev"
