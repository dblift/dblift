"""Recursive secret-URI resolver for config trees."""

from typing import Any, Optional

from config.secrets._cache import SecretsCache
from config.secrets._provider_base import SecretsResolutionError
from config.secrets._registry import get_provider_class, is_secret_uri, registered_schemes
from config.secrets._secrets_config import SecretsConfig

# Module-level cache — persists for the lifetime of the process.
_cache = SecretsCache(ttl_seconds=60.0)


def _cache_key(uri: str, secrets_config: Optional[SecretsConfig]) -> str:
    """Build a cache key that includes all auth-relevant config fields.

    The same URI resolved under different backends, tokens, or namespaces must
    never return a cached value from the wrong context. Credentials are included
    because the cache lives only in process memory (never persisted/logged), so
    storing them in a key string is no less safe than keeping them in SecretsConfig.
    """
    if secrets_config is None:
        return uri
    return (
        f"{uri}\x00{secrets_config.vault_url or ''}"
        f"\x00{secrets_config.vault_token or ''}"
        f"\x00{secrets_config.vault_namespace or ''}"
        f"\x00{secrets_config.aws_region or ''}"
        f"\x00{secrets_config.azure_vault_name or ''}"
        f"\x00{secrets_config.gcp_project_id or ''}"
    )


def resolve_secret_refs(data: Any, secrets_config: Optional[SecretsConfig] = None) -> Any:
    """Recursively walk *data* and resolve any secret URIs found in string values."""
    if secrets_config is not None:
        ttl_seconds = getattr(secrets_config, "cache_ttl_seconds", None)
        if isinstance(ttl_seconds, (int, float)) and not isinstance(ttl_seconds, bool):
            _cache._ttl = float(ttl_seconds)
    if isinstance(data, dict):
        return {k: resolve_secret_refs(v, secrets_config) for k, v in data.items()}
    if isinstance(data, list):
        return [resolve_secret_refs(item, secrets_config) for item in data]
    if isinstance(data, str) and is_secret_uri(data):
        return _resolve_uri(data, secrets_config)
    return data


def _resolve_uri(uri: str, secrets_config: Optional[SecretsConfig]) -> str:
    key = _cache_key(uri, secrets_config)
    cached = _cache.get(key)
    if cached is not None:
        return cached

    scheme = uri.split("://", 1)[0]
    provider_factory = get_provider_class(scheme)
    if provider_factory is None:
        raise SecretsResolutionError(
            f"No secrets provider registered for scheme '{scheme}'. "
            f"Registered providers: {registered_schemes()}"
        )

    # The registry may hold either a class (normal case) or a pre-configured
    # instance (test stubs, or advanced singleton usage).
    if isinstance(provider_factory, type):
        provider = provider_factory(secrets_config)
    else:
        provider = provider_factory

    if not provider.is_available():
        raise SecretsResolutionError(
            f"Secrets provider '{scheme}' is not available. "
            "Check provider configuration and credentials."
        )

    value: str = provider.resolve(uri)
    _cache.set(key, value)
    return value


def clear_cache() -> None:
    """Clear the module-level resolved-secrets cache (primarily for testing)."""
    _cache.clear()
