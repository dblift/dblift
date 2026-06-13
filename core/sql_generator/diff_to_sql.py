"""Convenience functions for generating SQL scripts from diffs.

This module provides high-level functions to convert schema diffs
into SQL scripts that can be reviewed and executed by DBAs.
"""

import logging
from dataclasses import dataclass
from typing import Dict, List, Optional

from core.comparison.diff_models import SchemaDiff
from core.sql_generator.diff_sql_generator import DiffGenerationContext, DiffSqlGenerator
from core.sql_generator.script_formatter import SqlScriptFormatter
from core.sql_generator.sql_statement import GenerationOptions, SqlStatement
from core.sql_model.database_link import DatabaseLink
from core.sql_model.event import Event
from core.sql_model.extension import Extension
from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
from core.sql_model.foreign_server import ForeignServer
from core.sql_model.index import Index
from core.sql_model.linked_server import LinkedServer
from core.sql_model.package import Package
from core.sql_model.procedure import Procedure
from core.sql_model.sequence import Sequence
from core.sql_model.synonym import Synonym
from core.sql_model.table import Table
from core.sql_model.trigger import Trigger
from core.sql_model.user_defined_type import UserDefinedType
from core.sql_model.view import View

logger = logging.getLogger(__name__)


@dataclass
class GenerateSqlScriptOptions:
    """Options for generate_sql_script() and generate_sql_statements().

    Groups the 16 expected_* object maps and the script-formatting flags,
    reducing the function signatures from 22 parameters to (diff, options).

    Example::

        options = GenerateSqlScriptOptions(
            expected_tables={"users": users_table},
            dialect="postgresql",
            title="Schema Update",
        )
        script = generate_sql_script(diff, options=options)
    """

    # Per-object-type expected objects (used to generate ADD/ALTER/CREATE statements)
    expected_tables: Optional[Dict[str, Table]] = None
    expected_views: Optional[Dict[str, View]] = None
    expected_indexes: Optional[Dict[str, Index]] = None
    expected_sequences: Optional[Dict[str, Sequence]] = None
    expected_triggers: Optional[Dict[str, Trigger]] = None
    expected_procedures: Optional[Dict[str, Procedure]] = None
    expected_functions: Optional[Dict[str, Procedure]] = None
    expected_synonyms: Optional[Dict[str, Synonym]] = None
    expected_extensions: Optional[Dict[str, Extension]] = None
    expected_user_defined_types: Optional[Dict[str, UserDefinedType]] = None
    expected_packages: Optional[Dict[str, Package]] = None
    expected_events: Optional[Dict[str, Event]] = None
    expected_database_links: Optional[Dict[str, DatabaseLink]] = None
    expected_linked_servers: Optional[Dict[str, LinkedServer]] = None
    expected_foreign_data_wrappers: Optional[Dict[str, ForeignDataWrapper]] = None
    expected_foreign_servers: Optional[Dict[str, ForeignServer]] = None

    # Script generation settings.
    # AlterGeneratorFactory requires a registered dialect; "postgresql"
    # is the safe default for callers that don't specify one.
    dialect: str = "postgresql"  # lint: allow-dialect-string
    title: Optional[str] = None
    description: Optional[str] = None
    include_comments: bool = True
    include_checks: bool = True

    def to_diff_generation_context(self) -> DiffGenerationContext:
        """Build a DiffGenerationContext from these options."""
        return DiffGenerationContext(
            expected_tables=self.expected_tables,
            expected_views=self.expected_views,
            expected_indexes=self.expected_indexes,
            expected_sequences=self.expected_sequences,
            expected_triggers=self.expected_triggers,
            expected_procedures=self.expected_procedures,
            expected_functions=self.expected_functions,
            expected_synonyms=self.expected_synonyms,
            expected_extensions=self.expected_extensions,
            expected_user_defined_types=self.expected_user_defined_types,
            expected_packages=self.expected_packages,
            expected_events=self.expected_events,
            expected_database_links=self.expected_database_links,
            expected_linked_servers=self.expected_linked_servers,
            expected_foreign_data_wrappers=self.expected_foreign_data_wrappers,
            expected_foreign_servers=self.expected_foreign_servers,
        )


