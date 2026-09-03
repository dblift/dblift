"""Registry for the CLI's feature-tier resolution, contributed by higher tiers.

OSS core calls :func:`resolve_tier` to learn which tier the current
invocation is entitled to. The tier value itself is opaque to OSS: it is
produced and consumed entirely by paid code — OSS only stores and passes it
through (``CliCommandContext.license_tier``). With nothing registered, every
invocation resolves to ``None``. Installed higher tiers register a resolver
here (via the ``dblift.features`` entry-point group) that inspects the
license token and returns the tier it grants.

A registered resolver that raises is treated the same as no resolver at
all: :func:`resolve_tier` swallows it and returns ``None`` (fail-closed),
rather than letting a misbehaving license check crash the CLI.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Optional

_log = logging.getLogger(__name__)

_RESOLVER: Optional[Callable[[Any], Any]] = None


def register_resolver(resolver: Callable[[Any], Any]) -> None:
    """Register *resolver* as the tier resolver for :func:`resolve_tier`.

    Single slot: registering again replaces the previous resolver (last wins).
    """
    global _RESOLVER
    _RESOLVER = resolver


def resolve_tier(args: Any) -> Any:
    """Return the resolved tier for *args*, defaulting to ``None``.

    The return value is opaque to OSS code — whatever the registered
    resolver produces. A resolver that raises denies (``None``) rather
    than crashing the invocation.
    """
    if _RESOLVER is None:
        return None
    try:
        return _RESOLVER(args)
    except Exception as exc:  # a broken resolver must not crash dispatch
        _log.warning("tier resolver raised, denying: %s", exc)
        return None


def registered_resolver() -> Optional[Callable[[Any], Any]]:
    """Snapshot of the registered resolver (introspection hook)."""
    return _RESOLVER


def clear_resolver() -> None:
    """Test hook."""
    global _RESOLVER
    _RESOLVER = None
