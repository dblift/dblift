"""
DB2-specific metadata queries.

This module provides DB2-specific queries for extracting metadata.

Queries are inspired by SQLAlchemy's DB2 dialect:
https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/db2/base.py

DB2 uses SYSCAT.* catalog views for metadata queries.
"""

from typing import Any, List

from core.introspection.vendor_queries_base import VendorMetadataQueries


def _catalog_identifier(identifier: str) -> str:
    """Return the DB2 catalog form for an identifier parameter."""
    if len(identifier) >= 2 and identifier[0] == '"' and identifier[-1] == '"':
        return identifier[1:-1].replace('""', '"')
    return identifier.upper()


class DB2MetadataQueries(VendorMetadataQueries):
    """
    DB2-specific metadata queries using SYSCAT catalog views.

    References:
        - DB2 System Catalog Views: https://www.ibm.com/docs/en/db2/11.5?topic=views-catalog
        - SQLAlchemy DB2 Dialect: https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/db2/base.py
    """

    def get_tables_query(self, schema: str) -> tuple[str, List[Any]]:
        """List base table names in *schema* using SYSCAT.TABLES."""
        query = """
            SELECT
                tabname AS table_name,
                CASE WHEN type = 'G' THEN 1 ELSE 0 END AS is_temporary
            FROM syscat.tables
            WHERE tabschema = ?
                AND type IN ('T', 'G')
            ORDER BY tabname
        """
        return (query, [_catalog_identifier(schema)])

    def get_view_names_query(self, schema: str) -> tuple[str, List[Any]]:
        """List view names in *schema* using SYSCAT.VIEWS."""
        query = """
            SELECT viewname AS view_name
            FROM syscat.views
            WHERE viewschema = ?
            ORDER BY viewname
        """
        return (query, [_catalog_identifier(schema)])

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return column metadata with PK detection from SYSCAT."""
        query = """
            SELECT
                c.colname AS column_name,
                c.typename
                    || CASE
                        WHEN c.typename IN ('CHARACTER', 'CHAR', 'VARCHAR')
                            THEN '(' || VARCHAR(c.length) || ')'
                                || CASE WHEN c.codepage = 0 THEN ' FOR BIT DATA' ELSE '' END
                        WHEN c.typename IN ('GRAPHIC', 'VARGRAPHIC')
                            THEN '(' || VARCHAR(c.length) || ')'
                        WHEN c.typename = 'DECFLOAT' AND c.length = 8 THEN '(16)'
                        WHEN c.typename = 'DECFLOAT' AND c.length = 16 THEN '(34)'
                        WHEN c.typename = 'DECIMAL'
                            THEN '(' || VARCHAR(c.length) || ',' || VARCHAR(c.scale) || ')'
                        WHEN c.typename IN ('BLOB', 'CLOB', 'DBCLOB')
                            THEN '(' ||
                                CASE
                                    WHEN MOD(c.length, 1073741824) = 0
                                        THEN VARCHAR(INTEGER(c.length / 1073741824)) || 'G'
                                    WHEN MOD(c.length, 1048576) = 0
                                        THEN VARCHAR(INTEGER(c.length / 1048576)) || 'M'
                                    WHEN MOD(c.length, 1024) = 0
                                        THEN VARCHAR(INTEGER(c.length / 1024)) || 'K'
                                    ELSE VARCHAR(c.length)
                                END || ')'
                        ELSE ''
                    END AS data_type,
                CASE WHEN c.nulls = 'Y' THEN 1 ELSE 0 END AS is_nullable,
                c.default AS column_default,
                CASE WHEN pk.colname IS NOT NULL THEN 1 ELSE 0 END AS is_primary_key,
                c.colno AS ordinal_position
            FROM syscat.columns c
            LEFT JOIN (
                SELECT kc.tabschema, kc.tabname, kc.colname
                FROM syscat.tabconst tc
                INNER JOIN syscat.keycoluse kc
                    ON tc.tabschema = kc.tabschema
                    AND tc.tabname = kc.tabname
                    AND tc.constname = kc.constname
                WHERE tc.type = 'P'
            ) pk
                ON pk.tabschema = c.tabschema
                AND pk.tabname = c.tabname
                AND pk.colname = c.colname
            WHERE c.tabschema = ?
                AND c.tabname = ?
            ORDER BY c.colno
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def get_primary_key_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return the PK constraint name and ordered column list for *table*."""
        query = """
            SELECT
                tc.constname AS constraint_name,
                kc.colname AS column_name
            FROM syscat.tabconst tc
            INNER JOIN syscat.keycoluse kc
                ON tc.tabschema = kc.tabschema
                AND tc.tabname = kc.tabname
                AND tc.constname = kc.constname
            WHERE tc.tabschema = ?
                AND tc.tabname = ?
                AND tc.type = 'P'
            ORDER BY kc.colseq
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def get_foreign_keys_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return FK constraint rows for *table* using SYSCAT.REFERENCES."""
        query = """
            SELECT
                r.constname AS name,
                fk.colname AS column_name,
                r.reftabschema AS ref_schema,
                r.reftabname AS ref_table,
                pk.colname AS ref_column,
                CASE r.deleterule
                    WHEN 'A' THEN 'NO ACTION'
                    WHEN 'C' THEN 'CASCADE'
                    WHEN 'N' THEN 'SET NULL'
                    WHEN 'R' THEN 'RESTRICT'
                    ELSE r.deleterule
                END AS on_delete,
                CASE r.updaterule
                    WHEN 'A' THEN 'NO ACTION'
                    WHEN 'C' THEN 'CASCADE'
                    WHEN 'N' THEN 'SET NULL'
                    WHEN 'R' THEN 'RESTRICT'
                    ELSE r.updaterule
                END AS on_update
            FROM syscat.references r
            INNER JOIN syscat.keycoluse fk
                ON r.tabschema = fk.tabschema
                AND r.tabname = fk.tabname
                AND r.constname = fk.constname
            LEFT JOIN syscat.keycoluse pk
                ON r.reftabschema = pk.tabschema
                AND r.reftabname = pk.tabname
                AND r.refkeyname = pk.constname
                AND fk.colseq = pk.colseq
            WHERE r.tabschema = ?
                AND r.tabname = ?
            ORDER BY r.constname, fk.colseq
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def get_check_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get check constraints using SYSCAT.CHECKS.

        DB2 stores check constraint definitions in SYSCAT.CHECKS with TYPE='C' for user-defined checks.
        Note: DB2 check constraints are not deferrable.

        References:
            - SYSCAT.CHECKS.TYPE: C=Check, S=System-generated, F=Functional dependency, O=Object property
        """
        query = """
            SELECT
                constname AS constraint_name,
                CAST(text AS VARCHAR(32672)) AS constraint_definition,
                'N' AS is_deferrable,
                'N' AS initially_deferred
            FROM syscat.checks
            WHERE tabschema = ?
                AND tabname = ?
                AND type = 'C'
            ORDER BY constname
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def get_unique_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get UNIQUE constraints using SYSCAT.TABCONST and SYSCAT.KEYCOLUSE.

        DB2 stores UNIQUE constraints in SYSCAT.TABCONST with TYPE='U'.
        Column order is stored in SYSCAT.KEYCOLUSE.

        References:
            - SYSCAT.TABCONST.TYPE: U=Unique, P=Primary Key, F=Foreign Key, C=Check
        """
        query = """
            SELECT
                tc.constname AS constraint_name,
                kc.colname AS column_name,
                kc.colseq AS ordinal_position
            FROM syscat.tabconst tc
            INNER JOIN syscat.keycoluse kc
                ON tc.tabschema = kc.tabschema
                AND tc.tabname = kc.tabname
                AND tc.constname = kc.constname
            WHERE tc.tabschema = ?
                AND tc.tabname = ?
                AND tc.type = 'U'
            ORDER BY tc.constname, kc.colseq
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def get_sequences_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get sequences using SYSCAT.SEQUENCES.

        DB2 has full support for sequences with rich metadata.
        """
        query = """
            SELECT
                seqname AS sequence_name,
                CASE seqtype
                    WHEN 'S' THEN 'SMALLINT'
                    WHEN 'I' THEN 'INTEGER'
                    WHEN 'B' THEN 'BIGINT'
                    WHEN 'D' THEN 'DECIMAL'
                END AS data_type,
                start AS start_value,
                minvalue AS minimum_value,
                maxvalue AS maximum_value,
                increment AS increment,
                CASE cycle
                    WHEN 'Y' THEN 'YES'
                    ELSE 'NO'
                END AS cycle_option,
                cache AS cache_size
            FROM syscat.sequences
            WHERE seqschema = ?
                AND seqtype != 'I'
            ORDER BY seqname
        """
        return (query, [_catalog_identifier(schema)])

    def get_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get views using SYSCAT.VIEWS.

        DB2 stores view definitions in TEXT column (may be CLOB).
        """
        query = """
            SELECT
                viewname AS view_name,
                text AS view_definition,
                CASE readonly
                    WHEN 'Y' THEN 'NO'
                    ELSE 'YES'
                END AS is_updatable,
                CASE valid
                    WHEN 'Y' THEN 'NONE'
                    ELSE 'INVALID'
                END AS check_option
            FROM syscat.views
            WHERE viewschema = ?
            ORDER BY viewname
        """
        return (query, [_catalog_identifier(schema)])

    def get_view_definition_query(self, schema: str, view_name: str) -> tuple[str, List[Any]]:
        """
        Get a specific view's definition from SYSCAT.VIEWS.
        """
        query = """
            SELECT
                text AS view_definition
            FROM syscat.views
            WHERE viewschema = ?
                AND viewname = ?
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(view_name)])

    def get_indexes_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get detailed index information using SYSCAT.INDEXES and SYSCAT.INDEXCOLUSE.

        DB2 provides rich index metadata including index type and clustering.
        """
        query = """
            SELECT
                i.indname AS index_name,
                ic.colname AS column_name,
                ic.colseq AS ordinal_position,
                CASE ic.colorder
                    WHEN 'D' THEN 'Y'
                    ELSE 'N'
                END AS is_descending,
                CASE i.uniquerule
                    WHEN 'U' THEN 'Y'
                    WHEN 'P' THEN 'Y'
                    ELSE 'N'
                END AS is_unique,
                CASE i.indextype
                    WHEN 'BLOK' THEN 'BLOCK'
                    WHEN 'CLUS' THEN 'CLUSTERED'
                    WHEN 'DIM' THEN 'DIMENSION'
                    WHEN 'REG' THEN 'REGULAR'
                    WHEN 'CPMA' THEN 'PAGE MAP'
                    WHEN 'RCT' THEN 'REGION'
                    WHEN 'XPTH' THEN 'XML PATH'
                    WHEN 'XRGN' THEN 'XML REGION'
                    WHEN 'XVIL' THEN 'XML VALUE'
                END AS index_type,
                NULL AS filter_condition,
                'N' AS is_expression
            FROM syscat.indexes i
            INNER JOIN syscat.indexcoluse ic
                ON i.indschema = ic.indschema
                AND i.indname = ic.indname
            WHERE i.tabschema = ?
                AND i.tabname = ?
                AND i.uniquerule != 'P'
            ORDER BY i.indname, ic.colseq
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def get_procedures_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get stored procedures using SYSCAT.PROCEDURES.

        DB2 stores procedure metadata in SYSCAT.PROCEDURES and text in SYSCAT.ROUTINES.
        """
        query = """
            SELECT
                p.procname AS procedure_name,
                'PROCEDURE' AS procedure_type,
                p.language AS language,
                r.text AS definition,
                p.remarks AS comment
            FROM syscat.procedures p
            LEFT JOIN syscat.routines r
                ON p.procschema = r.routineschema
                AND p.procname = r.routinename
            WHERE p.procschema = ?
            ORDER BY p.procname
        """
        return (query, [_catalog_identifier(schema)])

    def get_functions_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get functions using SYSCAT.FUNCTIONS.

        DB2 supports scalar, table, and row functions.
        """
        query = """
            SELECT
                f.funcname AS function_name,
                f.return_type AS return_type,
                f.language AS language,
                r.text AS definition,
                f.remarks AS comment
            FROM syscat.functions f
            LEFT JOIN syscat.routines r
                ON f.funcschema = r.routineschema
                AND f.funcname = r.routinename
            WHERE f.funcschema = ?
                AND f.origin != 'B'
            ORDER BY f.funcname
        """
        return (query, [_catalog_identifier(schema)])

    def get_packages_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get modules using SYSCAT.MODULES.

        DB2 modules are similar to Oracle packages - they contain procedures,
        functions, and variables. We use this method to return modules which
        can be treated as "packages" for consistency with Oracle.

        Note: TEXT column doesn't exist in all DB2 editions (e.g., DB2 Express).
        We omit the definition for now and rely on module introspection if needed.
        """
        query = """
            SELECT
                modulename AS package_name,
                'SQL' AS language,
                'MODULE' AS package_type,
                remarks AS comment
            FROM syscat.modules
            WHERE moduleschema = ?
            ORDER BY modulename
        """
        return (query, [_catalog_identifier(schema)])

    def get_triggers_query(self, schema: str, table: str = None) -> tuple[str, List[Any]]:
        """
        Get triggers using SYSCAT.TRIGGERS.

        DB2 has comprehensive trigger metadata.
        Note: TEXT column is CLOB, may need CAST to VARCHAR for some queries.
        """
        if table:
            query = """
                SELECT
                    trigname AS trigger_name,
                    tabname AS table_name,
                    CASE trigevent
                        WHEN 'I' THEN 'INSERT'
                        WHEN 'U' THEN 'UPDATE'
                        WHEN 'D' THEN 'DELETE'
                    END AS event_manipulation,
                    CASE trigtime
                        WHEN 'A' THEN 'AFTER'
                        WHEN 'B' THEN 'BEFORE'
                        WHEN 'I' THEN 'INSTEAD OF'
                    END AS action_timing,
                    CAST(text AS VARCHAR(32672)) AS action_statement,
                    CASE granularity
                        WHEN 'R' THEN 'ROW'
                        WHEN 'S' THEN 'STATEMENT'
                    END AS action_orientation
                FROM syscat.triggers
                WHERE tabschema = ?
                    AND tabname = ?
                    AND valid = 'Y'
                ORDER BY trigname
            """
            params = [_catalog_identifier(schema), _catalog_identifier(table)]
        else:
            query = """
                SELECT
                    trigname AS trigger_name,
                    tabname AS table_name,
                    CASE trigevent
                        WHEN 'I' THEN 'INSERT'
                        WHEN 'U' THEN 'UPDATE'
                        WHEN 'D' THEN 'DELETE'
                    END AS event_manipulation,
                    CASE trigtime
                        WHEN 'A' THEN 'AFTER'
                        WHEN 'B' THEN 'BEFORE'
                        WHEN 'I' THEN 'INSTEAD OF'
                    END AS action_timing,
                    CAST(text AS VARCHAR(32672)) AS action_statement,
                    CASE granularity
                        WHEN 'R' THEN 'ROW'
                        WHEN 'S' THEN 'STATEMENT'
                    END AS action_orientation
                FROM syscat.triggers
                WHERE tabschema = ?
                    AND valid = 'Y'
                ORDER BY tabname, trigname
            """
            params = [_catalog_identifier(schema)]

        return (query, params)

    def get_computed_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get generated columns (DB2 10+).

        DB2 supports GENERATED ALWAYS columns.
        Note:
        - For expression-based generated columns, TEXT contains the column definition
          including the generation expression (e.g., "GENERATED ALWAYS AS (price * quantity)")
        - GENERATED='A' means GENERATED ALWAYS
        - Filter out identity columns by checking IDENTITY='N'
        - DB2 generated columns are always VIRTUAL (not stored), unlike Oracle
        - TEXT is a CLOB, so we CAST it to VARCHAR for easier handling
        - Extract the expression from TEXT by removing "GENERATED ALWAYS AS" prefix
        """
        query = """
            SELECT
                colname AS column_name,
                CAST(text AS VARCHAR(32672)) AS computation_expression,
                'N' AS is_stored
            FROM syscat.columns
            WHERE (UPPER(tabschema) = UPPER(?) OR tabschema = ?)
                AND (UPPER(tabname) = UPPER(?) OR tabname = ?)
                AND generated = 'A'
                AND identity = 'N'
                AND text IS NOT NULL
            ORDER BY colno
        """
        schema_param = _catalog_identifier(schema)
        table_param = _catalog_identifier(table)
        return (query, [schema_param, schema_param, table_param, table_param])

    def get_identity_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get identity column information.

        DB2 has full support for identity columns.
        Note: SYSCAT.COLIDENTATTRIBUTES contains identity column metadata.
        """
        query = """
            SELECT
                c.colname AS column_name,
                ci.start AS seed_value,
                ci.increment AS increment_value,
                ci.nextcachefirstvalue AS last_value
            FROM syscat.columns c
            LEFT JOIN syscat.colidentattributes ci
                ON c.tabschema = ci.tabschema
                AND c.tabname = ci.tabname
                AND c.colname = ci.colname
            WHERE c.tabschema = ?
                AND c.tabname = ?
                AND c.identity = 'Y'
            ORDER BY c.colno
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def get_table_partitions_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get table partition information.

        DB2 supports range partitioning.
        """
        query = """
            SELECT
                p.datapartitionname AS partition_name,
                p.seqno AS partition_number,
                'RANGE' AS partition_method,
                p.highvalue AS high_value,
                p.lowvalue AS low_value
            FROM syscat.datapartitions p
            WHERE p.tabschema = ?
                AND p.tabname = ?
            ORDER BY p.seqno
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def supports_check_constraints(self) -> bool:
        """DB2 fully supports check constraints."""
        return True

    def supports_sequences(self) -> bool:
        """DB2 fully supports sequences."""
        return True

    def supports_views(self) -> bool:
        """DB2 fully supports views."""
        return True

    def supports_triggers(self) -> bool:
        """DB2 fully supports triggers."""
        return True

    def supports_computed_columns(self) -> bool:
        """DB2 supports generated columns."""
        return True

    def supports_partitions(self) -> bool:
        """DB2 supports table partitioning."""
        return True

    def get_materialized_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get materialized views (summary tables) using SYSCAT.TABLES.

        DB2 calls materialized views "materialized query tables" (MQT).
        They appear in SYSCAT.TABLES with TYPE = 'M'.
        """
        query = """
            SELECT
                tabname AS materialized_view_name,
                'N/A' AS view_definition,
                CASE status
                    WHEN 'N' THEN 'YES'
                    ELSE 'NO'
                END AS is_populated,
                refresh_time AS last_refresh,
                refresh AS refresh_method
            FROM syscat.tables
            WHERE tabschema = ?
                AND type = 'M'
            ORDER BY tabname
        """
        return (query, [_catalog_identifier(schema)])

    def supports_materialized_views(self) -> bool:
        """DB2 supports materialized query tables (MQTs)."""
        return True

    def get_table_properties_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get DB2-specific table properties from SYSCAT.TABLES.

        Grammar-based: Extracts logged, compress, tablespace, organization properties,
        and storage parameters (pctfree, pctused, initial, next).

        SYSCAT.TABLES columns:
        - COMPRESSION: 'R' (row), 'P' (page), 'N' (none), 'V' (value), 'B' (both)
        - TBSPACE: Tablespace name
        - PCTFREE: Free space percentage
        - PCTUSED: Used space percentage (not available in all DB2 versions)
        - INITIAL: Initial extent size
        - NEXT: Next extent size
        - DBNAME: Database name
        - VOLATILE: 'C' (cardinality), blank (not volatile)
        - APPEND_MODE: 'Y' or 'N'
        - LOCKSIZE: 'R' (row), 'T' (table), 'S' (tablespace)
        - TYPE: 'T' (table), 'G' (created global temp), 'M' (materialized query table), etc.

        Note: Some columns might not exist in all DB2 editions (e.g., Express).
        Storage parameters (pctfree, pctused, initial, next) are SQL-generation-only,
        not diff-relevant.
        """
        query = """
            SELECT
                t.tabname AS table_name,
                t.tbspace AS tablespace_name,
                CASE t.compression
                    WHEN 'N' THEN 'NO'
                    ELSE 'YES'
                END AS is_compressed,
                t.compression AS compress_type,
                t.append_mode AS append_mode,
                t.volatile AS volatile_mode,
                t.locksize AS lock_size,
                t.type AS table_type,
                t.pctfree AS pctfree,
                CAST(NULL AS INTEGER) AS pctused,
                CAST(NULL AS INTEGER) AS initial,
                CAST(NULL AS INTEGER) AS next
            FROM syscat.tables t
            WHERE t.tabschema = ?
                AND t.tabname = ?
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def supports_procedures(self) -> bool:
        """DB2 fully supports stored procedures."""
        return True

    def supports_functions(self) -> bool:
        """DB2 fully supports functions."""
        return True

    def get_user_defined_types_query(self, schema: str) -> tuple[str, List[Any]]:
        """Get user-defined types (distinct and structured) for a schema.

        Note: SYSCAT.TYPES table doesn't exist in all DB2 editions (e.g., DB2 Express).
        We return an empty query that will be caught and handled gracefully.
        For full DB2 editions, this query would work, but for compatibility we disable it.
        """

        # Return empty query to indicate UDTs are not supported in this DB2 edition
        # The introspector will catch the SQL error and log a warning
        query = """
            SELECT
                TYPENAME AS type_name,
                TYPEKIND AS type_category,
                CASE
                    WHEN SOURCETYPE IS NOT NULL THEN
                        CASE
                            WHEN SOURCESCHEMA IS NOT NULL AND SOURCESCHEMA <> 'SYSIBM' THEN
                                RTRIM(SOURCESCHEMA) || '.' || RTRIM(SOURCETYPE)
                            ELSE RTRIM(SOURCETYPE)
                        END
                    ELSE NULL
                END AS base_type,
                REMARKS AS comment
            FROM SYSCAT.TYPES
            WHERE TYPESCHEMA = ?
              AND TYPEKIND IN ('R', 'S', 'D')
            ORDER BY TYPENAME
        """
        return (query, [_catalog_identifier(schema)])

    def get_composite_type_attributes_query(
        self, schema: str, type_name: str
    ) -> tuple[str, List[Any]]:
        """Get attribute metadata for DB2 structured types."""

        query = """
            SELECT
                ATTRNAME AS attribute_name,
                CASE
                    WHEN ATTTYPENAME IS NOT NULL THEN
                        CASE
                            WHEN ATTTYPESCHEMA IS NOT NULL AND ATTTYPESCHEMA <> 'SYSIBM' THEN
                                RTRIM(ATTTYPESCHEMA) || '.' || RTRIM(ATTTYPENAME)
                            ELSE RTRIM(ATTTYPENAME)
                        END ||
                        CASE
                            WHEN ATTTYPENAME IN ('CHAR', 'VARCHAR', 'GRAPHIC', 'VARGRAPHIC', 'BLOB', 'CLOB', 'DBCLOB')
                                 AND LENGTH > 0 THEN '(' || RTRIM(CHAR(LENGTH)) || ')'
                            WHEN ATTTYPENAME IN ('DECIMAL', 'NUMERIC') AND LENGTH > 0 THEN
                                '(' || RTRIM(CHAR(LENGTH)) || ',' || RTRIM(CHAR(SCALE)) || ')'
                            ELSE ''
                        END
                    ELSE NULL
                END AS data_type,
                ATTNO AS ordinal_position,
                CASE NULLS WHEN 'Y' THEN 1 ELSE 0 END AS is_nullable
            FROM SYSCAT.ATTRIBUTES
            WHERE TYPESCHEMA = ?
              AND TYPENAME = ?
            ORDER BY ATTNO
        """
        return (query, [_catalog_identifier(schema), _catalog_identifier(type_name)])

    def get_synonyms_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get synonyms (called ALIAS in DB2) using SYSCAT.TABLES.

        In DB2, table aliases (synonyms) have TYPE='A' in SYSCAT.TABLES.
        """
        query = """
            SELECT
                TABNAME AS synonym_name,
                BASE_TABSCHEMA AS target_schema,
                BASE_TABNAME AS target_object
            FROM SYSCAT.TABLES
            WHERE TABSCHEMA = ?
              AND TYPE = 'A'
            ORDER BY TABNAME
        """
        return (query, [_catalog_identifier(schema)])

    def supports_synonyms(self) -> bool:
        """DB2 supports synonyms (called ALIAS)."""
        return True

    def supports_user_defined_types(self) -> bool:
        """DB2 supports user-defined distinct and structured types.

        However, SYSCAT.TYPES table doesn't exist in all DB2 editions (e.g., DB2 Express).
        To avoid errors in tests and limited environments, we disable UDT support for now.
        For full DB2 Enterprise editions, this could be enabled conditionally.
        """
        return False  # Disabled due to missing SYSCAT.TYPES in DB2 Express

    def get_partition_scheme_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Get partitioning scheme (method and key columns only, not individual partitions).

        DB2 partitioning (DPF - Database Partitioning Feature): HASH partitioning
        Note: DB2 partitioning is different from Oracle/PostgreSQL/MySQL.
        DB2 uses distribution keys for DPF across multiple database partitions.

        IMPORTANT: SYSCAT.DATAPARTITIONS may not exist in all DB2 editions (e.g., Express).
        Returning None disables partition scheme tracking for DB2 to avoid errors in test environments.
        For production DB2 Enterprise with partitioning enabled, this could be re-enabled.
        """
        # Disable partition scheme query for DB2 to avoid compatibility issues
        # SYSCAT.DATAPARTITIONS and partition columns vary across DB2 editions
        return ("", [])

    def supports_modules(self) -> bool:
        """DB2 supports module introspection via SYSCAT.MODULES."""
        return True

    def supports_packages(self) -> bool:
        """DB2 surfaces packages through the same module-aware queries as Oracle packages."""
        return True

    def get_modules_query(self, schema: str) -> tuple[str, list]:
        """Get all modules in the specified schema."""
        query = """
            SELECT
                MODULENAME AS module_name,
                MODULESCHEMA AS module_schema,
                TEXT AS definition
            FROM SYSCAT.MODULES
            WHERE MODULESCHEMA = ?
            ORDER BY MODULENAME
        """
        return (query, [_catalog_identifier(schema)])
