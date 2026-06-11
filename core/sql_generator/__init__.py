"""SQL Generation Module

This module provides functionality for generating SQL DDL scripts from SQL Model objects.
Includes SQL formatting, script organization, and dependency management.

Dialect-specific generators live in their plugin packages
(``db/plugins/<X>/generator/``). They are no longer re-exported here —
the legacy aliases (``PostgreSQLSqlGenerator``, ``MySQLSqlGenerator``, …)
were deprecated in 1.6.0 (roadmap action #12 PR 1) and removed in 1.7.0
(PR 2). Import from the plugin path directly:

    from db.plugins.postgresql.generator.ddl_generator import PostgreSQLSqlGenerator
"""

from core.sql_generator.alter import (
    AlterGeneratorFactory,
    BaseAlterGenerator,
)
from core.sql_generator.alter_generator import AlterGenerator
from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator
from core.sql_generator.dependency_analyzer import (
    DependencyAnalyzer,
    DependencyGraph,
)
from core.sql_generator.formatter import SqlFormatter
from core.sql_generator.generator_factory import SqlGeneratorFactory
from core.sql_generator.options import (
    OrganizationStrategy,
    OutputFormat,
    ScriptOptions,
)
from core.sql_generator.safety_checker import SafetyChecker, SafetyCheckResult
from core.sql_generator.script_formatter import SqlScriptFormatter
from core.sql_generator.script_organizer import ScriptOrganizer
from core.sql_generator.sql_generator import SqlGenerator
from core.sql_generator.sql_statement import GenerationOptions, SqlStatement

__all__ = [
    "AlterGenerator",
    "AlterGeneratorFactory",
    "BaseAlterGenerator",
    "BaseSqlGenerator",
    "BasicTableDdlGenerator",
    "DependencyAnalyzer",
    "DependencyGraph",
    "GenerationOptions",
    "SafetyChecker",
    "SafetyCheckResult",
    "SqlFormatter",
    "SqlGenerator",
    "SqlGeneratorFactory",
    "SqlScriptFormatter",
    "ScriptOrganizer",
    "ScriptOptions",
    "OrganizationStrategy",
    "OutputFormat",
    "SqlStatement",
]
