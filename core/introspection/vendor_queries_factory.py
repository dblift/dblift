"""
Factory for creating vendor-specific metadata query instances.

This module provides a factory for instantiating the appropriate
VendorMetadataQueries implementation based on the database dialect.

Plugin-discovered: each plugin's :class:`BaseQuirks` subclass declares
its :meth:`vendor_queries_class` (lazy import). The factory iterates
``ProviderRegistry.list_plugins()`` once on first use, asks each
plugin's quirks for its queries class, and registers it under every
dialect alias declared in the plugin's :class:`PluginInfo`. Third-party
plugins can still override entries at runtime via
:func:`register_vendor_queries` (OCP-05).
"""

from typing import Optional, Type

from .vendor_queries_base import VendorMetadataQueries

# Plugin-discovered registry — populated lazily on first use from
# ``ProviderRegistry.list_plugins()``. Runtime ``register_vendor_queries``
# calls can also write here (third-party plugins, test overrides).
_VENDOR_QUERIES_REGISTRY: dict[str, Type[VendorMetadataQueries]] = {}
_DEFAULTS_REGISTERED: bool = False


def _register_defaults() -> None:
    """Populate the registry from plugin-declared ``vendor_queries_class()``.

    Mirrors :meth:`IntrospectorFactory._register_defaults` — iterates
    every plugin in :class:`ProviderRegistry`, asks its quirks for the
    queries class, and binds it to every dialect alias the plugin
    declared.
    """
    global _DEFAULTS_REGISTERED
    from db.provider_registry import ProviderRegistry

    for plugin_info in ProviderRegistry.list_plugins():
        quirks = ProviderRegistry.get_quirks(plugin_info.name)
        queries_cls = quirks.vendor_queries_class()
        if queries_cls is None:
            continue
        for dialect in plugin_info.dialects:
            _VENDOR_QUERIES_REGISTRY.setdefault(dialect.lower(), queries_cls)
    _DEFAULTS_REGISTERED = True


def register_vendor_queries(
    dialect: str,
    query_class: Type[VendorMetadataQueries],
    *,
    aliases: Optional[list[str]] = None,
) -> None:
    """Register a new or replacement VendorMetadataQueries class for a dialect.

    Allows third-party plugins to add support for custom database dialects (or
    override built-in ones) without modifying :class:`VendorQueriesFactory`.

    Args:
        dialect: Primary dialect name (stored lower-cased).
        query_class: Concrete :class:`VendorMetadataQueries` subclass to register.
        aliases: Optional additional dialect names that should resolve to the same class.

    Example:
        >>> from core.introspection.vendor_queries_factory import register_vendor_queries
        >>> register_vendor_queries("cockroachdb", CockroachDbMetadataQueries, aliases=["crdb"])
    """
    _VENDOR_QUERIES_REGISTRY[dialect.lower()] = query_class
    for alias in aliases or []:
        _VENDOR_QUERIES_REGISTRY[alias.lower()] = query_class


class VendorQueriesFactory:
    """
    Factory for creating vendor-specific metadata query instances.

    This factory maps database dialects to their corresponding
    VendorMetadataQueries implementation via the module-level
    ``_VENDOR_QUERIES_REGISTRY``, populated from plugin quirks on
    first use.  Third-party plugins can still register dialects at
    runtime with :func:`register_vendor_queries`.

    Example:
        >>> queries = VendorQueriesFactory.create("postgresql")
        >>> sql, params = queries.get_check_constraints_query("public", "users")
        >>> # Execute the query to get check constraints
    """

    @classmethod
    def create(cls, dialect: str) -> Optional[VendorMetadataQueries]:
        """
        Create a VendorMetadataQueries instance for the given dialect.

        Args:
            dialect: Database dialect name (case-insensitive)

        Returns:
            VendorMetadataQueries instance for the dialect, or None if not supported

        Example:
            >>> queries = VendorQueriesFactory.create("postgresql")
            >>> if queries and queries.supports_check_constraints():
            ...     sql, params = queries.get_check_constraints_query("public", "users")
        """
        if not _DEFAULTS_REGISTERED:
            _register_defaults()
        query_class = _VENDOR_QUERIES_REGISTRY.get(dialect.lower())
        if query_class:
            return query_class()
        return None

    @classmethod
    def is_supported(cls, dialect: str) -> bool:
        """
        Check if a dialect is supported.

        Args:
            dialect: Database dialect name (case-insensitive)

        Returns:
            True if the dialect is supported, False otherwise
        """
        if not _DEFAULTS_REGISTERED:
            _register_defaults()
        return dialect.lower() in _VENDOR_QUERIES_REGISTRY

    @classmethod
    def supported_dialects(cls) -> list[str]:
        """
        Get a list of all supported dialects.

        Returns:
            List of supported dialect names
        """
        if not _DEFAULTS_REGISTERED:
            _register_defaults()
        return list(_VENDOR_QUERIES_REGISTRY.keys())
