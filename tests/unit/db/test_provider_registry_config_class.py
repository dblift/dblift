"""Tests for the ``config_class`` field on :class:`PluginInfo` (roadmap action #11).

The field lets a third-party plugin ship its own ``BaseDatabaseConfig`` subclass
without modifying ``config/_subclasses/`` or the eager-import block at the bottom
of ``config/database_config.py``. ``_resolve_config_class`` in
``config/database_config.py`` consults ``PluginInfo.config_class`` as Path 2 of
the resolution chain (legacy ``_registry`` first, then plugin-declared
``config_class``, then ``config_dialect`` parent fallback).
"""

from __future__ import annotations

from dataclasses import dataclass
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from config.database_config import BaseDatabaseConfig, _resolve_config_class
from db.base_provider import BaseProvider
from db.base_quirks import BaseQuirks
from db.provider_registry import PluginInfo, ProviderRegistry

# ---------------------------------------------------------------------------
# Synthetic plugin: a minimal but valid third-party plugin that ships its own
# config class. Used to verify the new resolution path end-to-end.
# ---------------------------------------------------------------------------


@dataclass
class _ThirdPartyConfig(BaseDatabaseConfig):
    """Third-party config subclass — declared OUTSIDE ``config/_subclasses/``."""

    def build_connection_string(self) -> str:  # pragma: no cover - not invoked by these tests
        return f"thirdpartydb://{self.url}"

    def build_database_url(self) -> str:  # pragma: no cover - not invoked by these tests
        return self.url or ""

    @classmethod
    def get_database_type(cls) -> str:
        return "thirdpartydb"


class _ThirdPartyProvider(BaseProvider):
    """Minimal provider to satisfy ``PluginInfo.provider_class`` typing."""

    @classmethod
    def create_migration_history_table_if_not_exists(  # type: ignore[override]
        cls, *_args: Any, **_kwargs: Any
    ) -> None:
        pass

    @classmethod
    def create_snapshot_table_if_not_exists(  # type: ignore[override]
        cls, *_args: Any, **_kwargs: Any
    ) -> None:
        pass


class _ThirdPartyQuirks(BaseQuirks):
    def __init__(self, dialect_name: str = "thirdpartydb") -> None:
        super().__init__(dialect_name=dialect_name)


def _build_third_party_sqlalchemy_url(database_config: Any) -> str:
    return f"thirdpartydb:///{database_config.database}"


_THIRD_PARTY_PLUGIN = PluginInfo(
    name="thirdpartydb",
    version="0.1.0",
    description="Synthetic third-party plugin for config_class tests",
    dialects=["thirdpartydb"],
    provider_class=_ThirdPartyProvider,
    transport="native",
    quirks_class=_ThirdPartyQuirks,
    config_class=_ThirdPartyConfig,
    sqlalchemy_url_builder=_build_third_party_sqlalchemy_url,
)


@pytest.fixture
def _reset_registry():
    """Snapshot + restore the registry global state across the test."""
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_quirks_cache = dict(ProviderRegistry._quirks_cache)
    saved_discovered = ProviderRegistry._discovered
    saved_legacy_registry = dict(BaseDatabaseConfig._registry)
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._quirks_cache.clear()
    ProviderRegistry._quirks_cache.update(saved_quirks_cache)
    ProviderRegistry._discovered = saved_discovered
    BaseDatabaseConfig._registry.clear()
    BaseDatabaseConfig._registry.update(saved_legacy_registry)


# ---------------------------------------------------------------------------
# Schema-level assertions: the field is declared and propagates.
# ---------------------------------------------------------------------------


def test_plugin_info_exposes_config_class_field():
    """The ``config_class`` field must be part of the ``PluginInfo`` schema."""
    fields = {f.name for f in PluginInfo.__dataclass_fields__.values()}
    assert "config_class" in fields


