"""Provider class registry — maps URI schemes to provider classes."""

from typing import Dict, Optional, Type

# Fixed set of known schemes — used for fast URI detection without requiring
# providers to be registered first (avoids import-order sensitivity).
KNOWN_SCHEMES: frozenset = frozenset()

# Populated by providers/__init__.py at import time.
_providers: Dict[str, Type] = {}


def register(scheme: str, cls: Type) -> None:
    """Register a provider class for the given URI scheme (internal use)."""
    _providers[scheme] = cls


def register_provider(scheme: str, cls: Type) -> None:
    """Register a custom secrets provider.

    Use this to add support for secrets backends not bundled with dblift
    (e.g. CyberArk, Delinea, 1Password, internal corporate vaults).
    Call this once at application startup, before any config is loaded.

    Args:
        scheme: URI scheme without ``://`` (e.g. ``"cyberark"``).  Must be
            non-empty and must not contain ``://``.
        cls:    Provider class.  Must subclass
            ``config.secrets.AbstractSecretsProvider`` and implement
            ``resolve(uri) -> str`` and ``is_available() -> bool``.

    Raises:
        ValueError: if *scheme* is empty or contains ``://``.
        TypeError:  if *cls* is not a subclass of ``AbstractSecretsProvider``.

    Example::

        from config.secrets import AbstractSecretsProvider, register_provider
        from config.secrets._secrets_config import SecretsConfig

        class CyberArkProvider(AbstractSecretsProvider):
            scheme = "cyberark"

            def is_available(self) -> bool:
                try:
                    import conjur  # noqa: F401
                    return True
                except ImportError:
                    return False

            def resolve(self, uri: str) -> str:
                variable_id = uri[len("cyberark://"):]
                import conjur
                return conjur.Client().retrieve_secret(variable_id)

        register_provider("cyberark", CyberArkProvider)
    """
    from config.secrets._provider_base import AbstractSecretsProvider

    if not scheme or "://" in scheme:
        raise ValueError(f"scheme must be a non-empty string without '://': {scheme!r}")
    if not (isinstance(cls, type) and issubclass(cls, AbstractSecretsProvider)):
        raise TypeError(f"cls must be a subclass of AbstractSecretsProvider, got {cls!r}")
    missing: frozenset = getattr(cls, "__abstractmethods__", frozenset())
    if missing:
        raise TypeError(
            f"cls must implement all abstract methods "
            f"({', '.join(sorted(missing))}): got {cls!r}"
        )
    _providers[scheme] = cls


def get_provider_class(scheme: str) -> Optional[Type]:
    """Return the provider class registered for *scheme*, or None."""
    return _providers.get(scheme)


def is_secret_uri(value: str) -> bool:
    """Return True when *value* is a URI whose scheme is a registered provider."""
    if not value or "://" not in value:
        return False
    scheme = value.split("://", 1)[0]
    # Check registered providers first (covers test stubs and future extensions),
    # fall back to KNOWN_SCHEMES so detection works even before providers are imported.
    return scheme in _providers or scheme in KNOWN_SCHEMES


def registered_schemes() -> list:
    return sorted(_providers.keys())
