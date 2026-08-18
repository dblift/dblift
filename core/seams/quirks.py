"""Neutral seam for higher-tier dialect-quirks extension registration.

``ProviderRegistry.get_quirks`` resolves exactly one quirks class per
dialect, so an installed package needing a hook the core does not have
had no legitimate way to contribute one. This seam is that way: an
extension class registered here is mixed in *ahead* of the resolved base
class, so ``provider.quirks.<hook>`` finds the added hook while every
existing call site keeps resolving exactly what it resolved before.

**Extensions add hooks; they never re-answer one.** If an extension
defines a name the resolved base class already answers — whether the
plugin's own quirks class declares it, it is inherited from
``BaseQuirks``, or the extension inherits it from a parent of its own —
composition raises :class:`QuirksExtensionCollisionError`. A hook the
core already answers is a statement about the database engine, and a
second answer for it belongs upstream in the core, not in an installed
extension. Silently winning by MRO is the failure mode this seam exists
to prevent: it shadows the core implementation, and a newer core
defining the same hook would then be overridden without a word. Two
extensions answering one hook for one dialect are rejected on the same
grounds — that shadowing is silent in the other direction. Dunders are
rejected outright, bar the bookkeeping Python writes into every class
body: a dunder says nothing about a database engine, it changes how the
composed class is built, instantiated or looked up.

An extension **may** subclass ``BaseQuirks`` so the mixin type-checks:
classes already in the base's own lineage contribute nothing, so nothing
they declare counts as a collision, and the plugin's own overrides stay
ahead of the ``BaseQuirks`` defaults in the composed MRO.

Registration targets dialect keys **explicitly** — an extension for
``postgresql`` reaches ``postgresql`` and nothing else. Wire-compatible
engines (``neon``, ``timescaledb``, ...) and MariaDB are separate plugins
with their own canonical names; a package that wants them lists them.
Registry *aliases* are not separate keys: registration and lookup both
resolve through ``ProviderRegistry.canonical_dialect_name``, so an
extension registered for ``sqlite`` also answers a user who configured
``sqlite3``.

**Deviation from the other seams in this package:** they log a warning
and continue when a registrar misbehaves, because a bad plugin must not
break startup. :func:`validate_quirks_extensions` raises instead, and
``core/seams/feature_loading.py`` calls it outside its per-entry-point
``try``/``except`` on purpose. A collision is not a flaky plugin — it is
an installed package violating this contract, and continuing means
running with exactly the divergence the seam exists to prevent.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional, Tuple

from core.exceptions import DbliftError

#: Keyed on the registry's *canonical* dialect name, so an extension
#: registered under an alias and one registered under the canonical name land
#: in the same list and a lookup under either key finds both.
_extensions: Dict[str, List[type]] = {}

#: The only names an extension may contribute that :func:`_reject_collisions`
#: ignores: the bookkeeping Python itself writes into a class body. Everything
#: else an extension contributes is checked, dunders included.
#:
#: An allowlist on purpose. The rule here was a denylist — ``__init__`` and
#: ``__slots__`` named explicitly, every other underscore name skipped — and a
#: denylist of what is forbidden can only ever be incomplete: that one waved
#: through ``__getattribute__``, ``__getattr__``, ``__init_subclass__`` and
#: ``__new__``, each of which re-answers what the composed class already
#: answers. What is *inert* is instead a closed set the interpreter defines.
#:
#: ``__module__``, ``__doc__``, ``__dict__`` and ``__weakref__`` are in the
#: dict of every class that does not inherit them, so the skip is load-bearing:
#: without it every extension collides immediately. ``__annotations__`` appears
#: as soon as the class body annotates a name. ``__qualname__`` is popped by
#: ``type.__new__`` on CPython 3.11 and ``__firstlineno__`` /
#: ``__static_attributes__`` only exist from 3.13; all three are listed so the
#: guard neither depends on nor is broken by the interpreter version.
_COMPOSITION_NEUTRAL_NAMES = frozenset(
    {
        "__module__",
        "__qualname__",
        "__doc__",
        "__dict__",
        "__weakref__",
        "__annotations__",
        "__firstlineno__",
        "__static_attributes__",
    }
)


class QuirksExtensionCollisionError(DbliftError):
    """Raised when a registered extension redefines an existing quirks hook."""


class QuirksExtensionCompositionError(DbliftError):
    """Raised when a dialect's registered extensions cannot form a class.

    Distinct from :class:`QuirksExtensionCollisionError`: nothing is being
    re-answered, the list of bases simply has no consistent linearisation —
    registering a class and then a subclass of it, most commonly.
    """


def register_quirks_extension(dialects: Iterable[str], extension: type) -> None:
    """Register *extension* as a quirks mixin for each dialect in *dialects*.

    Args:
        dialects: Dialect keys the extension applies to. Each is resolved to
            the plugin's canonical name, so registering under an alias
            (``mssql``, ``sqlite3``) registers for the dialect it names.
            Nothing propagates implicitly to *related* dialects: separate
            plugins (MariaDB, the PostgreSQL-wire engines) are separate keys.
        extension: The mixin class. Composed ahead of the dialect's base
            quirks class, in registration order.

    Collisions are not detected here — the base class a dialect resolves
    to is not known until composition. :func:`validate_quirks_extensions`
    forces that check at load time.
    """
    for dialect in dialects:
        registered = _extensions.setdefault(_canonical_dialect(dialect), [])
        if extension not in registered:
            registered.append(extension)
    _invalidate_resolved_quirks()


def compose_quirks_class(dialect: str, base: type) -> type:
    """Return the class ``get_quirks`` should instantiate for *dialect*.

    With nothing registered for *dialect* this is *base* itself — a
    pure-core install builds no dynamic subclass at all. Otherwise the
    registered extensions precede *base* in the MRO, in registration
    order.

    Raises:
        QuirksExtensionCollisionError: If a registered extension answers a
            name *base* already answers, or a name another extension for the
            same dialect already answers.
        QuirksExtensionCompositionError: If the resulting list of bases has
            no consistent method resolution order.
    """
    if not _extensions:
        return base
    extensions = _extensions.get(_canonical_dialect(dialect))
    if not extensions:
        return base
    _reject_collisions(dialect, base, extensions)
    try:
        return type(f"{base.__name__}Composed", (*extensions, base), {})
    except TypeError as exc:
        raise QuirksExtensionCompositionError(
            f"Quirks extensions registered for dialect {dialect!r} cannot be "
            f"composed with {_describe(base)}: {exc}. Bases, in registration "
            f"order: {', '.join(_describe(e) for e in extensions)}, "
            f"{_describe(base)}. Registering a class and then a subclass of it "
            f"is the usual cause — a subclass has to precede its parent and "
            f"composition preserves registration order. Register only the "
            f"class that should apply."
        ) from exc


def validate_quirks_extensions() -> None:
    """Compose every registered dialect now, raising on the first collision.

    Without this, a collision on a dialect nothing happens to resolve
    would sit undetected until the day someone runs against that engine.
    Resolution goes through ``ProviderRegistry`` rather than a second copy
    of its lookup rules, so validation cannot drift from what
    ``get_quirks`` will do.

    Raises:
        QuirksExtensionCollisionError: On the first colliding extension.
        QuirksExtensionCompositionError: On the first uncomposable dialect.
    """
    if not _extensions:
        return
    from db.provider_registry import ProviderRegistry

    for dialect in tuple(_extensions):
        compose_quirks_class(dialect, ProviderRegistry.quirks_base_class(dialect))


def clear_quirks_extensions() -> None:
    """Test hook."""
    _extensions.clear()
    _invalidate_resolved_quirks()


def _invalidate_resolved_quirks() -> None:
    """Drop the registry's memoised quirks instances.

    ``ProviderRegistry.get_quirks`` caches one instance per dialect, so a
    dialect resolved before an extension registered would keep serving the
    un-extended instance for the life of the process.

    Imported inside the function on purpose: ``db.provider_registry``
    imports this module at module scope to compose, so importing it back at
    module scope here would be a cycle.
    """
    from db.provider_registry import ProviderRegistry

    ProviderRegistry.clear_quirks_cache()


def _canonical_dialect(dialect: str) -> str:
    """Return the registry's canonical name for *dialect*, else its lowercase.

    Registration and lookup both go through this, or they disagree within a
    single ``get_quirks`` call: the base class resolves through the registry's
    aliases while the extension list would not. ``sqlite3`` and ``mongo``
    reach ``config.database.type`` un-normalised, so a package registering for
    ``sqlite`` must still answer a user who configured ``sqlite3``.

    Unknown names fall back to the lowercase input, so a dialect no plugin
    claims still keys stably.

    Imported inside the function for the same reason as
    :func:`_invalidate_resolved_quirks`.
    """
    from db.provider_registry import ProviderRegistry

    lowered = (dialect or "").lower()
    return ProviderRegistry.canonical_dialect_name(lowered) or lowered


def _reject_collisions(dialect: str, base: type, extensions: List[type]) -> None:
    """Raise unless every registered extension only *adds* names.

    Three checks sharing one name-derivation rule so they cannot drift: any
    name outside :data:`_COMPOSITION_NEUTRAL_NAMES` that is a dunder, then
    each remaining name against *base*, then each against the extensions
    registered before it for the same dialect. The last is the same silent
    shadowing in the unchecked direction — two packages answering one hook
    would otherwise resolve by registration order with no diagnostic.

    The dunder check cannot be folded into the check against *base*: nothing
    in a quirks lineage declares ``__getattr__`` or ``__slots__``, so both
    would pass a collision test and still take over the composed class.

    Both live here rather than in :func:`register_quirks_extension` because
    :func:`_contributed_names` is defined relative to *base*, which is not
    known until composition; :func:`validate_quirks_extensions` composes every
    registered dialect at load time, so the error is just as early.
    """
    answered: Dict[str, Tuple[type, type]] = {}
    for extension in extensions:
        for name, declaring in _contributed_names(base, extension).items():
            if name in _COMPOSITION_NEUTRAL_NAMES:
                continue
            if _is_dunder(name):
                raise QuirksExtensionCollisionError(
                    f"Quirks extension {_describe(extension)} registered for "
                    f"dialect {dialect!r} defines {name!r}"
                    f"{_inherited_from(extension, declaring)}. Composition owns "
                    f"every dunder but the bookkeeping Python writes into a class "
                    f"body itself: a dunder answers no question about the database "
                    f"engine, it changes how the composed class is built, "
                    f"instantiated or looked up. ProviderRegistry.get_quirks "
                    f"instantiates the composed class as composed(dialect_name=...), "
                    f"so __init__ empties quirks.dialect_name; __slots__ dictates "
                    f"the composed instance layout; __init_subclass__ runs during "
                    f"composition itself and writes ahead of every extension and the "
                    f"base; __getattr__ and __getattribute__ answer every hook, "
                    f"including ones nothing defines. Extensions add hooks, nothing "
                    f"else."
                )
            owner = _defining_class(base, name)
            if owner is not None:
                raise QuirksExtensionCollisionError(
                    f"Quirks extension {_describe(extension)} registered for "
                    f"dialect {dialect!r} redefines {name!r}"
                    f"{_inherited_from(extension, declaring)}, which "
                    f"{_describe(owner)} already defines. Extensions may only "
                    f"add hooks the core does not answer: an existing hook is a "
                    f"statement about the database engine, and a second answer "
                    f"for it belongs upstream in the core rather than in an "
                    f"installed extension."
                )
            previous = answered.get(name)
            # A shared declaring class is one implementation reached through two
            # registered extensions (a package's internal mixin) — unambiguous,
            # and rejecting it would break a legitimate arrangement.
            if previous is not None and previous[1] is not declaring:
                raise QuirksExtensionCollisionError(
                    f"Quirks extensions {_describe(previous[0])} and "
                    f"{_describe(extension)}, both registered for dialect "
                    f"{dialect!r}, each answer {name!r} "
                    f"({_describe(previous[1])} and {_describe(declaring)}). "
                    f"Registration order alone would decide which one wins, "
                    f"silently — the shadowing this seam exists to prevent. One "
                    f"of the two must drop the hook."
                )
            answered[name] = (extension, declaring)


def _contributed_names(base: type, extension: type) -> Dict[str, type]:
    """Map each name *extension* contributes to the class in its MRO declaring it.

    Walks the extension's whole MRO rather than ``vars(extension)``: a name
    the extension inherits from a parent of its own still precedes *base* in
    the composed MRO and still wins, so a leaf-only check lets through exactly
    the shadowing this seam forbids.

    Classes already in *base*'s MRO are skipped, so an extension subclassing
    ``BaseQuirks`` — the natural instinct, so the mixin type-checks —
    contributes nothing by doing so and is not rejected for every name
    ``BaseQuirks`` declares.
    """
    contributed: Dict[str, type] = {}
    base_lineage = base.__mro__
    for klass in extension.__mro__:
        if klass is object or klass in base_lineage:
            continue
        for name in vars(klass):
            contributed.setdefault(name, klass)
    return contributed


def _defining_class(base: type, name: str) -> Optional[type]:
    """Return the class in *base*'s MRO that defines *name*, or ``None``.

    Walks the full MRO rather than ``vars(base)``: a hook the plugin's own
    quirks class inherits from ``BaseQuirks`` is just as much an existing
    answer as one the plugin declares itself.
    """
    for klass in base.__mro__:
        if name in vars(klass):
            return klass
    return None


def _is_dunder(name: str) -> bool:
    """Whether *name* is a ``__dunder__`` — a name Python, not a hook, owns."""
    return name.startswith("__") and name.endswith("__")


def _inherited_from(extension: type, declaring: type) -> str:
    """Name the ancestor a colliding name came from, when it is not the leaf."""
    if declaring is extension:
        return ""
    return f" (inherited from {_describe(declaring)})"


def _describe(klass: type) -> str:
    """Render a class as ``module.QualName`` for collision messages."""
    return f"{klass.__module__}.{klass.__qualname__}"
