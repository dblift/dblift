"""Credential-masking helpers for :class:`BaseDatabaseConfig.to_safe_dict`.

Extracted from ``config.database_config`` during PR-H10 so the facade
module stays under its 500-line budget. Pure functions with no side effects.

URL masking is delegated to :mod:`core.utils.url_masking` rather than
duplicated here — the two copies had drifted and this one covered neither
``pwd=`` nor the CosmosDB ``AccountKey=``.
"""

from typing import Any, Dict

from core.utils.url_masking import mask_database_url

# Sensitive key patterns (case-insensitive matching)
_SENSITIVE_PATTERNS = (
    "password",
    "pwd",
    "secret",
    "key",
    "token",
    "credential",
    "api_key",
    "apikey",
    "auth",
    "access_token",
    "private",
)


def is_sensitive_key(key: str) -> bool:
    """Return True if ``key`` looks like it names sensitive data."""
    key_lower = key.lower()
    return any(pattern in key_lower for pattern in _SENSITIVE_PATTERNS)


def mask_url_credentials(url: str) -> str:
    """Mask credentials embedded in a connection URL.

    Single-sources the URL rules from :func:`core.utils.url_masking.mask_database_url`
    so that ``to_safe_dict`` masks exactly what the logger and CLI mask —
    ``user:pass@`` authorities, ``password=`` / ``pwd=`` parameters and the
    CosmosDB ``AccountKey=``. A narrower local copy previously let ``pwd=``
    and ``AccountKey=`` through into ``__repr__`` output.
    """
    return mask_database_url(url)


def mask_dict_in_place(result: Dict[str, Any], field_name: str) -> None:
    """Mask sensitive keys in ``result[field_name]`` (a dict) if present."""
    if not result.get(field_name):
        return
    masked = dict(result[field_name])
    for key in list(masked.keys()):
        if is_sensitive_key(key):
            masked[key] = "***MASKED***"
    result[field_name] = masked


def mask_credentials(result: Dict[str, Any]) -> Dict[str, Any]:
    """Apply all credential-masking rules to ``result`` and return it.

    Mutates ``result`` in place but also returns it for fluent use.
    """
    # Mask every sensitive scalar at the top level, not just ``password``.
    # Dialects add their own credential fields to ``to_dict`` — CosmosDB puts
    # ``account_key`` here rather than in ``extra_params`` — and naming only
    # the known field left those in clear text in every ``repr``.
    # Container values are skipped: they are walked below, and replacing a
    # whole dict would discard its non-sensitive entries.
    for key, value in list(result.items()):
        if value and not isinstance(value, (dict, list, tuple, set)) and is_sensitive_key(key):
            result[key] = "***MASKED***"

    # Mask URL if it contains credentials. Handled separately from the loop:
    # a URL is rewritten in place, not replaced wholesale, so the host and
    # database stay readable.
    url = result.get("url", "")
    if url:
        result["url"] = mask_url_credentials(url)

    # Mask any sensitive keys in extra_params / properties (case-insensitive)
    mask_dict_in_place(result, "extra_params")
    mask_dict_in_place(result, "properties")

    return result
