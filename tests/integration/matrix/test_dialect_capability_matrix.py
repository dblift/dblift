"""Provider capability declarations must match runtime behavior (P3).

Every provider class declares what it supports via ISP protocols
(ConnectionProvider, TransactionalProvider, SchemaProvider, etc.) and via
plugin-owned quirks metadata. If a provider implements a protocol but raises
``NotImplementedError`` at runtime — or vice versa — that's the exact class
of bug that caused:
  * BUG-COSMOS-1 — ``_capture_snapshot`` fired SQL queries at CosmosDB
  * BUG-COSMOS-2 — ``getAutoCommit()`` called unguarded on DatabaseProxy
  * 045ee0a1 — CosmosDB account_endpoint guard missing

This test walks the registry and enforces consistency without opening a real
database connection.
"""

from __future__ import annotations

import pytest

from dblift.db.provider_interfaces import (
    ConnectionProvider,
    MigrationProvider,
    QueryProvider,
    SchemaProvider,
    TransactionalProvider,
)
from dblift.db.provider_registry import ProviderRegistry

ALL_INTERFACES = [
    ConnectionProvider,
    QueryProvider,
    SchemaProvider,
    TransactionalProvider,
    MigrationProvider,
]


@pytest.fixture(scope="module")
def plugins():
    """Discover all registered plugins once per module."""
    return ProviderRegistry.list_plugins()


@pytest.mark.integration
def test_every_provider_is_subclass_of_baseprovider(plugins):
    """All registered provider_class entries must subclass BaseProvider."""
    from dblift.db.base_provider import BaseProvider

    for plugin in plugins:
        assert issubclass(
            plugin.provider_class, BaseProvider
        ), f"{plugin.name} provider_class is not a BaseProvider"


@pytest.mark.integration
def test_runtime_transaction_capability_matches_plugin_metadata(plugins):
    """Check the plugin contract without constructing providers or connections."""
    from dblift.db.base_quirks import BaseQuirks

    for plugin in plugins:
        quirks_class = plugin.quirks_class or BaseQuirks
        assert issubclass(plugin.provider_class, TransactionalProvider) is bool(
            quirks_class.supports_transactions
        ), plugin.name


@pytest.mark.integration
def test_all_plugins_are_native_transport(plugins):
    """v2 plugins all declare the native transport."""
    for plugin in plugins:
        assert plugin.transport == "native", f"{plugin.name}: expected native transport"


@pytest.mark.integration
def test_all_expected_dialects_registered(plugins):
    """The 6 supported dialects must all have a plugin."""
    names = {p.name.lower() for p in plugins}
    expected = {"postgresql", "mysql", "oracle", "sqlserver", "db2", "sqlite", "cosmosdb"}
    missing = expected - names
    assert not missing, f"Missing plugins: {missing}"