def generate_sql_script(
    diff: SchemaDiff,
    script_options: Optional[GenerateSqlScriptOptions] = None,
    # Backward-compatible keyword arguments (ignored when script_options is provided)
    expected_tables: Optional[Dict[str, Table]] = None,
    expected_views: Optional[Dict[str, View]] = None,
    expected_indexes: Optional[Dict[str, Index]] = None,
    expected_sequences: Optional[Dict[str, Sequence]] = None,
    expected_triggers: Optional[Dict[str, Trigger]] = None,
    expected_procedures: Optional[Dict[str, Procedure]] = None,
    expected_functions: Optional[Dict[str, Procedure]] = None,
    expected_synonyms: Optional[Dict[str, Synonym]] = None,
    expected_extensions: Optional[Dict[str, Extension]] = None,
    expected_user_defined_types: Optional[Dict[str, UserDefinedType]] = None,
    expected_packages: Optional[Dict[str, Package]] = None,
    expected_events: Optional[Dict[str, Event]] = None,
    expected_database_links: Optional[Dict[str, DatabaseLink]] = None,
    expected_linked_servers: Optional[Dict[str, LinkedServer]] = None,
    expected_foreign_data_wrappers: Optional[Dict[str, ForeignDataWrapper]] = None,
    expected_foreign_servers: Optional[Dict[str, ForeignServer]] = None,
    dialect: str = "postgresql",  # lint: allow-dialect-string
    title: Optional[str] = None,
    description: Optional[str] = None,
    include_comments: bool = True,
    include_checks: bool = True,
) -> str:
    """Generate a complete SQL script from a schema diff.

    This is the main entry point for generating SQL scripts that DBAs
    can review and execute to synchronize database schemas.

    Preferred usage (SIMP-49) — pass a GenerateSqlScriptOptions instance::

        opts = GenerateSqlScriptOptions(
            expected_tables={"users": users_table},
            dialect="postgresql",
            title="Schema Update Script",
        )
        script = generate_sql_script(diff, opts)

    Legacy usage (all keyword args) is still supported for backward compatibility.

    Args:
        diff: Schema diff to convert to SQL
        script_options: Grouped generation options (preferred). When provided,
            all remaining keyword arguments are ignored.
        expected_tables: (legacy) Optional mapping of table names to expected Table objects
        expected_views: (legacy) Optional mapping of view names to expected View objects
        expected_indexes: (legacy) Optional mapping of index names to expected Index objects
        expected_sequences: (legacy) Optional mapping of sequence names to expected Sequence objects
        expected_triggers: (legacy) Optional mapping of trigger names to expected Trigger objects
        expected_procedures: (legacy) Optional mapping of procedure names to expected Procedure objects
        expected_functions: (legacy) Optional mapping of function names to expected Procedure objects
        expected_synonyms: (legacy) Optional mapping of synonym names to expected Synonym objects
        expected_extensions: (legacy) Optional mapping of extension names to expected Extension objects
        expected_user_defined_types: (legacy) Optional mapping of type names to expected UserDefinedType objects
        expected_packages: (legacy) Optional mapping of package names to expected Package objects
        expected_events: (legacy) Optional mapping of event names to expected Event objects
        expected_database_links: (legacy) Optional mapping of link names to expected DatabaseLink objects
        expected_linked_servers: (legacy) Optional mapping of server names to expected LinkedServer objects
        expected_foreign_data_wrappers: (legacy) Optional mapping of wrapper names to expected ForeignDataWrapper objects
        expected_foreign_servers: (legacy) Optional mapping of server names to expected ForeignServer objects
        dialect: (legacy) SQL dialect (postgresql, oracle, mysql, sqlserver)
        title: (legacy) Optional title for the script
        description: (legacy) Optional description
        include_comments: (legacy) Whether to include comments in the script
        include_checks: (legacy) Whether to include pre-execution checks

    Returns:
        Complete SQL script as string
    """
    # Resolve options: prefer the dataclass, fall back to individual kwargs
    if script_options is None:
        script_options = GenerateSqlScriptOptions(
            expected_tables=expected_tables,
            expected_views=expected_views,
            expected_indexes=expected_indexes,
            expected_sequences=expected_sequences,
            expected_triggers=expected_triggers,
            expected_procedures=expected_procedures,
            expected_functions=expected_functions,
            expected_synonyms=expected_synonyms,
            expected_extensions=expected_extensions,
            expected_user_defined_types=expected_user_defined_types,
            expected_packages=expected_packages,
            expected_events=expected_events,
            expected_database_links=expected_database_links,
            expected_linked_servers=expected_linked_servers,
            expected_foreign_data_wrappers=expected_foreign_data_wrappers,
            expected_foreign_servers=expected_foreign_servers,
            dialect=dialect,
            title=title,
            description=description,
            include_comments=include_comments,
            include_checks=include_checks,
        )

    # Generate SQL statements
    generator = DiffSqlGenerator(dialect=script_options.dialect)
    gen_options = GenerationOptions(dialect=script_options.dialect)
    context = script_options.to_diff_generation_context()
    statements = generator.generate_from_diff(diff, context=context, options=gen_options)

    # For dialects that require SDK execution, mark DROP statements and
    # build SDK operation metadata via plugin quirks hooks.
    from db.provider_registry import ProviderRegistry

    dialect_quirks = ProviderRegistry.get_quirks((script_options.dialect or "").lower())
    if dialect_quirks.requires_sdk_for_drop():
        for statement in statements:
            if statement.requires_sdk or statement.statement_type == "DROP":
                statement.requires_sdk = True
                if not statement.sdk_operation:
                    statement.sdk_operation = dialect_quirks.build_sdk_drop_operation(statement)

    # Format into script
    formatter = SqlScriptFormatter(
        include_comments=script_options.include_comments,
        include_checks=script_options.include_checks,
    )

    effective_title = script_options.title or f"Schema Update Script ({script_options.dialect})"
    effective_description = (
        script_options.description or "Generated SQL script to synchronize database schema"
    )

    script = formatter.format_script(
        statements, title=effective_title, description=effective_description
    )

    # Append SDK script block if the dialect provides one.
    if dialect_quirks.requires_sdk_for_drop():
        sdk_statements = [s for s in statements if s.requires_sdk]
        if sdk_statements:
            sdk_block = dialect_quirks.generate_sdk_script(sdk_statements)
            if sdk_block:
                script += sdk_block

    return script


