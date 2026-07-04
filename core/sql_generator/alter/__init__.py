"""ALTER Statement Generation Module.

This module provides the framework's ALTER generation surface
(factory + base class). Dialect-specific ALTER generators live in
``db/plugins/<X>/generator/alter_generator.py`` — the legacy aliases
(``PostgreSQLAlterGenerator``, ``MySQLAlterGenerator``, …) re-exported
here were deprecated in 1.6.0 (roadmap action #12 PR 1) and removed in
1.7.0 (PR 2). Import from the plugin path directly.
"""

from core.sql_generator.alter.alter_generator_factory import AlterGeneratorFactory
from core.sql_generator.alter.base_alter_generator import BaseAlterGenerator

__all__ = [
    "AlterGeneratorFactory",
    "BaseAlterGenerator",
]
