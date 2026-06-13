"""
MySQL/MariaDB-specific metadata queries.

This module provides MySQL/MariaDB-specific queries for extracting metadata.

Queries are inspired by SQLAlchemy's MySQL dialect:
https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/mysql/base.py

MySQL primarily uses information_schema views for metadata queries,
with some additional queries using SHOW statements.
"""

from typing import Any, List

from core.introspection.vendor_queries_base import VendorMetadataQueries


class MySQLMetadataQueries(VendorMetadataQueries):
    """
    MySQL/MariaDB-specific metadata queries using information_schema.

    References:
        - MySQL Information Schema: https://dev.mysql.com/doc/refman/8.0/en/information-schema.html
        - SQLAlchemy MySQL Dialect: https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/mysql/base.py
    """

    def get_check_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get check constraints using information_schema (MySQL 8.0.16+).

        Check constraints were added in MySQL 8.0.16.
        MariaDB 10.2+ also supports check constraints.

        Note: MySQL's information_schema.check_constraints doesn't have table_name,
        so we join with table_constraints to filter by table.
        """
        query = """
            SELECT
                cc.constraint_name,
                cc.check_clause AS constraint_definition,
                'N' AS is_deferrable,
                'N' AS initially_deferred
            FROM information_schema.check_constraints cc
            INNER JOIN information_schema.table_constraints tc
                ON cc.constraint_schema = tc.constraint_schema
                AND cc.constraint_name = tc.constraint_name
            WHERE cc.constraint_schema = ?
                AND tc.table_name = ?
                AND tc.constraint_type = 'CHECK'
            ORDER BY cc.constraint_name
        """
        return (query, [schema, table])

    def get_sequences_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get sequences (MariaDB 10.3+).

        MySQL does not support sequences, but MariaDB 10.3+ does.
        This query will work for MariaDB and fail gracefully for MySQL.
        """
        query = """
            SELECT
                SEQUENCE_NAME as sequence_name,
                'BIGINT' AS data_type,
                START_VALUE as start_value,
                MINIMUM_VALUE as minimum_value,
                MAXIMUM_VALUE as maximum_value,
                INCREMENT as increment,
                CASE CYCLE_OPTION
                    WHEN 1 THEN 'YES'
                    ELSE 'NO'
                END AS cycle_option,
                CACHE_SIZE as cache_size
            FROM information_schema.SEQUENCES
            WHERE SEQUENCE_SCHEMA = ?
            ORDER BY SEQUENCE_NAME
        """
        return (query, [schema])

    def get_table_properties_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get MySQL-specific table properties (engine, row format, collation, auto_increment).
        """
        query = """
            SELECT
                ENGINE AS storage_engine,
                ROW_FORMAT AS row_format,
                TABLE_COLLATION AS table_collation,
                AUTO_INCREMENT AS next_auto_increment,
                CREATE_OPTIONS AS create_options
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = ?
                AND TABLE_NAME = ?
            LIMIT 1
        """
        return (query, [schema, table])

    def get_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get views using information_schema.

        MySQL stores view definitions in information_schema.VIEWS.

        Grammar-based: Added algorithm, sql_security, and definer extraction.
        Note: Algorithm is not directly available in information_schema.views,
        but can be extracted from SHOW CREATE VIEW or parsed from view definition.
        For now, we extract definer and sql_security which are available.
        """
        query = """
            SELECT
                table_name AS view_name,
                view_definition,
                is_updatable,
                check_option,
                DEFINER AS definer,
                SECURITY_TYPE AS sql_security
            FROM information_schema.views
            WHERE table_schema = ?
            ORDER BY table_name
        """
        return (query, [schema])

    def get_view_definition_query(self, schema: str, view_name: str) -> tuple[str, List[Any]]:
        """
        Get a specific view's definition from information_schema.
        """
        query = """
            SELECT
                view_definition
            FROM information_schema.views
            WHERE table_schema = ?
                AND table_name = ?
        """
        return (query, [schema, view_name])

    def get_indexes_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get detailed index information using information_schema.STATISTICS.

        MySQL includes information about fulltext and spatial indexes.

        Grammar-based: INDEX_TYPE already includes FULLTEXT/SPATIAL.
        Note: ONLINE/OFFLINE status is not directly available in information_schema,
        but can be detected from table metadata or SHOW CREATE TABLE.
        """
        query = """
            SELECT
                INDEX_NAME as index_name,
                COLUMN_NAME as column_name,
                SEQ_IN_INDEX as ordinal_position,
                CASE COLLATION
                    WHEN 'D' THEN 'Y'
                    ELSE 'N'
                END AS is_descending,
                CASE NON_UNIQUE
                    WHEN 0 THEN 'Y'
                    ELSE 'N'
                END AS is_unique,
                INDEX_TYPE as index_type,
                NULL AS filter_condition,
                CASE EXPRESSION
                    WHEN NULL THEN 'N'
                    ELSE 'Y'
                END AS is_expression,
                EXPRESSION AS index_expression
            FROM information_schema.STATISTICS
            WHERE TABLE_SCHEMA = ?
                AND TABLE_NAME = ?
                AND INDEX_NAME != 'PRIMARY'
            ORDER BY INDEX_NAME, SEQ_IN_INDEX
        """
        return (query, [schema, table])

    def get_procedures_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get stored procedures using information_schema.ROUTINES.

        MySQL stores procedure metadata in information_schema.
        """
        query = """
            SELECT
                ROUTINE_NAME as procedure_name,
                'PROCEDURE' AS procedure_type,
                'SQL' AS language,
                ROUTINE_DEFINITION as definition,
                ROUTINE_COMMENT as comment,
                SECURITY_TYPE AS security_type,
                DEFINER AS definer,
                IS_DETERMINISTIC AS is_deterministic,
                SQL_DATA_ACCESS AS data_access
            FROM information_schema.ROUTINES
            WHERE ROUTINE_SCHEMA = ?
                AND ROUTINE_TYPE = 'PROCEDURE'
            ORDER BY ROUTINE_NAME
        """
        return (query, [schema])

    def get_functions_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get functions using information_schema.ROUTINES.

        MySQL supports both scalar and aggregate functions.
        """
        query = """
            SELECT
                ROUTINE_NAME as function_name,
                /* Use DTD_IDENTIFIER to capture full type details like VARCHAR(255), DECIMAL(10,2) */
                DTD_IDENTIFIER as return_type,
                'SQL' AS language,
                ROUTINE_DEFINITION as definition,
                ROUTINE_COMMENT as comment,
                'FUNCTION' as function_type,
                SECURITY_TYPE AS security_type,
                DEFINER AS definer,
                IS_DETERMINISTIC AS is_deterministic,
                SQL_DATA_ACCESS AS data_access
            FROM information_schema.ROUTINES
            WHERE ROUTINE_SCHEMA = ?
                AND ROUTINE_TYPE = 'FUNCTION'
            ORDER BY ROUTINE_NAME
        """
        return (query, [schema])

    def get_parameters_query(self, schema: str, routine_name: str) -> tuple[str, List[Any]]:
        """
        Get routine parameters using information_schema.PARAMETERS.

        BUG-02: FUNCTION routines have an implicit return-value row with
        ORDINAL_POSITION=0 and PARAMETER_MODE=NULL. Without filtering it out
        we surfaced a bogus ``param_0`` in introspection snapshots. Excluding
        rows where PARAMETER_MODE IS NULL drops the return row while keeping
        IN/OUT/INOUT parameters for both FUNCTIONs and PROCEDUREs.
        """
        query = """
            SELECT
                ORDINAL_POSITION AS ordinal_position,
                PARAMETER_NAME AS param_name,
                DTD_IDENTIFIER AS parameter_type,
                PARAMETER_MODE AS param_mode
            FROM information_schema.PARAMETERS
            WHERE SPECIFIC_SCHEMA = ?
                AND SPECIFIC_NAME = ?
                AND PARAMETER_MODE IS NOT NULL
            ORDER BY ORDINAL_POSITION
        """
        return (query, [schema, routine_name])

    def get_triggers_query(self, schema: str, table: str = None) -> tuple[str, List[Any]]:
        """
        Get triggers using information_schema.TRIGGERS.

        MySQL has good trigger metadata in information_schema.

        Grammar-based: Added DEFINER extraction.
        """
        if table:
            query = """
                SELECT
                    TRIGGER_NAME as trigger_name,
                    EVENT_OBJECT_TABLE as table_name,
                    EVENT_MANIPULATION as event_manipulation,
                    ACTION_TIMING as action_timing,
                    ACTION_STATEMENT as action_statement,
                    ACTION_ORIENTATION as action_orientation,
                    DEFINER as definer
                FROM information_schema.TRIGGERS
                WHERE TRIGGER_SCHEMA = ?
                    AND EVENT_OBJECT_TABLE = ?
                ORDER BY TRIGGER_NAME
            """
            params = [schema, table]
        else:
            query = """
                SELECT
                    TRIGGER_NAME as trigger_name,
                    EVENT_OBJECT_TABLE as table_name,
                    EVENT_MANIPULATION as event_manipulation,
                    ACTION_TIMING as action_timing,
                    ACTION_STATEMENT as action_statement,
                    ACTION_ORIENTATION as action_orientation,
                    DEFINER as definer
                FROM information_schema.TRIGGERS
                WHERE TRIGGER_SCHEMA = ?
                ORDER BY EVENT_OBJECT_TABLE, TRIGGER_NAME
            """
            params = [schema]

        return (query, params)

    def get_events_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get scheduled events using information_schema.EVENTS.

        MySQL has event metadata in information_schema (MySQL 5.1+).
        """
        query = """
            SELECT
                EVENT_NAME as event_name,
                EVENT_DEFINITION as event_definition,
                CASE
                    WHEN INTERVAL_VALUE IS NOT NULL AND INTERVAL_FIELD IS NOT NULL
                        THEN CONCAT(
                            'EVERY ', INTERVAL_VALUE, ' ', INTERVAL_FIELD,
                            CASE WHEN STARTS IS NOT NULL
                                THEN CONCAT(' STARTS ', STARTS)
                                ELSE ''
                            END,
                            CASE WHEN ENDS IS NOT NULL
                                THEN CONCAT(' ENDS ', ENDS)
                                ELSE ''
                            END
                        )
                    WHEN EXECUTE_AT IS NOT NULL
                        THEN CONCAT('AT ', EXECUTE_AT)
                    ELSE ''
                END as event_schedule,
                STATUS as status,
                EVENT_TYPE as event_type,
                EVENT_COMMENT as event_comment,
                DEFINER as definer,
                ON_COMPLETION as on_completion
            FROM information_schema.EVENTS
            WHERE EVENT_SCHEMA = ?
            ORDER BY EVENT_NAME
        """
        return (query, [schema])

    def get_computed_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get generated columns (MySQL 5.7+).

        MySQL supports GENERATED/VIRTUAL columns.
        """
        query = """
            SELECT
                COLUMN_NAME as column_name,
                GENERATION_EXPRESSION as computation_expression,
                CASE EXTRA
                    WHEN 'STORED GENERATED' THEN 'Y'
                    WHEN 'VIRTUAL GENERATED' THEN 'N'
                    WHEN 'PERSISTENT GENERATED' THEN 'Y'
                    ELSE 'N'
                END AS is_stored
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = ?
                AND TABLE_NAME = ?
                AND EXTRA IN ('STORED GENERATED', 'VIRTUAL GENERATED', 'PERSISTENT GENERATED')
            ORDER BY ORDINAL_POSITION
        """
        return (query, [schema, table])

    def get_identity_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get AUTO_INCREMENT column information.

        MySQL uses AUTO_INCREMENT for identity columns.
        """
        query = """
            SELECT
                c.COLUMN_NAME as column_name,
                1 AS seed_value,
                1 AS increment_value,
                t.AUTO_INCREMENT as current_value
            FROM information_schema.COLUMNS c
            INNER JOIN information_schema.TABLES t
                ON c.TABLE_SCHEMA = t.TABLE_SCHEMA
                AND c.TABLE_NAME = t.TABLE_NAME
            WHERE c.TABLE_SCHEMA = ?
                AND c.TABLE_NAME = ?
                AND c.EXTRA LIKE '%auto_increment%'
            ORDER BY c.ORDINAL_POSITION
        """
        return (query, [schema, table])

    def get_table_partitions_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get table partition information.

        MySQL supports RANGE, LIST, HASH, and KEY partitioning.
        """
        query = """
            SELECT
                p.PARTITION_NAME as partition_name,
                p.PARTITION_EXPRESSION as partition_expression,
                p.PARTITION_METHOD as partition_method,
                p.PARTITION_DESCRIPTION as high_value
            FROM information_schema.PARTITIONS p
            WHERE p.TABLE_SCHEMA = ?
                AND p.TABLE_NAME = ?
                AND p.PARTITION_NAME IS NOT NULL
            ORDER BY p.PARTITION_ORDINAL_POSITION
        """
        return (query, [schema, table])

    def supports_check_constraints(self) -> bool:
        """MySQL 8.0.16+ and MariaDB 10.2+ support check constraints."""
        return True

    def supports_sequences(self) -> bool:
        """MariaDB 10.3+ supports sequences. MySQL does not."""
        return False  # Default to False for MySQL

    def supports_views(self) -> bool:
        """MySQL fully supports views."""
        return True

    def supports_triggers(self) -> bool:
        """MySQL fully supports triggers."""
        return True

    def supports_computed_columns(self) -> bool:
        """MySQL 5.7+ supports generated columns."""
        return True

    def supports_partitions(self) -> bool:
        """MySQL supports table partitioning."""
        return True

    def supports_procedures(self) -> bool:
        """MySQL fully supports stored procedures."""
        return True

    def supports_functions(self) -> bool:
        """MySQL fully supports functions."""
        return True

    def supports_events(self) -> bool:
        """MySQL / MariaDB expose scheduled events via ``information_schema.events``."""
        return True

    def get_partition_scheme_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Get partitioning scheme (method and key columns only, not individual partitions).

        MySQL partitioning types (5.1+): RANGE, LIST, HASH, KEY, LINEAR HASH, LINEAR KEY
        Note: We only track the partitioning strategy, not individual partitions.
        """
        query = """
            SELECT
                pt.partition_method,
                pt.partition_expression
            FROM information_schema.partitions pt
            WHERE pt.table_schema = ?
                AND pt.table_name = ?
                AND pt.partition_name IS NOT NULL
            LIMIT 1
        """
        return (query, [schema, table])

    # ------------------------------------------------------------------
    # Structural metadata — native (native) provider path
    # ------------------------------------------------------------------

    def get_tables_query(self, schema: str) -> tuple[str, List[Any]]:
        """List base table names in *schema*."""
        query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = ?
              AND table_type = 'BASE TABLE'
            ORDER BY table_name
        """
        return (query, [schema])

    def get_view_names_query(self, schema: str) -> tuple[str, List[Any]]:
        """List view names in *schema*."""
        query = """
            SELECT table_name AS view_name
            FROM information_schema.tables
            WHERE table_schema = ?
              AND table_type = 'VIEW'
            ORDER BY table_name
        """
        return (query, [schema])

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return column metadata with PK detection from information_schema."""
        query = """
            SELECT
                c.column_name,
                c.column_type                                          AS data_type,
                CASE WHEN c.is_nullable = 'YES' THEN 1 ELSE 0 END     AS is_nullable,
                c.column_default,
                CASE WHEN c.column_key = 'PRI' THEN 1 ELSE 0 END      AS is_primary_key,
                c.ordinal_position
            FROM information_schema.columns c
            WHERE c.table_schema = ?
              AND c.table_name   = ?
            ORDER BY c.ordinal_position
        """
        return (query, [schema, table])

    def get_primary_key_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return the PK constraint name and ordered column list for *table*."""
        query = """
            SELECT
                tc.constraint_name,
                kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON  tc.constraint_name = kcu.constraint_name
                AND tc.table_schema    = kcu.table_schema
                AND tc.table_name      = kcu.table_name
            WHERE tc.table_schema    = ?
              AND tc.table_name      = ?
              AND tc.constraint_type = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
        """
        return (query, [schema, table])

    def get_foreign_keys_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return FK constraint rows for *table* (one row per constrained column)."""
        query = """
            SELECT
                tc.constraint_name              AS name,
                kcu.column_name,
                kcu.referenced_table_schema     AS ref_schema,
                kcu.referenced_table_name       AS ref_table,
                kcu.referenced_column_name      AS ref_column,
                rc.delete_rule                  AS on_delete,
                rc.update_rule                  AS on_update
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON  tc.constraint_name = kcu.constraint_name
                AND tc.table_schema    = kcu.table_schema
                AND tc.table_name      = kcu.table_name
            JOIN information_schema.referential_constraints rc
                ON  rc.constraint_name   = tc.constraint_name
                AND rc.constraint_schema = tc.table_schema
            WHERE tc.table_schema    = ?
              AND tc.table_name      = ?
              AND tc.constraint_type = 'FOREIGN KEY'
            ORDER BY tc.constraint_name, kcu.ordinal_position
        """
        return (query, [schema, table])

    def get_unique_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return UNIQUE constraint rows for *table* (one row per constrained column)."""
        query = """
            SELECT
                tc.constraint_name  AS name,
                kcu.column_name
            FROM information_schema.table_constraints tc
            JOIN information_schema.key_column_usage kcu
                ON  tc.constraint_name = kcu.constraint_name
                AND tc.table_schema    = kcu.table_schema
                AND tc.table_name      = kcu.table_name
            WHERE tc.table_schema    = ?
              AND tc.table_name      = ?
              AND tc.constraint_type = 'UNIQUE'
            ORDER BY tc.constraint_name, kcu.ordinal_position
        """
        return (query, [schema, table])