def generate_sql_statements(
    diff: SchemaDiff,
    script_options: Optional[GenerateSqlScriptOptions] = None,
    # Backward-compatible keyword arguments (ignored when script_options is provided)
    expected_tables: Optional[Dict[str, Table]] = None,
    expected_views: Optional[Dict[str, View]] = None,
    expected_indexes: Optional[Dict[str, Index]] = None,
    expected_sequences: Optional[Dict[str, Sequence]] = None,
    expected_triggers: Optional[Dict[str, Trigger]] = None,
    expected_procedures: Optional[Dict[str, Procedure]] = None,
    expected_functions: Optional[Dict[str, Procedure]] = None,
    expected_synonyms: Optional[Dict[str, Synonym]] = None,
    expected_extensions: Optional[Dict[str, Extension]] = None,
    expected_user_defined_types: Optional[Dict[str, UserDefinedType]] = None,
    expected_packages: Optional[Dict[str, Package]] = None,
    expected_events: Optional[Dict[str, Event]] = None,
    expected_database_links: Optional[Dict[str, DatabaseLink]] = None,
    expected_linked_servers: Optional[Dict[str, LinkedServer]] = None,
    expected_foreign_data_wrappers: Optional[Dict[str, ForeignDataWrapper]] = None,
    expected_foreign_servers: Optional[Dict[str, ForeignServer]] = None,
    dialect: str = "postgresql",  # lint: allow-dialect-string
) -> List[SqlStatement]:
    """Generate SQL statements from a schema diff.

    Returns the raw SQL statements without formatting, useful for
    programmatic processing.

    Preferred usage (SIMP-49) — pass a GenerateSqlScriptOptions instance::

        opts = GenerateSqlScriptOptions(
            expected_tables={"users": users_table},
            dialect="postgresql",
        )
        statements = generate_sql_statements(diff, opts)

    Legacy usage (all keyword args) is still supported for backward compatibility.

    Args:
        diff: Schema diff to convert to SQL
        script_options: Grouped generation options (preferred). When provided,
            all remaining keyword arguments are ignored.
        expected_tables: (legacy) Optional mapping of table names to expected Table objects
        expected_views: (legacy) Optional mapping of view names to expected View objects
        expected_indexes: (legacy) Optional mapping of index names to expected Index objects
        expected_sequences: (legacy) Optional mapping of sequence names to expected Sequence objects
        expected_triggers: (legacy) Optional mapping of trigger names to expected Trigger objects
        expected_procedures: (legacy) Optional mapping of procedure names to expected Procedure objects
        expected_functions: (legacy) Optional mapping of function names to expected Procedure objects
        expected_synonyms: (legacy) Optional mapping of synonym names to expected Synonym objects
        expected_extensions: (legacy) Optional mapping of extension names to expected Extension objects
        expected_user_defined_types: (legacy) Optional mapping of type names to expected UserDefinedType objects
        expected_packages: (legacy) Optional mapping of package names to expected Package objects
        expected_events: (legacy) Optional mapping of event names to expected Event objects
        expected_database_links: (legacy) Optional mapping of link names to expected DatabaseLink objects
        expected_linked_servers: (legacy) Optional mapping of server names to expected LinkedServer objects
        expected_foreign_data_wrappers: (legacy) Optional mapping of wrapper names to expected ForeignDataWrapper objects
        expected_foreign_servers: (legacy) Optional mapping of server names to expected ForeignServer objects
        dialect: (legacy) SQL dialect

    Returns:
        List of SQL statements
    """
    if script_options is None:
        script_options = GenerateSqlScriptOptions(
            expected_tables=expected_tables,
            expected_views=expected_views,
            expected_indexes=expected_indexes,
            expected_sequences=expected_sequences,
            expected_triggers=expected_triggers,
            expected_procedures=expected_procedures,
            expected_functions=expected_functions,
            expected_synonyms=expected_synonyms,
            expected_extensions=expected_extensions,
            expected_user_defined_types=expected_user_defined_types,
            expected_packages=expected_packages,
            expected_events=expected_events,
            expected_database_links=expected_database_links,
            expected_linked_servers=expected_linked_servers,
            expected_foreign_data_wrappers=expected_foreign_data_wrappers,
            expected_foreign_servers=expected_foreign_servers,
            dialect=dialect,
        )

    generator = DiffSqlGenerator(dialect=script_options.dialect)
    gen_options = GenerationOptions(dialect=script_options.dialect)
    context = script_options.to_diff_generation_context()
    return generator.generate_from_diff(diff, context=context, options=gen_options)
