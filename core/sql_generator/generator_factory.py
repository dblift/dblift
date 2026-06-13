"""
Factory for creating database-specific SQL generator instances.

This module provides a factory for instantiating the appropriate
BaseSqlGenerator implementation based on the database dialect.
"""

import logging
from typing import TYPE_CHECKING, Dict, Optional, Union

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.formatter import SqlFormatter

logger = logging.getLogger(__name__)

if TYPE_CHECKING:
    from core.sql_generator.sql_generator import SqlGenerator


class SqlGeneratorFactory:
    """
    Factory for creating database-specific SQL generator instances.

    This factory maps database dialects to their corresponding
    BaseSqlGenerator implementation.

    Example:
        >>> generator = SqlGeneratorFactory.create("postgresql")
        >>> sql = generator.generate_ddl([table])
    """

    # Mapping of dialect names to generator classes
    # Will be populated as we implement each database-specific generator
    _DIALECT_MAP: Dict[str, type[BaseSqlGenerator]] = {}
    # Explicit flag mirrors ``AlterGeneratorFactory._populated`` so the
    # two factories share the same lazy-init contract. Using the
    # truthiness of ``_DIALECT_MAP`` would re-run discovery whenever
    # an external caller registered a single generator and then called
    # ``register`` to clear it back to empty.
    _populated: bool = False

    @classmethod
    def reset(cls) -> None:
        """Clear cached registrations.

        Tests that patch ``ProviderRegistry`` need to discard the
        previously-built ``_DIALECT_MAP`` so the patched plugins take
        effect on the next call. (PR #241 Bugbot.)
        """
        cls._DIALECT_MAP.clear()
        cls._populated = False

    @classmethod
    def create(
        cls,
        dialect: str,
        formatter: Optional[SqlFormatter] = None,
        use_dependency_ordering: bool = True,
    ) -> Union[BaseSqlGenerator, "SqlGenerator"]:
        """
        Create a BaseSqlGenerator instance for the given dialect.

        Args:
            dialect: Database dialect name (case-insensitive)
            formatter: Optional SQL formatter instance
            use_dependency_ordering: Whether to order objects by dependencies

        Returns:
            BaseSqlGenerator instance for the dialect

        Note:
            If no specific implementation exists for the dialect, falls back
            to the original SqlGenerator.
        """
        # Register default implementations on first call
        if not cls._populated:
            cls._register_defaults()
            cls._populated = True

        dialect_lower = dialect.lower()

        # Check if we have a specific implementation
        generator_class = cls._DIALECT_MAP.get(dialect_lower)

        if generator_class:
            return generator_class(
                formatter=formatter,
                default_dialect=dialect_lower,
                use_dependency_ordering=use_dependency_ordering,
            )

        # Fallback to original SqlGenerator for now
        # This allows incremental migration
        from core.sql_generator.sql_generator import SqlGenerator

        return SqlGenerator(
            formatter=formatter,
            default_dialect=dialect_lower,
            use_dependency_ordering=use_dependency_ordering,
        )

    @classmethod
    def _register_defaults(cls) -> None:
        """Register default generator implementations.

        Story 26-3: dialect-specific generators live inside their plugin
        package and are advertised via ``DialectQuirks.ddl_generator_class()``.
        Iterate the registered plugins and consult each one's quirks —
        no hardcoded dialect names in this factory.

        Each plugin is registered in its own ``try/except`` block so
        that a single broken plugin (e.g. a syntax error in a
        newly-developed generator module) does not prevent the other
        dialects from registering. Matches the per-plugin fault
        isolation the previous hardcoded ``_register_defaults`` had
        via individual ``try/except ImportError`` blocks. (PR #241
        Bugbot.)
        """
        from db.provider_registry import ProviderRegistry

        ProviderRegistry.discover_plugins()
        for plugin_info in ProviderRegistry.list_plugins():
            try:
                quirks = ProviderRegistry.get_quirks(plugin_info.name)
                generator_class = quirks.ddl_generator_class()
                if generator_class is None:
                    continue
                for alias in plugin_info.dialects:
                    cls.register(alias, generator_class)
            except Exception as exc:
                logger.warning(
                    "Failed to register DDL generator for plugin %r: %s",
                    plugin_info.name,
                    exc,
                )

    @classmethod
    def register(cls, dialect: str, generator_class: type[BaseSqlGenerator]) -> None:
        """Register a new generator implementation for a dialect.

        Args:
            dialect: Database dialect name (case-insensitive)
            generator_class: Class implementing BaseSqlGenerator
        """
        cls._DIALECT_MAP[dialect.lower()] = generator_class

    @classmethod
    def is_supported(cls, dialect: str) -> bool:
        """
        Check if a dialect has a specific generator implementation.

        Args:
            dialect: Database dialect name (case-insensitive)

        Returns:
            True if a specific implementation exists, False otherwise
        """
        if not cls._populated:
            cls._register_defaults()
            cls._populated = True
        return dialect.lower() in cls._DIALECT_MAP

    @classmethod
    def supported_dialects(cls) -> list[str]:
        """
        Get a list of all dialects with specific implementations.

        Returns:
            List of supported dialect names
        """
        if not cls._populated:
            cls._register_defaults()
            cls._populated = True
        return list(cls._DIALECT_MAP.keys())
