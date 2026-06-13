"""
SQLite-specific metadata queries.

This module provides SQLite-specific queries for extracting metadata
using sqlite_master and PRAGMA commands.

Note: SQLite is simpler than other databases and doesn't support:
- Schemas (the database file IS the schema)
- Stored procedures
- Materialized views
- Check constraints with names (before SQLite 3.25)
- User-defined types
"""

from typing import Any, List, Optional, Tuple

from core.introspection.vendor_queries_base import VendorMetadataQueries


class SQLiteMetadataQueries(VendorMetadataQueries):
    """
    SQLite-specific metadata queries using sqlite_master and PRAGMA commands.

    References:
        - SQLite System Tables: https://www.sqlite.org/schematab.html
        - SQLite PRAGMA: https://www.sqlite.org/pragma.html
    """

    def get_check_constraints_query(self, schema: str, table: str) -> Tuple[str, List[Any]]:
        """
        Get check constraints from sqlite_master.

        Note: SQLite stores CHECK constraints in the table definition SQL,
        not in a separate system table. We extract from the table DDL.
        This is a simplified implementation that returns an empty result.
        Full constraint extraction would require parsing the CREATE TABLE statement.
        """
        # SQLite doesn't have a direct way to query check constraints
        # We would need to parse the CREATE TABLE statement
        query = """
            SELECT
                NULL as constraint_name,
                NULL as constraint_definition,
                0 as is_deferrable,
                0 as initially_deferred
            WHERE 0
        """
        return (query, [])

    def get_sequences_query(self, schema: str) -> Tuple[str, List[Any]]:
        """
        Get sequences - SQLite uses AUTOINCREMENT instead of sequences.

        SQLite doesn't have traditional sequences. AUTOINCREMENT is handled
        via the sqlite_sequence table.
        """
        query = """
            SELECT
                name as sequence_name,
                'INTEGER' as data_type,
                1 as start_value,
                1 as minimum_value,
                9223372036854775807 as maximum_value,
                1 as increment,
                'NO' as cycle_option,
                NULL as cache_size,
                'NO' as is_temporary,
                NULL as owning_schema,
                name as owning_table,
                NULL as owning_column
            FROM sqlite_sequence
            ORDER BY name
        """
        return (query, [])

    def get_views_query(self, schema: str) -> Tuple[str, List[Any]]:
        """
        Get views using sqlite_master.
        """
        query = """
            SELECT
                name AS view_name,
                sql AS view_definition,
                0 AS is_updatable,
                'NONE' AS check_option,
                NULL AS column_names,
                0 AS is_materialized,
                NULL AS security_definer,
                NULL AS security_invoker
            FROM sqlite_master
            WHERE type = 'view'
            ORDER BY name
        """
        return (query, [])

    def get_view_definition_query(self, schema: str, view_name: str) -> Tuple[str, List[Any]]:
        """
        Get a specific view's definition.
        """
        query = """
            SELECT sql AS view_definition
            FROM sqlite_master
            WHERE type = 'view' AND name = ?
        """
        return (query, [view_name])

    def get_indexes_query(self, schema: str, table: str) -> Tuple[str, List[Any]]:
        """
        Get detailed index information using sqlite_master and PRAGMA.

        Note: For column details, use PRAGMA index_info(index_name).
        """
        query = """
            SELECT
                m.name AS index_name,
                NULL AS column_name,
                NULL AS ordinal_position,
                0 AS is_descending,
                CASE WHEN m.sql LIKE '%UNIQUE%' THEN 1 ELSE 0 END AS is_unique,
                'BTREE' AS index_type,
                NULL AS filter_condition,
                0 AS is_expression,
                NULL AS index_expression,
                'NO' AS is_concurrent,
                NULL AS include_columns,
                NULL AS fillfactor,
                NULL AS compression,
                NULL AS comment
            FROM sqlite_master m
            WHERE m.type = 'index'
            AND m.tbl_name = ?
            AND m.name NOT LIKE 'sqlite_%'
            ORDER BY m.name
        """
        return (query, [table])

    def get_triggers_query(self, schema: str, table: Optional[str] = None) -> Tuple[str, List[Any]]:
        """
        Get triggers using sqlite_master.
        """
        if table:
            query = """
                SELECT
                    name AS trigger_name,
                    tbl_name AS table_name,
                    NULL AS event_manipulation,
                    NULL AS action_timing,
                    sql AS action_statement,
                    NULL AS action_orientation,
                    sql AS trigger_definition,
                    NULL AS when_clause,
                    NULL AS tgenabled,
                    'NO' AS is_constraint_trigger,
                    0 AS tgdeferrable,
                    0 AS tginitdeferred,
                    NULL AS function_schema,
                    NULL AS function_name,
                    NULL AS function_arguments
                FROM sqlite_master
                WHERE type = 'trigger'
                AND tbl_name = ?
                ORDER BY name
            """
            params = [table]
        else:
            query = """
                SELECT
                    name AS trigger_name,
                    tbl_name AS table_name,
                    NULL AS event_manipulation,
                    NULL AS action_timing,
                    sql AS action_statement,
                    NULL AS action_orientation,
                    sql AS trigger_definition,
                    NULL AS when_clause,
                    NULL AS tgenabled,
                    'NO' AS is_constraint_trigger,
                    0 AS tgdeferrable,
                    0 AS tginitdeferred,
                    NULL AS function_schema,
                    NULL AS function_name,
                    NULL AS function_arguments
                FROM sqlite_master
                WHERE type = 'trigger'
                ORDER BY tbl_name, name
            """
            params = []

        return (query, params)

    def get_computed_columns_query(self, schema: str, table: str) -> Tuple[str, List[Any]]:
        """
        Get generated/computed columns (SQLite 3.31+).

        Note: SQLite doesn't have a direct way to query generated columns.
        This would require parsing the CREATE TABLE statement.
        """
        # SQLite doesn't expose generated column info directly
        query = """
            SELECT
                NULL as column_name,
                NULL as computation_expression,
                0 as is_stored
            WHERE 0
        """
        return (query, [])

    def get_identity_columns_query(self, schema: str, table: str) -> Tuple[str, List[Any]]:
        """
        Get identity column information.

        In SQLite, INTEGER PRIMARY KEY columns are effectively identity columns.
        """
        # SQLite uses ROWID or INTEGER PRIMARY KEY for identity-like behavior
        # PRAGMA table_info can help identify these
        query = """
            SELECT
                NULL as column_name,
                NULL as seed_value,
                NULL as increment_value,
                NULL as last_value
            WHERE 0
        """
        return (query, [])

    def get_table_partitions_query(self, schema: str, table: str) -> Tuple[str, List[Any]]:
        """
        Get table partition information.

        Note: SQLite doesn't support table partitioning.
        """
        query = """
            SELECT
                NULL as partition_name,
                NULL as partition_expression,
                NULL as partition_method,
                NULL as high_value
            WHERE 0
        """
        return (query, [])

    def get_procedures_query(self, schema: str) -> Tuple[str, List[Any]]:
        """
        Get stored procedures.

        Note: SQLite doesn't support stored procedures.
        """
        query = """
            SELECT
                NULL as procedure_name,
                NULL as procedure_type,
                NULL as language,
                NULL as definition,
                NULL as comment,
                NULL as parameter_json,
                NULL as volatility,
                NULL as security_definer
            WHERE 0
        """
        return (query, [])

    def get_functions_query(self, schema: str) -> Tuple[str, List[Any]]:
        """
        Get functions.

        Note: SQLite has built-in functions but doesn't support user-defined functions
        in the traditional SQL sense (they're defined in application code).
        """
        query = """
            SELECT
                NULL as function_name,
                NULL as return_type,
                NULL as language,
                NULL as definition,
                NULL as comment,
                NULL as function_type,
                NULL as extension_name,
                NULL as parameter_json,
                NULL as volatility,
                NULL as security_definer
            WHERE 0
        """
        return (query, [])

    def supports_check_constraints(self) -> bool:
        """SQLite supports check constraints but doesn't expose them separately."""
        return False  # Not queryable separately

    def supports_sequences(self) -> bool:
        """SQLite doesn't support traditional sequences (uses AUTOINCREMENT)."""
        return False

    def supports_views(self) -> bool:
        """SQLite supports views."""
        return True

    def supports_triggers(self) -> bool:
        """SQLite supports triggers."""
        return True

    def supports_computed_columns(self) -> bool:
        """SQLite supports generated columns (version 3.31+) but not queryable."""
        return False

    def supports_partitions(self) -> bool:
        """SQLite doesn't support table partitioning."""
        return False

    def get_materialized_views_query(self, schema: str) -> Tuple[str, List[Any]]:
        """
        Get materialized views.

        Note: SQLite doesn't support materialized views.
        """
        query = """
            SELECT
                NULL as materialized_view_name,
                NULL as view_definition,
                NULL as is_populated,
                NULL as is_unlogged,
                NULL as column_names
            WHERE 0
        """
        return (query, [])

    def supports_materialized_views(self) -> bool:
        """SQLite doesn't support materialized views."""
        return False

    def supports_procedures(self) -> bool:
        """SQLite doesn't support stored procedures."""
        return False

    def supports_functions(self) -> bool:
        """SQLite doesn't support user-defined SQL functions."""
        return False

    def get_user_defined_types_query(self, schema: str) -> Tuple[str, List[Any]]:
        """
        Get user-defined types.

        Note: SQLite doesn't support user-defined types.
        """
        query = """
            SELECT
                NULL as type_name,
                NULL as type_category,
                NULL as comment
            WHERE 0
        """
        return (query, [])

    def supports_user_defined_types(self) -> bool:
        """SQLite doesn't support user-defined types."""
        return False

    def get_extensions_query(self, schema: Optional[str] = None) -> Tuple[str, List[Any]]:
        """
        Get installed extensions.

        SQLite has loadable extensions but they're not queryable from SQL.
        """
        query = """
            SELECT
                NULL as extension_name,
                NULL as version,
                NULL as schema,
                NULL as relocatable,
                NULL as description
            WHERE 0
        """
        return (query, [])

    def supports_extensions(self) -> bool:
        """SQLite extensions exist but aren't queryable."""
        return False

    def get_foreign_data_wrappers_query(self) -> Tuple[str, List[Any]]:
        """
        Get foreign data wrappers.

        Note: SQLite doesn't support foreign data wrappers.
        """
        query = """
            SELECT
                NULL as wrapper_name,
                NULL as options,
                NULL as owner,
                NULL as handler_name,
                NULL as handler_schema,
                NULL as validator_name,
                NULL as validator_schema
            WHERE 0
        """
        return (query, [])

    def get_foreign_servers_query(self) -> Tuple[str, List[Any]]:
        """
        Get foreign servers.

        Note: SQLite doesn't support foreign servers.
        """
        query = """
            SELECT
                NULL as server_name,
                NULL as fdw_name,
                NULL as server_type,
                NULL as server_version,
                NULL as options,
                NULL as owner
            WHERE 0
        """
        return (query, [])

    # SQLite-specific queries

    def get_tables_query(self, schema: str) -> Tuple[str, List[Any]]:
        """
        Get all tables from sqlite_master.
        """
        query = """
            SELECT
                sm.name AS table_name,
                sm.sql AS create_statement
            FROM sqlite_master AS sm
            WHERE sm.type = 'table'
            AND sm.name NOT LIKE 'sqlite_%'
            AND NOT EXISTS (
                SELECT 1 FROM sqlite_master AS vt
                WHERE vt.type = 'table'
                AND vt.sql LIKE 'CREATE VIRTUAL TABLE%'
                AND vt.sql LIKE '%USING fts5%'
                AND (
                    sm.name = vt.name || '_content'
                    OR sm.name = vt.name || '_data'
                    OR sm.name = vt.name || '_idx'
                    OR sm.name = vt.name || '_docsize'
                    OR sm.name = vt.name || '_config'
                    OR sm.name = vt.name || '_segdir'
                    OR sm.name = vt.name || '_segments'
                    OR sm.name = vt.name || '_stat'
                )
            )
            ORDER BY sm.name
        """
        return (query, [])

    def get_table_columns_pragma(self, table: str) -> str:
        """
        Get PRAGMA command for table columns.

        Returns PRAGMA table_info command which provides:
        - cid: column id
        - name: column name
        - type: data type
        - notnull: 1 if NOT NULL
        - dflt_value: default value
        - pk: 1 if primary key
        """
        return f"PRAGMA table_info('{table}')"

    def get_foreign_keys_pragma(self, table: str) -> str:
        """
        Get PRAGMA command for foreign keys.

        Returns PRAGMA foreign_key_list command which provides:
        - id: key id
        - seq: column sequence
        - table: referenced table
        - from: local column
        - to: referenced column
        - on_update: action on update
        - on_delete: action on delete
        - match: match type
        """
        return f"PRAGMA foreign_key_list('{table}')"

    def get_index_columns_pragma(self, index_name: str) -> str:
        """
        Get PRAGMA command for index columns.

        Returns PRAGMA index_info command which provides:
        - seqno: column sequence
        - cid: column id in table
        - name: column name
        """
        return f"PRAGMA index_info('{index_name}')"
