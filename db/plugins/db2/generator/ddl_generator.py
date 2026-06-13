"""
DB2-specific SQL generation implementation.

This module provides DB2-specific SQL generation logic, inheriting
common functionality from BaseSqlGenerator and overriding methods that
require DB2-specific handling.
"""

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


class DB2SqlGenerator(BaseSqlGenerator):
    """
    DB2-specific SQL generation implementation.

    This class provides DB2-specific SQL generation logic while
    inheriting common functionality from BaseSqlGenerator.
    """

    def _generate_additional_statements(self, obj: SqlObject, dialect: str) -> List[str]:
        """
        Generate additional statements needed after CREATE (DB2-specific).

        For DB2 tables, generate ALTER TABLE statements for CHECK constraints.

        Args:
            obj: SQL Model object
            dialect: SQL dialect

        Returns:
            List of additional SQL statements
        """
        additional = []

        # For DB2 tables, generate ALTER TABLE statements for CHECK constraints
        # This matches the pattern in original migration scripts
        if (
            hasattr(obj, "generate_alter_table_check_constraints")
            and dialect
            and dialect.lower() == "db2"
        ):
            alter_statements = obj.generate_alter_table_check_constraints()
            additional.extend(alter_statements)

        # For DB2 tables, generate ALTER TABLE statements for self-referencing foreign keys
        # DB2 doesn't allow self-referencing foreign keys in CREATE TABLE statements
        if (
            hasattr(obj, "generate_alter_table_self_referencing_foreign_keys")
            and dialect
            and dialect.lower() == "db2"
        ):
            alter_statements = obj.generate_alter_table_self_referencing_foreign_keys()
            additional.extend(alter_statements)

        return additional

    def _format_statements(self, statements: List[str], dialect: str) -> str:
        """
        Format statements for DB2 (no special separators needed).

        Args:
            statements: List of SQL statements
            dialect: SQL dialect (should be "db2")

        Returns:
            Formatted SQL string
        """
        statements = [stmt for stmt in statements if stmt and stmt.strip()]
        if not statements:
            return ""
        return "\n\n".join(statements)

    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """
        Generate a DROP statement for an object (DB2-specific).

        Args:
            obj: SQL Model object to drop
            dialect: SQL dialect (should be "db2")

        Returns:
            DROP statement SQL string
        """
        schema_prefix = self._schema_prefix_from_object(obj)

        obj_name = obj.format_identifier(obj.name)

        # Handle different object types
        obj_type = get_object_type_name(obj)

        if obj_type == "VIEW" or obj_type == "MATERIALIZED_VIEW":
            return f"DROP {obj_type} {schema_prefix}{obj_name}"

        elif obj_type == "TABLE":
            return f"DROP TABLE {schema_prefix}{obj_name}"

        elif obj_type == "INDEX":
            return f"DROP INDEX {schema_prefix}{obj_name}"

        elif obj_type == "SEQUENCE":
            return f"DROP SEQUENCE {schema_prefix}{obj_name}"

        elif obj_type == "PROCEDURE" or obj_type == "FUNCTION":
            return f"DROP {obj_type} {schema_prefix}{obj_name}"

        elif obj_type == "TRIGGER":
            return f"DROP TRIGGER {schema_prefix}{obj_name}"

        # Default fallback
        return f"DROP {obj_type} {schema_prefix}{obj_name}"

    def _get_create_dispatch(self) -> dict[type, str]:
        """Return mapping of {TypeClass: 'method_name'} for DB2 types.

        DB2 supports exactly the 8 common types defined in
        BaseSqlGenerator; no dialect-specific additions are needed.
        """
        return super()._get_create_dispatch()

    def _generate_create_fallback(self, obj: SqlObject) -> str:
        """Fallback to basic CREATE statement for unsupported DB2 types."""
        return self._generate_basic_create_statement(obj)

    def _generate_view_create_statement(self, view: "View") -> str:
        """Generate DB2-specific CREATE VIEW statement."""
        # Start statement
        stmt = f"CREATE {self._build_view_statement_prefix(view)}"
        stmt += self._build_view_columns_clause(view)

        # Add query
        if view.query:
            stmt += f" AS\n{view.query}"

        return stmt

    def _generate_index_create_statement(self, index: "Index") -> str:
        """Generate DB2-specific CREATE INDEX statement."""
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(index)
        idx_name = index.format_identifier(index.name)
        table_schema_name = (
            index.format_identifier(index.table_schema) if index.table_schema else ""
        )
        table_name = index.format_identifier(index.table_name)
        table_schema_prefix = self._build_schema_prefix(table_schema_name)

        stmt = "CREATE "
        if index.unique:
            stmt += "UNIQUE "

        stmt += f"INDEX {schema_prefix}{idx_name} ON {table_schema_prefix}{table_name}"

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

        return stmt

    def _generate_procedure_create_statement(self, procedure: "Procedure") -> str:
        """Generate DB2-specific CREATE PROCEDURE/FUNCTION statement."""
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

        # DB2 uses CREATE
        create_keyword = "CREATE"
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
                param_list.append(param_str)
            stmt += f"({', '.join(param_list)})"

        # Add return type for functions
        if procedure.is_function and procedure.return_type:
            stmt += f" RETURNS {procedure.return_type}"

        # Add body
        if procedure.body:
            stmt += f"\nBEGIN\n{procedure.body}\nEND"

        return stmt

    def _generate_table_create_statement(self, table: "Table") -> str:
        """Generate DB2-specific CREATE TABLE statement."""
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator

        return BasicTableDdlGenerator(table).generate_create_statement()

    def _generate_synonym_create_statement(self, synonym: "Synonym") -> str:
        """Generate DB2-specific CREATE ALIAS statement (synonym equivalent)."""
        # Format synonym name with schema if present
        schema_prefix = self._schema_prefix_from_object(synonym)
        synonym_name = synonym.format_identifier(synonym.name)

        # DB2: CREATE ALIAS (synonym equivalent)
        stmt = f"CREATE ALIAS {schema_prefix}{synonym_name}"

        # Add FOR clause with target
        stmt += f"\nFOR {synonym.target_full_name}"

        return stmt

    def _generate_sequence_create_statement(self, sequence: "Sequence") -> str:
        """Generate DB2-specific CREATE SEQUENCE statement."""
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

        # Add CYCLE clause (DB2 uses NOCYCLE by default)
        if sequence.cycle:
            stmt += " CYCLE"
        else:
            stmt += " NOCYCLE"

        # Add CACHE clause (DB2 supports CACHE)
        if sequence.cache is not None and sequence.cache > 1:
            stmt += f" CACHE {sequence.cache}"

        return stmt

    def _generate_user_defined_type_create_statement(self, udt: "UserDefinedType") -> str:
        """Generate DB2-specific CREATE TYPE statement."""
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(udt)
        type_name = udt.format_identifier(udt.name)

        # DB2 structured types (composite types)
        if udt.is_composite and udt.attributes:
            attr_defs = []
            for attr in udt.attributes:
                attr_name = udt.format_identifier(attr.get("name", ""))
                attr_type = attr.get("type", "")
                attr_defs.append(f"    {attr_name} {attr_type}")
            body = ",\n".join(attr_defs)

            stmt = f"CREATE TYPE {schema_prefix}{type_name} AS (\n{body}\n) MODE DB2SQL"
            return stmt

        # DB2 doesn't support ENUM types natively, create a check constraint workaround
        if udt.is_enum and udt.enum_values:
            # Create a simple VARCHAR type with a comment about allowed values
            enum_vals = "', '".join(udt.enum_values)
            stmt = f"CREATE DISTINCT TYPE {schema_prefix}{type_name} AS VARCHAR(255)"
            stmt += f" -- Allowed values: '{enum_vals}'"
            return stmt

        # DB2 distinct types
        if udt.is_distinct and udt.base_type:
            stmt = f"CREATE DISTINCT TYPE {schema_prefix}{type_name} AS {udt.base_type}"
            return stmt

        # Generic fallback
        if udt.definition:
            return f"CREATE TYPE {schema_prefix}{type_name} AS {udt.definition}"

        return f"CREATE TYPE {schema_prefix}{type_name}"

    def _generate_trigger_create_statement(self, trigger: "Trigger") -> str:
        """Generate DB2-specific CREATE TRIGGER statement."""
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

        # Add orientation (DB2 supports FOR EACH ROW)
        if trigger.orientation == "ROW":
            stmt += "  FOR EACH ROW\n"

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
