"""
Factory for creating database-specific introspection instances.

This module provides a factory for instantiating the appropriate
BaseIntrospector implementation based on the database dialect.
"""

from typing import Any, Optional

from core.introspection.base_introspector import BaseIntrospector


class IntrospectorFactory:
    """
    Factory for creating database-specific introspection instances.

    This factory maps database dialects to their corresponding
    BaseIntrospector implementation.

    Example:
        >>> introspector = IntrospectorFactory.create(provider, log)
        >>> tables = introspector.get_tables("public")
    """

    # Mapping of dialect names to introspector classes
    # Will be populated as we implement each database-specific introspector
    _DIALECT_MAP: dict[str, type[BaseIntrospector]] = {}

    @classmethod
    def _register_defaults(cls) -> None:
        """Register introspectors for all discovered plugins via quirks system."""
        from db.provider_registry import ProviderRegistry

        for plugin_info in ProviderRegistry.list_plugins():
            quirks = ProviderRegistry.get_quirks(plugin_info.name)
            introspector_cls = quirks.introspector_class()
            if introspector_cls is None:
                continue
            for dialect in plugin_info.dialects:
                cls.register(dialect, introspector_cls)

    @classmethod
    def create(
        cls, provider: Any, log: Optional[Any] = None, use_vendor_queries: bool = True
    ) -> BaseIntrospector:
        """
        Create a BaseIntrospector instance for the given provider's dialect.

        Args:
            provider: Database provider (for connection management)
            log: Optional logger instance
            use_vendor_queries: Whether to use vendor-specific queries

        Returns:
            BaseIntrospector instance for the dialect

        Note:
            If no specific implementation exists for the dialect, falls back
            to the original SchemaIntrospector.
        """
        # Register default implementations on first call
        if not cls._DIALECT_MAP:
            cls._register_defaults()

        dialect = (
            provider.config.database.type
            if hasattr(provider, "config") and hasattr(provider.config, "database")
            else "unknown"
        )
        dialect_lower = dialect.lower()

        # Check if we have a specific implementation
        introspector_class = cls._DIALECT_MAP.get(dialect_lower)

        if introspector_class:
            return introspector_class(provider, log, use_vendor_queries)

        # Fallback for third-party plugins that don't ship their own
        # ``introspector_class``. Lazy import the canonical class via
        # the ``schema_introspector`` module path (now a back-compat
        # alias for :class:`BaseIntrospector`) so tests that ``patch(
        # "core.introspection.schema_introspector.SchemaIntrospector")``
        # continue to intercept this code path.
        from core.introspection.schema_introspector import SchemaIntrospector

        return SchemaIntrospector(provider, log, use_vendor_queries)

    @classmethod
    def register(cls, dialect: str, introspector_class: type[BaseIntrospector]) -> None:
        """
        Register a new introspector implementation for a dialect.

        Args:
            dialect: Database dialect name (case-insensitive)
            introspector_class: Class implementing BaseIntrospector
        """
        cls._DIALECT_MAP[dialect.lower()] = introspector_class

    @classmethod
    def is_supported(cls, dialect: str) -> bool:
        """
        Check if a dialect has a specific introspector implementation.

        Args:
            dialect: Database dialect name (case-insensitive)

        Returns:
            True if a specific implementation exists, False otherwise
        """
        return dialect.lower() in cls._DIALECT_MAP

    @classmethod
    def supported_dialects(cls) -> list[str]:
        """
        Get a list of all dialects with specific implementations.

        Returns:
            List of supported dialect names
        """
        return list(cls._DIALECT_MAP.keys())