def test_plugin_info_exposes_sqlalchemy_url_builder_field():
    """SQLAlchemy URL construction must be a plugin metadata hook."""
    fields = {f.name for f in PluginInfo.__dataclass_fields__.values()}
    assert "sqlalchemy_url_builder" in fields


def test_config_class_defaults_to_none():
    """A plugin that doesn't declare a config class must default to ``None``
    so the legacy ``_registry`` and ``config_dialect`` paths stay active."""
    pi = PluginInfo(
        name="bare",
        version="0.0.0",
        description="",
        dialects=["bare"],
        provider_class=_ThirdPartyProvider,
        transport="native",
    )
    assert pi.config_class is None
    assert pi.sqlalchemy_url_builder is None


def test_first_party_plugins_now_declare_config_class(_reset_registry):
    """Every first-party plugin must declare its config class on the
    PluginInfo so the new resolution path is the canonical one."""
    ProviderRegistry.discover_plugins()

    # mariadb relies on ``config_dialect="mysql"``; it intentionally has no
    # config_class of its own.
    direct_class_dialects = (
        "postgresql",
        "mysql",
        "oracle",
        "sqlserver",
        "db2",
        "sqlite",
        "cosmosdb",
    )
    for dialect in direct_class_dialects:
        plugin = ProviderRegistry._plugins.get(dialect)
        assert plugin is not None, f"{dialect} plugin missing from registry"
        assert (
            plugin.config_class is not None
        ), f"{dialect} plugin must declare config_class on its PluginInfo"
        assert isinstance(plugin.config_class, type)
        assert issubclass(plugin.config_class, BaseDatabaseConfig)


# ---------------------------------------------------------------------------
# Resolution-chain behaviour.
# ---------------------------------------------------------------------------


def test_third_party_config_class_resolves_through_plugin_metadata(_reset_registry):
    """A third-party plugin that declares ``config_class`` on its PluginInfo
    must be reachable by ``_resolve_config_class`` without ever touching the
    legacy ``@register_database_type`` decorator path."""
    # The third-party config is NOT registered via the decorator; insert
    # the plugin metadata directly.
    ProviderRegistry._plugins["thirdpartydb"] = _THIRD_PARTY_PLUGIN
    ProviderRegistry._discovered = True
    assert "thirdpartydb" not in BaseDatabaseConfig._registry

    resolved = _resolve_config_class(BaseDatabaseConfig, "thirdpartydb")

    assert resolved is _ThirdPartyConfig


def test_sqlalchemy_url_builder_resolves_through_plugin_metadata(_reset_registry):
    """A third-party plugin owns its SQLAlchemy URL construction."""
    ProviderRegistry._plugins["thirdpartydb"] = _THIRD_PARTY_PLUGIN
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(type="thirdpartydb", database="app")

    url = ProviderRegistry.build_sqlalchemy_url(database_config)

    assert url == "thirdpartydb:///app"


def test_missing_sqlalchemy_url_builder_raises(_reset_registry):
    """Native connection setup fails clearly if the plugin has no URL builder."""
    plugin_without_builder = PluginInfo(
        name="thirdpartydb",
        version="0.1.0",
        description="",
        dialects=["thirdpartydb"],
        provider_class=_ThirdPartyProvider,
        transport="native",
        config_class=_ThirdPartyConfig,
    )
    ProviderRegistry._plugins["thirdpartydb"] = plugin_without_builder
    ProviderRegistry._discovered = True
    database_config = SimpleNamespace(type="thirdpartydb", database="app")

    with pytest.raises(ValueError, match="thirdpartydb plugin must declare"):
        ProviderRegistry.build_sqlalchemy_url(database_config)


