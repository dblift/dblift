"""
Base class for vendor-specific metadata queries.

This module provides the interface for database-specific metadata extraction
queries. Queries are inspired by SQLAlchemy's dialect implementations.

References:
    - SQLAlchemy reflection: https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/engine/reflection.py
    - SQLAlchemy dialects: https://github.com/sqlalchemy/sqlalchemy/tree/main/lib/sqlalchemy/dialects
"""

from abc import ABC, abstractmethod
from typing import Any, List, Optional


class VendorMetadataQueries(ABC):
    """
    Abstract base class for vendor-specific metadata queries.

    Each database vendor should implement this interface to provide
    queries that extract metadata for DBLift introspection.

    Inspired by SQLAlchemy's Inspector and dialect-specific reflection methods.
    """

    @abstractmethod
    def get_check_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get query to retrieve check constraints for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - constraint_name: Name of the check constraint
            - constraint_definition: SQL expression of the check constraint
            - is_deferrable: Whether constraint is deferrable (optional)
            - initially_deferred: Whether constraint is initially deferred (optional)
        """

    @abstractmethod
    def get_sequences_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get query to retrieve sequences in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - sequence_name: Name of the sequence
            - data_type: Data type (BIGINT, INTEGER, etc.)
            - start_value: Starting value
            - minimum_value: Minimum value
            - maximum_value: Maximum value
            - increment: Increment value
            - cycle_option: Whether sequence cycles (YES/NO)
            - cache_size: Cache size (optional)
        """

    @abstractmethod
    def get_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get query to retrieve views in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - view_name: Name of the view
            - view_definition: SQL definition of the view
            - is_updatable: Whether view is updatable (optional)
            - check_option: Check option (CASCADED, LOCAL, NONE)
        """

    @abstractmethod
    def get_view_definition_query(self, schema: str, view_name: str) -> tuple[str, List[Any]]:
        """
        Get query to retrieve the definition of a specific view.

        Args:
            schema: Schema name
            view_name: View name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - view_definition: SQL definition of the view
        """

    @abstractmethod
    def get_indexes_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get query to retrieve detailed index information.

        This includes index type, partial index conditions, and expression indexes.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - index_name: Name of the index
            - column_name: Column name (or expression)
            - ordinal_position: Position in index
            - is_descending: Whether column is descending
            - is_unique: Whether index is unique
            - index_type: Type of index (BTREE, HASH, GIN, etc.)
            - filter_condition: WHERE clause for partial indexes (optional)
            - is_expression: Whether this is an expression index
        """

    def get_all_indexes_query(self, schema: str) -> Optional[tuple[str, List[Any]]]:
        """
        Get query to retrieve all indexes for an entire schema in one call.

        Override in subclasses that support bulk index retrieval.
        Returns None by default, signaling that per-table fallback should be used.

        Args:
            schema: Schema name

        Returns:
            Optional tuple of (SQL query string, list of parameters), or None if not supported.
            Query must include a 'table_name' column to allow grouping by table.
        """
        return None

    # ------------------------------------------------------------------
    # Structural metadata queries. Override in each dialect subclass.
    # Callers check for None before executing.
    # ------------------------------------------------------------------

    def get_tables_query(self, schema: str) -> Optional[tuple[str, List[Any]]]:
        """Return base-table names in *schema*.

        Expected result columns: ``table_name``.
        Returns None if the dialect does not support this query.
        """
        return None

    def get_view_names_query(self, schema: str) -> Optional[tuple[str, List[Any]]]:
        """Return view names in *schema* (regular and materialised).

        Expected result columns: ``view_name``.
        Returns None if the dialect does not support this query.
        """
        return None

    def get_columns_query(self, schema: str, table: str) -> Optional[tuple[str, List[Any]]]:
        """Return columns for *table* in *schema* with PK detection.

        Expected result columns: ``column_name``, ``data_type``,
        ``is_nullable`` (bool), ``column_default`` (str | None),
        ``is_primary_key`` (bool), ``ordinal_position`` (int).
        Returns None if the dialect does not support this query.
        """
        return None

    def get_primary_key_query(self, schema: str, table: str) -> Optional[tuple[str, List[Any]]]:
        """Return the primary-key constraint and its columns for *table*.

        Expected result columns: ``constraint_name``, ``column_name``
        (one row per PK column, ordered by position).
        Returns None if the dialect does not support this query.
        """
        return None

    def get_foreign_keys_query(self, schema: str, table: str) -> Optional[tuple[str, List[Any]]]:
        """Return foreign-key constraints for *table* in *schema*.

        Expected result columns: ``name``, ``column_name``,
        ``ref_schema``, ``ref_table``, ``ref_column``,
        ``on_delete``, ``on_update``.
        Multiple rows per FK (one per column); group by ``name``.
        Returns None if the dialect does not support this query.
        """
        return None

    def get_triggers_query(
        self, schema: str, table: Optional[str] = None
    ) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve triggers.

        Args:
            schema: Schema name
            table: Optional table name (if None, get all triggers in schema)

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - trigger_name: Name of the trigger
            - table_name: Table the trigger is on
            - event_manipulation: Event (INSERT, UPDATE, DELETE)
            - action_timing: When trigger fires (BEFORE, AFTER, INSTEAD OF)
            - action_statement: Trigger body/definition
            - action_orientation: ROW or STATEMENT level

        Note:
            This is optional - not all databases support trigger introspection
            via standard methods. Return None if not supported.
        """
        return (None, [])

    def get_computed_columns_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve computed/generated column details.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - column_name: Name of the computed column
            - computation_expression: Expression used to compute value
            - is_stored: Whether column is physically stored
            - is_persisted: Whether column is persisted (SQL Server)

        Note:
            This is optional. Return None if not supported.
        """
        return (None, [])

    def get_identity_columns_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve identity/auto-increment column details.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - column_name: Name of the identity column
            - seed_value: Starting value
            - increment_value: Increment amount
            - last_value: Current/last generated value (optional)

        Note:
            This is optional. Return None if not supported.
        """
        return (None, [])

    def get_table_partitions_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve table partition information.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - partition_name: Name of the partition
            - partition_expression: Partitioning expression/key
            - partition_method: RANGE, LIST, HASH, etc.
            - high_value: Upper bound for range partitions

        Note:
            This is optional. Return None if not supported.
        """
        return (None, [])

    def get_materialized_views_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve materialized views in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - materialized_view_name: Name of the materialized view
            - view_definition: SQL definition of the materialized view
            - is_populated: Whether the materialized view is populated (optional)
            - last_refresh: Timestamp of last refresh (optional)
            - refresh_method: FAST, COMPLETE, FORCE, etc. (optional)

        Note:
            This is optional. Return None if not supported.
        """
        return (None, [])

    def get_procedures_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve stored procedures in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - procedure_name: Name of the procedure
            - procedure_type: Type (PROCEDURE, FUNCTION, etc.)
            - language: Procedure language (SQL, PLSQL, PLPGSQL, etc.)
            - definition: Procedure body/source code
            - comment: Procedure comment (optional)

        Note:
            Return (None, []) if not supported or if procedures should be
            retrieved via vendor metadata procedure queries
        """
        return (None, [])

    def get_functions_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve functions in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - function_name: Name of the function
            - return_type: Return data type
            - language: Function language
            - definition: Function body/source code
            - comment: Function comment (optional)

        Note:
            Return (None, []) if not supported.
        """
        return (None, [])

    def get_procedure_parameters_query(
        self, schema: str, procedure_name: str
    ) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve parameters for a specific procedure/function.

        Args:
            schema: Schema name
            procedure_name: Procedure/function name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - parameter_name: Name of the parameter
            - data_type: Parameter data type
            - parameter_mode: IN, OUT, INOUT
            - ordinal_position: Position in parameter list
            - default_value: Default value (optional)

        Note:
            Return (None, []) if the dialect does not need a supplemental query.
        """
        return (None, [])

    def get_procedure_arguments_query(
        self, schema: str, procedure_name: str
    ) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve arguments for a specific procedure.

        This is an alias for get_procedure_parameters_query for Oracle compatibility.
        Some vendors (like Oracle) use "arguments" terminology instead of "parameters".

        Args:
            schema: Schema name
            procedure_name: Procedure name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Note:
            Return (None, []) if not supported.
            Default implementation delegates to get_procedure_parameters_query.
        """
        return self.get_procedure_parameters_query(schema, procedure_name)

    def supports_check_constraints(self) -> bool:
        """Whether this dialect supports check constraint introspection."""
        return True

    def supports_sequences(self) -> bool:
        """Whether this dialect supports sequences."""
        return True

    def supports_views(self) -> bool:
        """Whether this dialect supports view introspection."""
        return True

    def supports_triggers(self) -> bool:
        """Whether this dialect supports trigger introspection."""
        return False

    def supports_computed_columns(self) -> bool:
        """Whether this dialect supports computed column introspection."""
        return False

    def supports_partitions(self) -> bool:
        """Whether this dialect supports partition introspection."""
        return False

    def supports_materialized_views(self) -> bool:
        """Whether this dialect supports materialized view introspection."""
        return False

    def supports_procedures(self) -> bool:
        """Whether this dialect supports procedure introspection."""
        return False

    def supports_functions(self) -> bool:
        """Whether this dialect supports function introspection."""
        return False

    def get_synonyms_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve synonyms in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - synonym_name: Name of the synonym
            - target_schema: Schema of the target object (optional)
            - target_object: Name of the target object
            - target_database: Database of the target object (optional, SQL Server)
            - db_link: Database link for remote objects (optional, Oracle)

        Note:
            Return (None, []) if not supported.
        """
        return (None, [])

    def supports_synonyms(self) -> bool:
        """Whether this dialect supports synonym introspection."""
        return False

    def supports_database_links(self) -> bool:
        """Whether this dialect supports database link introspection."""
        return False

    def get_database_links(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve database links in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query, parameters)

        Note:
            Return (None, []) if not supported.
        """
        return (None, [])

    def get_user_defined_types_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve user-defined types in a schema.

        This provides detailed metadata like enum values and composite type
        attributes.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - type_name: Name of the type
            - type_category: Category (ENUM, COMPOSITE, DOMAIN, DISTINCT, etc.)
            - definition: Type definition (optional)
            - comment: Type comment (optional)

        Note:
            Return (None, []) if not supported.
        """
        return (None, [])

    def get_enum_values_query(self, schema: str, type_name: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve values for an enum type.

        Args:
            schema: Schema name
            type_name: Enum type name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - enum_value: The enum value
            - sort_order: Sort order of the value

        Note:
            Return (None, []) if not supported.
        """
        return (None, [])

    def get_composite_type_attributes_query(
        self, schema: str, type_name: str
    ) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve attributes for a composite/structured type.

        Args:
            schema: Schema name
            type_name: Composite type name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - attribute_name: Name of the attribute
            - data_type: Data type of the attribute
            - ordinal_position: Position in the type
            - is_nullable: Whether attribute can be NULL

        Note:
            Return (None, []) if not supported.
        """
        return (None, [])

    def supports_user_defined_types(self) -> bool:
        """Whether this dialect supports user-defined type introspection."""
        return False

    def get_extensions_query(self, schema: Optional[str] = None) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve installed extensions (PostgreSQL-specific).

        Args:
            schema: Schema name (optional, PostgreSQL extensions are database-wide)

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - extension_name: Name of the extension
            - version: Extension version
            - schema: Schema where extension is installed
            - relocatable: Whether extension can be relocated
            - description: Extension description

        Note:
            Return (None, []) if not supported (non-PostgreSQL databases).
        """
        return (None, [])

    def supports_extensions(self) -> bool:
        """Whether this dialect supports extensions (PostgreSQL-specific)."""
        return False

    # --- Optional query methods (added by story 20-18) ---
    # These methods are called via hasattr() in extractors. Adding them here
    # with safe defaults formalizes the ABC contract and eliminates duck-typing.

    # Constraint queries

    def get_unique_constraints_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve unique constraints for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - constraint_name: Name of the unique constraint
            - column_name: Column name
            - ordinal_position: Position in constraint

        Note:
            Return (None, []) if not supported.
            DB2 uses SYSCAT.TABCONST / SYSCAT.KEYCOLUSE for unique constraints.
        """
        return (None, [])

    # Table property and structure queries

    def get_table_properties_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve table-level properties (engine, charset, etc.).

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            Vendor-specific: may include engine, charset, collation, tablespace,
            compression, row_format, etc.

        Note:
            Return (None, []) if not supported.
            Implemented by DB2, SQL Server, Oracle, MySQL.
        """
        return (None, [])

    def get_partition_scheme_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve the partition scheme for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            Vendor-specific: may include partition_method, partition_columns,
            partition_expression, partition_scheme_name, etc.

        Note:
            Return (None, []) if not supported.
            Implemented by DB2, SQL Server, PostgreSQL, Oracle, MySQL.
        """
        return (None, [])

    def get_table_inheritance_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve table inheritance information.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - parent_table: Name of the parent table

        Note:
            Return (None, []) if not supported.
            PostgreSQL-specific (table inheritance via INHERITS).
        """
        return (None, [])

    def get_table_row_security_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve row-level security status for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - relrowsecurity: Whether RLS is enabled
            - relforcerowsecurity: Whether RLS is forced

        Note:
            Return (None, []) if not supported.
            PostgreSQL-specific.
        """
        return (None, [])

    def get_policies_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve row-level security policies for a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - policy_name: Name of the policy
            - permissive: Whether policy is permissive
            - roles: Roles the policy applies to
            - cmd: Command the policy applies to (ALL, SELECT, etc.)
            - qual: USING expression
            - with_check: WITH CHECK expression

        Note:
            Return (None, []) if not supported.
            PostgreSQL-specific.
        """
        return (None, [])

    def get_partitioned_tables_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve partitioned tables in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - table_name: Name of the partitioned table
            - partition_strategy: Partitioning strategy (RANGE, LIST, HASH)
            - partition_columns: Columns used for partitioning

        Note:
            Return (None, []) if not supported.
            PostgreSQL-specific.
        """
        return (None, [])

    # Procedure and function queries

    def get_packages_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve packages in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - package_name: Name of the package
            - package_type: PACKAGE or PACKAGE BODY
            - source: Package source code

        Note:
            Return (None, []) if not supported.
            Implemented by DB2, Oracle.
        """
        return (None, [])

    def get_function_definition_query(
        self, schema: str, function_name: str
    ) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve the definition of a specific function.

        Args:
            schema: Schema name
            function_name: Function name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - text: Source code line of the function

        Note:
            Return (None, []) if not supported.
            Oracle-specific (USER_SOURCE / ALL_SOURCE).
        """
        return (None, [])

    def get_parameters_query(self, schema: str, routine_name: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve parameters for a routine (MySQL-specific alias).

        This is distinct from get_procedure_parameters_query. MySQL uses
        INFORMATION_SCHEMA.PARAMETERS directly.

        Args:
            schema: Schema name
            routine_name: Routine (procedure/function) name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - parameter_name: Name of the parameter
            - data_type: Parameter data type
            - parameter_mode: IN, OUT, INOUT
            - ordinal_position: Position in parameter list

        Note:
            Return (None, []) if not supported.
            MySQL-specific.
        """
        return (None, [])

    # Column queries

    def get_column_defaults_query(self, schema: str, table: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve column default value details.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - column_name: Name of the column
            - default_definition: Default value expression
            - default_name: Name of the default constraint (SQL Server)

        Note:
            Return (None, []) if not supported.
            SQL Server-specific.
        """
        return (None, [])

    # Miscellaneous queries

    def get_events_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve scheduled events in a schema.

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            - event_name: Name of the event
            - event_type: Type of event
            - event_definition: Event body/definition
            - interval_value: Interval for recurring events
            - status: ENABLED or DISABLED

        Note:
            Return (None, []) if not supported.
            MySQL-specific.
        """
        return (None, [])

    def get_foreign_servers_query(self) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve foreign servers / foreign data wrappers.

        Returns:
            Tuple of (SQL query string, list of parameters)

        Expected columns in result:
            Vendor-specific: may include server_name, fdw_name, server_type,
            server_version, options, etc.

        Note:
            Return (None, []) if not supported.
            Implemented by PostgreSQL, SQLite.
        """
        return (None, [])

    def supports_linked_servers(self) -> bool:
        """Whether this dialect supports linked server introspection (SQL Server-specific)."""
        return False

    def get_linked_servers_query(self) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve linked servers (SQL Server-specific).

        Returns:
            Tuple of (SQL query string, list of parameters)

        Note:
            Return (None, []) if not supported.
        """
        return (None, [])

    def supports_modules(self) -> bool:
        """Whether this dialect supports module introspection (DB2-specific)."""
        return False

    def supports_packages(self) -> bool:
        """Whether this dialect supports package introspection (Oracle/DB2)."""
        return False

    def supports_events(self) -> bool:
        """Whether this dialect supports scheduled-event introspection (MySQL/MariaDB)."""
        return False

    def supports_foreign_data_wrappers(self) -> bool:
        """Whether this dialect supports foreign data wrapper introspection (PostgreSQL)."""
        return False

    def supports_foreign_servers(self) -> bool:
        """Whether this dialect supports foreign server introspection (PostgreSQL)."""
        return False

    def get_modules_query(self, schema: str) -> tuple[str | None, List[Any]]:
        """
        Get query to retrieve modules in a schema (DB2-specific).

        Args:
            schema: Schema name

        Returns:
            Tuple of (SQL query string, list of parameters)

        Note:
            Return (None, []) if not supported.
        """
        return (None, [])
