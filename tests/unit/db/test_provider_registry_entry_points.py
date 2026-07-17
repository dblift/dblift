"""Entry-point discovery tests (Epic 26 story 26-12).

Verifies that ``ProviderRegistry`` reads ``dblift.providers`` entry
points, registers their ``PluginInfo``, and that third-party plugins
can opt in without modifying ``core/`` or ``db/plugins/``.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from db.base_provider import BaseProvider
from db.base_quirks import BaseQuirks
from db.provider_registry import PluginInfo, ProviderRegistry


class _FakeProvider(BaseProvider):
    """Minimal in-test provider used by the synthetic entry-point."""

    @classmethod
    def create_migration_history_table_if_not_exists(  # type: ignore[override]
        cls, *_args, **_kwargs
    ) -> None:
        pass

    @classmethod
    def create_snapshot_table_if_not_exists(  # type: ignore[override]
        cls, *_args, **_kwargs
    ) -> None:
        pass


class _FakeQuirks(BaseQuirks):
    def __init__(self, dialect_name: str = "fakedb") -> None:
        super().__init__(dialect_name=dialect_name)


_FAKE_PLUGIN = PluginInfo(
    name="fakedb",
    version="0.0.1",
    description="Synthetic plugin for entry-point discovery test",
    dialects=["fakedb"],
    provider_class=_FakeProvider,
    transport="native",
    quirks_class=_FakeQuirks,
)


@pytest.fixture
def _reset_registry():
    """Snapshot + restore ProviderRegistry global state across the test."""
    saved_plugins = dict(ProviderRegistry._plugins)
    saved_quirks_cache = dict(ProviderRegistry._quirks_cache)
    saved_discovered = ProviderRegistry._discovered
    ProviderRegistry._plugins.clear()
    ProviderRegistry._quirks_cache.clear()
    ProviderRegistry._discovered = False
    yield
    ProviderRegistry._plugins.clear()
    ProviderRegistry._plugins.update(saved_plugins)
    ProviderRegistry._quirks_cache.clear()
    ProviderRegistry._quirks_cache.update(saved_quirks_cache)
    ProviderRegistry._discovered = saved_discovered


def test_entry_point_pass_registers_plugin(_reset_registry):
    """A ``dblift.providers`` entry-point that returns a ``PluginInfo``
    must end up in ``ProviderRegistry._plugins`` after discovery."""
    fake_ep = SimpleNamespace(name="fakedb", value="x:y", load=lambda: _FAKE_PLUGIN)

    with patch("importlib.metadata.entry_points", return_value=[fake_ep]):
        ProviderRegistry._discover_via_entry_points()

    assert "fakedb" in ProviderRegistry._plugins
    plugin = ProviderRegistry._plugins["fakedb"]
    assert plugin.provider_class is _FakeProvider
    assert plugin.quirks_class is _FakeQuirks


def test_entry_point_returning_non_plugin_info_is_ignored(_reset_registry):
    """A misconfigured entry-point that returns a non-PluginInfo value
    must be skipped without breaking discovery of other plugins."""
    bad_ep = SimpleNamespace(name="bad", value="x:y", load=lambda: "not a PluginInfo")
    good_ep = SimpleNamespace(name="fakedb", value="x:y", load=lambda: _FAKE_PLUGIN)

    with patch("importlib.metadata.entry_points", return_value=[bad_ep, good_ep]):
        ProviderRegistry._discover_via_entry_points()

    assert "bad" not in ProviderRegistry._plugins
    assert "fakedb" in ProviderRegistry._plugins


def test_entry_point_load_failure_does_not_break_other_plugins(_reset_registry):
    """An exception during ``ep.load()`` must not abort the loop."""

    def _raise():
        raise RuntimeError("boom")

    bad_ep = SimpleNamespace(name="bad", value="x:y", load=_raise)
    good_ep = SimpleNamespace(name="fakedb", value="x:y", load=lambda: _FAKE_PLUGIN)

    with patch("importlib.metadata.entry_points", return_value=[bad_ep, good_ep]):
        ProviderRegistry._discover_via_entry_points()

    assert "bad" not in ProviderRegistry._plugins
    assert "fakedb" in ProviderRegistry._plugins


def test_filesystem_fallback_skips_already_registered(_reset_registry):
    """If a plugin is already registered (e.g. via entry-points), the
    filesystem scan must not re-register it.

    Pre-register the postgresql plugin under its dir-name key, then run
    the filesystem scan — it should leave the registration untouched.
    """
    # Pre-register an obviously-fake stand-in keyed at "postgresql".
    ProviderRegistry._plugins["postgresql"] = _FAKE_PLUGIN
    ProviderRegistry._discover_via_filesystem()
    # The pre-registered entry must still be ours.
    assert ProviderRegistry._plugins["postgresql"] is _FAKE_PLUGIN


def test_first_party_plugins_round_trip_through_full_discovery(_reset_registry):
    """``discover_plugins`` (entry-point + filesystem) must end up with
    all first-party plugins registered, regardless of which path
    finds each one."""
    ProviderRegistry.discover_plugins()
    for dialect in (
        "postgresql",
        "mysql",
        "mariadb",
        "oracle",
        "sqlserver",
        "db2",
        "sqlite",
        "cosmosdb",
        "duckdb",
        "neon",
        "supabase",
        "aurora-postgresql",
        "alloydb",
        "yugabytedb",
        "timescaledb",
        "citus",
        "cockroachdb",
        "redshift",
        "snowflake",
    ):
        assert dialect in ProviderRegistry._plugins, f"{dialect} not registered"
