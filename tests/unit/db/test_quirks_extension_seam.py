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

import abc
import enum
import re
from abc import ABCMeta
from dataclasses import dataclass
from typing import Dict, Generic, Iterator, List, NamedTuple, Protocol, Tuple, TypeVar

import pytest

from dblift.core.seams.quirks import (
    _DUNDER_REASONS,
    _EXTENSION_SHAPE_ADVICE,
    _GENERIC_DUNDER_REASON,
    QuirksExtensionCollisionError,
    QuirksExtensionCompositionError,
    clear_quirks_extensions,
    compose_quirks_class,
    register_quirks_extension,
    validate_quirks_extensions,
)
from dblift.core.sql_model import table_options
from dblift.core.sql_model.table import Table
from dblift.core.sql_model.table_options import MySqlTableOptions, TableOptions
from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks
from dblift.db.plugins.sqlite.quirks import SqliteQuirks
from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks
from dblift.db.provider_registry import ProviderRegistry


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


def _rejected_name(message: str) -> str:
    """The name a rejection message quotes.

    Read out of the message rather than asserted by hand: which dunder a
    class contributing several of them trips on *first* is ``vars()``
    ordering, and a test naming one of them pins an implementation detail of
    CPython instead of the seam's decision.
    """
    match = re.search(r"\bdefines '([^']+)'", message)
    assert match is not None, f"no rejected name in message: {message}"
    return match.group(1)


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


class _RefusesToBeComposed(type):
    """A metaclass that rejects being used as a base, with a non-``TypeError``.

    ``bases`` is empty only for :class:`_ExtensionWithACustomMetaclass` itself,
    so the refusal fires when ``compose_quirks_class`` builds the composed
    class and not at import.
    """

    def __new__(
        mcls,
        name: str,
        bases: Tuple[type, ...],
        namespace: Dict[str, object],
        **kwargs: object,
    ) -> "_RefusesToBeComposed":
        if bases:
            raise ValueError("metaclass refuses this composition")
        return super().__new__(mcls, name, bases, namespace, **kwargs)


class _ExtensionWithACustomMetaclass(metaclass=_RefusesToBeComposed):
    """A metaclass contributes nothing to ``vars()``, so no guard sees it."""

    def metaclass_extension_hook(self) -> str:
        return "metaclass"


