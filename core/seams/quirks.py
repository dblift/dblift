"""Neutral seam for higher-tier dialect-quirks extension registration.

``ProviderRegistry.get_quirks`` resolves exactly one quirks class per
dialect, so an installed package needing a hook the core does not have
had no legitimate way to contribute one. This seam is that way: an
extension class registered here is mixed in *ahead* of the resolved base
class, so ``provider.quirks.<hook>`` finds the added hook while every
existing call site keeps resolving exactly what it resolved before.

**Extensions add hooks; they never re-answer one.** If an extension
defines a name the resolved base class already answers — whether the
plugin's own quirks class declares it or it is inherited from
``BaseQuirks`` — composition raises
:class:`QuirksExtensionCollisionError`. A hook the core already answers
is a statement about the database engine, and a second answer for it
belongs upstream in the core, not in an installed extension. Silently
winning by MRO is the failure mode this seam exists to prevent: it
shadows the core implementation, and a newer core defining the same hook
would then be overridden without a word.

Registration targets dialect keys **explicitly** — an extension for
``postgresql`` reaches ``postgresql`` and nothing else. Wire-compatible
engines (``neon``, ``timescaledb``, ...) and the registry's aliases
(``postgres``, ``mssql``, ``sqlite3``) are separate keys; a package that
wants them lists them.

**Deviation from the other seams in this package:** they log a warning
and continue when a registrar misbehaves, because a bad plugin must not
break startup. :func:`validate_quirks_extensions` raises instead, and
``core/seams/feature_loading.py`` calls it outside its per-entry-point
``try``/``except`` on purpose. A collision is not a flaky plugin — it is
an installed package violating this contract, and continuing means
running with exactly the divergence the seam exists to prevent.
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from core.exceptions import DbliftError

_extensions: Dict[str, List[type]] = {}


class QuirksExtensionCollisionError(DbliftError):
    """Raised when a registered extension redefines an existing quirks hook."""


def register_quirks_extension(dialects: Iterable[str], extension: type) -> None:
    """Register *extension* as a quirks mixin for each dialect in *dialects*.

    Args:
        dialects: Dialect keys the extension applies to, exactly as they
            are passed to ``ProviderRegistry.get_quirks`` (case-insensitive).
            Nothing propagates implicitly to related dialects.
        extension: The mixin class. Composed ahead of the dialect's base
            quirks class, in registration order.

    Collisions are not detected here — the base class a dialect resolves
    to is not known until composition. :func:`validate_quirks_extensions`
    forces that check at load time.
    """
    for dialect in dialects:
        registered = _extensions.setdefault(dialect.lower(), [])
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
        QuirksExtensionCollisionError: If a registered extension defines a
            public name that *base* already resolves.
    """
    extensions = _extensions.get(dialect.lower())
    if not extensions:
        return base
    for extension in extensions:
        _reject_collisions(dialect, base, extension)
    return type(f"{base.__name__}Composed", (*extensions, base), {})


def validate_quirks_extensions() -> None:
    """Compose every registered dialect now, raising on the first collision.

    Without this, a collision on a dialect nothing happens to resolve
    would sit undetected until the day someone runs against that engine.
    Resolution goes through ``ProviderRegistry`` rather than a second copy
    of its lookup rules, so validation cannot drift from what
    ``get_quirks`` will do.

    Raises:
        QuirksExtensionCollisionError: On the first colliding extension.
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


def _reject_collisions(dialect: str, base: type, extension: type) -> None:
    """Raise if *extension* redefines any public name *base* already answers."""
    for name in vars(extension):
        if name.startswith("_"):
            continue
        owner = _defining_class(base, name)
        if owner is None:
            continue
        raise QuirksExtensionCollisionError(
            f"Quirks extension {_describe(extension)} registered for dialect "
            f"{dialect!r} redefines {name!r}, which {_describe(owner)} already "
            f"defines. Extensions may only add hooks the core does not answer: "
            f"an existing hook is a statement about the database engine, and a "
            f"second answer for it belongs upstream in the core rather than in "
            f"an installed extension."
        )


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


def _describe(klass: type) -> str:
    """Render a class as ``module.QualName`` for collision messages."""
    return f"{klass.__module__}.{klass.__qualname__}"
