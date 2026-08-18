"""Contract tests for the dialect-quirks extension seam.

``core/seams/quirks.py`` lets an installed package **add** hooks to a
dialect's quirks class without editing the in-tree plugin. It may not
answer a hook the core already answers: a hook the core defines is a
statement about the database engine, and a second answer for it belongs
upstream in the core. Shadowing therefore raises
:class:`QuirksExtensionCollisionError` instead of quietly winning by MRO.

Companion to ``test_dialect_quirks_conformance.py``, which guards the
``BaseQuirks`` surface itself.
"""

from __future__ import annotations

from typing import Iterator

import pytest

from core.seams.quirks import (
    QuirksExtensionCollisionError,
    clear_quirks_extensions,
    compose_quirks_class,
    register_quirks_extension,
    validate_quirks_extensions,
)
from db.base_quirks import BaseQuirks
from db.plugins.postgresql.quirks import PostgresqlQuirks
from db.plugins.sqlite.quirks import SqliteQuirks
from db.provider_registry import ProviderRegistry


@pytest.fixture(autouse=True)
def _clean_extension_registry() -> Iterator[None]:
    """Registration is global state — no test may leak into the next."""
    ProviderRegistry.discover_plugins()
    clear_quirks_extensions()
    yield
    clear_quirks_extensions()


#: A hook ``BaseQuirks`` defines and the PostgreSQL plugin inherits unchanged.
#: Shadowing it is the case that only an MRO-wide check catches.
_INHERITED_BASE_HOOK = "boolean_false_literal"


class _PluginOwnedQuirks(BaseQuirks):
    """Stands in for a plugin quirks class that declares a hook of its own."""

    def plugin_owned_hook(self) -> str:
        return "plugin"


class _AddsNewHook:
    """Extension adding a hook no quirks class in the tree defines."""

    def dialect_extension_hook(self) -> str:
        return "extension"


class _AddsSecondNewHook:
    """Second extension, disjoint from :class:`_AddsNewHook`."""

    def another_extension_hook(self) -> str:
        return "second"


class _ShadowsInheritedHook:
    """Extension redefining a hook the plugin inherits from ``BaseQuirks``."""

    boolean_false_literal = "shadowed"


class _ShadowsPluginOwnedHook:
    """Extension redefining a hook declared on the plugin's own class."""

    def plugin_owned_hook(self) -> str:
        return "shadowed"


def test_probe_hooks_still_sit_where_the_shadowing_tests_assume() -> None:
    """The two shadowing tests are only meaningful while this holds."""
    assert _INHERITED_BASE_HOOK in vars(BaseQuirks)
    assert _INHERITED_BASE_HOOK not in vars(PostgresqlQuirks)
    assert _INHERITED_BASE_HOOK in vars(_ShadowsInheritedHook)
    assert "plugin_owned_hook" in vars(_PluginOwnedQuirks)
    assert "plugin_owned_hook" not in vars(BaseQuirks)


def test_extension_hook_is_reachable_through_get_quirks() -> None:
    """The point of the seam: an added hook resolves on the live instance."""
    register_quirks_extension(["mysql"], _AddsNewHook)

    quirks = ProviderRegistry.get_quirks("mysql")

    assert quirks.dialect_extension_hook() == "extension"
    assert isinstance(quirks, BaseQuirks)
    assert quirks.dialect_name == "mysql"


def test_shadowing_a_hook_inherited_from_base_quirks_is_rejected() -> None:
    """The hook is on ``BaseQuirks``, not on ``PostgresqlQuirks`` — still a collision."""
    register_quirks_extension(["postgresql"], _ShadowsInheritedHook)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("postgresql")

    message = str(excinfo.value)
    assert _INHERITED_BASE_HOOK in message
    assert "_ShadowsInheritedHook" in message
    assert "BaseQuirks" in message


def test_shadowing_a_hook_declared_by_the_plugin_class_is_rejected() -> None:
    """The other half: a hook the plugin itself declares is equally off limits."""
    register_quirks_extension(["fake-dialect"], _ShadowsPluginOwnedHook)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        compose_quirks_class("fake-dialect", _PluginOwnedQuirks)

    message = str(excinfo.value)
    assert "plugin_owned_hook" in message
    assert "_ShadowsPluginOwnedHook" in message
    assert "_PluginOwnedQuirks" in message


def test_two_extensions_precede_the_base_in_registration_order() -> None:
    """Composition order is registration order, base last."""
    register_quirks_extension(["sqlite"], _AddsNewHook)
    register_quirks_extension(["sqlite"], _AddsSecondNewHook)

    composed = compose_quirks_class("sqlite", SqliteQuirks)

    assert composed.__mro__[1:4] == (_AddsNewHook, _AddsSecondNewHook, SqliteQuirks)

    quirks = ProviderRegistry.get_quirks("sqlite")
    assert quirks.dialect_extension_hook() == "extension"
    assert quirks.another_extension_hook() == "second"


def test_registering_after_a_dialect_was_resolved_invalidates_the_cache() -> None:
    """``_quirks_cache`` must not serve a pre-extension instance forever."""
    before = ProviderRegistry.get_quirks("oracle")
    assert not hasattr(before, "dialect_extension_hook")

    register_quirks_extension(["oracle"], _AddsNewHook)

    after = ProviderRegistry.get_quirks("oracle")
    assert after.dialect_extension_hook() == "extension"
    assert after.dialect_name == "oracle"


def test_validate_raises_for_a_dialect_that_was_never_resolved() -> None:
    """A collision on an unused dialect must still fail loudly at load time."""
    register_quirks_extension(["db2"], _ShadowsInheritedHook)
    assert "db2" not in ProviderRegistry._quirks_cache

    with pytest.raises(QuirksExtensionCollisionError):
        validate_quirks_extensions()


def test_validate_is_a_no_op_without_registrations() -> None:
    """Pure-core installs pay nothing and see nothing."""
    validate_quirks_extensions()


def test_without_extensions_no_dynamic_subclass_is_created() -> None:
    """No extension registered means the plugin class is returned untouched."""
    assert compose_quirks_class("postgresql", PostgresqlQuirks) is PostgresqlQuirks
    assert type(ProviderRegistry.get_quirks("postgresql")) is PostgresqlQuirks


@pytest.mark.parametrize("dialect", ["neon", "timescaledb"])
def test_postgresql_extension_does_not_leak_into_wire_compatible_dialects(
    dialect: str,
) -> None:
    """Registration is per dialect key; PG-wire engines are separate dialects."""
    register_quirks_extension(["postgresql"], _AddsNewHook)
    assert ProviderRegistry.get_quirks("postgresql").dialect_extension_hook() == "extension"

    plugin_info = ProviderRegistry.get_plugin_info(dialect)
    assert plugin_info is not None and plugin_info.quirks_class is not None

    quirks = ProviderRegistry.get_quirks(dialect)
    assert type(quirks) is plugin_info.quirks_class
    assert not hasattr(quirks, "dialect_extension_hook")
