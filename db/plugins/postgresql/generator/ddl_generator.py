"""
PostgreSQL-specific SQL generation implementation.

This module provides PostgreSQL-specific SQL generation logic, inheriting
common functionality from BaseSqlGenerator and overriding methods that
require PostgreSQL-specific handling.
"""

import re
from typing import TYPE_CHECKING, List, Optional

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_model.base import SqlObject, get_object_type_name

if TYPE_CHECKING:
    from core.sql_model.extension import Extension
    from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
    from core.sql_model.foreign_server import ForeignServer
    from core.sql_model.index import Index
    from core.sql_model.procedure import Procedure
    from core.sql_model.sequence import Sequence
    from core.sql_model.synonym import Synonym
    from core.sql_model.table import Table
    from core.sql_model.trigger import Trigger
    from core.sql_model.user_defined_type import UserDefinedType
    from core.sql_model.view import View


class PostgreSQLSqlGenerator(BaseSqlGenerator):
    """
    PostgreSQL-specific SQL generation implementation.

    This class provides PostgreSQL-specific SQL generation logic while
    inheriting common functionality from BaseSqlGenerator.
    """

    def _format_statements(self, statements: List[str], dialect: str) -> str:
        """
        Format statements for PostgreSQL (no special separators needed).

        Args:
            statements: List of SQL statements
            dialect: SQL dialect (should be "postgresql")

        Returns:
            Formatted SQL string
        """
        statements = [stmt for stmt in statements if stmt and stmt.strip()]
        if not statements:
            return ""
        return "\n\n".join(statements)

    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """
        Generate a DROP statement for an object (PostgreSQL-specific).

        Args:
            obj: SQL Model object to drop
            dialect: SQL dialect (should be "postgresql")

        Returns:
            DROP statement SQL string
        """
        schema_prefix = self._schema_prefix_from_object(obj)

        obj_name = obj.format_identifier(obj.name)

        # Handle different object types
        obj_type = get_object_type_name(obj)

        if obj_type == "MATERIALIZED_VIEW":
            return f"DROP MATERIALIZED VIEW IF EXISTS {schema_prefix}{obj_name}"

        if obj_type == "VIEW":
            return f"DROP VIEW IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "TABLE":
            return f"DROP TABLE IF EXISTS {schema_prefix}{obj_name} CASCADE"

        elif obj_type == "INDEX":
            return f"DROP INDEX IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "SEQUENCE":
            return f"DROP SEQUENCE IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "FUNCTION":
            return f"DROP FUNCTION IF EXISTS {schema_prefix}{obj_name} CASCADE"

        elif obj_type == "PROCEDURE":
            return f"DROP PROCEDURE IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "TRIGGER":
            table_name = getattr(obj, "table_name", None)
            if table_name:
                table_schema = getattr(obj, "table_schema", None) or getattr(obj, "schema", None)
                table_schema_prefix = ""
                if table_schema:
                    table_schema_prefix = f"{obj.format_identifier(table_schema)}."
                return (
                    f"DROP TRIGGER IF EXISTS {obj_name} "
                    f"ON {table_schema_prefix}{obj.format_identifier(table_name)}"
                )
            return f"-- Cannot drop PostgreSQL trigger {obj_name}: table name is unknown"

        elif obj_type == "EXTENSION":
            return f"DROP EXTENSION IF EXISTS {obj_name}"

        # Default fallback
        return f"DROP {obj_type} IF EXISTS {schema_prefix}{obj_name}"

    def _get_create_dispatch(self) -> dict[type, str]:
        """Return mapping of {TypeClass: 'method_name'} for PostgreSQL types.

        Extends the 8 common types from BaseSqlGenerator with
        PostgreSQL-specific types (Extension, ForeignServer, ForeignDataWrapper).
        """
        # Import PostgreSQL-specific types only; common types come from super()
        from core.sql_model.extension import Extension
        from core.sql_model.foreign_data_wrapper import ForeignDataWrapper
        from core.sql_model.foreign_server import ForeignServer

        dispatch = super()._get_create_dispatch()
        dispatch.update(
            {
                ForeignServer: "_generate_foreign_server_create_statement",
                ForeignDataWrapper: "_generate_foreign_data_wrapper_create_statement",
                Extension: "_generate_extension_create_statement",
            }
        )
        return dispatch

    def _should_skip_formatting(self, obj: SqlObject, sql: str) -> bool:
        """Skip sqlglot formatting for PG DDL forms it logs as unsupported."""
        if super()._should_skip_formatting(obj, sql):
            return True

        from core.sql_model.user_defined_type import UserDefinedType
        from core.sql_model.view import View

        if isinstance(obj, View) and obj.materialized:
            return True
        if isinstance(obj, UserDefinedType) and getattr(obj, "is_enum", False):
            return True
        return False

    def _should_preserve_object_definition(self, obj: SqlObject, definition: Optional[str]) -> bool:
        from core.sql_model.table import Table

        if isinstance(obj, Table):
            return False
        return super()._should_preserve_object_definition(obj, definition)

    def _postprocess_create_statement(self, obj: SqlObject, create_sql: str, dialect: str) -> str:
        from core.sql_model.table import Table

        if isinstance(obj, Table):
            return _normalize_postgresql_table_ddl(create_sql)
        return create_sql

    def _generate_view_create_statement(self, view: "View") -> str:
        """Generate PostgreSQL-specific CREATE VIEW statement."""
        # Use CREATE OR REPLACE for regular views, but not for materialized views in some cases
        # For backward compatibility with tests, use basic CREATE for materialized views
        if view.materialized:
            create_keyword = "CREATE"
        elif view.dialect and view.dialect.lower() in ("postgresql", "postgres"):
            create_keyword = "CREATE OR REPLACE"
        else:
            create_keyword = "CREATE"

        # Support UNLOGGED for materialized views (PostgreSQL)
        unlogged_prefix = (
            "UNLOGGED " if (view.materialized and getattr(view, "unlogged", False)) else ""
        )

        # Start statement
        stmt = f"{create_keyword} {unlogged_prefix}{self._build_view_statement_prefix(view)}"
        stmt += self._build_view_columns_clause(view)

        # Add security context (PostgreSQL) - must come before AS clause
        if view.security_definer:
            stmt += " WITH (security_definer=true)"
        elif view.security_invoker:
            stmt += " WITH (security_invoker=true)"

        # Add query
        if view.query:
            query = view.query.strip()
            if view.materialized:
                query = query.rstrip(";").rstrip()
            stmt += f" AS\n{query}"

            # Add WITH DATA for materialized views (PostgreSQL default)
            if view.materialized:
                if getattr(view, "is_populated", None) is False:
                    stmt += "\nWITH NO DATA"
                else:
                    stmt += "\nWITH DATA"

        return stmt

    def _generate_index_create_statement(self, index: "Index") -> str:
        """Generate PostgreSQL-specific CREATE INDEX statement."""
        # Format identifiers
        idx_name = index.format_identifier(index.name)
        table_schema_name = (
            index.format_identifier(index.table_schema) if index.table_schema else ""
        )
        table_name = index.format_identifier(index.table_name)

        # PostgreSQL creates indexes in the same schema as the table
        schema_prefix = ""
        table_schema_prefix = self._build_schema_prefix(table_schema_name)

        stmt = "CREATE "
        if index.unique:
            stmt += "UNIQUE "

        # PostgreSQL CONCURRENTLY clause
        if getattr(index, "concurrently", False):
            stmt += "CONCURRENTLY "

        stmt += f"INDEX {schema_prefix}{idx_name} ON {table_schema_prefix}{table_name}"

        # Add index type if supported
        if index.type and index.type.upper() != "BTREE":
            stmt += f" USING {index.type}"

        # Add columns with expression support
        if index.columns:
            formatted_columns = []
            for i, col in enumerate(index.columns):
                # Check if this column is an expression
                is_expression = (
                    index.expression_flags
                    and i < len(index.expression_flags)
                    and index.expression_flags[i]
                )

                if is_expression:
                    formatted_col = col  # Don't quote expressions
                else:
                    formatted_col = index.format_identifier(col)

                # Add sort direction if available
                if (
                    index.sort_directions
                    and i < len(index.sort_directions)
                    and index.sort_directions[i]
                ):
                    formatted_col += f" {index.sort_directions[i]}"
                formatted_columns.append(formatted_col)
            stmt += f" ({', '.join(formatted_columns)})"

        # Add index storage options (PostgreSQL) - SQL-generation-only
        # Note: WITH clause must come before WHERE clause in PostgreSQL
        index_options = []
        if index.fillfactor is not None:
            index_options.append(f"fillfactor = {index.fillfactor}")
        if index.compression:
            index_options.append(f"compression = {index.format_identifier(index.compression)}")
        if index_options:
            stmt += f" WITH ({', '.join(index_options)})"

        # Add WHERE clause for partial indexes
        if index.condition:
            stmt += f" WHERE {index.condition}"

        return stmt

    def _generate_procedure_create_statement(self, procedure: "Procedure") -> str:
        """Generate PostgreSQL-specific CREATE PROCEDURE/FUNCTION statement."""
        if procedure.definition:
            return procedure.definition

        # Skip generating SQL for system functions/operators
        if (
            procedure.is_function
            and not procedure.body
            and not procedure.definition
            and self._is_system_function(procedure)
        ):
            return ""

        # Format schema and procedure/function name
        schema_prefix = self._schema_prefix_from_object(procedure)
        proc_name = procedure.format_identifier(procedure.name)

        # PostgreSQL uses CREATE OR REPLACE
        create_keyword = "CREATE OR REPLACE"
        object_keyword = "FUNCTION" if procedure.is_function else "PROCEDURE"

        # Start statement
        stmt = f"{create_keyword} {object_keyword} {schema_prefix}{proc_name}"

        # Add parameters if available
        if procedure.parameters:
            param_list = []
            for param in procedure.parameters:
                param_str = f"{procedure.format_identifier(param.name)} {param.data_type}"
                if param.direction and param.direction.upper() != "IN":
                    param_str = f"{param.direction} {param_str}"
                if param.default_value:
                    param_str += f" DEFAULT {param.default_value}"
                param_list.append(param_str)
            stmt += f"({', '.join(param_list)})"
        else:
            stmt += "()"

        # Add return type for functions
        if procedure.is_function and procedure.return_type:
            stmt += f" RETURNS {procedure.return_type}"

        # Add language specification (PostgreSQL-specific)
        if procedure.language and procedure.language != "SQL":
            stmt += f"\nLANGUAGE {procedure.language.lower()}"

        # Add volatility (PostgreSQL-specific)
        if procedure.volatility:
            stmt += f"\n{procedure.volatility.upper()}"

        # Add security definer
        if procedure.security_definer:
            stmt += "\nSECURITY DEFINER"

        # Add body
        if procedure.body:
            stmt += f"\nAS $$\n{procedure.body}\n$$"

        return stmt

    def _generate_synonym_create_statement(self, synonym: "Synonym") -> str:
        """Generate PostgreSQL-specific CREATE SYNONYM statement.

        Note: PostgreSQL doesn't natively support synonyms, so this creates a view as a workaround.
        """
        # Format synonym name with schema if present
        schema_prefix = self._schema_prefix_from_object(synonym)
        synonym_name = synonym.format_identifier(synonym.name)

        # PostgreSQL doesn't support synonyms natively, create a view instead
        # This is a common workaround for synonym-like functionality
        stmt = (
            f"CREATE VIEW {schema_prefix}{synonym_name} AS SELECT * FROM {synonym.target_full_name}"
        )

        return stmt

    def _generate_sequence_create_statement(self, sequence: "Sequence") -> str:
        """Generate PostgreSQL-specific CREATE SEQUENCE statement."""
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(sequence)
        seq_name = sequence.format_identifier(sequence.name)

        # PostgreSQL supports TEMPORARY sequences
        temp_prefix = ""
        if sequence.temp:
            temp_prefix = "TEMPORARY "

        stmt = f"CREATE {temp_prefix}SEQUENCE {schema_prefix}{seq_name}"

        # Add START WITH clause
        if sequence.start_with is not None:
            stmt += f" START WITH {sequence.start_with}"

        # Add INCREMENT BY clause
        if sequence.increment_by is not None and sequence.increment_by != 1:
            stmt += f" INCREMENT BY {sequence.increment_by}"

        # Add MINVALUE clause
        if sequence.min_value is not None:
            stmt += f" MINVALUE {sequence.min_value}"

        # Add MAXVALUE clause
        if sequence.max_value is not None:
            stmt += f" MAXVALUE {sequence.max_value}"

        # Add CYCLE clause (PostgreSQL uses NO CYCLE by default)
        # PostgreSQL syntax: CYCLE or NO CYCLE (with space, not NOCYCLE)
        if sequence.cycle:
            stmt += " CYCLE"
        # Note: PostgreSQL defaults to NO CYCLE, so we can omit it
        # Only add NO CYCLE if explicitly needed (but it's the default, so we skip it)

        # Add CACHE clause (PostgreSQL supports CACHE)
        if sequence.cache is not None and sequence.cache > 1:
            stmt += f" CACHE {sequence.cache}"

        return stmt

    def _generate_user_defined_type_create_statement(self, udt: "UserDefinedType") -> str:
        """Generate PostgreSQL-specific CREATE TYPE statement."""
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(udt)
        type_name = udt.format_identifier(udt.name)

        # PostgreSQL composite types
        if udt.is_composite and udt.attributes:
            attr_defs = []
            for attr in udt.attributes:
                attr_name = udt.format_identifier(attr.get("name", ""))
                attr_type = attr.get("type", "")
                attr_defs.append(f"    {attr_name} {attr_type}")
            body = ",\n".join(attr_defs)

            stmt = f"CREATE TYPE {schema_prefix}{type_name} AS (\n{body}\n)"
            return stmt

        # PostgreSQL enum types
        if udt.is_enum and udt.enum_values:
            stmt = f"CREATE TYPE {schema_prefix}{type_name} AS ENUM ("
            enum_vals = [f"'{val}'" for val in udt.enum_values]
            stmt += ", ".join(enum_vals)
            stmt += ")"
            return stmt

        # PostgreSQL domains
        if udt.is_domain and udt.base_type:
            stmt = f"CREATE DOMAIN {schema_prefix}{type_name} AS {udt.base_type}"
            if udt.definition:
                stmt += f"\n{udt.definition}"
            return stmt

        # Generic fallback
        if udt.definition:
            return f"CREATE TYPE {schema_prefix}{type_name} AS {udt.definition}"

        return f"CREATE TYPE {schema_prefix}{type_name}"

    def _generate_trigger_create_statement(self, trigger: "Trigger") -> str:
        """Generate PostgreSQL-specific CREATE TRIGGER statement."""
        # If we have a complete definition, use it
        if trigger.definition and trigger.definition.strip().upper().startswith("CREATE"):
            return trigger.definition

        # Format identifiers
        trigger_name = trigger.format_identifier(trigger.name)

        # Build the statement
        stmt = f"CREATE TRIGGER {trigger_name}\n"

        # Add timing
        if trigger.timing:
            stmt += f"  {trigger.timing}\n"

        # Add events
        if trigger.events:
            stmt += f"  {trigger.event_str}\n"

        # Add table reference
        stmt += f"  ON {trigger.qualified_table_name}\n"

        # Add orientation (PostgreSQL supports FOR EACH ROW)
        if trigger.orientation == "ROW":
            stmt += "  FOR EACH ROW\n"

        # Add trigger body
        body_sql = trigger._format_body(trigger.definition or "")
        if body_sql:
            stmt += body_sql

        return stmt

    def _generate_foreign_server_create_statement(self, foreign_server: "ForeignServer") -> str:
        """Generate PostgreSQL-specific CREATE SERVER statement."""
        # For PostgreSQL-specific objects, delegate to the fallback method
        return foreign_server._generate_basic_create_statement()

    def _generate_foreign_data_wrapper_create_statement(self, fdw: "ForeignDataWrapper") -> str:
        """Generate PostgreSQL-specific CREATE FOREIGN DATA WRAPPER statement."""
        # For PostgreSQL-specific objects, delegate to the fallback method
        return fdw._generate_basic_create_statement()

    def _generate_extension_create_statement(self, extension: "Extension") -> str:
        """Generate PostgreSQL-specific CREATE EXTENSION statement."""
        # For PostgreSQL-specific objects, delegate to the fallback method
        return extension._generate_basic_create_statement()

    def _generate_table_create_statement(self, table: "Table") -> str:
        """Generate PostgreSQL-specific CREATE TABLE statement."""
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator

        return BasicTableDdlGenerator(table).generate_create_statement()


def _normalize_postgresql_table_ddl(statement: str) -> str:
    lines = []
    for line in statement.splitlines():
        if line.startswith("    "):
            line = f"  {line[4:]}"
        line = _normalize_postgresql_column_type_line(line)
        lines.append(line)
    return "\n".join(lines)


_COLUMN_TYPE_ALIASES = {
    "int2": "SMALLINT",
    "int4": "INT",
    "int8": "BIGINT",
    "bool": "BOOLEAN",
    "varchar": "VARCHAR",
    "numeric": "DECIMAL",
}


def _normalize_postgresql_column_type_line(line: str) -> str:
    match = re.match(r'^(\s+"[^"]+"\s+)([A-Za-z][A-Za-z0-9_]*)(.*)$', line)
    if not match:
        return line
    prefix, raw_type, suffix = match.groups()
    normalized_type = _COLUMN_TYPE_ALIASES.get(raw_type.lower())
    if not normalized_type:
        return line
    return f"{prefix}{normalized_type}{suffix}"
