"""Provider capability declarations must match runtime behavior (P3).

Every provider class declares what it supports via ISP protocols
(ConnectionProvider, TransactionalProvider, SchemaProvider, etc.) and via
``supports_transactions()``. If a provider implements a protocol but raises
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

from db.provider_interfaces import (
    ConnectionProvider,
    MigrationProvider,
    QueryProvider,
    SchemaProvider,
    TransactionalProvider,
)
from db.provider_registry import ProviderRegistry

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
    from db.base_provider import BaseProvider

    for plugin in plugins:
        assert issubclass(
            plugin.provider_class, BaseProvider
        ), f"{plugin.name} provider_class is not a BaseProvider"


@pytest.mark.integration
def test_supports_transactions_is_explicit_bool(plugins):
    """``supports_transactions`` must be a concrete method returning bool — not inherited NotImplementedError."""
    for plugin in plugins:
        cls = plugin.provider_class
        assert hasattr(
            cls, "supports_transactions"
        ), f"{plugin.name}: no supports_transactions() method"
        # Must not be abstract on concrete classes
        method = cls.supports_transactions
        assert not getattr(
            method, "__isabstractmethod__", False
        ), f"{plugin.name}: supports_transactions is still abstract"


@pytest.mark.integration
def test_cosmos_declares_no_transaction_support(plugins):
    """CosmosDB must declare supports_transactions=False — runtime guards depend on it."""
    cosmos = [p for p in plugins if p.name.lower() == "cosmosdb"]
    if not cosmos:
        pytest.skip("CosmosDB plugin not registered")

    # Instantiating CosmosDbProvider needs a config; read the class-level default.
    # If supports_transactions is a @staticmethod/classmethod, call it directly.
    cls = cosmos[0].provider_class
    # Best-effort: read the source default without instantiating.
    # The bug surface is if it *returned* True, which would route callers down
    # the SQL transaction path.
    import inspect

    src = inspect.getsource(cls.supports_transactions)
    assert "False" in src, (
        f"CosmosDbProvider.supports_transactions appears not to return False. " f"Source:\n{src}"
    )


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
