"""Internal re-export shim for ``cli/`` consumers.

The ``cli/`` package historically imported a handful of symbols directly
from ``db.*`` (provider registry, provider internals, etc.). The flake8 rule
``banned-modules`` (configured in ``.flake8``) now forbids that pattern:
``cli/`` must reach the database layer only through ``api.*``.

This module exists solely to centralize those low-level handles in a
single place under ``api/`` so the architectural rule holds. It is
deliberately leading-underscored: these symbols are not part of the
public ``api/`` surface (which is reserved for ``DBLiftClient``, events,
etc.). Library users should not depend on this module.

If you find yourself adding a new re-export here, ask whether the
underlying need can instead be expressed through ``DBLiftClient`` or a
new typed entry point in ``api/``.
"""

from dblift.db.error import format_connection_error
from dblift.db.provider_capabilities import get_provider_display_url
from dblift.db.provider_interfaces import ConnectionProvider
from dblift.db.provider_registry import ProviderRegistry

__all__ = [
    "ConnectionProvider",
    "ProviderRegistry",
    "format_connection_error",
    "get_provider_display_url",
]
