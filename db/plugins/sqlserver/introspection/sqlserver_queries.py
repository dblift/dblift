"""
SQL Server-specific metadata queries.

This module provides SQL Server-specific queries for extracting metadata.

Queries are inspired by SQLAlchemy's SQL Server dialect:
https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/mssql/base.py

SQL Server uses sys.* catalog views for metadata queries, which provide
richer information than information_schema views.
"""

from typing import Any, List

from core.introspection.vendor_queries_base import VendorMetadataQueries


class SQLServerMetadataQueries(VendorMetadataQueries):
    """
    SQL Server-specific metadata queries using sys.* catalog views.

    References:
        - SQL Server System Catalog Views: https://learn.microsoft.com/en-us/sql/relational-databases/system-catalog-views/
        - SQLAlchemy MSSQL Dialect: https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/mssql/base.py
    """

    def get_table_properties_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get SQL Server-specific table properties.

        Grammar-based: Extracts filegroup, memory_optimized, system_versioned, and history_table.
        Note: temporal_type and history_table_id were added in SQL Server 2016.
        is_memory_optimized was added in SQL Server 2014.

        We use a simplified approach for maximum compatibility.
        The filegroup information is obtained via indexes since all tables have at least
        one index (clustered index or heap).
        """
        # Use a simpler query that works across all SQL Server versions
        query = """
            SELECT
                t.name AS table_name,
                COALESCE(
                    (
                        SELECT TOP 1 ds.name
                        FROM sys.indexes i
                        INNER JOIN sys.data_spaces ds
                            ON i.data_space_id = ds.data_space_id
                        WHERE i.object_id = t.object_id
                          AND i.index_id IN (0, 1)  -- 0 = heap, 1 = clustered index
                        ORDER BY i.index_id
                    ),
                    'PRIMARY'
                ) AS filegroup_name,
                CASE
                    WHEN t.is_memory_optimized = 1 THEN 'YES'
                    ELSE 'NO'
                END AS is_memory_optimized,
                CASE
                    WHEN t.temporal_type = 2 THEN 'YES'
                    ELSE 'NO'
                END AS is_system_versioned,
                ht.name AS history_table_name,
                hs.name AS history_schema_name,
                start_col.name AS period_start_column,
                end_col.name AS period_end_column
            FROM sys.tables t
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            LEFT JOIN sys.tables ht
                ON t.history_table_id = ht.object_id
            LEFT JOIN sys.schemas hs
                ON ht.schema_id = hs.schema_id
            LEFT JOIN sys.periods per
                ON per.object_id = t.object_id
            LEFT JOIN sys.columns start_col
                ON start_col.object_id = t.object_id
                AND start_col.column_id = per.start_column_id
            LEFT JOIN sys.columns end_col
                ON end_col.object_id = t.object_id
                AND end_col.column_id = per.end_column_id
            WHERE s.name = ?
                AND t.name = ?
        """
        return (query, [schema, table])

    def get_check_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get check constraints using sys.check_constraints.

        SQL Server provides constraint definitions in sys.check_constraints.
        """
        query = """
            SELECT
                cc.name AS constraint_name,
                cc.definition AS constraint_definition,
                'N' AS is_deferrable,
                'N' AS initially_deferred,
                CASE cc.is_disabled
                    WHEN 0 THEN 'Y'
                    ELSE 'N'
                END AS is_enabled,
                CASE cc.is_not_trusted
                    WHEN 0 THEN 'Y'
                    ELSE 'N'
                END AS is_validated
            FROM sys.check_constraints cc
            INNER JOIN sys.tables t
                ON cc.parent_object_id = t.object_id
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            WHERE s.name = ?
                AND t.name = ?
            ORDER BY cc.name
        """
        return (query, [schema, table])

    def get_sequences_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get sequences using sys.sequences (SQL Server 2012+).

        SQL Server introduced sequences in version 2012.
        """
        query = """
            SELECT
                seq.name AS sequence_name,
                TYPE_NAME(seq.user_type_id) AS data_type,
                CAST(seq.start_value AS BIGINT) AS start_value,
                CAST(seq.minimum_value AS BIGINT) AS minimum_value,
                CAST(seq.maximum_value AS BIGINT) AS maximum_value,
                CAST(seq.increment AS BIGINT) AS increment,
                CASE seq.is_cycling
                    WHEN 1 THEN 'YES'
                    ELSE 'NO'
                END AS cycle_option,
                seq.cache_size
            FROM sys.sequences seq
            INNER JOIN sys.schemas s
                ON seq.schema_id = s.schema_id
            WHERE s.name = ?
            ORDER BY seq.name
        """
        return (query, [schema])

    def get_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get views using sys.views and OBJECT_DEFINITION().

        SQL Server stores view definitions accessible via OBJECT_DEFINITION().
        Indexed views (views with a unique clustered index) are excluded here so
        they are only returned by ``get_materialized_views_query`` — otherwise
        they would be emitted twice in exported schemas.
        """
        query = """
            SELECT
                v.name AS view_name,
                OBJECT_DEFINITION(v.object_id) AS view_definition,
                CASE
                    WHEN EXISTS (
                        SELECT 1 FROM sys.triggers t
                        WHERE t.parent_id = v.object_id
                        AND t.is_instead_of_trigger = 1
                    ) THEN 'YES'
                    ELSE 'NO'
                END AS is_updatable,
                'NONE' AS check_option
            FROM sys.views v
            INNER JOIN sys.schemas s
                ON v.schema_id = s.schema_id
            WHERE s.name = ?
                AND v.is_ms_shipped = 0
                AND NOT EXISTS (
                    SELECT 1
                    FROM sys.indexes i
                    WHERE i.object_id = v.object_id
                    AND i.type = 1
                    AND i.is_unique = 1
                )
            ORDER BY v.name
        """
        return (query, [schema])

    def get_view_definition_query(self, schema: str, view_name: str) -> tuple[str, List[Any]]:
        """
        Get a specific view's definition using OBJECT_DEFINITION().
        """
        query = """
            SELECT
                OBJECT_DEFINITION(v.object_id) AS view_definition
            FROM sys.views v
            INNER JOIN sys.schemas s
                ON v.schema_id = s.schema_id
            WHERE s.name = ?
                AND v.name = ?
        """
        return (query, [schema, view_name])

    def get_indexes_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get detailed index information using sys.indexes and sys.index_columns.

        Includes filtered indexes, included columns, and columnstore indexes.
        """
        query = """
            SELECT
                i.name AS index_name,
                c.name AS column_name,
                ic.key_ordinal AS ordinal_position,
                CASE ic.is_descending_key
                    WHEN 1 THEN 'Y'
                    ELSE 'N'
                END AS is_descending,
                CASE i.is_unique
                    WHEN 1 THEN 'Y'
                    ELSE 'N'
                END AS is_unique,
                i.type_desc AS index_type,
                i.filter_definition AS filter_condition,
                CASE ic.is_included_column
                    WHEN 1 THEN 'Y'
                    ELSE 'N'
                END AS is_included,
                'N' AS is_expression,
                (
                    SELECT c2.name
                    FROM sys.index_columns ic2
                    INNER JOIN sys.columns c2
                        ON ic2.object_id = c2.object_id
                        AND ic2.column_id = c2.column_id
                    WHERE ic2.object_id = i.object_id
                        AND ic2.index_id = i.index_id
                        AND ic2.is_included_column = 1
                    ORDER BY ic2.key_ordinal, c2.name
                    FOR JSON PATH
                ) AS include_columns
            FROM sys.indexes i
            INNER JOIN sys.objects t
                ON i.object_id = t.object_id
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            INNER JOIN sys.index_columns ic
                ON i.object_id = ic.object_id
                AND i.index_id = ic.index_id
            INNER JOIN sys.columns c
                ON ic.object_id = c.object_id
                AND ic.column_id = c.column_id
            WHERE s.name = ?
                AND t.name = ?
                AND t.type IN ('U', 'V')
                AND t.is_ms_shipped = 0
                AND i.is_primary_key = 0
                AND i.is_unique_constraint = 0
            ORDER BY i.name, ic.key_ordinal
        """
        return (query, [schema, table])

    def get_all_indexes_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get all table and indexed-view indexes for a schema in one call.

        SQL Server stores indexes for both tables and indexed views in sys.indexes.
        Snapshot generation needs view indexes as first-class index entries so
        indexed/materialized view changes are diffable.
        """
        query = """
            SELECT
                o.name AS table_name,
                i.name AS index_name,
                c.name AS column_name,
                ic.key_ordinal AS ordinal_position,
                CASE ic.is_descending_key
                    WHEN 1 THEN 'Y'
                    ELSE 'N'
                END AS is_descending,
                CASE i.is_unique
                    WHEN 1 THEN 'Y'
                    ELSE 'N'
                END AS is_unique,
                i.type_desc AS index_type,
                i.filter_definition AS filter_condition,
                CASE ic.is_included_column
                    WHEN 1 THEN 'Y'
                    ELSE 'N'
                END AS is_included,
                'N' AS is_expression,
                (
                    SELECT c2.name
                    FROM sys.index_columns ic2
                    INNER JOIN sys.columns c2
                        ON ic2.object_id = c2.object_id
                        AND ic2.column_id = c2.column_id
                    WHERE ic2.object_id = i.object_id
                        AND ic2.index_id = i.index_id
                        AND ic2.is_included_column = 1
                    ORDER BY ic2.key_ordinal, c2.name
                    FOR JSON PATH
                ) AS include_columns
            FROM sys.indexes i
            INNER JOIN sys.objects o
                ON i.object_id = o.object_id
            INNER JOIN sys.schemas s
                ON o.schema_id = s.schema_id
            INNER JOIN sys.index_columns ic
                ON i.object_id = ic.object_id
                AND i.index_id = ic.index_id
            INNER JOIN sys.columns c
                ON ic.object_id = c.object_id
                AND ic.column_id = c.column_id
            WHERE s.name = ?
                AND o.type IN ('U', 'V')
                AND o.is_ms_shipped = 0
                AND i.is_primary_key = 0
                AND i.is_unique_constraint = 0
            ORDER BY o.name, i.name, ic.key_ordinal
        """
        return (query, [schema])

    def get_triggers_query(self, schema: str, table: str = None) -> tuple[str, List[Any]]:
        """
        Get triggers using sys.triggers.

        SQL Server has rich trigger metadata in sys.triggers.
        """
        if table:
            query = """
                SELECT
                    tr.name AS trigger_name,
                    OBJECT_NAME(tr.parent_id) AS table_name,
                    CASE
                        WHEN tr.is_instead_of_trigger = 1 THEN 'INSTEAD OF'
                        ELSE 'AFTER'
                    END AS action_timing,
                    STUFF((
                        SELECT ', ' + type_desc
                        FROM (
                            SELECT CASE WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsInsertTrigger') = 1 THEN 'INSERT' END
                            UNION ALL
                            SELECT CASE WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsUpdateTrigger') = 1 THEN 'UPDATE' END
                            UNION ALL
                            SELECT CASE WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsDeleteTrigger') = 1 THEN 'DELETE' END
                        ) t(type_desc)
                        WHERE type_desc IS NOT NULL
                        FOR XML PATH('')
                    ), 1, 2, '') AS event_manipulation,
                    OBJECT_DEFINITION(tr.object_id) AS action_statement,
                    'STATEMENT' AS action_orientation
                FROM sys.triggers tr
                INNER JOIN sys.objects o
                    ON tr.parent_id = o.object_id
                INNER JOIN sys.schemas s
                    ON o.schema_id = s.schema_id
                WHERE s.name = ?
                    AND o.name = ?
                    AND tr.is_disabled = 0
                ORDER BY tr.name
            """
            params = [schema, table]
        else:
            query = """
                SELECT
                    tr.name AS trigger_name,
                    OBJECT_NAME(tr.parent_id) AS table_name,
                    CASE
                        WHEN tr.is_instead_of_trigger = 1 THEN 'INSTEAD OF'
                        ELSE 'AFTER'
                    END AS action_timing,
                    STUFF((
                        SELECT ', ' + type_desc
                        FROM (
                            SELECT CASE WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsInsertTrigger') = 1 THEN 'INSERT' END
                            UNION ALL
                            SELECT CASE WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsUpdateTrigger') = 1 THEN 'UPDATE' END
                            UNION ALL
                            SELECT CASE WHEN OBJECTPROPERTY(tr.object_id, 'ExecIsDeleteTrigger') = 1 THEN 'DELETE' END
                        ) t(type_desc)
                        WHERE type_desc IS NOT NULL
                        FOR XML PATH('')
                    ), 1, 2, '') AS event_manipulation,
                    OBJECT_DEFINITION(tr.object_id) AS action_statement,
                    'STATEMENT' AS action_orientation
                FROM sys.triggers tr
                INNER JOIN sys.objects o
                    ON tr.parent_id = o.object_id
                INNER JOIN sys.schemas s
                    ON o.schema_id = s.schema_id
                WHERE s.name = ?
                    AND tr.is_disabled = 0
                ORDER BY OBJECT_NAME(tr.parent_id), tr.name
            """
            params = [schema]

        return (query, params)

    def get_computed_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get computed columns using sys.computed_columns.

        SQL Server has first-class support for computed columns.
        """
        query = """
            SELECT
                c.name AS column_name,
                cc.definition AS computation_expression,
                CASE cc.is_persisted
                    WHEN 1 THEN 'Y'
                    ELSE 'N'
                END AS is_stored,
                CASE cc.is_persisted
                    WHEN 1 THEN 'Y'
                    ELSE 'N'
                END AS is_persisted
            FROM sys.computed_columns cc
            INNER JOIN sys.columns c
                ON cc.object_id = c.object_id
                AND cc.column_id = c.column_id
            INNER JOIN sys.tables t
                ON c.object_id = t.object_id
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            WHERE s.name = ?
                AND t.name = ?
            ORDER BY c.column_id
        """
        return (query, [schema, table])

    def get_identity_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get identity column information using sys.identity_columns.

        SQL Server has rich identity column metadata.
        """
        query = """
            SELECT
                c.name AS column_name,
                ic.seed_value,
                ic.increment_value,
                ic.last_value
            FROM sys.identity_columns ic
            INNER JOIN sys.columns c
                ON ic.object_id = c.object_id
                AND ic.column_id = c.column_id
            INNER JOIN sys.tables t
                ON c.object_id = t.object_id
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            WHERE s.name = ?
                AND t.name = ?
            ORDER BY c.column_id
        """
        return (query, [schema, table])

    def get_table_partitions_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get table partition information.

        SQL Server supports table partitioning with partition functions and schemes.
        """
        query = """
            SELECT
                p.partition_number AS partition_name,
                pf.name + '(' + STRING_AGG(c.name, ', ') + ')' AS partition_expression,
                pf.type_desc AS partition_method,
                prv.value AS high_value
            FROM sys.partitions p
            INNER JOIN sys.tables t
                ON p.object_id = t.object_id
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            INNER JOIN sys.indexes i
                ON t.object_id = i.object_id
                AND p.index_id = i.index_id
            INNER JOIN sys.partition_schemes ps
                ON i.data_space_id = ps.data_space_id
            INNER JOIN sys.partition_functions pf
                ON ps.function_id = pf.function_id
            LEFT JOIN sys.partition_range_values prv
                ON pf.function_id = prv.function_id
                AND p.partition_number = prv.boundary_id
            LEFT JOIN sys.index_columns ic
                ON i.object_id = ic.object_id
                AND i.index_id = ic.index_id
                AND ic.partition_ordinal > 0
            LEFT JOIN sys.columns c
                ON ic.object_id = c.object_id
                AND ic.column_id = c.column_id
            WHERE s.name = ?
                AND t.name = ?
            GROUP BY p.partition_number, pf.name, pf.type_desc, prv.value
            ORDER BY p.partition_number
        """
        return (query, [schema, table])

    def get_procedures_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get stored procedures using sys.procedures.

        SQL Server stores procedure definitions in sys.sql_modules.
        """
        query = """
            SELECT
                p.name AS procedure_name,
                'PROCEDURE' AS procedure_type,
                'TSQL' AS language,
                m.definition,
                ep.value AS comment,
                dp.name AS execute_as_principal,
                CASE
                    WHEN OBJECTPROPERTYEX(p.object_id, 'ExecIsReadOnly') = 1 THEN 'READS SQL DATA'
                    ELSE 'MODIFIES SQL DATA'
                END AS data_access,
                ISNULL((
                    SELECT
                        CASE
                            WHEN pr.name LIKE '@%' THEN SUBSTRING(pr.name, 2, LEN(pr.name))
                            ELSE pr.name
                        END AS name,
                        TYPE_NAME(pr.user_type_id) AS data_type,
                        CASE WHEN pr.is_output = 1 THEN 'OUT' ELSE 'IN' END AS mode
                    FROM sys.parameters pr
                    WHERE pr.object_id = p.object_id
                    ORDER BY pr.parameter_id
                    FOR JSON PATH
                ), '[]') AS parameter_json
            FROM sys.procedures p
            INNER JOIN sys.schemas s
                ON p.schema_id = s.schema_id
            LEFT JOIN sys.sql_modules m
                ON p.object_id = m.object_id
            LEFT JOIN sys.extended_properties ep
                ON ep.major_id = p.object_id
                AND ep.name = 'MS_Description'
                AND ep.minor_id = 0
            LEFT JOIN sys.database_principals dp
                ON dp.principal_id = m.execute_as_principal_id
            WHERE s.name = ?
                AND p.is_ms_shipped = 0
            ORDER BY p.name
        """
        return (query, [schema])

    def get_functions_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get functions using sys.objects.

        SQL Server has multiple function types: scalar, inline table-valued, multi-statement table-valued.
        """
        query = """
            SELECT
                o.name AS function_name,
                TYPE_NAME(COALESCE(r.user_type_id, r.system_type_id)) AS return_type,
                'TSQL' AS language,
                m.definition,
                ep.value AS comment,
                o.type_desc AS function_type,
                CASE
                    WHEN OBJECTPROPERTYEX(o.object_id, 'IsDeterministic') = 1 THEN 'YES'
                    ELSE 'NO'
                END AS is_deterministic,
                dp.name AS execute_as_principal,
                CASE
                    WHEN OBJECTPROPERTYEX(o.object_id, 'ExecIsReadOnly') = 1 THEN 'READS SQL DATA'
                    ELSE 'MODIFIES SQL DATA'
                END AS data_access,
                ISNULL((
                    SELECT
                        CASE
                            WHEN pr.name LIKE '@%' THEN SUBSTRING(pr.name, 2, LEN(pr.name))
                            ELSE pr.name
                        END AS name,
                        TYPE_NAME(pr.user_type_id) AS data_type,
                        CASE WHEN pr.is_output = 1 THEN 'OUT' ELSE 'IN' END AS mode
                    FROM sys.parameters pr
                    WHERE pr.object_id = o.object_id
                      AND pr.parameter_id > 0
                    ORDER BY pr.parameter_id
                    FOR JSON PATH
                ), '[]') AS parameter_json
            FROM sys.objects o
            INNER JOIN sys.schemas s
                ON o.schema_id = s.schema_id
            LEFT JOIN sys.sql_modules m
                ON o.object_id = m.object_id
            LEFT JOIN sys.extended_properties ep
                ON ep.major_id = o.object_id
                AND ep.name = 'MS_Description'
                AND ep.minor_id = 0
            LEFT JOIN sys.parameters r
                ON r.object_id = o.object_id
                AND r.parameter_id = 0
            LEFT JOIN sys.database_principals dp
                ON dp.principal_id = m.execute_as_principal_id
            WHERE s.name = ?
                AND o.type IN ('FN', 'IF', 'TF')
                AND o.is_ms_shipped = 0
            ORDER BY o.name
        """
        return (query, [schema])

    def supports_check_constraints(self) -> bool:
        """SQL Server fully supports check constraints."""
        return True

    def supports_sequences(self) -> bool:
        """SQL Server supports sequences (version 2012+)."""
        return True

    def supports_views(self) -> bool:
        """SQL Server fully supports views."""
        return True

    def supports_triggers(self) -> bool:
        """SQL Server fully supports triggers."""
        return True

    def supports_computed_columns(self) -> bool:
        """SQL Server fully supports computed columns."""
        return True

    def supports_partitions(self) -> bool:
        """SQL Server supports table partitioning."""
        return True

    def get_materialized_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get indexed/materialized views using sys.views.

        SQL Server doesn't have native materialized views like Oracle/PostgreSQL.
        However, indexed views (views with a unique clustered index) are effectively
        materialized.

        Detection strategy: Find views with a unique clustered index, which makes
        them indexed views (SQL Server's equivalent of materialized views).
        """
        query = """
            SELECT
                v.name AS materialized_view_name,
                OBJECT_DEFINITION(v.object_id) AS view_definition,
                'YES' AS is_populated,
                NULL AS last_refresh,
                'MANUAL' AS refresh_method,
                idx.name AS clustered_index_name,
                STUFF((
                    SELECT ',' + c.name
                    FROM sys.index_columns ic2
                    INNER JOIN sys.columns c
                        ON ic2.object_id = c.object_id
                        AND ic2.column_id = c.column_id
                    WHERE ic2.object_id = idx.object_id
                        AND ic2.index_id = idx.index_id
                    ORDER BY ic2.key_ordinal
                    FOR XML PATH('')
                ), 1, 1, '') AS clustered_index_columns
            FROM sys.views v
            INNER JOIN sys.schemas s
                ON v.schema_id = s.schema_id
            INNER JOIN sys.indexes idx
                ON idx.object_id = v.object_id
                AND idx.type = 1
                AND idx.is_unique = 1
            WHERE s.name = ?
                AND v.is_ms_shipped = 0
            ORDER BY v.name
        """
        return (query, [schema])

    def supports_materialized_views(self) -> bool:
        """SQL Server supports indexed views (effectively materialized views)."""
        return True

    def supports_procedures(self) -> bool:
        """SQL Server fully supports stored procedures."""
        return True

    def supports_functions(self) -> bool:
        """SQL Server fully supports functions (scalar and table-valued)."""
        return True

    def get_synonyms_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get synonyms using sys.synonyms.

        Inspired by SQLAlchemy: lib/sqlalchemy/dialects/mssql/base.py
        """
        query = """
            SELECT
                s.name AS synonym_name,
                PARSENAME(s.base_object_name, 3) AS target_database,
                PARSENAME(s.base_object_name, 2) AS target_schema,
                PARSENAME(s.base_object_name, 1) AS target_object
            FROM sys.synonyms s
            WHERE SCHEMA_NAME(s.schema_id) = ?
            ORDER BY s.name
        """
        return (query, [schema])

    def supports_synonyms(self) -> bool:
        """SQL Server fully supports synonyms."""
        return True

    def get_user_defined_types_query(self, schema: str) -> tuple[str, List[Any]]:
        """Get user-defined alias types defined in the specified schema."""

        query = """
            SELECT
                t.name AS type_name,
                'DISTINCT' AS type_category,
                UPPER(bt.base_name) +
                    CASE
                        WHEN bt.base_name IN ('varchar', 'char', 'varbinary', 'binary') THEN
                            '(' + CASE WHEN t.max_length = -1 THEN 'MAX' ELSE CAST(t.max_length AS VARCHAR(10)) END + ')'
                        WHEN bt.base_name IN ('nvarchar', 'nchar') THEN
                            '(' + CASE WHEN t.max_length = -1 THEN 'MAX' ELSE CAST(t.max_length / 2 AS VARCHAR(10)) END + ')'
                        WHEN bt.base_name IN ('decimal', 'numeric') THEN
                            '(' + CAST(t.precision AS VARCHAR(10)) + ',' + CAST(t.scale AS VARCHAR(10)) + ')'
                        WHEN bt.base_name IN ('datetime2', 'datetimeoffset', 'time') THEN
                            '(' + CAST(t.scale AS VARCHAR(10)) + ')'
                        ELSE ''
                    END AS base_type,
                ep.value AS comment
            FROM sys.types t
            INNER JOIN sys.schemas s
                ON t.schema_id = s.schema_id
            CROSS APPLY (
                SELECT LOWER(TYPE_NAME(t.system_type_id)) AS base_name
            ) AS bt
            LEFT JOIN sys.extended_properties ep
                ON ep.major_id = t.user_type_id
                AND ep.minor_id = 0
                AND ep.name = 'MS_Description'
            WHERE s.name = ?
              AND t.is_user_defined = 1
              AND t.is_assembly_type = 0
              AND t.is_table_type = 0
            ORDER BY t.name
        """
        return (query, [schema])

    def supports_user_defined_types(self) -> bool:
        """SQL Server supports user-defined alias types."""
        return True

    def get_column_defaults_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Get column default values using SQL Server system tables.

        Use sys.default_constraints to get the actual default definitions.
        """
        query = """
            SELECT
                c.name AS column_name,
                dc.definition AS default_value
            FROM sys.columns c
            INNER JOIN sys.tables t ON c.object_id = t.object_id
            INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
            LEFT JOIN sys.default_constraints dc ON c.default_object_id = dc.object_id
            WHERE s.name = ? AND t.name = ?
            ORDER BY c.column_id
        """
        return (query, [schema, table])

    def get_partition_scheme_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Get partitioning scheme (partition function and columns).

        SQL Server partitioning uses:
        - Partition Function: Defines boundary values (RANGE LEFT/RIGHT)
        - Partition Scheme: Maps partitions to filegroups
        - Table uses partition scheme with partition column(s)

        Note: We only track the partitioning strategy, not individual partitions.
        """
        query = """
            SELECT
                pf.name AS partition_function,
                pf.type_desc AS partition_type,
                STRING_AGG(c.name, ',') AS partition_columns
            FROM sys.tables t
            INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
            INNER JOIN sys.indexes i ON t.object_id = i.object_id AND i.index_id IN (0, 1)
            INNER JOIN sys.partition_schemes ps ON i.data_space_id = ps.data_space_id
            INNER JOIN sys.partition_functions pf ON ps.function_id = pf.function_id
            INNER JOIN sys.index_columns ic ON i.object_id = ic.object_id AND i.index_id = ic.index_id
            INNER JOIN sys.columns c ON ic.object_id = c.object_id AND ic.column_id = c.column_id
            WHERE s.name = ?
                AND t.name = ?
                AND ic.partition_ordinal > 0
            GROUP BY pf.name, pf.type_desc
        """
        return (query, [schema, table])

    def supports_linked_servers(self) -> bool:
        """SQL Server supports linked server introspection."""
        return True

    def get_linked_servers_query(self) -> tuple[str, list]:
        """Get all linked servers defined on this SQL Server instance."""
        query = """
            SELECT
                name,
                product,
                provider,
                data_source,
                catalog
            FROM sys.servers
            WHERE is_linked = 1
            ORDER BY name
        """
        return (query, [])

    # ------------------------------------------------------------------
    # Structural metadata queries (Phase 4 — native driver support)
    # ------------------------------------------------------------------

    def get_tables_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return base-table names in *schema*.

        Expected result columns: ``table_name``.
        Uses ``sys.tables`` joined to ``sys.schemas`` for schema filtering.
        """
        query = """
            SELECT t.name AS table_name
            FROM sys.tables t
            JOIN sys.schemas s ON s.schema_id = t.schema_id
            WHERE s.name = ?
            ORDER BY t.name
        """
        return (query, [schema])

    def get_view_names_query(self, schema: str) -> tuple[str, List[Any]]:
        """Return view names in *schema*.

        Expected result columns: ``view_name``.
        Uses ``sys.views`` joined to ``sys.schemas`` for schema filtering.
        """
        query = """
            SELECT v.name AS view_name
            FROM sys.views v
            JOIN sys.schemas s ON s.schema_id = v.schema_id
            WHERE s.name = ?
            ORDER BY v.name
        """
        return (query, [schema])

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return columns for *table* in *schema* with PK detection.

        Expected result columns: ``column_name``, ``data_type``,
        ``is_nullable`` (bit), ``column_default`` (str | None),
        ``is_primary_key`` (bit), ``ordinal_position`` (int).

        Data type includes length/precision/scale suffix where applicable
        (e.g. ``varchar(100)``, ``decimal(10,2)``, ``nvarchar(MAX)``).
        PK detection uses ``sys.index_columns`` filtered to primary-key indexes.
        """
        query = """
            SELECT
                c.name                          AS column_name,
                tp.name
                    + CASE
                        WHEN tp.name IN ('varchar','nvarchar','char','nchar','varbinary','binary')
                            AND c.max_length <> -1
                            THEN '(' + CAST(
                                CASE WHEN tp.name LIKE 'n%'
                                    THEN c.max_length / 2
                                    ELSE c.max_length
                                END AS VARCHAR) + ')'
                        WHEN tp.name IN ('varchar','nvarchar','char','nchar','varbinary','binary')
                            AND c.max_length = -1  THEN '(MAX)'
                        WHEN tp.name IN ('decimal','numeric')
                            THEN '(' + CAST(c.precision AS VARCHAR)
                                 + ',' + CAST(c.scale AS VARCHAR) + ')'
                        ELSE ''
                    END                         AS data_type,
                c.is_nullable                   AS is_nullable,
                dc.definition                   AS column_default,
                CASE WHEN pk.column_id IS NOT NULL THEN 1 ELSE 0 END AS is_primary_key,
                c.column_id                     AS ordinal_position
            FROM sys.columns c
            JOIN sys.objects o ON o.object_id = c.object_id
                              AND o.type IN ('U', 'V')
            JOIN sys.schemas s ON s.schema_id = o.schema_id
            JOIN sys.types tp  ON tp.user_type_id = c.user_type_id
            LEFT JOIN sys.default_constraints dc ON dc.object_id = c.default_object_id
            LEFT JOIN (
                SELECT ic2.object_id, ic2.column_id
                FROM sys.indexes i2
                JOIN sys.index_columns ic2 ON ic2.object_id = i2.object_id
                                           AND ic2.index_id  = i2.index_id
                WHERE i2.is_primary_key = 1
            ) pk ON pk.object_id = c.object_id AND pk.column_id = c.column_id
            WHERE s.name = ? AND o.name = ?
            ORDER BY c.column_id
        """
        return (query, [schema, table])

    def get_primary_key_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return the primary-key constraint and its columns for *table*.

        Expected result columns: ``constraint_name``, ``column_name``
        (one row per PK column, ordered by ``key_ordinal``).
        Uses ``sys.key_constraints`` filtered to type ``'PK'``.
        """
        query = """
            SELECT
                kc.name      AS constraint_name,
                c.name       AS column_name
            FROM sys.key_constraints kc
            JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id
                                      AND ic.index_id  = kc.unique_index_id
            JOIN sys.columns c ON c.object_id = ic.object_id
                               AND c.column_id = ic.column_id
            JOIN sys.tables t  ON t.object_id  = kc.parent_object_id
            JOIN sys.schemas s ON s.schema_id  = t.schema_id
            WHERE s.name = ? AND t.name = ? AND kc.type = 'PK'
            ORDER BY ic.key_ordinal
        """
        return (query, [schema, table])

    def get_foreign_keys_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return foreign-key constraints for *table* in *schema*.

        Expected result columns: ``name``, ``column_name``,
        ``ref_schema``, ``ref_table``, ``ref_column``,
        ``on_delete``, ``on_update``.
        Multiple rows per FK (one per column); callers group by ``name``.

        Uses ``sys.foreign_key_columns`` for correct per-column pairing
        (avoids cross-product from joining ``sys.columns`` twice without
        the FK-column bridge table).
        """
        query = """
            SELECT
                fk.name                                         AS name,
                c_local.name                                    AS column_name,
                s_ref.name                                      AS ref_schema,
                t_ref.name                                      AS ref_table,
                c_ref.name                                      AS ref_column,
                CASE fk.delete_referential_action
                    WHEN 0 THEN 'NO ACTION' WHEN 1 THEN 'CASCADE'
                    WHEN 2 THEN 'SET NULL'  WHEN 3 THEN 'SET DEFAULT'
                END                                             AS on_delete,
                CASE fk.update_referential_action
                    WHEN 0 THEN 'NO ACTION' WHEN 1 THEN 'CASCADE'
                    WHEN 2 THEN 'SET NULL'  WHEN 3 THEN 'SET DEFAULT'
                END                                             AS on_update
            FROM sys.foreign_keys fk
            JOIN sys.foreign_key_columns fkc ON fkc.constraint_object_id = fk.object_id
            JOIN sys.tables t_local  ON t_local.object_id  = fk.parent_object_id
            JOIN sys.schemas s_local ON s_local.schema_id  = t_local.schema_id
            JOIN sys.columns c_local ON c_local.object_id  = fkc.parent_object_id
                                     AND c_local.column_id = fkc.parent_column_id
            JOIN sys.tables t_ref    ON t_ref.object_id    = fk.referenced_object_id
            JOIN sys.schemas s_ref   ON s_ref.schema_id    = t_ref.schema_id
            JOIN sys.columns c_ref   ON c_ref.object_id    = fkc.referenced_object_id
                                     AND c_ref.column_id   = fkc.referenced_column_id
            WHERE s_local.name = ? AND t_local.name = ?
            ORDER BY fk.name, fkc.constraint_column_id
        """
        return (query, [schema, table])

    def get_unique_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return unique constraints (not unique indexes) for *table* in *schema*.

        Expected result columns: ``name``, ``column_name``
        (one row per constraint column, ordered by ``key_ordinal``).
        Uses ``sys.key_constraints`` filtered to type ``'UQ'``.
        """
        query = """
            SELECT
                kc.name      AS name,
                c.name       AS column_name
            FROM sys.key_constraints kc
            JOIN sys.index_columns ic ON ic.object_id = kc.parent_object_id
                                      AND ic.index_id  = kc.unique_index_id
            JOIN sys.columns c ON c.object_id = ic.object_id
                               AND c.column_id = ic.column_id
            JOIN sys.tables t  ON t.object_id  = kc.parent_object_id
            JOIN sys.schemas s ON s.schema_id  = t.schema_id
            WHERE s.name = ? AND t.name = ? AND kc.type = 'UQ'
            ORDER BY kc.name, ic.key_ordinal
        """
        return (query, [schema, table])
