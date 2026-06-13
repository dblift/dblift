"""
Oracle-specific metadata queries.

This module provides Oracle-specific queries for extracting metadata
from Oracle data dictionary views.

Queries are inspired by SQLAlchemy's Oracle dialect:
https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/oracle/base.py

Oracle uses data dictionary views (USER_*, ALL_*, DBA_*) for metadata queries.
We primarily use USER_* views for simplicity (current schema).
"""

from typing import Any, List, Tuple

from core.introspection.vendor_queries_base import VendorMetadataQueries


def _catalog_identifier(identifier: str) -> str:
    """Return the catalog value represented by an optional quoted identifier."""
    if len(identifier) >= 2 and identifier[0] == '"' and identifier[-1] == '"':
        return identifier[1:-1].replace('""', '"')
    return identifier


def _table_name_predicate(alias: str, table: str) -> str:
    """Return exact or case-insensitive table predicate for catalog queries."""
    if len(table) >= 2 and table[0] == '"' and table[-1] == '"':
        return f"{alias}.table_name = ?"
    return f"UPPER({alias}.table_name) = UPPER(?)"


def _constraint_state_columns(alias: str) -> str:
    """Project Oracle constraint state columns used by SqlConstraint."""
    return f"""
                CASE {alias}.deferrable
                    WHEN 'DEFERRABLE' THEN 'Y'
                    ELSE 'N'
                END AS is_deferrable,
                CASE {alias}.deferred
                    WHEN 'DEFERRED' THEN 'Y'
                    ELSE 'N'
                END AS initially_deferred,
                CASE {alias}.status
                    WHEN 'ENABLED' THEN 'Y'
                    ELSE 'N'
                END AS is_enabled,
                CASE {alias}.validated
                    WHEN 'VALIDATED' THEN 'Y'
                    ELSE 'N'
                END AS is_validated"""