def test_a_metaclass_refusing_composition_is_reported_as_a_composition_error() -> None:
    """Whatever a metaclass raises has to arrive as a seam error, not raw.

    No guard can cover this ahead of ``type(...)``: a metaclass is not a name
    in the extension's ``vars()``, which holds only neutral bookkeeping and
    the hook, so composition is reached and the metaclass decides.
    ``validate_quirks_extensions`` is called outside
    ``load_feature_extensions``'s per-entry-point ``try``/``except``, so an
    exception left untranslated escapes CLI startup with nothing tying it to
    quirks composition.
    """
    register_quirks_extension(["mysql"], _ExtensionWithACustomMetaclass)

    with pytest.raises(QuirksExtensionCompositionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    message = str(excinfo.value)
    assert "metaclass refuses this composition" in message
    assert "_ExtensionWithACustomMetaclass" in message
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


# ---------------------------------------------------------------------------
# Dunders the enumeration used to wave through
# ---------------------------------------------------------------------------
#
# ``__init__`` and ``__slots__`` were named explicitly and every other
# underscore name was skipped, so the rule was a denylist of two. These
# classes are the dunders that denylist let past, each of which re-answers
# something the composed class already answers.


class _DefinesGetattribute:
    """Intercepts every attribute read on the composed instance."""

    def __getattribute__(self, name: str) -> object:
        if name == _INHERITED_BASE_HOOK:
            return "HIJACKED"
        return object.__getattribute__(self, name)


class _DefinesGetattr:
    """Answers every hook that does not exist, so ``hasattr`` is always true."""

    def __getattr__(self, name: str) -> str:
        return "invented"


#: Every class :class:`_DefinesInitSubclass` saw created, so a test can assert
#: the hook never ran rather than only that composition raised.
_INIT_SUBCLASS_CALLS: List[type] = []


class _DefinesInitSubclass:
    """A package mixin auto-registering its subclasses — a mainstream idiom.

    ``compose_quirks_class`` builds the composed class with ``type(...)``,
    which *is* a subclass creation, so this fires during composition and
    writes into the composed class's own namespace — MRO position 0, ahead of
    every extension and the base.
    """

    def __init_subclass__(cls, **kwargs: object) -> None:
        super().__init_subclass__(**kwargs)
        _INIT_SUBCLASS_CALLS.append(cls)
        setattr(cls, _INHERITED_BASE_HOOK, "INJECTED-AT-COMPOSITION")


class _DefinesNew:
    """Controls construction of the composed instance."""

    def __new__(cls, *args: object, **kwargs: object) -> "_DefinesNew":
        return super().__new__(cls)


@dataclass
class _DataclassExtension:
    """``@dataclass`` generates ``__init__``, so the seam must reject it."""

    scratch: str = "generated"

    def dataclass_extension_hook(self) -> str:
        return "dataclass"


class _ParentWithInit:
    def __init__(self, *args: object, **kwargs: object) -> None:  # noqa: D107
        pass


class _InheritsInitFromItsOwnParent(_ParentWithInit):
    """The ``__init__`` arrives by inheritance, not from this class body."""

    def inherited_init_hook(self) -> str:
        return "inherited"


@pytest.mark.parametrize(
    "extension, name",
    [
        (_OverridesInit, "__init__"),
        (_DeclaresSlots, "__slots__"),
        (_DefinesGetattribute, "__getattribute__"),
        (_DefinesGetattr, "__getattr__"),
        (_DefinesInitSubclass, "__init_subclass__"),
        (_DefinesNew, "__new__"),
    ],
)
def test_an_extension_defining_a_composition_dunder_is_rejected(extension: type, name: str) -> None:
    """None of these adds a hook; each re-answers what composition owns.

    The wording is asserted, not just the quoted name: the message is built
    from module constants that nothing else pins, so emptying
    :data:`_DUNDER_REASONS` or dropping the advice used to change what an
    author reads without failing a single test.

    The reason is *indexed*, and the one name with no reason of its own is
    the one case naming :data:`_GENERIC_DUNDER_REASON`. Writing the lookup as
    ``.get(name, _GENERIC_DUNDER_REASON)`` would mirror the message's own
    expression, so an emptied ``_DUNDER_REASONS`` would still pass — with
    every rejection carrying the generic reason the test then asked for.
    """
    register_quirks_extension(["mysql"], extension)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    message = str(excinfo.value)
    assert name in message
    assert extension.__name__ in message
    expected_reason = _GENERIC_DUNDER_REASON if name == "__new__" else _DUNDER_REASONS[name]
    assert expected_reason in message
    assert _EXTENSION_SHAPE_ADVICE in message


def test_an_init_subclass_extension_never_reaches_composition() -> None:
    """The rejection has to precede ``type()``, or the hook has already run.

    Raising after composition would be no protection: the injected
    ``boolean_false_literal`` sits in the composed class's own namespace,
    ahead of every extension and the base.
    """
    _INIT_SUBCLASS_CALLS.clear()
    register_quirks_extension(["mysql"], _DefinesInitSubclass)

    with pytest.raises(QuirksExtensionCollisionError):
        compose_quirks_class("mysql", ProviderRegistry.quirks_base_class("mysql"))

    assert _INIT_SUBCLASS_CALLS == []


def test_a_dataclass_extension_is_rejected() -> None:
    """``@dataclass`` writes dunders the author never named.

    Which one the guard reaches first is ``vars()`` ordering — here
    ``__dataclass_params__``, not the ``__init__`` this test was written
    for — so the assertion names neither. What it pins is that the reported
    name is a dunder ``@dataclass`` generated rather than one the class body
    declares, and that the class is refused.
    """
    register_quirks_extension(["mysql"], _DataclassExtension)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    message = str(excinfo.value)
    assert "_DataclassExtension" in message
    assert _rejected_name(message) in vars(_DataclassExtension)


def test_an_extension_inheriting_init_from_its_own_parent_is_rejected() -> None:
    """A leaf-``vars`` check misses it, yet the parent still wins by MRO."""
    register_quirks_extension(["mysql"], _InheritsInitFromItsOwnParent)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    message = str(excinfo.value)
    assert "__init__" in message
    assert "_ParentWithInit" in message


def test_an_extension_of_only_new_hooks_still_composes() -> None:
    """The inverted rule must not reject what the enumeration accepted."""
    register_quirks_extension(["mysql"], _AddsNewHook)
    register_quirks_extension(["sqlserver"], _TypedExtension)

    assert ProviderRegistry.get_quirks("mysql").dialect_extension_hook() == "extension"
    assert ProviderRegistry.get_quirks("sqlserver").typed_extension_hook() == "typed"


# ---------------------------------------------------------------------------
# Standard-library bases contribute dunders, so they are rejected
# ---------------------------------------------------------------------------


T = TypeVar("T")


class _ExtendsAbc(abc.ABC):
    def abc_extension_hook(self) -> str:
        return "abc"


class _UsesAbcMeta(metaclass=ABCMeta):
    def abcmeta_extension_hook(self) -> str:
        return "abcmeta"


class _ExtendsGeneric(Generic[T]):
    def generic_extension_hook(self) -> str:
        return "generic"


class _ExtendsProtocol(Protocol):
    def protocol_extension_hook(self) -> str:
        return "protocol"


class _ExtendsNamedTuple(NamedTuple):
    scratch: str = "tuple"


class _ExtendsEnum(enum.Enum):
    ONLY = "member"


@pytest.mark.parametrize(
    "extension",
    [
        _ExtendsAbc,
        _UsesAbcMeta,
        _ExtendsGeneric,
        _ExtendsProtocol,
        _ExtendsNamedTuple,
        _ExtendsEnum,
    ],
    ids=["abc.ABC", "ABCMeta", "Generic", "Protocol", "NamedTuple", "Enum"],
)
def test_a_standard_library_base_class_extension_is_rejected(extension: type) -> None:
    """Pins the decision, so widening it is a visible diff rather than drift.

    Each of these bases writes dunders into its subclass —
    ``__abstractmethods__``, ``__orig_bases__``, ``__parameters__``,
    ``__slots__``, ``__new__`` — and the seam rejects every dunder it does
    not own, so all six are refused. The reasons are not the same reason.

    ``abc.ABC``, ``ABCMeta``, ``Generic`` and ``Protocol`` are refused **by
    choice**: on this interpreter all four compose *and* instantiate
    correctly, ``dialect_name`` and the base's own hooks intact. Allowing
    them would have to be by provenance — trusting the declaring class — and
    that means trusting ``Protocol.__init__`` and
    ``Generic.__init_subclass__``, the two most dangerous names of all, on
    the strength of interpreter behaviour no version guarantees. An extension
    needs none of these bases: it subclasses ``BaseQuirks`` or it is a plain
    class.

    ``NamedTuple`` and ``Enum`` are refused by necessity, and the guard is
    what makes the failure legible. A ``NamedTuple`` extension composes as a
    class but its ``__new__`` then rejects ``composed(dialect_name=...)``; an
    ``Enum`` extension does not compose at all, failing with an
    ``AttributeError`` out of the enum machinery that ``compose_quirks_class``
    would otherwise report as an unsatisfiable MRO — the wrong diagnosis for
    a base that can never compose.
    """
    register_quirks_extension(["mysql"], extension)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("mysql")

    message = str(excinfo.value)
    assert extension.__name__ in message
    rejected = _rejected_name(message)
    assert rejected.startswith("__") and rejected.endswith("__"), message


# ---------------------------------------------------------------------------
# Private names are hooks too
# ---------------------------------------------------------------------------


class _ShadowsAPrivateQuirksName:
    """Extension redefining a private name the PostgreSQL plugin declares."""

    _PG_SERIAL_TYPES = frozenset({"nothing-is-a-serial"})


def test_shadowing_a_private_name_the_quirks_class_declares_is_rejected() -> None:
    """A private shadow is a real shadow — skipping ``_name`` would let it win.

    ``PostgresqlQuirks.render_identity_clause`` reads
    ``self._PG_SERIAL_TYPES``, so an extension declaring that name changes
    what the dialect answers for every ``SERIAL`` column, exactly as a public
    hook would. Nothing else in this suite fails if the guard skips
    single-underscore names.
    """
    assert "_PG_SERIAL_TYPES" in vars(PostgresqlQuirks)

    register_quirks_extension(["postgresql"], _ShadowsAPrivateQuirksName)

    with pytest.raises(QuirksExtensionCollisionError) as excinfo:
        ProviderRegistry.get_quirks("postgresql")

    message = str(excinfo.value)
    assert "_PG_SERIAL_TYPES" in message
    assert "_ShadowsAPrivateQuirksName" in message
    assert "PostgresqlQuirks" in message