def test_legacy_registry_wins_when_both_paths_populated(_reset_registry):
    """If a dialect is in both ``_registry`` and ``plugin.config_class``, the
    legacy path must win — protects backward compat for any caller that has
    intentionally swapped the legacy class via direct registry manipulation."""
    BaseDatabaseConfig._registry["thirdpartydb"] = _ThirdPartyConfig

    class _Override(_ThirdPartyConfig):
        pass

    overriding_plugin = PluginInfo(
        name="thirdpartydb",
        version="0.1.0",
        description="",
        dialects=["thirdpartydb"],
        provider_class=_ThirdPartyProvider,
        transport="native",
        config_class=_Override,
    )
    ProviderRegistry._plugins["thirdpartydb"] = overriding_plugin
    ProviderRegistry._discovered = True

    resolved = _resolve_config_class(BaseDatabaseConfig, "thirdpartydb")

    assert resolved is _ThirdPartyConfig
    assert resolved is not _Override


def test_config_dialect_parent_fallback_still_works(_reset_registry):
    """A plugin that ships ``config_dialect=<parent>`` (no direct
    ``config_class``) must still resolve through the parent's registry
    entry — the MariaDB → MySQL path."""
    BaseDatabaseConfig._registry["thirdpartyparent"] = _ThirdPartyConfig
    aliasing_plugin = PluginInfo(
        name="thirdpartychild",
        version="0.0.1",
        description="",
        dialects=["thirdpartychild"],
        provider_class=_ThirdPartyProvider,
        transport="native",
        config_dialect="thirdpartyparent",
    )
    ProviderRegistry._plugins["thirdpartychild"] = aliasing_plugin
    ProviderRegistry._discovered = True

    resolved = _resolve_config_class(BaseDatabaseConfig, "thirdpartychild")

    assert resolved is _ThirdPartyConfig


def test_unknown_dialect_returns_none(_reset_registry):
    """A dialect with no registry entry, no plugin metadata, and no parent
    fallback must return ``None`` so the caller can choose between
    ``_allow_incomplete`` and ``ValueError``."""
    ProviderRegistry._discovered = True
    assert _resolve_config_class(BaseDatabaseConfig, "totallyunknown") is None


def test_plugin_config_class_must_subclass_base_database_config(_reset_registry):
    """Defensive: a misconfigured plugin that ships a ``config_class`` not
    derived from ``BaseDatabaseConfig`` must be ignored so it can't silently
    swap the contract — fall through to the next resolution path instead."""

    class _NotAConfig:
        pass

    BaseDatabaseConfig._registry["thirdpartyparent"] = _ThirdPartyConfig
    misconfigured_plugin = PluginInfo(
        name="thirdpartymisconfigured",
        version="0.0.1",
        description="",
        dialects=["thirdpartymisconfigured"],
        provider_class=_ThirdPartyProvider,
        transport="native",
        config_dialect="thirdpartyparent",  # parent fallback should kick in
        config_class=_NotAConfig,  # type: ignore[arg-type]
    )
    ProviderRegistry._plugins["thirdpartymisconfigured"] = misconfigured_plugin
    ProviderRegistry._discovered = True

    resolved = _resolve_config_class(BaseDatabaseConfig, "thirdpartymisconfigured")

    # Path 2 rejected the bad class; Path 3 (parent fallback) succeeds.
    assert resolved is _ThirdPartyConfig


# ---------------------------------------------------------------------------
# Discovery integration: plugin.py declares the field via filesystem path.
# ---------------------------------------------------------------------------


def test_discovery_threads_config_class_from_plugin_py(_reset_registry):
    """A ``plugin.py`` discovered through the entry-point group must propagate
    ``config_class`` from its ``PLUGIN`` constant into the registered
    ``PluginInfo``."""
    fake_ep = SimpleNamespace(name="thirdpartydb", value="x:y", load=lambda: _THIRD_PARTY_PLUGIN)

    with patch("importlib.metadata.entry_points", return_value=[fake_ep]):
        ProviderRegistry._discover_via_entry_points()

    assert "thirdpartydb" in ProviderRegistry._plugins
    plugin = ProviderRegistry._plugins["thirdpartydb"]
    assert plugin.config_class is _ThirdPartyConfig
