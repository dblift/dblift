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
    QuirksExtensionCompositionError,
    clear_quirks_extensions,
    compose_quirks_class,
    register_quirks_extension,
    validate_quirks_extensions,
)
from core.sql_model import table_options
from core.sql_model.table import Table
from core.sql_model.table_options import MySqlTableOptions, TableOptions
from db.base_quirks import BaseQuirks
from db.plugins.postgresql.quirks import PostgresqlQuirks
from db.plugins.sqlite.quirks import SqliteQuirks
from db.plugins.sqlserver.quirks import SqlserverQuirks
from db.provider_registry import ProviderRegistry


@pytest.fixture(autouse=True)
def _clean_extension_registry() -> Iterator[None]:
    """Registration is global state — no test may leak into the next.

    ``table_options._namespace_cache`` is cleared alongside it: it memoises
    capability ownership for the life of the process, so a test that resolves
    a namespace while an extension is registered would otherwise hand its
    answer to every later test in the same process.
    """
    ProviderRegistry.discover_plugins()
    clear_quirks_extensions()
    table_options._namespace_cache.clear()
    yield
    clear_quirks_extensions()
    table_options._namespace_cache.clear()


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


# ---------------------------------------------------------------------------
# Capability ownership survives composition
# ---------------------------------------------------------------------------


def test_extension_does_not_orphan_the_dialect_capability_ownership() -> None:
    """A purely-additive extension must not cost MySQL its capability.

    ``canonical_dialect_name_for_capability`` reads the class body only, so
    an inheriting plugin does not become a second owner. The composed class
    is built with an *empty* namespace, so ownership has to be resolved from
    the pre-composition class or the dialect owns nothing at all.
    """
    register_quirks_extension(["mysql"], _AddsNewHook)

    owner = ProviderRegistry.canonical_dialect_name_for_capability(
        "table_uses_storage_engine_clause"
    )

    assert owner == "mysql"


@pytest.mark.parametrize(
    "capability, expected",
    [
        ("table_uses_storage_engine_clause", "mysql"),
        ("table_uses_filegroup_syntax", "sqlserver"),
        ("table_supports_inherits", "postgresql"),
        ("table_supports_storage_params", "oracle"),
    ],
)
def test_every_namespace_owning_capability_survives_an_extension(
    capability: str, expected: str
) -> None:
    """All four ``dialect_options`` namespace owners, not just MySQL."""
    register_quirks_extension([expected], _AddsNewHook)

    assert ProviderRegistry.canonical_dialect_name_for_capability(capability) == expected


def test_table_options_still_round_trip_with_an_extension_registered() -> None:
    """End to end: the namespace lookup feeds ``Table.from_options``.

    The cache is empty here because the autouse fixture cleared it, which is
    the real startup ordering: ``load_feature_extensions`` registers
    extensions before anything builds a ``Table``.
    """
    register_quirks_extension(["mysql"], _AddsNewHook)

    table = Table.from_options(
        "orders",
        [],
        options=TableOptions(
            mysql=MySqlTableOptions(storage_engine="InnoDB", row_format="COMPRESSED")
        ),
    )

    assert table.to_options().mysql.storage_engine == "InnoDB"
    assert table.to_options().mysql.row_format == "COMPRESSED"


# ---------------------------------------------------------------------------
# Collisions the extension inherits from its own lineage
# ---------------------------------------------------------------------------


class _SharedInternalMixin:
    """A tier package's own shared mixin — outside the core's lineage."""

    boolean_false_literal = "shadowed-by-parent"


class _InheritsTheShadowFromItsOwnParent(_SharedInternalMixin):
    """The colliding name arrives by inheritance, not from this class body."""

    def inherited_shadow_hook(self) -> str:
        return "extension"


class _TypedExtension(BaseQuirks):
    """Subclassing ``BaseQuirks`` for typing — the natural instinct, and legal."""

    def typed_extension_hook(self) -> str:
        return "typed"


def test_shadowing_inherited_from_the_extensions_own_parent_is_rejected() -> None:
    """A leaf-``vars`` check misses this, yet the parent still wins by MRO."""
    register_quirks_extension(["postgresql"], _InheritsTheShadowFromItsOwnParent)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("postgresql")

    message = str(excinfo.value)
    assert _INHERITED_BASE_HOOK in message
    assert "_InheritsTheShadowFromItsOwnParent" in message
    assert "_SharedInternalMixin" in message
    assert "BaseQuirks" in message


def test_an_extension_subclassing_base_quirks_raises_no_false_collision() -> None:
    """Every ``BaseQuirks`` name is in the base's own lineage, so none collides."""
    register_quirks_extension(["sqlserver"], _TypedExtension)

    quirks = ProviderRegistry.get_quirks("sqlserver")

    assert quirks.typed_extension_hook() == "typed"
    assert quirks.dialect_name == "sqlserver"


