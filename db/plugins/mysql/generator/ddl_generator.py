"""
MySQL-specific SQL generation implementation.

This module provides MySQL-specific SQL generation logic, inheriting
common functionality from BaseSqlGenerator and overriding methods that
require MySQL-specific handling.
"""

from typing import TYPE_CHECKING, List

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_model.base import SqlObject, SqlObjectType, get_object_type_name

if TYPE_CHECKING:
    from core.sql_model.event import Event
    from core.sql_model.index import Index
    from core.sql_model.procedure import Procedure
    from core.sql_model.sequence import Sequence
    from core.sql_model.synonym import Synonym
    from core.sql_model.table import Table
    from core.sql_model.trigger import Trigger
    from core.sql_model.user_defined_type import UserDefinedType
    from core.sql_model.view import View


class MySQLSqlGenerator(BaseSqlGenerator):
    """
    MySQL-specific SQL generation implementation.

    This class provides MySQL-specific SQL generation logic while
    inheriting common functionality from BaseSqlGenerator.
    """

    def _requires_dialect_specific_wrapping(self, obj: SqlObject, dialect: str) -> bool:
        """
        Check if object needs MySQL ``DELIMITER $$`` wrapping.

        Story 26-5 (Bugbot follow-up): the wide PROC/FUNC/TRIGGER/EVENT
        set is owned by ``MysqlQuirks._BLOCK_DELIMITER_OBJECT_TYPES``
        and exposed via ``requires_block_delimiter_wrapping``. Reading
        it back here keeps a single source of truth for the wide
        delimiter set and eliminates the previously-hardcoded
        ``dialect.lower() != "mysql"`` check. ``BaseQuirks`` returns
        False for non-MySQL dialects, so no guard is needed.
        """
        if not dialect:
            return False
        from db.provider_registry import ProviderRegistry

        canonical = ProviderRegistry.canonical_dialect_name(dialect) or dialect.lower()
        return ProviderRegistry.get_quirks(canonical).requires_block_delimiter_wrapping(
            get_object_type_name(obj)
        )

    def _wrap_dialect_specific_block(self, sql: str, dialect: str) -> str:
        """
        Wrap SQL block with MySQL DELIMITER directives.

        Args:
            sql: SQL statement
            dialect: SQL dialect

        Returns:
            SQL wrapped with DELIMITER directives
        """
        stripped = sql.rstrip()
        if stripped.endswith(";"):
            stripped = stripped[:-1]
        return f"DELIMITER $$\n{stripped}\n$$\nDELIMITER ;"

    def _should_skip_formatting(self, obj: SqlObject, sql: str) -> bool:
        """
        Check if we should skip formatting for MySQL objects.

        MySQL DEFINER clauses and identifier quoting should be preserved.

        Args:
            obj: SQL Model object
            sql: SQL statement

        Returns:
            True if formatting should be skipped
        """
        if not sql:
            return False

        dialect = getattr(obj, "dialect", None)
        if (
            dialect
            and dialect.lower() == "mysql"
            and obj.object_type
            in {
                SqlObjectType.VIEW,
                SqlObjectType.PROCEDURE,
                SqlObjectType.FUNCTION,
                SqlObjectType.TRIGGER,
                SqlObjectType.EVENT,
            }
        ):
            # Preserve MySQL DEFINER clauses and identifier quoting
            return True

        return False

    def _format_statements(self, statements: List[str], dialect: str) -> str:
        """
        Format statements for MySQL (no special separators needed).

        Args:
            statements: List of SQL statements
            dialect: SQL dialect (should be "mysql")

        Returns:
            Formatted SQL string
        """
        statements = [stmt for stmt in statements if stmt and stmt.strip()]
        if not statements:
            return ""
        return "\n\n".join(statements)

    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """
        Generate a DROP statement for an object (MySQL-specific).

        Args:
            obj: SQL Model object to drop
            dialect: SQL dialect (should be "mysql")

        Returns:
            DROP statement SQL string
        """
        schema_prefix = self._schema_prefix_from_object(obj)

        obj_name = obj.format_identifier(obj.name)

        # Handle different object types
        obj_type = get_object_type_name(obj)

        if obj_type == "VIEW" or obj_type == "MATERIALIZED_VIEW":
            return f"DROP {obj_type} IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "TABLE":
            return f"DROP TABLE IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "INDEX":
            table_name = getattr(obj, "table_name", None)
            if not table_name:
                return f"-- Cannot drop MySQL index {obj_name}: missing table name"
            table_schema = getattr(obj, "table_schema", None) or getattr(obj, "schema", None)
            table_schema_name = obj.format_identifier(table_schema) if table_schema else ""
            table_name_formatted = obj.format_identifier(table_name)
            table_schema_prefix = self._build_schema_prefix(table_schema_name)
            return f"DROP INDEX {obj_name} ON {table_schema_prefix}{table_name_formatted}"

        elif obj_type == "SEQUENCE":
            # MySQL doesn't have sequences, but handle gracefully
            return f"DROP SEQUENCE IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "PROCEDURE" or obj_type == "FUNCTION":
            return f"DROP {obj_type} IF EXISTS {schema_prefix}{obj_name}"

        elif obj_type == "TRIGGER":
            return f"DROP TRIGGER IF EXISTS {schema_prefix}{obj_name}"

        # Default fallback
        return f"DROP {obj_type} IF EXISTS {schema_prefix}{obj_name}"

    def _get_create_dispatch(self) -> dict[type, str]:
        """Return mapping of {TypeClass: 'method_name'} for MySQL types.

        Extends the 8 common types from BaseSqlGenerator with the
        MySQL-specific Event type.
        """
        # Import MySQL-specific type only; common types come from super()
        from core.sql_model.event import Event

        dispatch = super()._get_create_dispatch()
        dispatch[Event] = "_generate_event_create_statement"
        return dispatch

    def _generate_create_fallback(self, obj: SqlObject) -> str:
        """Return empty string for unsupported MySQL types."""
        return ""

    def _generate_view_create_statement(self, view: "View") -> str:
        """Generate MySQL-specific CREATE VIEW statement."""
        # MySQL-specific view options
        algorithm_clause = ""
        definer_clause = ""
        sql_security_clause = ""

        if getattr(view, "algorithm", None):
            algorithm_clause = f"ALGORITHM = {view.algorithm} "

        if getattr(view, "definer", None) and view.definer:
            # Preserve MySQL DEFINER quoting
            definer_parts = view.definer.split("@")
            if len(definer_parts) == 2:
                definer_clause = f"DEFINER = `{definer_parts[0]}`@`{definer_parts[1]}` "

        if getattr(view, "sql_security", None):
            sql_security_clause = f"SQL SECURITY {view.sql_security} "

        # Start statement
        stmt = f"CREATE {algorithm_clause}{definer_clause}{sql_security_clause}{self._build_view_statement_prefix(view)}"
        stmt += self._build_view_columns_clause(view)

        # Add query
        if view.query:
            stmt += f" AS {view.query}"

        return stmt

    def _generate_index_create_statement(self, index: "Index") -> str:
        """Generate MySQL-specific CREATE INDEX statement."""
        # Format identifiers
        idx_name = index.format_identifier(index.name)
        table_schema_name = (
            index.format_identifier(index.table_schema) if index.table_schema else ""
        )
        table_name = index.format_identifier(index.table_name)

        # MySQL creates indexes in the same schema as the table
        schema_prefix = ""
        table_schema_prefix = self._build_schema_prefix(table_schema_name)

        stmt = "CREATE "

        # MySQL ONLINE/OFFLINE clause
        if getattr(index, "online", None) is True:
            stmt += "ONLINE "
        elif getattr(index, "online", None) is False:
            stmt += "OFFLINE "

        if index.unique:
            stmt += "UNIQUE "

        # MySQL supports FULLTEXT and SPATIAL as index types before INDEX keyword
        if index.type and index.type.upper() in ("FULLTEXT", "SPATIAL"):
            stmt += f"{index.type.upper()} "
        elif index.type and index.type.upper() != "BTREE":
            # Other index types go after the column list with USING
            pass

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
                index_type = (index.type or "").upper()
                if (
                    index_type not in {"FULLTEXT", "SPATIAL"}
                    and index.sort_directions
                    and i < len(index.sort_directions)
                    and index.sort_directions[i]
                ):
                    formatted_col += f" {index.sort_directions[i]}"
                formatted_columns.append(formatted_col)
            stmt += f" ({', '.join(formatted_columns)})"

        # Add USING clause for other index types (not FULLTEXT/SPATIAL)
        if (
            index.type
            and index.type.upper() not in ("BTREE", "FULLTEXT", "SPATIAL")
            and index.type.upper() != "BTREE"
        ):
            stmt += f" USING {index.type}"

        return stmt

    def _generate_procedure_create_statement(self, procedure: "Procedure") -> str:
        """Generate MySQL-specific CREATE PROCEDURE/FUNCTION statement."""
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

        # MySQL uses CREATE
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
                # MySQL supports parameter defaults
                if param.default_value:
                    param_str += f" = {param.default_value}"
                param_list.append(param_str)
            stmt += f"({', '.join(param_list)})"
        else:
            stmt += "()"

        # Add return type for functions
        if procedure.is_function and procedure.return_type:
            stmt += f" RETURNS {procedure.return_type}"

        # Add MySQL-specific characteristics
        characteristics = []

        # Handle volatility (DETERMINISTIC/NOT DETERMINISTIC)
        if procedure.volatility:
            if procedure.volatility.upper() == "IMMUTABLE":
                characteristics.append("DETERMINISTIC")
            else:
                characteristics.append("NOT DETERMINISTIC")
        elif procedure.is_function:
            # Default to NOT DETERMINISTIC to satisfy MySQL requirement
            characteristics.append("NOT DETERMINISTIC")

        # Handle security definer
        if procedure.security_definer is not None:
            security_clause = (
                "SQL SECURITY DEFINER" if procedure.security_definer else "SQL SECURITY INVOKER"
            )
            characteristics.append(security_clause)

        # Handle data access
        if procedure.data_access:
            characteristics.append(procedure.data_access.upper())

        # Handle comment
        if procedure.comment:
            escaped_comment = procedure.comment.replace("'", "''")
            characteristics.append(f"COMMENT '{escaped_comment}'")

        if characteristics:
            stmt += "\n    " + "\n    ".join(characteristics)

        # Add body
        if procedure.body:
            body_text = (procedure.body or "").strip()
            if body_text.upper().startswith("BEGIN"):
                stmt += f"\n{body_text}"
            else:
                stmt += f"\nBEGIN\n{procedure.body}\nEND"

        return stmt

    def _generate_synonym_create_statement(self, synonym: "Synonym") -> str:
        """Generate MySQL-specific CREATE SYNONYM statement.

        Note: MySQL doesn't natively support synonyms, so this creates a view as a workaround.
        """
        # Format synonym name with schema if present
        schema_prefix = self._schema_prefix_from_object(synonym)
        synonym_name = synonym.format_identifier(synonym.name)

        # MySQL doesn't support synonyms natively, create a view instead
        # This is a common workaround for synonym-like functionality
        stmt = (
            f"CREATE VIEW {schema_prefix}{synonym_name} AS SELECT * FROM {synonym.target_full_name}"
        )

        return stmt

    def _generate_sequence_create_statement(self, sequence: "Sequence") -> str:
        """Generate MySQL-specific CREATE SEQUENCE statement.

        Note: MySQL doesn't natively support sequences, so this creates an AUTO_INCREMENT table as a workaround.
        """
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(sequence)
        seq_name = sequence.format_identifier(sequence.name)

        # MySQL doesn't support sequences natively, create a table with AUTO_INCREMENT
        # This is a common workaround for sequence-like functionality
        stmt = f"CREATE TABLE {schema_prefix}{seq_name}_seq ("
        stmt += "id BIGINT AUTO_INCREMENT PRIMARY KEY"

        # Set AUTO_INCREMENT starting value if specified
        if sequence.start_with is not None:
            stmt += f") AUTO_INCREMENT = {sequence.start_with}"
        else:
            stmt += ")"

        return stmt

    def _generate_user_defined_type_create_statement(self, udt: "UserDefinedType") -> str:
        """Generate MySQL-specific CREATE TYPE statement.

        Note: MySQL doesn't natively support user-defined types, so this creates table workarounds.
        """
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(udt)
        type_name = udt.format_identifier(udt.name)

        # MySQL doesn't support user-defined types natively
        # For composite types, create a table as a workaround
        if udt.is_composite and udt.attributes:
            attr_defs = []
            for attr in udt.attributes:
                attr_name = udt.format_identifier(attr.get("name", ""))
                attr_type = attr.get("type", "")
                attr_defs.append(f"    {attr_name} {attr_type}")
            body = ",\n".join(attr_defs)

            stmt = f"CREATE TABLE {schema_prefix}{type_name}_type (\n{body}\n)"
            stmt += f" -- User-defined type workaround for {type_name}"
            return stmt

        # For enum types, create a table with CHECK constraint workaround
        if udt.is_enum and udt.enum_values:
            enum_vals = "', '".join(udt.enum_values)
            stmt = f"CREATE TABLE {schema_prefix}{type_name}_enum ("
            stmt += f"value VARCHAR(255) CHECK (value IN ('{enum_vals}'))"
            stmt += f") -- Enum type workaround for {type_name}"
            return stmt

        # Generic comment-based fallback
        return f"-- MySQL does not support user-defined types: {type_name}"

    def _generate_trigger_create_statement(self, trigger: "Trigger") -> str:
        """Generate MySQL-specific CREATE TRIGGER statement."""
        # If we have a complete definition, use it
        if trigger.definition and trigger.definition.strip().upper().startswith("CREATE"):
            return trigger.definition

        # Format identifiers
        trigger_name = trigger.format_identifier(trigger.name)

        # MySQL DEFINER clause
        definer_clause = ""
        if trigger.definer:
            definer_clause = f"DEFINER = {trigger._format_mysql_definer(trigger.definer)} "

        # Build the statement
        stmt = f"CREATE {definer_clause}TRIGGER {trigger_name}\n"

        # Add timing
        if trigger.timing:
            stmt += f"  {trigger.timing}\n"

        # Add events
        if trigger.events:
            stmt += f"  {trigger.event_str}\n"

        # Add table reference
        stmt += f"  ON {trigger.qualified_table_name}\n"

        # Add orientation (MySQL supports FOR EACH ROW)
        if trigger.orientation == "ROW":
            stmt += "  FOR EACH ROW\n"

        # Add FOLLOWS clause (MySQL supports trigger ordering)
        if trigger.follows_trigger:
            follows_name = trigger.format_identifier(trigger.follows_trigger)
            stmt += f"  FOLLOWS {follows_name}\n"
        elif trigger.precedes_trigger:
            precedes_name = trigger.format_identifier(trigger.precedes_trigger)
            stmt += f"  PRECEDES {precedes_name}\n"

        # Add trigger body
        body_sql = trigger._format_body(trigger.definition or "")
        if body_sql:
            stmt += body_sql

        return stmt

    def _generate_table_create_statement(self, table: "Table") -> str:
        """Generate MySQL-specific CREATE TABLE statement."""
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator

        return BasicTableDdlGenerator(table).generate_create_statement()

    def _generate_event_create_statement(self, event: "Event") -> str:
        """Generate MySQL-specific CREATE EVENT statement."""
        # For MySQL events, delegate to the basic create statement
        return event._generate_basic_create_statement()
