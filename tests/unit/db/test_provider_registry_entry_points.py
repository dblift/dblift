"""Entry-point discovery tests (Epic 26 story 26-12).

Verifies that ``ProviderRegistry`` reads ``dblift.providers`` entry
points, registers their ``PluginInfo``, and that third-party plugins
can opt in without modifying ``core/`` or ``db/plugins/``.
"""

from __future__ import annotations

import dataclasses
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import db.plugins
from db.base_provider import BaseProvider
from db.base_quirks import BaseQuirks
from db.provider_registry import PluginInfo, ProviderRegistry

# Fields that ``_load_plugin`` derives itself from the filesystem/package
# scan (module name, dunder attrs, class introspection) and must therefore
# keep overriding on every load. Every other ``PluginInfo`` field belongs to
# the plugin's own ``plugin.py:PLUGIN`` declaration and must survive a
# filesystem-triggered reconstruction unchanged.
_FILESYSTEM_DERIVED_FIELDS = {
    "name",
    "version",
    "description",
    "dialects",
    "provider_class",
    "transport",
    "quirks_class",
}


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


def test_filesystem_discovery_does_not_reload_hyphenated_dir_mismatch(_reset_registry):
    """A plugin directory name that differs from its declared identity only
    by ``_`` vs ``-`` must not be treated as unregistered.

    ``db/plugins/aurora_postgresql`` (underscore directory) declares
    ``__plugin_name__ = "aurora-postgresql"`` and ``__plugin_dialects__ =
    ["aurora-postgresql"]`` (hyphen). The filesystem-discovery skip check in
    ``_discover_via_filesystem`` compares ``plugin_dir.name.lower()``
    (``"aurora_postgresql"``) against the registered keys verbatim, so a
    plugin already registered (e.g. via the entry-point pass) under
    ``"aurora-postgresql"`` is *not* recognised as already-registered, gets
    reloaded from the filesystem, and the freshly reconstructed
    ``PluginInfo`` clobbers the richer, previously-registered one.
    """
    from db.plugins.aurora_postgresql.plugin import PLUGIN as declared_aurora

    ProviderRegistry.register_plugin(declared_aurora)
    ProviderRegistry._discover_via_filesystem()

    assert (
        ProviderRegistry._plugins["aurora-postgresql"] is declared_aurora
    ), "filesystem discovery replaced the already-registered PluginInfo"


def test_load_plugin_preserves_all_non_filesystem_declared_fields(_reset_registry):
    """Guard against Defect A: ``_load_plugin``'s ``PluginInfo`` reconstruction
    must carry every field the filesystem scan does not itself derive.

    ``aurora-postgresql`` ships no ``provider.py`` / ``quirks.py`` of its own
    — its package-level derivation finds nothing usable, so ``_load_plugin``
    must fall back to whatever ``plugin.py:PLUGIN`` declared for everything
    the filesystem doesn't own (``config_dialect``, ``config_class``,
    ``sqlalchemy_url_builder``, ``native_driver_module``, ``install_extra``,
    and any field added to ``PluginInfo`` later), not just the ones a manual
    enumeration happens to remember.

    This iterates ``dataclasses.fields(PluginInfo)`` generically instead of
    naming each field, so a field added to ``PluginInfo`` after this test is
    written is still checked automatically — that is exactly the shape of
    bug that dropped ``install_extra`` previously (a field-by-field
    reconstruction that wasn't updated when the field was added).
    """
    from db.plugins.aurora_postgresql.plugin import PLUGIN as declared_aurora

    plugin_dir = Path(db.plugins.__file__).parent / "aurora_postgresql"
    loaded = ProviderRegistry._load_plugin(plugin_dir)

    assert loaded is not None
    for field in dataclasses.fields(PluginInfo):
        if field.name in _FILESYSTEM_DERIVED_FIELDS:
            continue
        assert getattr(loaded, field.name) == getattr(
            declared_aurora, field.name
        ), f"field {field.name!r} was dropped by the _load_plugin reconstruction"


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
