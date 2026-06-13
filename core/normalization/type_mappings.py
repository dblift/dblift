"""
Comprehensive type mappings for canonical type normalization.

Provides extensive mappings between vendor-specific types and canonical forms,
including reverse mappings and type aliases.
"""

from typing import Dict, Optional

from core.normalization.type_constants import CANONICAL_TO_VARIANTS

# Reverse mapping: variant -> canonical
VARIANT_TO_CANONICAL: Dict[str, str] = {}

# Build reverse mapping
for canonical, variants in CANONICAL_TO_VARIANTS.items():
    for variant in variants:
        VARIANT_TO_CANONICAL[variant.upper()] = canonical

# Type aliases (same semantic meaning, different names)
TYPE_ALIASES: Dict[str, str] = {
    # PostgreSQL aliases
    "INT4": "INTEGER",
    "INT8": "BIGINT",
    "INT2": "SMALLINT",
    "FLOAT4": "REAL",
    "FLOAT8": "DOUBLE",
    "CHARACTER VARYING": "VARCHAR",
    "CHAR VARYING": "VARCHAR",
    # Oracle aliases
    "VARCHAR2": "VARCHAR",
    "NVARCHAR2": "VARCHAR",
    "NUMBER": "NUMERIC",  # When used as numeric
    # MySQL aliases
    "TINYINT": "SMALLINT",  # When used as small integer
    "MEDIUMINT": "INTEGER",
    # SQL Server aliases
    "DATETIME2": "TIMESTAMP",
    "SMALLDATETIME": "TIMESTAMP",
    "UNIQUEIDENTIFIER": "UUID",
    # DB2 aliases
    "DECIMAL": "NUMERIC",
    "DEC": "NUMERIC",
}


def _build_version_specific_mappings() -> Dict[tuple, Dict[str, str]]:
    """Build version-specific type mappings from plugin quirks classes.

    Reads :attr:`db.base_quirks.BaseQuirks.version_specific_type_mappings`
    on each registered :class:`db.provider_registry.PluginInfo.quirks_class`
    (class attributes, not instances) so normalization does not depend on
    :meth:`db.provider_registry.ProviderRegistry.get_quirks` or quirks cache
    state at import time.
    """
    from db.provider_registry import ProviderRegistry

    result: Dict[tuple, Dict[str, str]] = {}
    for plugin_info in ProviderRegistry.list_plugins():
        quirks_cls = plugin_info.quirks_class
        if quirks_cls is None:
            continue
        per_dialect = getattr(quirks_cls, "version_specific_type_mappings", None)
        if per_dialect:
            result.update(per_dialect)
    return result


_version_specific_mappings_cache: Optional[Dict[tuple, Dict[str, str]]] = None


def get_version_specific_mappings() -> Dict[tuple, Dict[str, str]]:
    """Lazily aggregate ``version_specific_type_mappings`` from registered plugins.

    Built on first call (not at import time) so importing this module cannot
    trigger plugin discovery or circular imports when a plugin loads
    normalization code transitively.
    """
    global _version_specific_mappings_cache
    if _version_specific_mappings_cache is None:
        _version_specific_mappings_cache = _build_version_specific_mappings()
    return _version_specific_mappings_cache


def __getattr__(name: str) -> object:
    """Backward-compatible ``VERSION_SPECIFIC_MAPPINGS`` lazy alias."""
    if name == "VERSION_SPECIFIC_MAPPINGS":
        return get_version_specific_mappings()
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
