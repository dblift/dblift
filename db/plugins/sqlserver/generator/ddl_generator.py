"""
SQL Server-specific SQL generation implementation.

This module provides SQL Server-specific SQL generation logic, inheriting
common functionality from BaseSqlGenerator and overriding methods that
require SQL Server-specific handling.
"""

import re
from typing import TYPE_CHECKING, List

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_model.base import SqlObject, get_object_type_name

if TYPE_CHECKING:
    from core.sql_model.index import Index
    from core.sql_model.procedure import Procedure
    from core.sql_model.sequence import Sequence
    from core.sql_model.synonym import Synonym
    from core.sql_model.table import Table
    from core.sql_model.trigger import Trigger
    from core.sql_model.user_defined_type import UserDefinedType
    from core.sql_model.view import View


class SQLServerSqlGenerator(BaseSqlGenerator):
    """
    SQL Server-specific SQL generation implementation.

    This class provides SQL Server-specific SQL generation logic while
    inheriting common functionality from BaseSqlGenerator.
    """

    def _format_statements(self, statements: List[str], dialect: str) -> str:
        """
        Format statements for SQL Server (uses GO separators).

        SQL Server requires GO statements as batch separators.

        Args:
            statements: List of SQL statements
            dialect: SQL dialect (should be "sqlserver")

        Returns:
            Formatted SQL string with GO separators
        """
        statements = [stmt for stmt in statements if stmt and stmt.strip()]
        if not statements:
            return ""
        body = "\nGO\n\n".join(statements)
        return f"{body}\nGO"

    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """
        Generate a DROP statement for an object (SQL Server-specific).

        Args:
            obj: SQL Model object to drop
            dialect: SQL dialect (should be "sqlserver")

        Returns:
            DROP statement SQL string
        """
        schema_prefix = self._schema_prefix_from_object(obj)

        obj_name = obj.format_identifier(obj.name)

        # Handle different object types
        obj_type = get_object_type_name(obj)

        if obj_type == "MATERIALIZED_VIEW":
            return f"DROP VIEW IF EXISTS {schema_prefix}{obj_name}"

        if obj_type == "VIEW":
            return f"DROP VIEW IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "TABLE":
            return f"DROP TABLE IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "INDEX":
            # SQL Server requires ON table_name
            table_name = obj.table_name if hasattr(obj, "table_name") else "unknown"
            return f"DROP INDEX IF EXISTS {obj_name} ON {schema_prefix}{table_name}"

        elif obj_type == "SEQUENCE":
            return f"DROP SEQUENCE IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "PROCEDURE" or obj_type == "FUNCTION":
            return f"DROP {obj_type} IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "TRIGGER":
            return f"DROP TRIGGER IF EXISTS {schema_prefix}{obj_name}"

        # Default fallback
        return f"DROP {obj_type} IF EXISTS {schema_prefix}{obj_name}"

    def _get_create_dispatch(self) -> dict[type, str]:
        """Return mapping of {TypeClass: 'method_name'} for SQL Server types.

        SQL Server supports exactly the 8 common types defined in
        BaseSqlGenerator; no dialect-specific additions are needed.
        """
        return super()._get_create_dispatch()

    def _generate_additional_statements(self, obj: SqlObject, dialect: str) -> List[str]:
        """Generate SQL Server-specific follow-up statements after CREATE."""
        additional = super()._generate_additional_statements(obj, dialect)

        if not dialect or dialect.lower() not in {"sqlserver", "mssql"}:
            return additional

        from core.sql_model.view import View

        if isinstance(obj, View) and obj.materialized:
            clustered_name = getattr(obj, "clustered_index_name", None)
            clustered_columns = getattr(obj, "clustered_index_columns", None) or []
            if clustered_name and clustered_columns:
                schema_prefix = self._schema_prefix_from_object(obj)
                view_name = obj.format_identifier(obj.name)
                idx_name = obj.format_identifier(clustered_name)
                formatted_cols = ", ".join(obj.format_identifier(c) for c in clustered_columns)
                additional.append(
                    f"CREATE UNIQUE CLUSTERED INDEX {idx_name} "
                    f"ON {schema_prefix}{view_name} ({formatted_cols})"
                )

        return additional

    def _generate_create_fallback(self, obj: SqlObject) -> str:
        """Fallback to basic CREATE statement for unsupported SQL Server types."""
        return self._generate_basic_create_statement(obj)

    def _generate_view_create_statement(self, view: "View") -> str:
        """Generate SQL Server-specific CREATE VIEW statement.

        Batch-5 BUG-05: SQL Server has no ``CREATE MATERIALIZED VIEW`` syntax —
        indexed views are emitted as ``CREATE VIEW ... WITH SCHEMABINDING``
        followed by a ``CREATE UNIQUE CLUSTERED INDEX``. The shared
        ``_build_view_statement_prefix`` helper branches on
        ``view.materialized`` and returns the generic
        ``"MATERIALIZED VIEW {schema}.{name}"`` fragment, which is invalid
        T-SQL. Build the prefix locally with a hard-coded ``VIEW`` keyword so
        the generated DDL can be re-imported cleanly.
        """
        schema_prefix = self._schema_prefix_from_object(view)
        view_name = view.format_identifier(view.name)
        stmt = f"CREATE VIEW {schema_prefix}{view_name}"

        # Add columns if specified
        stmt += self._build_view_columns_clause(view)

        # SQL Server indexed views must be schema-bound before the AS clause.
        if view.materialized:
            stmt += "\nWITH SCHEMABINDING"

        # Add query
        if view.query:
            query = view.query
            query_upper = query.upper().strip()

            # SQL Server's OBJECT_DEFINITION returns the full CREATE VIEW statement
            # Extract just the SELECT part if the query contains CREATE VIEW
            if query_upper.startswith("CREATE"):
                # Extract the SELECT statement after "AS"
                match = re.search(r"\bAS\s+(SELECT.*)", query, re.IGNORECASE | re.DOTALL)
                if match:
                    query = match.group(1).strip()
                else:
                    # If no AS found, try to extract SELECT directly
                    match = re.search(r"\bSELECT.*", query, re.IGNORECASE | re.DOTALL)
                    if match:
                        query = match.group(0).strip()
            query = re.sub(r"^\s*WITH\s+SCHEMABINDING\s+", "", query, flags=re.IGNORECASE)
            stmt += f" AS\n{query}"

        return stmt

    def _generate_index_create_statement(self, index: "Index") -> str:
        """Generate SQL Server-specific CREATE INDEX statement."""
        # Format identifiers
        idx_name = index.format_identifier(index.name)
        table_schema_name = (
            index.format_identifier(index.table_schema) if index.table_schema else ""
        )
        table_name = index.format_identifier(index.table_name)

        # SQL Server: Index names cannot be schema-qualified, only table names can be
        # Remove schema prefix from index name
        table_schema_prefix = self._build_schema_prefix(table_schema_name)

        stmt = "CREATE "
        if index.unique:
            stmt += "UNIQUE "

        stmt += f"INDEX {idx_name} ON {table_schema_prefix}{table_name}"

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

        # Add INCLUDE clause for SQL Server (covering indexes)
        if getattr(index, "include_columns", None):
            include_columns = [index.format_identifier(col) for col in index.include_columns]
            stmt += f" INCLUDE ({', '.join(include_columns)})"

        # Add WHERE clause for filtered indexes
        if index.condition:
            stmt += f" WHERE {index.condition}"

        # Add index options (SQL Server)
        index_options = []
        if index.fillfactor is not None:
            index_options.append(f"FILLFACTOR = {index.fillfactor}")
        if index.compression:
            index_options.append(f"DATA_COMPRESSION = {index.format_identifier(index.compression)}")
        if index_options:
            stmt += f" WITH ({', '.join(index_options)})"

        return stmt

    def _generate_procedure_create_statement(self, procedure: "Procedure") -> str:
        """Generate SQL Server-specific CREATE PROCEDURE/FUNCTION statement."""
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

        # SQL Server uses CREATE
        create_keyword = "CREATE"
        object_keyword = "FUNCTION" if procedure.is_function else "PROCEDURE"

        # Start statement
        stmt = f"{create_keyword} {object_keyword} {schema_prefix}{proc_name}"

        # Add parameters if available
        if procedure.parameters:
            param_list = []
            for param in procedure.parameters:
                # SQL Server parameters start with @
                param_name = param.name if param.name.startswith("@") else f"@{param.name}"
                param_str = f"{param_name} {param.data_type}"
                if param.direction and param.direction.upper() != "IN":
                    param_str = f"{param_str} {param.direction}"
                if param.default_value:
                    param_str += f" = {param.default_value}"
                param_list.append(param_str)
            stmt += f"({', '.join(param_list)})"

        # Add return type for functions
        if procedure.is_function and procedure.return_type:
            stmt += f" RETURNS {procedure.return_type}"

        # Add body
        if procedure.body:
            stmt += f"\nAS\nBEGIN\n{procedure.body}\nEND"

        return stmt

    def _generate_table_create_statement(self, table: "Table") -> str:
        """Generate SQL Server-specific CREATE TABLE statement."""
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator

        return BasicTableDdlGenerator(table).generate_create_statement()

    def _generate_synonym_create_statement(self, synonym: "Synonym") -> str:
        """Generate SQL Server-specific CREATE SYNONYM statement."""
        # Format synonym name with schema if present
        schema_prefix = self._schema_prefix_from_object(synonym)
        synonym_name = synonym.format_identifier(synonym.name)

        # SQL Server: CREATE SYNONYM
        stmt = f"CREATE SYNONYM {schema_prefix}{synonym_name}"

        # Add FOR clause with target
        stmt += f"\nFOR {synonym.target_full_name}"

        return stmt

    def _generate_sequence_create_statement(self, sequence: "Sequence") -> str:
        """Generate SQL Server-specific CREATE SEQUENCE statement."""
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(sequence)
        seq_name = sequence.format_identifier(sequence.name)

        stmt = f"CREATE SEQUENCE {schema_prefix}{seq_name}"

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

        # Add CYCLE clause (SQL Server uses NO CYCLE)
        if sequence.cycle:
            stmt += " CYCLE"
        else:
            stmt += " NO CYCLE"

        # Add CACHE clause (SQL Server supports CACHE)
        if sequence.cache is not None and sequence.cache > 1:
            stmt += f" CACHE {sequence.cache}"

        return stmt

    def _generate_user_defined_type_create_statement(self, udt: "UserDefinedType") -> str:
        """Generate SQL Server-specific CREATE TYPE statement."""
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(udt)
        type_name = udt.format_identifier(udt.name)

        # SQL Server table types (composite types)
        if udt.is_composite and udt.attributes:
            attr_defs = []
            for attr in udt.attributes:
                attr_name = udt.format_identifier(attr.get("name", ""))
                attr_type = attr.get("type", "")
                attr_defs.append(f"    {attr_name} {attr_type}")
            body = ",\n".join(attr_defs)

            # SQL Server uses TABLE type for composite types
            stmt = f"CREATE TYPE {schema_prefix}{type_name} AS TABLE (\n{body}\n)"
            return stmt

        # SQL Server doesn't support ENUM types natively, create a check constraint workaround
        if udt.is_enum and udt.enum_values:
            # Create a simple VARCHAR type with a comment about allowed values
            enum_vals = "', '".join(udt.enum_values)
            stmt = f"CREATE TYPE {schema_prefix}{type_name} FROM VARCHAR(255)"
            stmt += f" -- Allowed values: '{enum_vals}'"
            return stmt

        # SQL Server distinct types (FROM syntax)
        if udt.is_distinct and udt.base_type:
            stmt = f"CREATE TYPE {schema_prefix}{type_name} FROM {udt.base_type}"
            return stmt

        # Generic fallback
        if udt.definition:
            return f"CREATE TYPE {schema_prefix}{type_name} FROM {udt.definition}"

        return f"CREATE TYPE {schema_prefix}{type_name}"

    def _generate_trigger_create_statement(self, trigger: "Trigger") -> str:
        """Generate SQL Server-specific CREATE TRIGGER statement."""
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

        # SQL Server doesn't have FOR EACH ROW syntax - it's always row-level

        # Add trigger body
        body_sql = trigger._format_body(trigger.definition or "")
        if body_sql:
            stmt += body_sql

        return stmt

    def _generate_basic_create_statement(self, obj: SqlObject) -> str:
        """Generate a basic CREATE statement as fallback."""
        # Basic CREATE statement without dialect-specific logic
        obj_type = get_object_type_name(obj)
        schema_prefix = self._schema_prefix_from_object(obj)
        obj_name = obj.format_identifier(obj.name)

        return f"CREATE {obj_type} {schema_prefix}{obj_name}"