class OracleMetadataQueries(VendorMetadataQueries):
    """
    Oracle-specific metadata queries using data dictionary views.

    References:
        - Oracle Data Dictionary Views: https://docs.oracle.com/en/database/oracle/oracle-database/19/refrn/
        - SQLAlchemy Oracle Dialect: https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/oracle/base.py
    """

    def get_tables_query(self, schema: str) -> tuple[str, List[Any]]:
        """List base table names in *schema* using ALL_TABLES."""
        query = """
            SELECT
                t.table_name,
                CASE WHEN t.temporary = 'Y' THEN 1 ELSE 0 END AS is_temporary,
                t.duration AS temporary_duration
            FROM all_tables t
            WHERE UPPER(t.owner) = UPPER(?)
                AND t.table_name NOT LIKE 'BIN$%'
                AND t.table_name NOT LIKE 'MLOG$%'
                AND t.table_name NOT LIKE 'RUPD$%'
                AND t.table_name NOT LIKE 'MVIEW$_%'
                AND t.table_name NOT LIKE 'MVW$_%'
                AND t.table_name NOT LIKE 'I_SNAP$%'
                AND t.table_name NOT LIKE 'SNAP$%'
                AND t.table_name NOT LIKE 'AQ$%'
                AND t.table_name NOT LIKE 'DR$%'
                AND NOT EXISTS (
                    SELECT 1
                    FROM all_mviews mv
                    WHERE mv.owner = t.owner
                        AND mv.mview_name = t.table_name
                )
            ORDER BY t.table_name
        """
        return (query, [schema])

    def get_view_names_query(self, schema: str) -> tuple[str, List[Any]]:
        """List view names in *schema* using ALL_VIEWS."""
        query = """
            SELECT view_name
            FROM all_views
            WHERE UPPER(owner) = UPPER(?)
                AND view_name NOT LIKE 'BIN$%'
            ORDER BY view_name
        """
        return (query, [schema])

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return column metadata for tables and views using ALL_TAB_COLS."""
        table_predicate = _table_name_predicate("c", table)
        query = """
            SELECT
                c.column_name,
                c.data_type
                    || CASE
                        WHEN c.data_type IN ('CHAR', 'NCHAR', 'VARCHAR2', 'NVARCHAR2')
                            AND c.char_used = 'C'
                            THEN '(' || TO_CHAR(c.char_length) || ' CHAR)'
                        WHEN c.data_type IN ('CHAR', 'NCHAR', 'VARCHAR2', 'NVARCHAR2')
                            THEN '(' || TO_CHAR(c.data_length) || ')'
                        WHEN c.data_type = 'RAW'
                            THEN '(' || TO_CHAR(c.data_length) || ')'
                        WHEN c.data_type = 'NUMBER' AND c.data_precision IS NOT NULL
                            THEN '(' || TO_CHAR(c.data_precision)
                                || NVL2(c.data_scale, ',' || TO_CHAR(c.data_scale), '') || ')'
                        WHEN c.data_type = 'NUMBER' AND c.data_precision IS NULL
                            AND c.data_scale IS NOT NULL
                            THEN '(*,' || TO_CHAR(c.data_scale) || ')'
                        WHEN c.data_type = 'FLOAT' AND c.data_precision IS NOT NULL
                            THEN '(' || TO_CHAR(c.data_precision) || ')'
                        ELSE ''
                    END AS data_type,
                CASE c.nullable WHEN 'Y' THEN 1 ELSE 0 END AS is_nullable,
                CASE WHEN pk.column_name IS NOT NULL THEN 1 ELSE 0 END AS is_primary_key,
                c.column_id AS ordinal_position,
                c.data_default AS column_default
            FROM all_tab_cols c
            LEFT JOIN (
                SELECT cc.owner, cc.table_name, cc.column_name
                FROM all_constraints con
                INNER JOIN all_cons_columns cc
                    ON con.owner = cc.owner
                    AND con.constraint_name = cc.constraint_name
                    AND con.table_name = cc.table_name
                WHERE con.constraint_type = 'P'
            ) pk
                ON pk.owner = c.owner
                AND pk.table_name = c.table_name
                AND pk.column_name = c.column_name
            WHERE UPPER(c.owner) = UPPER(?)
                AND {table_predicate}
                AND c.hidden_column = 'NO'
            ORDER BY c.column_id
        """.format(table_predicate=table_predicate)
        return (query, [schema, _catalog_identifier(table)])

    def get_primary_key_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return the PK constraint name and ordered column list for *table*."""
        table_predicate = _table_name_predicate("con", table)
        state_columns = _constraint_state_columns("con")
        query = """
            SELECT
                con.constraint_name,
                cc.column_name,
{state_columns}
            FROM all_constraints con
            INNER JOIN all_cons_columns cc
                ON con.owner = cc.owner
                AND con.constraint_name = cc.constraint_name
                AND con.table_name = cc.table_name
            WHERE UPPER(con.owner) = UPPER(?)
                AND {table_predicate}
                AND con.constraint_type = 'P'
            ORDER BY cc.position
        """.format(
            state_columns=state_columns,
            table_predicate=table_predicate,
        )
        return (query, [schema, _catalog_identifier(table)])

    def get_foreign_keys_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return FK constraint rows for *table* using ALL_CONSTRAINTS."""
        table_predicate = _table_name_predicate("fk_con", table)
        state_columns = _constraint_state_columns("fk_con")
        query = """
            SELECT
                fk_con.constraint_name AS name,
                fk_col.column_name,
                pk_con.owner AS ref_schema,
                pk_con.table_name AS ref_table,
                pk_col.column_name AS ref_column,
                fk_con.delete_rule AS on_delete,
                NULL AS on_update,
{state_columns}
            FROM all_constraints fk_con
            INNER JOIN all_cons_columns fk_col
                ON fk_con.owner = fk_col.owner
                AND fk_con.constraint_name = fk_col.constraint_name
                AND fk_con.table_name = fk_col.table_name
            INNER JOIN all_constraints pk_con
                ON fk_con.r_owner = pk_con.owner
                AND fk_con.r_constraint_name = pk_con.constraint_name
            INNER JOIN all_cons_columns pk_col
                ON pk_con.owner = pk_col.owner
                AND pk_con.constraint_name = pk_col.constraint_name
                AND pk_con.table_name = pk_col.table_name
                AND fk_col.position = pk_col.position
            WHERE UPPER(fk_con.owner) = UPPER(?)
                AND {table_predicate}
                AND fk_con.constraint_type = 'R'
            ORDER BY fk_con.constraint_name, fk_col.position
        """.format(
            state_columns=state_columns,
            table_predicate=table_predicate,
        )
        return (query, [schema, _catalog_identifier(table)])

    def get_unique_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return unique constraints for *table* using ALL_CONSTRAINTS."""
        table_predicate = _table_name_predicate("con", table)
        state_columns = _constraint_state_columns("con")
        query = """
            SELECT
                con.constraint_name,
                cc.column_name,
{state_columns}
            FROM all_constraints con
            INNER JOIN all_cons_columns cc
                ON con.owner = cc.owner
                AND con.constraint_name = cc.constraint_name
                AND con.table_name = cc.table_name
            WHERE UPPER(con.owner) = UPPER(?)
                AND {table_predicate}
                AND con.constraint_type = 'U'
            ORDER BY con.constraint_name, cc.position
        """.format(
            state_columns=state_columns,
            table_predicate=table_predicate,
        )
        return (query, [schema, _catalog_identifier(table)])

    def get_check_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get check constraints using ALL_CONSTRAINTS and ALL_CONS_COLUMNS.

        Oracle stores check constraint definitions in SEARCH_CONDITION column (type LONG).

        LONG column compatibility notes (applies to ALL Oracle versions):
        - SUBSTR() on a LONG column causes ORA-00932 — do not use NVL/SUBSTR workarounds
        - LONG columns cannot be used in WHERE clause predicates (IS NOT NULL → ORA-00932)
        - LONG columns must appear LAST in the SELECT list for Oracle driver compatibility
        - NULL filtering is handled in Python (see constraint_extractor.get_check_constraints)
        """
        table_predicate = _table_name_predicate("c", table)
        query = """
            SELECT
                c.constraint_name,
                CASE c.deferrable
                    WHEN 'DEFERRABLE' THEN 'Y'
                    ELSE 'N'
                END AS is_deferrable,
                CASE c.deferred
                    WHEN 'DEFERRED' THEN 'Y'
                    ELSE 'N'
                END AS initially_deferred,
                CASE c.status
                    WHEN 'ENABLED' THEN 'Y'
                    ELSE 'N'
                END AS is_enabled,
                CASE c.validated
                    WHEN 'VALIDATED' THEN 'Y'
                    ELSE 'N'
                END AS is_validated,
                c.generated AS generated,
                c.search_condition AS constraint_definition
            FROM all_constraints c
            WHERE UPPER(c.owner) = UPPER(?)
                AND {table_predicate}
                AND c.constraint_type = 'C'
            ORDER BY c.constraint_name
        """.format(table_predicate=table_predicate)
        return (query, [schema, _catalog_identifier(table)])

    def get_sequences_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get sequences using ALL_SEQUENCES.

        Oracle sequences have rich metadata including cache and cycle options.
        """
        query = (
            "SELECT sequence_name, min_value, max_value, increment_by, cycle_flag, cache_size, last_number "
            "FROM ALL_SEQUENCES WHERE UPPER(sequence_owner) = UPPER(?) ORDER BY sequence_name"
        )
        return (query, [schema])

    def get_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get views using ALL_VIEWS.

        Oracle stores view definitions in TEXT column (may be LONG type).

        Grammar-based: Added FORCE/NOFORCE detection via ALL_VIEWS view_type.
        Note: FORCE/NOFORCE is not directly stored in ALL_VIEWS, but we can infer
        from view definition or check if view can be created with errors.
        """
        # Use exact case matching to prevent incorrect matches
        query = """
            SELECT
                view_name,
                text AS view_definition,
                CASE read_only
                    WHEN 'Y' THEN 'NO'
                    ELSE 'YES'
                END AS is_updatable,
                'NONE' AS check_option,
                view_type
            FROM all_views
            WHERE UPPER(owner) = UPPER(?)
                AND view_name NOT LIKE 'BIN$%'
            ORDER BY view_name
        """
        return (query, [schema])

    def get_view_definition_query(self, schema: str, view_name: str) -> tuple[str, List[Any]]:
        """
        Get a specific view's definition from ALL_VIEWS.
        """
        # Use exact case matching to prevent incorrect matches
        query = """
            SELECT
                text AS view_definition
            FROM all_views
            WHERE UPPER(owner) = UPPER(?)
                AND UPPER(view_name) = UPPER(?)
        """
        return (query, [schema, view_name])

    def get_indexes_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get detailed index information using ALL_INDEXES and ALL_IND_COLUMNS.

        Includes index type, function-based indexes, and partitioned indexes.
        Note: Avoids COLUMN_EXPRESSION which may not be available in all Oracle editions.

        Grammar-based: Added TABLESPACE extraction.
        """
        table_predicate = _table_name_predicate("i", table)
        query = """
            SELECT
                i.index_name,
                ic.column_name,
                ic.column_position AS ordinal_position,
                CASE ic.descend
                    WHEN 'DESC' THEN 'Y'
                    ELSE 'N'
                END AS is_descending,
                CASE i.uniqueness
                    WHEN 'UNIQUE' THEN 'Y'
                    ELSE 'N'
                END AS is_unique,
                i.index_type,
                NULL AS filter_condition,
                CASE
                    WHEN ie.column_expression IS NOT NULL THEN 'Y'
                    ELSE 'N'
                END AS is_expression,
                ie.column_expression AS index_expression,
                COALESCE(i.tablespace_name, pi.def_tablespace_name, ip.partition_tablespace) AS tablespace,
                pi.locality AS locality,
                CASE
                    WHEN i.index_type = 'DOMAIN' THEN DBMS_METADATA.GET_DDL('INDEX', i.index_name, i.owner)
                    ELSE NULL
                END AS definition
            FROM all_indexes i
            INNER JOIN all_ind_columns ic
                ON i.owner = ic.index_owner
                AND i.index_name = ic.index_name
            LEFT JOIN all_ind_expressions ie
                ON ie.index_owner = ic.index_owner
                AND ie.index_name = ic.index_name
                AND ie.column_position = ic.column_position
            LEFT JOIN all_part_indexes pi
                ON pi.owner = i.owner
                AND pi.index_name = i.index_name
            LEFT JOIN (
                SELECT
                    index_owner,
                    index_name,
                    MAX(tablespace_name) AS partition_tablespace
                FROM all_ind_partitions
                GROUP BY index_owner, index_name
            ) ip
                ON ip.index_owner = i.owner
                AND ip.index_name = i.index_name
            WHERE UPPER(i.table_owner) = UPPER(?)
                AND {table_predicate}
                AND i.index_type != 'LOB'
            ORDER BY i.index_name, ic.column_position
        """.format(table_predicate=table_predicate)
        return (query, [schema, _catalog_identifier(table)])

    def get_triggers_query(self, schema: str, table: str = None) -> tuple[str, List[Any]]:
        """
        Get triggers using ALL_TRIGGERS.

        Oracle has rich trigger metadata including timing and event information.
        """
        if table:
            table_predicate = _table_name_predicate("", table).replace(".table_name", "table_name")
            query = """
                SELECT
                    trigger_name,
                    table_name,
                    triggering_event AS event_manipulation,
                    CASE trigger_type
                        WHEN 'BEFORE EACH ROW' THEN 'BEFORE'
                        WHEN 'AFTER EACH ROW' THEN 'AFTER'
                        WHEN 'INSTEAD OF' THEN 'INSTEAD OF'
                        WHEN 'BEFORE STATEMENT' THEN 'BEFORE'
                        WHEN 'AFTER STATEMENT' THEN 'AFTER'
                        ELSE trigger_type
                    END AS action_timing,
                    trigger_body AS action_statement,
                    CASE
                        WHEN trigger_type LIKE '%EACH ROW%' THEN 'ROW'
                        ELSE 'STATEMENT'
                    END AS action_orientation
                FROM all_triggers
                WHERE UPPER(owner) = UPPER(?)
                    AND {table_predicate}
                ORDER BY trigger_name
            """.format(table_predicate=table_predicate)
            params = [schema, _catalog_identifier(table)]
        else:
            query = """
                SELECT
                    trigger_name,
                    table_name,
                    triggering_event AS event_manipulation,
                    CASE trigger_type
                        WHEN 'BEFORE EACH ROW' THEN 'BEFORE'
                        WHEN 'AFTER EACH ROW' THEN 'AFTER'
                        WHEN 'INSTEAD OF' THEN 'INSTEAD OF'
                        WHEN 'BEFORE STATEMENT' THEN 'BEFORE'
                        WHEN 'AFTER STATEMENT' THEN 'AFTER'
                        ELSE trigger_type
                    END AS action_timing,
                    trigger_body AS action_statement,
                    CASE
                        WHEN trigger_type LIKE '%EACH ROW%' THEN 'ROW'
                        ELSE 'STATEMENT'
                    END AS action_orientation
                FROM all_triggers
                WHERE UPPER(owner) = UPPER(?)
                ORDER BY table_name, trigger_name
            """
            params = [schema]

        return (query, params)

    def get_computed_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get virtual columns (Oracle's computed columns).

        Oracle virtual columns are defined in ALL_TAB_COLS. The expression is kept
        in DATA_DEFAULT (LONG type). DATA_DEFAULT_VC (VARCHAR2) exists from 12.2+ only.

        LONG column compatibility: place DATA_DEFAULT LAST in SELECT; do not use
        SUBSTR() on LONG (causes ORA-00932 on all Oracle versions).
        """
        table_predicate = _table_name_predicate("", table).replace(".table_name", "table_name")
        query = """
            SELECT
                column_name,
                CASE virtual_column
                    WHEN 'YES' THEN 'N'
                    ELSE 'Y'
                END AS is_stored,
                data_default AS computation_expression
            FROM all_tab_cols
            WHERE UPPER(owner) = UPPER(?)
                AND {table_predicate}
                AND virtual_column = 'YES'
            ORDER BY column_id
        """.format(table_predicate=table_predicate)
        return (query, [schema, _catalog_identifier(table)])

    def get_identity_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get identity column information (Oracle 12c+).

        Oracle 12c introduced identity columns similar to SQL standard.
        """
        table_predicate = _table_name_predicate("ic", table)
        query = """
            SELECT
                c.column_name,
                REGEXP_SUBSTR(ic.identity_options, 'START WITH: ([^,]+)', 1, 1, NULL, 1)
                    AS seed_value,
                REGEXP_SUBSTR(ic.identity_options, 'INCREMENT BY: ([^,]+)', 1, 1, NULL, 1)
                    AS increment_value,
                NULL AS last_value
            FROM all_tab_identity_cols ic
            INNER JOIN all_tab_cols c
                ON ic.owner = c.owner
                AND ic.table_name = c.table_name
                AND ic.column_name = c.column_name
            WHERE UPPER(ic.owner) = UPPER(?)
                AND {table_predicate}
            ORDER BY c.column_id
        """.format(table_predicate=table_predicate)
        return (query, [schema, _catalog_identifier(table)])

    def get_table_partitions_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get table partition information.

        Oracle has sophisticated partitioning with RANGE, LIST, HASH, and composite methods.
        """
        t_table_predicate = _table_name_predicate("t", table)
        p_table_predicate = _table_name_predicate("p", table)
        query = """
            SELECT
                main.partition_name,
                main.partition_method,
                main.partition_position,
                p.high_value,
                main.partition_expression
            FROM (
                SELECT
                    p.partition_name,
                    t.partitioning_type AS partition_method,
                    p.partition_position,
                    LISTAGG(tc.column_name, ', ') WITHIN GROUP (ORDER BY tc.column_position)
                        AS partition_expression
                FROM all_tab_partitions p
                INNER JOIN all_part_tables t
                    ON p.table_owner = t.owner
                    AND p.table_name = t.table_name
                LEFT JOIN all_part_key_columns tc
                    ON t.owner = tc.owner
                    AND t.table_name = tc.name
                WHERE UPPER(t.owner) = UPPER(?)
                    AND {t_table_predicate}
                GROUP BY p.partition_name, t.partitioning_type, p.partition_position
            ) main
            LEFT JOIN all_tab_partitions p
                ON main.partition_name = p.partition_name
                AND UPPER(p.table_owner) = UPPER(?)
                AND {p_table_predicate}
            ORDER BY main.partition_position
        """.format(
            t_table_predicate=t_table_predicate,
            p_table_predicate=p_table_predicate,
        )
        table_param = _catalog_identifier(table)
        return (query, [schema, table_param, schema, table_param])

    def get_procedures_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get stored procedures using ALL_OBJECTS.

        Oracle stores procedure definitions in ALL_SOURCE. For simplicity,
        we extract procedure names and metadata without concatenating the full
        source code (which can be retrieved separately if needed).
        """
        query = """
            SELECT
                obj.object_name AS procedure_name,
                obj.object_type AS procedure_type,
                'PLSQL' AS language,
                (
                    SELECT COALESCE(
                        XMLAGG(
                            XMLELEMENT(e, src.text) ORDER BY src.line
                        ).getClobVal(),
                        TO_CLOB('')
                    )
                    FROM all_source src
                    WHERE src.owner = obj.owner
                      AND src.name = obj.object_name
                      AND src.type = obj.object_type
                ) AS definition
            FROM all_objects obj
            WHERE UPPER(obj.owner) = UPPER(?)
                AND obj.object_type = 'PROCEDURE'
                AND obj.object_name NOT LIKE 'BIN$%'
            ORDER BY obj.object_name
        """
        return (query, [schema])

    def get_functions_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get functions using ALL_OBJECTS.

        Oracle stores function definitions in ALL_SOURCE. For simplicity,
        we extract function names and metadata without concatenating the full
        source code (which can be retrieved separately if needed).
        """
        query = """
            SELECT
                object_name AS function_name,
                object_type AS function_type,
                'PLSQL' AS language
            FROM all_objects
            WHERE UPPER(owner) = UPPER(?)
                AND object_type = 'FUNCTION'
                AND object_name NOT LIKE 'BIN$%'
            ORDER BY object_name
        """
        return (query, [schema])

    def get_function_arguments_query(
        self, schema: str, function_name: str
    ) -> tuple[str, List[Any]]:
        """
        Get function arguments from ALL_ARGUMENTS.

        In ALL_ARGUMENTS, POSITION = 0 represents the function return type.
        """
        query = """
            SELECT
                argument_name,
                position,
                data_type,
                in_out
            FROM all_arguments
            WHERE UPPER(owner) = UPPER(?)
                AND UPPER(object_name) = UPPER(?)
                AND package_name IS NULL
            ORDER BY position
        """
        return (query, [schema, function_name])

    def get_procedure_arguments_query(
        self, schema: str, procedure_name: str
    ) -> tuple[str, List[Any]]:
        """
        Get procedure arguments from ALL_ARGUMENTS.

        Similar to function arguments, but for procedures.
        """
        query = """
            SELECT
                argument_name,
                position,
                data_type,
                in_out
            FROM all_arguments
            WHERE UPPER(owner) = UPPER(?)
                AND UPPER(object_name) = UPPER(?)
                AND package_name IS NULL
                AND position > 0
            ORDER BY position
        """
        return (query, [schema, procedure_name])

    def get_function_definition_query(
        self, schema: str, function_name: str
    ) -> tuple[str, List[Any]]:
        """
        Get concatenated function definition from ALL_SOURCE.

        Note: LISTAGG is limited to 4000 characters in older Oracle versions.
        """
        query = """
            SELECT
                LISTAGG(text, '') WITHIN GROUP (ORDER BY line) AS definition
            FROM all_source
            WHERE UPPER(owner) = UPPER(?)
                AND UPPER(name) = UPPER(?)
                AND type = 'FUNCTION'
        """
        return (query, [schema, function_name])

    def get_packages_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get packages using ALL_OBJECTS.

        Oracle packages consist of a specification and an optional body.
        Package specs and bodies are stored as separate object types in Oracle.

        Oracle stores package definitions in ALL_SOURCE. For simplicity,
        we extract package names and metadata without concatenating the full
        source code (which can be retrieved separately if needed via ALL_SOURCE
        with proper ordering by line number).

        Note: LISTAGG has a 4000-byte limit (or 32767 bytes with extended strings
        in 12c+), which can cause truncation or errors for large packages.
        """
        query = """
            SELECT
                obj.object_name AS package_name,
                obj.object_type AS package_type,
                'PLSQL' AS language,
                (
                    SELECT COALESCE(
                        XMLAGG(
                            XMLELEMENT(e, src.text) ORDER BY src.line
                        ).getClobVal(),
                        TO_CLOB('')
                    )
                    FROM all_source src
                    WHERE src.owner = obj.owner
                      AND src.name = obj.object_name
                      AND src.type = obj.object_type
                ) AS definition
            FROM all_objects obj
            WHERE UPPER(obj.owner) = UPPER(?)
                AND obj.object_type IN ('PACKAGE', 'PACKAGE BODY')
                AND obj.object_name NOT LIKE 'BIN$%'
            ORDER BY obj.object_name, DECODE(obj.object_type, 'PACKAGE', 1, 'PACKAGE BODY', 2)
        """
        return (query, [schema])

    def get_user_defined_types_query(self, schema: str) -> tuple[str, List[Any]]:
        """Get user-defined types (object, collection) for the schema."""

        query = """
            SELECT
                t.type_name AS type_name,
                CASE
                    WHEN t.typecode = 'OBJECT' THEN 'OBJECT'
                    WHEN t.typecode IN ('TABLE', 'VARRAY') THEN t.typecode
                    ELSE t.typecode
                END AS type_category,
                NULL AS definition,
                NULL AS type_comment
            FROM all_types t
            WHERE UPPER(t.owner) = UPPER(?)
              AND t.typecode IN ('OBJECT', 'TABLE', 'VARRAY')
            ORDER BY t.type_name
        """
        return (query, [schema])

    def get_composite_type_attributes_query(
        self, schema: str, type_name: str
    ) -> tuple[str, List[Any]]:
        """Get attributes for Oracle object and collection types."""

        query = """
            SELECT
                a.attr_name AS attribute_name,
                (CASE
                    WHEN a.attr_type_owner IS NOT NULL AND a.attr_type_owner <> 'SYS' THEN
                        a.attr_type_owner || '.' || a.attr_type_name
                    ELSE a.attr_type_name
                END) ||
                (CASE
                    WHEN a.attr_type_name IN ('VARCHAR2', 'NVARCHAR2', 'CHAR', 'NCHAR', 'RAW') AND a.length IS NOT NULL THEN
                        '(' || TO_CHAR(a.length) || ')'
                    WHEN a.attr_type_name = 'NUMBER' AND a.precision IS NOT NULL THEN
                        '(' || TO_CHAR(a.precision) || NVL2(a.scale, ',' || TO_CHAR(a.scale), '') || ')'
                    WHEN a.attr_type_name = 'FLOAT' AND a.precision IS NOT NULL THEN
                        '(' || TO_CHAR(a.precision) || ')'
                    ELSE ''
                END) AS data_type,
                a.attr_no AS ordinal_position,
                1 AS is_nullable
            FROM all_type_attrs a
            WHERE UPPER(a.owner) = UPPER(?)
              AND UPPER(a.type_name) = UPPER(?)
            ORDER BY a.attr_no
        """
        return (query, [schema, type_name])

    def supports_check_constraints(self) -> bool:
        """Oracle fully supports check constraints."""
        return True

    def supports_sequences(self) -> bool:
        """Oracle fully supports sequences."""
        return True

    def supports_views(self) -> bool:
        """Oracle fully supports views."""
        return True

    def supports_triggers(self) -> bool:
        """Oracle fully supports triggers."""
        return True

    def supports_computed_columns(self) -> bool:
        """Oracle supports virtual columns (computed columns)."""
        return True

    def supports_partitions(self) -> bool:
        """Oracle has extensive partitioning support."""
        return True

    def get_materialized_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get materialized views using ALL_MVIEWS.

        Oracle has comprehensive materialized view support with various refresh options.
        """
        query = """
            SELECT
                mview_name AS materialized_view_name,
                query AS view_definition,
                CASE staleness
                    WHEN 'FRESH' THEN 'YES'
                    ELSE 'NO'
                END AS is_populated,
                last_refresh_date AS last_refresh,
                refresh_method,
                refresh_mode,
                fast_refreshable
            FROM all_mviews
            WHERE UPPER(owner) = UPPER(?)
            ORDER BY mview_name
        """
        return (query, [schema])

    def supports_materialized_views(self) -> bool:
        """Oracle has comprehensive materialized view support."""
        return True

    def supports_procedures(self) -> bool:
        """Oracle fully supports stored procedures."""
        return True

    def supports_functions(self) -> bool:
        """Oracle fully supports functions."""
        return True

    def supports_user_defined_types(self) -> bool:
        """Oracle supports user-defined types (OBJECT, collection)."""
        return True

    def get_synonyms_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get synonyms using ALL_SYNONYMS.

        Inspired by SQLAlchemy: lib/sqlalchemy/dialects/oracle/base.py
        """
        query = """
            SELECT
                synonym_name,
                table_owner AS target_schema,
                table_name AS target_object,
                db_link
            FROM all_synonyms
            WHERE UPPER(owner) = UPPER(?)
                AND synonym_name NOT LIKE 'BIN$%'
            ORDER BY synonym_name
        """
        return (query, [schema])

    def supports_synonyms(self) -> bool:
        """Oracle fully supports synonyms."""
        return True

    def get_database_links(self, schema: str) -> Tuple[str, List[Any]]:
        """
        Get database links using ALL_DB_LINKS.

        Returns only private (schema-owned) database links.
        When connecting as a privileged user (like SYSTEM), database links are owned
        by the connected user, not the current schema. So we need to check for links
        owned by the SESSION_USER.

        Public database links are not managed as they are database-wide objects.
        """
        query = """
            SELECT
                db_link,
                username,
                host
            FROM all_db_links
            WHERE owner = SYS_CONTEXT('USERENV', 'SESSION_USER')
            ORDER BY db_link
        """
        return (query, [])

    def supports_database_links(self) -> bool:
        """Oracle fully supports database links."""
        return True

    def supports_packages(self) -> bool:
        """Oracle PL/SQL packages are introspected via ``ALL_PROCEDURES`` / ``ALL_SOURCE``."""
        return True

    def get_table_properties_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get Oracle table properties such as tablespace and storage parameters.

        Uses ALL_TABLES to retrieve storage metadata for a specific table.
        Storage parameters (pctfree, pctused, initial, next) are SQL-generation-only,
        not diff-relevant.

        Note: 'next' is a reserved keyword in Oracle, so we must quote the alias.
        """
        # Note: 'free', 'used', 'initial', and 'next' are reserved keywords in Oracle,
        # so we use different aliases to avoid parsing issues
        # Format query on a single line to avoid Oracle parser issues with multiline queries
        table_predicate = _table_name_predicate("", table).replace(".table_name", "table_name")
        query = (
            "SELECT tablespace_name, pct_free AS pctfree_value, pct_used AS pctused_value, "
            "initial_extent AS initial_value, next_extent AS next_extent_size "
            f"FROM all_tables WHERE UPPER(owner) = UPPER(?) AND {table_predicate}"
        )
        return (query, [_catalog_identifier(schema), _catalog_identifier(table)])

    def get_partition_scheme_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Get partitioning scheme (method and key columns only, not individual partitions).

        Oracle partitioning types: RANGE, LIST, HASH, REFERENCE, SYSTEM, INTERVAL
        Note: We only track the partitioning strategy, not individual partitions
        (Oracle INTERVAL partitions can be auto-created).
        """
        table_predicate = _table_name_predicate("pt", table)
        query = """
            SELECT
                pt.partitioning_type,
                LISTAGG(ptc.column_name, ',') WITHIN GROUP (ORDER BY ptc.column_position) AS partition_columns
            FROM all_part_tables pt
            LEFT JOIN all_part_key_columns ptc
                ON pt.owner = ptc.owner
                AND pt.table_name = ptc.name
            WHERE UPPER(pt.owner) = UPPER(?)
                AND {table_predicate}
            GROUP BY pt.partitioning_type
        """.format(table_predicate=table_predicate)
        return (query, [schema, _catalog_identifier(table)])
