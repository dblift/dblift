"""Provider contract matrix for native providers."""

from __future__ import annotations

import inspect

import pytest

from dblift.core.sql_model.dialect import (
    dialect_clean_strategy,
    dialect_supports_transactional_ddl,
    dialect_supports_transactions,
)
from dblift.db.base_provider import BaseProvider, NativeProvider
from dblift.db.provider_registry import ProviderRegistry


@pytest.fixture(scope="module")
def plugins():
    return ProviderRegistry.list_plugins()


@pytest.mark.unit
def test_all_registered_providers_subclass_base_provider(plugins):
    for plugin in plugins:
        assert issubclass(plugin.provider_class, BaseProvider), plugin.name


@pytest.mark.unit
def test_all_plugins_declare_native_transport_metadata(plugins):
    for plugin in plugins:
        assert plugin.transport == "native", plugin.name


@pytest.mark.unit
def test_native_providers_are_not_required_to_expose_native_driver_metadata(plugins):
    for plugin in plugins:
        if plugin.transport != "native":
            continue
        assert issubclass(plugin.provider_class, NativeProvider), plugin.name


@pytest.mark.unit
def test_transaction_capabilities_match_dialect_matrix(plugins):
    for plugin in plugins:
        provider = plugin.provider_class.__new__(plugin.provider_class)
        dialect = plugin.name
        assert provider.supports_transactions() is dialect_supports_transactions(dialect), dialect
        assert provider.supports_transactional_ddl() is dialect_supports_transactional_ddl(
            dialect
        ), dialect


@pytest.mark.unit
def test_native_clean_dialects_expose_provider_clean_preview(plugins):
    for plugin in plugins:
        for dialect in plugin.dialects:
            if dialect_clean_strategy(dialect) == "native":
                assert hasattr(plugin.provider_class, "get_clean_preview"), plugin.name


@pytest.mark.unit
def test_locking_api_shape_is_provider_level(plugins):
    for plugin in plugins:
        acquire_sig = inspect.signature(plugin.provider_class.acquire_migration_lock)
        release_sig = inspect.signature(plugin.provider_class.release_migration_lock)

        assert list(acquire_sig.parameters) == [
            "self",
            "schema",
            "wait_timeout_seconds",
        ], plugin.name
        assert acquire_sig.parameters["wait_timeout_seconds"].default == 60, plugin.name
        assert list(release_sig.parameters) == ["self", "schema"], plugin.name
