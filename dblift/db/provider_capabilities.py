"""Helpers for optional provider capabilities.

Shared command code should use these helpers instead of scattering
``hasattr`` checks for provider-specific hooks.
"""

from __future__ import annotations

from typing import Any, Optional

from dblift.config import DbliftConfig
from dblift.core.migration.clean_summary import CleanExecutionSummary


def ensure_provider_connection(provider: Any) -> bool:
    """Ensure provider connection state when the provider exposes that hook.

    Returns True when a provider-level hook was called.
    """
    hook = getattr(provider, "_ensure_connection", None)
    if callable(hook):
        hook()
        return True
    return False


def get_provider_display_url(
    provider: Any,
    config: Optional[DbliftConfig] = None,
) -> Optional[str]:
    """Return a neutral display URL for providers."""
    display_url_hook = getattr(provider, "get_display_url", None)
    if callable(display_url_hook):
        url = display_url_hook()
        if url:
            return str(url)

    connection_manager = getattr(provider, "connection_manager", None)
    if connection_manager is not None:
        get_url = getattr(connection_manager, "get_database_url", None)
        if callable(get_url):
            url = get_url()
            if url:
                return str(url)

    db = getattr(config, "database", None) if config is not None else None
    if db is not None:
        for attr in ("url", "account_endpoint", "path", "database"):
            value = getattr(db, attr, None)
            if value is not None and str(value).strip():
                return str(value)
    return None


def get_provider_driver_display(
    provider: Any, config: Optional[DbliftConfig] = None
) -> Optional[str]:
    """Return the plugin-declared native driver display name, if available."""
    quirks = getattr(provider, "quirks", None)
    display = getattr(quirks, "native_driver_display", None)
    if isinstance(display, str) and display.strip():
        return display

    db = getattr(config, "database", None) if config is not None else None
    raw_type = getattr(db, "type", None)
    dialect = (getattr(raw_type, "value", None) or str(raw_type or "")).strip().lower()
    if not dialect:
        dialect = str(getattr(provider, "canonical_dialect_key", "") or "").strip().lower()
    if not dialect:
        return None

    from dblift.db.provider_registry import ProviderRegistry

    registry_display = ProviderRegistry.get_quirks(dialect).native_driver_display
    return registry_display or None


def get_clean_preview(provider: Any, schema: str) -> Optional[CleanExecutionSummary]:
    """Return a provider-native clean preview if supported."""
    hook = getattr(provider, "get_clean_preview", None)
    if callable(hook):
        result: Optional[CleanExecutionSummary] = hook(schema)
        return result
    return None