def test_a_base_quirks_extension_does_not_outrank_the_plugins_own_override() -> None:
    """The plugin's declaration must stay ahead of the ``BaseQuirks`` default."""
    plugin_value = vars(SqlserverQuirks)[_INHERITED_BASE_HOOK]
    assert plugin_value != vars(BaseQuirks)[_INHERITED_BASE_HOOK]

    register_quirks_extension(["sqlserver"], _TypedExtension)

    quirks = ProviderRegistry.get_quirks("sqlserver")
    assert getattr(quirks, _INHERITED_BASE_HOOK) == plugin_value


# ---------------------------------------------------------------------------
# Extension against extension
# ---------------------------------------------------------------------------


class _SecondPackageAddsTheSameHook:
    """A different package answering the hook :class:`_AddsNewHook` answers."""

    def dialect_extension_hook(self) -> str:
        return "second package"


class _ContributesNothingPublic:
    """Registered only so its own subclass can be registered after it."""


class _SubclassOfAnotherExtension(_ContributesNothingPublic):
    def subclass_extension_hook(self) -> str:
        return "subclass"


def test_two_extensions_answering_the_same_hook_are_rejected() -> None:
    """Silent resolution by registration order is the failure this seam prevents."""
    register_quirks_extension(["mysql"], _AddsNewHook)
    register_quirks_extension(["mysql"], _SecondPackageAddsTheSameHook)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    message = str(excinfo.value)
    assert "dialect_extension_hook" in message
    assert "_AddsNewHook" in message
    assert "_SecondPackageAddsTheSameHook" in message


class _SharedNewHookMixin:
    """A tier package's internal mixin, carrying a hook the core does not have."""

    def shared_new_hook(self) -> str:
        return "shared"


class _FirstUserOfTheSharedMixin(_SharedNewHookMixin):
    def first_only_hook(self) -> str:
        return "first"


class _SecondUserOfTheSharedMixin(_SharedNewHookMixin):
    def second_only_hook(self) -> str:
        return "second"


def test_two_extensions_sharing_a_mixin_are_not_a_collision() -> None:
    """One implementation reached through two extensions answers unambiguously."""
    register_quirks_extension(["mysql"], _FirstUserOfTheSharedMixin)
    register_quirks_extension(["mysql"], _SecondUserOfTheSharedMixin)

    quirks = ProviderRegistry.get_quirks("mysql")

    assert quirks.shared_new_hook() == "shared"
    assert quirks.first_only_hook() == "first"
    assert quirks.second_only_hook() == "second"


def test_registering_a_class_and_its_own_subclass_reports_what_the_caller_did() -> None:
    """Registration order (parent, child) is an unsatisfiable MRO."""
    register_quirks_extension(["mysql"], _ContributesNothingPublic)
    register_quirks_extension(["mysql"], _SubclassOfAnotherExtension)

    with pytest.raises(QuirksExtensionCompositionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    message = str(excinfo.value)
    assert "_ContributesNothingPublic" in message
    assert "_SubclassOfAnotherExtension" in message
    assert "mysql" in message


# ---------------------------------------------------------------------------
# Alias keying
# ---------------------------------------------------------------------------


def test_an_alias_resolves_the_extension_registered_for_the_canonical_name() -> None:
    """``sqlite3`` survives normalisation into ``config.database.type``."""
    register_quirks_extension(["sqlite"], _AddsNewHook)

    quirks = ProviderRegistry.get_quirks("sqlite3")

    assert quirks.dialect_extension_hook() == "extension"
    assert quirks.dialect_name == "sqlite3"


def test_registering_under_an_alias_reaches_the_canonical_dialect() -> None:
    """The other direction, so registration and lookup cannot drift apart."""
    register_quirks_extension(["mssql"], _AddsNewHook)

    assert ProviderRegistry.get_quirks("sqlserver").dialect_extension_hook() == "extension"


# ---------------------------------------------------------------------------
# Names composition itself owns
# ---------------------------------------------------------------------------


class _OverridesInit:
    def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: D107
        pass


class _DeclaresSlots:
    __slots__ = ("scratch",)

    def slotted_extension_hook(self) -> str:
        return "slotted"


def test_an_extension_defining_init_is_rejected() -> None:
    """``get_quirks`` calls ``composed(dialect_name=...)``; a shadowing
    ``__init__`` silently empties ``quirks.dialect_name``."""
    register_quirks_extension(["mysql"], _OverridesInit)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    assert "__init__" in str(excinfo.value)


def test_an_extension_declaring_slots_is_rejected() -> None:
    """``__slots__`` is about the composed instance layout, not a hook."""
    register_quirks_extension(["mysql"], _DeclaresSlots)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    assert "__slots__" in str(excinfo.value)
