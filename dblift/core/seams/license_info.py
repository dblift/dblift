"""Registry for the CLI's license-info provider, contributed by higher tiers.

OSS core calls :func:`get_license_info` to learn what (if anything) to show
in the "Licensed to: ..." log banner. With nothing registered, every
invocation resolves to ``None`` and the banner is omitted. Installed higher
tiers register a provider here (via the ``dblift.features`` entry-point
group) that returns the resolved license's display info, or ``None`` when
no valid license is present.
"""

from __future__ import annotations

from typing import Any, Callable, Dict, Optional

_PROVIDER: Optional[Callable[[Any], Optional[Dict[str, Any]]]] = None


def register_provider(provider: Callable[[Any], Optional[Dict[str, Any]]]) -> None:
    """Register *provider* as the license-info provider for :func:`get_license_info`.

    Single slot: registering again replaces the previous provider (last wins).
    """
    global _PROVIDER
    _PROVIDER = provider


def get_license_info(args: Any) -> Optional[Dict[str, Any]]:
    """Return the license-info dict for *args*, defaulting to ``None``."""
    if _PROVIDER is None:
        return None
    return _PROVIDER(args)


def registered_provider() -> Optional[Callable[[Any], Optional[Dict[str, Any]]]]:
    """Snapshot of the registered provider (introspection hook)."""
    return _PROVIDER


def clear_provider() -> None:
    """Test hook."""
    global _PROVIDER
    _PROVIDER = None
