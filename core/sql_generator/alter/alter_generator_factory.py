"""Factory for creating database-specific ALTER generators.

This module provides a factory for creating the appropriate ALTER generator
based on the database dialect.
"""

import logging
from typing import Dict, Type

from core.seams.feature_loading import load_feature_extensions
from core.seams.sql_generators import attach_registered_sql_generators
from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator

logger = logging.getLogger(__name__)


class AlterGeneratorFactory:
    """Factory for creating database-specific ALTER generators.

    Story 26-3: each dialect's ALTER generator is owned by its plugin
    and exposed via ``DialectQuirks.alter_generator_class()``. The
    registry is built lazily on first use by iterating registered
    plugins; no dialect name is hardcoded in this factory.
    """

    _generators: Dict[str, Type[BaseAlterGenerator]] = {}
    _populated: bool = False

    @classmethod
    def reset(cls) -> None:
        """Clear cached registrations.

        Tests that patch ``ProviderRegistry`` need to discard the
        previously-built ``_generators`` so the patched plugins take
        effect on the next call. (PR #241 Bugbot.)
        """
        cls._generators.clear()
        cls._populated = False

    @classmethod
    def _ensure_populated(cls) -> None:
        if cls._populated:
            return
        from db.provider_registry import ProviderRegistry

        load_feature_extensions()
        attach_registered_sql_generators()
        ProviderRegistry.discover_plugins()
        for plugin_info in ProviderRegistry.list_plugins():
            # Per-plugin fault isolation: a broken plugin must not
            # prevent the others from registering. (PR #241 Bugbot.)
            try:
                quirks = ProviderRegistry.get_quirks(plugin_info.name)
                alter_class = quirks.alter_generator_class()
                if alter_class is None:
                    continue
                for alias in plugin_info.dialects:
                    cls._generators[alias.lower()] = alter_class
            except Exception as exc:
                logger.warning(
                    "Failed to register ALTER generator for plugin %r: %s",
                    plugin_info.name,
                    exc,
                )
        cls._populated = True

    @classmethod
    def create_generator(cls, dialect: str) -> BaseAlterGenerator:
        """Create an ALTER generator for the specified dialect.

        Args:
            dialect: Database dialect (postgresql, oracle, mysql, sqlserver, db2)

        Returns:
            Database-specific ALTER generator instance

        Raises:
            ValueError: If dialect is not supported
        """
        cls._ensure_populated()
        dialect_lower = dialect.lower()

        # Get generator class from registry
        if dialect_lower not in cls._generators:
            supported_dialects = ", ".join(sorted(cls._generators.keys()))
            raise ValueError(
                f"Unsupported dialect '{dialect}'. " f"Supported dialects: {supported_dialects}"
            )

        generator_class = cls._generators[dialect_lower]
        logger.debug(f"Creating {generator_class.__name__} for dialect '{dialect}'")

        return generator_class(dialect)

    @classmethod
    def get_supported_dialects(cls) -> list[str]:
        """Get list of supported database dialects.

        Returns:
            List of supported dialect names
        """
        cls._ensure_populated()
        return sorted(cls._generators.keys())

    @classmethod
    def register_generator(cls, dialect: str, generator_class: Type[BaseAlterGenerator]) -> None:
        """Register a new ALTER generator for a dialect.

        Args:
            dialect: Database dialect name
            generator_class: ALTER generator class

        Raises:
            TypeError: If generator_class is not a BaseAlterGenerator subclass
        """
        if not issubclass(generator_class, BaseAlterGenerator):
            raise TypeError(
                f"Generator class must be a subclass of BaseAlterGenerator, "
                f"got {generator_class.__name__}"
            )

        cls._generators[dialect.lower()] = generator_class
        logger.info(f"Registered {generator_class.__name__} for dialect '{dialect}'")
