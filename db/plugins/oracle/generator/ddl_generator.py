"""
Oracle-specific SQL generation implementation.

This module provides Oracle-specific SQL generation logic, inheriting
common functionality from BaseSqlGenerator and overriding methods that
require Oracle-specific handling.
"""

import re
from typing import TYPE_CHECKING, List

from core.sql_generator.base_generator import BaseSqlGenerator
from core.sql_model.base import SqlObject, get_object_type_name

if TYPE_CHECKING:
    from core.sql_model.index import Index
    from core.sql_model.package import Package
    from core.sql_model.procedure import Procedure
    from core.sql_model.sequence import Sequence
    from core.sql_model.synonym import Synonym
    from core.sql_model.table import Table
    from core.sql_model.trigger import Trigger
    from core.sql_model.user_defined_type import UserDefinedType
    from core.sql_model.view import View


class OracleSqlGenerator(BaseSqlGenerator):
    """
    Oracle-specific SQL generation implementation.

    This class provides Oracle-specific SQL generation logic while
    inheriting common functionality from BaseSqlGenerator.
    """

    _PLSQL_CREATE_RE = re.compile(
        r"^\s*CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:NON)?EDITIONABLE\s+)?"
        r"(?:PROCEDURE|FUNCTION|PACKAGE(?:\s+BODY)?|TRIGGER|TYPE\s+BODY)\b",
        re.IGNORECASE,
    )

    def _format_statements(self, statements: List[str], dialect: str) -> str:
        """
        Format statements for Oracle (no special separators needed).

        Args:
            statements: List of SQL statements
            dialect: SQL dialect (should be "oracle")

        Returns:
            Formatted SQL string
        """
        statements = [stmt for stmt in statements if stmt and stmt.strip()]
        if not statements:
            return ""
        return "\n\n".join(statements)

    def _ensure_statement_terminated(self, sql: str) -> str:
        """Terminate Oracle DDL without corrupting SQL*Plus PL/SQL block separators."""
        if not sql:
            return sql

        stripped = sql.rstrip()
        if stripped.endswith("/;"):
            stripped = stripped[:-1].rstrip()

        if stripped.endswith("/"):
            return stripped

        if self._requires_sqlplus_block_terminator(stripped):
            if not stripped.endswith(";"):
                stripped += ";"
            return stripped + "\n/"

        if not stripped.endswith(";"):
            return stripped + ";"
        return stripped

    def _requires_sqlplus_block_terminator(self, sql: str) -> bool:
        """Return True for Oracle PL/SQL unit DDL that needs a trailing slash."""
        if not self._PLSQL_CREATE_RE.match(sql):
            return False
        return bool(re.search(r"\bEND\b\s*[A-Za-z0-9_$#\"]*\s*;?\s*$", sql, re.IGNORECASE))

    def _generate_drop_statement(self, obj: SqlObject, dialect: str) -> str:
        """
        Generate a DROP statement for an object (Oracle-specific).

        Args:
            obj: SQL Model object to drop
            dialect: SQL dialect (should be "oracle")

        Returns:
            DROP statement SQL string
        """
        schema_prefix = self._schema_prefix_from_object(obj)

        obj_name = obj.format_identifier(obj.name)

        # Handle different object types
        obj_type = get_object_type_name(obj)

        if obj_type == "MATERIALIZED_VIEW":
            return f"DROP MATERIALIZED VIEW {schema_prefix}{obj_name}"

        if obj_type == "VIEW":
            return f"DROP VIEW {schema_prefix}{obj_name}"

        elif obj_type == "TABLE":
            return f"DROP TABLE {schema_prefix}{obj_name} CASCADE CONSTRAINTS"

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
        """Return mapping of {TypeClass: 'method_name'} for Oracle types.

        Extends the 8 common types from BaseSqlGenerator with the
        Oracle-specific Package type.
        """
        # Import Oracle-specific type only; common types come from super()
        from core.sql_model.package import Package

        dispatch = super()._get_create_dispatch()
        dispatch[Package] = "_generate_package_create_statement"
        return dispatch

    def _postprocess_create_statement(self, obj: SqlObject, create_sql: str, dialect: str) -> str:
        from core.sql_model.table import Table

        if isinstance(obj, Table):
            return self._normalize_oracle_table_storage(create_sql)
        return create_sql

    def _normalize_oracle_table_storage(self, create_sql: str) -> str:
        def replace_storage_clause(match: re.Match[str]) -> str:
            pctused = f"\nPCTUSED {match.group(2)}" if match.group(2) else ""
            return f"PCTFREE {match.group(1)}{pctused}\nSTORAGE (INITIAL {match.group(3)} NEXT {match.group(4)})"

        return re.sub(
            r"PCTFREE\s+(\d+)(?:,\s+PCTUSED\s+(\d+))?,\s+INITIAL\s+(\d+),\s+NEXT\s+(\d+)",
            replace_storage_clause,
            create_sql,
            flags=re.IGNORECASE,
        )

    def _generate_view_create_statement(self, view: "View") -> str:
        """Generate Oracle-specific CREATE VIEW statement."""
        # Oracle uses CREATE OR REPLACE for regular views only
        # Materialized views do NOT support OR REPLACE in Oracle
        create_keyword = "CREATE OR REPLACE" if not view.materialized else "CREATE"

        # Add FORCE/NOFORCE clause for Oracle
        force_clause = ""
        if getattr(view, "force", None) is True:
            force_clause = "FORCE "
        elif getattr(view, "force", None) is False:
            force_clause = "NOFORCE "

        # Start statement
        stmt = f"{create_keyword} {force_clause}{self._build_view_statement_prefix(view)}"
        stmt += self._build_view_columns_clause(view)

        if view.materialized:
            is_populated = getattr(view, "is_populated", None)
            if is_populated is False:
                stmt += "\nBUILD DEFERRED"
            else:
                stmt += "\nBUILD IMMEDIATE"

            refresh_method = getattr(view, "refresh_method", None) or "COMPLETE"
            refresh_mode = getattr(view, "refresh_mode", None) or "DEMAND"
            stmt += f"\nREFRESH {refresh_method} ON {refresh_mode}"

        # Add query
        if view.query:
            stmt += f" AS\n{view.query}"

        return stmt

    def _generate_index_create_statement(self, index: "Index") -> str:
        """Generate Oracle-specific CREATE INDEX statement."""
        if getattr(index, "definition", None):
            return str(index.definition)

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

        # Handle BITMAP indexes (Oracle-specific)
        if index.type == "BITMAP":
            stmt += "BITMAP "

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

        # Add LOCAL clause for partitioned tables (Oracle-specific)
        if getattr(index, "is_local", None):
            stmt += " LOCAL"

        # Add TABLESPACE clause (Oracle-specific)
        if getattr(index, "tablespace", None):
            stmt += f" TABLESPACE {index.format_identifier(index.tablespace or '')}"

        return stmt

    def _generate_procedure_create_statement(self, procedure: "Procedure") -> str:
        """Generate Oracle-specific CREATE PROCEDURE/FUNCTION statement."""
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

        # Oracle uses CREATE OR REPLACE
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
            # Oracle procedures/functions can have empty parameter lists
            if procedure.parameters is not None:
                stmt += "()"

        # Add return type for functions (Oracle uses RETURN)
        if procedure.is_function and procedure.return_type:
            stmt += f" RETURN {procedure.return_type}"

        # Add body
        if procedure.body:
            stmt += f"\nAS\n{procedure.body}"

        return stmt

    def _generate_table_create_statement(self, table: "Table") -> str:
        """Generate Oracle-specific CREATE TABLE statement."""
        from core.sql_generator.basic_table_ddl_generator import BasicTableDdlGenerator

        return BasicTableDdlGenerator(table).generate_create_statement()

    def _generate_synonym_create_statement(self, synonym: "Synonym") -> str:
        """Generate Oracle-specific CREATE SYNONYM statement."""
        # Format synonym name with schema if present
        schema_prefix = self._schema_prefix_from_object(synonym)
        synonym_name = synonym.format_identifier(synonym.name)

        # Oracle: CREATE [OR REPLACE] [PUBLIC] SYNONYM
        stmt = f"CREATE OR REPLACE SYNONYM {schema_prefix}{synonym_name}"

        # Add FOR clause with target
        stmt += f"\nFOR {synonym.target_full_name}"

        return stmt

    def _generate_sequence_create_statement(self, sequence: "Sequence") -> str:
        """Generate Oracle-specific CREATE SEQUENCE statement."""
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

        # Add CYCLE clause (Oracle uses NOCYCLE by default)
        if sequence.cycle:
            stmt += " CYCLE"
        else:
            stmt += " NOCYCLE"

        # Add CACHE / NOCACHE clause (Oracle-specific)
        if sequence.cache is None:
            stmt += " NOCACHE"
        elif sequence.cache <= 1:
            stmt += " NOCACHE"
        else:
            stmt += f" CACHE {sequence.cache}"

        return stmt

    def _generate_user_defined_type_create_statement(self, udt: "UserDefinedType") -> str:
        """Generate Oracle-specific CREATE TYPE statement."""
        # Format identifiers
        schema_prefix = self._schema_prefix_from_object(udt)
        type_name = udt.format_identifier(udt.name)

        # Oracle OBJECT types
        if udt.is_composite and udt.attributes:
            attr_defs = []
            for attr in udt.attributes:
                attr_name = udt.format_identifier(attr.get("name", ""))
                attr_type = attr.get("type", "")
                attr_defs.append(f"    {attr_name} {attr_type}")
            body = ",\n".join(attr_defs)

            # Oracle uses OBJECT modifier for composite types
            stmt = f"CREATE TYPE {schema_prefix}{type_name} AS OBJECT (\n{body}\n)"
            return stmt

        # Oracle doesn't support ENUM types natively, but we can create a check constraint workaround
        if udt.is_enum and udt.enum_values:
            # Create a simple VARCHAR type with a comment about allowed values
            enum_vals = "', '".join(udt.enum_values)
            stmt = f"CREATE TYPE {schema_prefix}{type_name} AS VARCHAR2(255)"
            stmt += f" -- Allowed values: '{enum_vals}'"
            return stmt

        # Generic fallback
        if udt.definition:
            return f"CREATE TYPE {schema_prefix}{type_name} AS {udt.definition}"

        return f"CREATE TYPE {schema_prefix}{type_name}"

    def _generate_trigger_create_statement(self, trigger: "Trigger") -> str:
        """Generate Oracle-specific CREATE TRIGGER statement."""
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

        # Add orientation (Oracle supports FOR EACH ROW)
        if trigger.orientation == "ROW":
            stmt += "  FOR EACH ROW\n"
        # Oracle defaults to statement level if FOR EACH ROW is omitted

        # Add FOLLOWS clause (Oracle supports trigger ordering)
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

        # Oracle-specific: Add terminator
        stmt += "\n/"

        return stmt

    def _generate_package_create_statement(self, package: "Package") -> str:
        """Generate Oracle-specific CREATE PACKAGE statement."""
        # For complex package generation, delegate to the fallback method
        # which contains all the detailed Oracle-specific logic
        return package._generate_basic_create_statement()
