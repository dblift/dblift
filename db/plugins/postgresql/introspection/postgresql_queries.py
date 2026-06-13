"""
PostgreSQL-specific metadata queries.

This module provides PostgreSQL-specific queries for extracting metadata
from PostgreSQL system catalogs.

Queries are inspired by SQLAlchemy's PostgreSQL dialect:
https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/postgresql/base.py

PostgreSQL uses pg_catalog system tables for most metadata queries,
which provide richer information than information_schema views.
"""

from typing import Any, List, Optional

from core.introspection.vendor_queries_base import VendorMetadataQueries


class PostgreSQLMetadataQueries(VendorMetadataQueries):
    """
    PostgreSQL-specific metadata queries using pg_catalog.

    References:
        - PostgreSQL System Catalogs: https://www.postgresql.org/docs/current/catalogs.html
        - SQLAlchemy PG Dialect: https://github.com/sqlalchemy/sqlalchemy/blob/main/lib/sqlalchemy/dialects/postgresql/base.py
    """

    def get_check_constraints_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get check constraints using pg_catalog.

        Uses pg_get_constraintdef() to get the complete constraint definition.
        """
        query = """
            SELECT
                con.conname AS constraint_name,
                pg_catalog.pg_get_constraintdef(con.oid, true) AS constraint_definition,
                con.condeferrable AS is_deferrable,
                con.condeferred AS initially_deferred
            FROM pg_catalog.pg_constraint con
            INNER JOIN pg_catalog.pg_class rel
                ON rel.oid = con.conrelid
            INNER JOIN pg_catalog.pg_namespace nsp
                ON nsp.oid = rel.relnamespace
            WHERE nsp.nspname = ?
                AND rel.relname = ?
                AND con.contype = 'c'
            ORDER BY con.conname
        """
        return (query, [schema, table])

    def get_sequences_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get sequences using pg_sequences.

        Uses PostgreSQL's pg_sequences system view which provides complete
        sequence metadata including cache size.

        Version compatibility:
            - PostgreSQL 10+: Fully supported (pg_sequences view available)
            - PostgreSQL 9.6 and earlier: Not supported by this query

        Note: PostgreSQL 9.6 reached EOL in November 2021. If older version
        support is needed, a fallback query using pg_class and pg_sequence
        catalog tables would be required.

        Grammar-based: Added TEMPORARY sequence detection via pg_class.relpersistence.
        """
        query = """
            SELECT
                ps.sequencename AS sequence_name,
                ps.data_type::text,
                ps.start_value,
                ps.min_value AS minimum_value,
                ps.max_value AS maximum_value,
                ps.increment_by AS increment,
                CASE WHEN ps.cycle THEN 'YES' ELSE 'NO' END AS cycle_option,
                ps.cache_size,
                CASE c.relpersistence
                    WHEN 't' THEN 'YES'
                    ELSE 'NO'
                END AS is_temporary,
                own_n.nspname AS owning_schema,
                owning.relname AS owning_table,
                own_attr.attname AS owning_column
            FROM pg_catalog.pg_sequences ps
            INNER JOIN pg_catalog.pg_class c
                ON c.relname = ps.sequencename
            INNER JOIN pg_catalog.pg_namespace n
                ON c.relnamespace = n.oid
            LEFT JOIN pg_catalog.pg_depend dep
                ON dep.objid = c.oid
                AND dep.deptype = 'a'
            LEFT JOIN pg_catalog.pg_class owning
                ON dep.refobjid = owning.oid
            LEFT JOIN pg_catalog.pg_namespace own_n
                ON own_n.oid = owning.relnamespace
            LEFT JOIN pg_catalog.pg_attribute own_attr
                ON own_attr.attrelid = owning.oid
                AND own_attr.attnum = dep.refobjsubid
            WHERE n.nspname = ?
              -- BUG-01: pg_sequences is schema-aware but the join above
              -- only filters pg_class by schema. Without this second
              -- predicate, a sequence named ``order_seq`` existing in 3
              -- schemas returned 3 rows (one per ps row × one matching
              -- c row in the target schema), producing duplicate
              -- CREATE SEQUENCE statements in exports.
              AND ps.schemaname = ?
            ORDER BY ps.sequencename
        """
        return (query, [schema, schema])

    def get_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get views using pg_catalog.

        Includes view definition, metadata about updatability, and security context.
        """
        query = """
            SELECT
                c.relname AS view_name,
                pg_catalog.pg_get_viewdef(c.oid, true) AS view_definition,
                CASE
                    WHEN v.is_updatable = 'YES' THEN true
                    ELSE false
                END AS is_updatable,
                COALESCE(v.check_option, 'NONE') AS check_option,
                column_info.column_names,
                CASE
                    WHEN c.relkind = 'm' THEN true
                    ELSE false
                END AS is_materialized,
                NULL AS security_definer,
                NULL AS security_invoker
            FROM pg_catalog.pg_class c
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            LEFT JOIN information_schema.views v
                ON v.table_schema = n.nspname
                AND v.table_name = c.relname
            LEFT JOIN (
                SELECT
                    c.table_schema,
                    c.table_name,
                    json_agg(c.column_name ORDER BY c.ordinal_position)::text AS column_names
                FROM information_schema.columns c
                GROUP BY c.table_schema, c.table_name
            ) column_info
                ON column_info.table_schema = n.nspname
                AND column_info.table_name = c.relname
            WHERE n.nspname = ?
                -- BUG-02: only regular views here. Materialized views
                -- ('m') are captured by get_materialized_views_query;
                -- including them here caused the snapshot service to
                -- emit each matview twice (once as view, once as matview)
                -- because schema_snapshot_service calls BOTH methods.
                AND c.relkind = 'v'
            ORDER BY c.relname
        """
        return (query, [schema])

    def get_view_definition_query(self, schema: str, view_name: str) -> tuple[str, List[Any]]:
        """
        Get a specific view's definition.

        Uses pg_get_viewdef() for a cleaner definition format.
        """
        query = """
            SELECT
                pg_catalog.pg_get_viewdef(c.oid, true) AS view_definition
            FROM pg_catalog.pg_class c
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            WHERE n.nspname = ?
                AND c.relname = ?
                AND c.relkind = 'v'
        """
        return (query, [schema, view_name])

    def get_indexes_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get detailed index information using pg_catalog.

        Includes index type, partial index conditions, and expression indexes.
        Uses pg_get_indexdef() to get the complete index definition which
        includes expressions and WHERE clauses.

        Grammar-based: Added CONCURRENTLY detection.
        Note: PostgreSQL doesn't store whether an index was created with CONCURRENTLY
        after creation. We attempt to detect it by checking the index definition string,
        but this is a best-effort approach and may not always be accurate.
        """
        query = """
            SELECT
                i.relname AS index_name,
                a.attname AS column_name,
                COALESCE(a.attnum, sub.attnum) AS ordinal_position,
                CASE
                    WHEN a.attnum IS NOT NULL AND a.attnum > 0 THEN
                        CASE WHEN ix.indoption[a.attnum - 1] & 1 = 1 THEN true ELSE false END
                    ELSE false
                END AS is_descending,
                ix.indisunique AS is_unique,
                am.amname AS index_type,
                pg_catalog.pg_get_expr(ix.indpred, ix.indrelid, true) AS filter_condition,
                CASE WHEN a.attnum IS NULL OR a.attnum = 0 THEN true ELSE false END AS is_expression,
                CASE
                    WHEN a.attnum IS NULL OR a.attnum = 0 THEN
                        -- For expression indexes, get the expression from pg_get_indexdef
                        -- Note: pg_get_indexdef expects integer, so cast ordinality
                        pg_catalog.pg_get_indexdef(ix.indexrelid, sub.ordinality::integer, true)
                    ELSE
                        -- For regular columns, get the column name (already in a.attname)
                        NULL
                END AS index_expression,
                CASE
                    WHEN pg_catalog.pg_get_indexdef(ix.indexrelid, 0, true) LIKE '%CONCURRENTLY%' THEN 'YES'
                    ELSE 'NO'
                END AS is_concurrent,
                include_cols.include_columns AS include_columns,
                (SELECT option_value::int FROM pg_catalog.pg_options_to_table(i.reloptions) WHERE option_name = 'fillfactor') AS fillfactor,
                (SELECT option_value FROM pg_catalog.pg_options_to_table(i.reloptions) WHERE option_name = 'compression') AS compression,
                (SELECT description FROM pg_catalog.pg_description WHERE objoid = i.oid AND objsubid = 0) AS comment
            FROM pg_catalog.pg_index ix
            INNER JOIN pg_catalog.pg_class t
                ON t.oid = ix.indrelid
            INNER JOIN pg_catalog.pg_class i
                ON i.oid = ix.indexrelid
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = t.relnamespace
            INNER JOIN pg_catalog.pg_am am
                ON am.oid = i.relam
            -- Use unnest to get all index keys (including expressions with attnum = 0)
            LEFT JOIN LATERAL unnest(ix.indkey::smallint[]) WITH ORDINALITY AS sub(attnum, ordinality) ON TRUE
            LEFT JOIN pg_catalog.pg_attribute a
                ON a.attrelid = t.oid
                AND a.attnum = sub.attnum
                AND sub.attnum > 0
            LEFT JOIN LATERAL (
                SELECT
                    json_agg(pg_catalog.quote_ident(att.attname) ORDER BY sub2.ordinality)::text AS include_columns
                FROM unnest(ix.indkey::smallint[]) WITH ORDINALITY AS sub2(attnum, ordinality)
                JOIN pg_catalog.pg_attribute att
                    ON att.attrelid = t.oid
                    AND att.attnum = sub2.attnum
                WHERE sub2.ordinality > ix.indnkeyatts
            ) include_cols ON TRUE
            WHERE n.nspname = ?
                AND t.relname = ?
                AND NOT ix.indisprimary
                AND sub.ordinality <= ix.indnkeyatts
            ORDER BY i.relname, sub.ordinality
        """
        return (query, [schema, table])

    def get_triggers_query(self, schema: str, table: str = None) -> tuple[str, List[Any]]:
        """
        Get triggers using information_schema enhanced with pg_catalog.

        PostgreSQL provides good trigger metadata through information_schema.
        Grammar-based: Added CONSTRAINT TRIGGER detection via pg_trigger.tgconstraint.
        Uses information_schema for reliable event/timing extraction and pg_catalog for constraint detection.
        """
        base_select = """
            SELECT
                tr.trigger_name,
                tr.event_object_table AS table_name,
                tr.event_manipulation,
                tr.action_timing,
                tr.action_statement,
                tr.action_orientation,
                pg_catalog.pg_get_triggerdef(t.oid, true) AS trigger_definition,
                pg_catalog.pg_get_expr(t.tgqual, t.tgrelid, true) AS when_clause,
                t.tgenabled,
                CASE WHEN t.tgconstraint != 0 THEN 'YES' ELSE 'NO' END AS is_constraint_trigger,
                t.tgdeferrable,
                t.tginitdeferred,
                pn.nspname AS function_schema,
                p.proname AS function_name,
                pg_catalog.pg_get_function_identity_arguments(p.oid) AS function_arguments
            FROM information_schema.triggers tr
            INNER JOIN pg_catalog.pg_namespace n
                ON n.nspname = tr.event_object_schema
            INNER JOIN pg_catalog.pg_class c
                ON c.relname = tr.event_object_table
                AND c.relnamespace = n.oid
            INNER JOIN pg_catalog.pg_trigger t
                ON t.tgrelid = c.oid
                AND t.tgname = tr.trigger_name
                AND NOT t.tgisinternal
            INNER JOIN pg_catalog.pg_proc p
                ON p.oid = t.tgfoid
            INNER JOIN pg_catalog.pg_namespace pn
                ON pn.oid = p.pronamespace
        """

        if table:
            query = base_select + """
            WHERE tr.event_object_schema = ?
                AND tr.event_object_table = ?
            ORDER BY tr.trigger_name
            """
            params = [schema, table]
        else:
            query = base_select + """
            WHERE tr.event_object_schema = ?
            ORDER BY tr.event_object_table, tr.trigger_name
            """
            params = [schema]

        return (query, params)

    def get_computed_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get generated/computed columns (PostgreSQL 12+).

        PostgreSQL uses GENERATED ALWAYS AS syntax for computed columns.
        """
        query = """
            SELECT
                a.attname AS column_name,
                pg_catalog.pg_get_expr(d.adbin, d.adrelid) AS computation_expression,
                CASE a.attgenerated
                    WHEN 's' THEN true
                    ELSE false
                END AS is_stored
            FROM pg_catalog.pg_attribute a
            INNER JOIN pg_catalog.pg_class c
                ON c.oid = a.attrelid
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_attrdef d
                ON d.adrelid = a.attrelid
                AND d.adnum = a.attnum
            WHERE n.nspname = ?
                AND c.relname = ?
                AND a.attgenerated != ''
                AND NOT a.attisdropped
            ORDER BY a.attnum
        """
        return (query, [schema, table])

    def get_identity_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get identity column information (PostgreSQL 10+).

        PostgreSQL supports SQL standard IDENTITY columns. This query adds
        sequence metadata to the base column projection.
        """
        query = """
            SELECT
                a.attname AS column_name,
                s.seqstart AS seed_value,
                s.seqincrement AS increment_value,
                NULL AS last_value
            FROM pg_catalog.pg_attribute a
            INNER JOIN pg_catalog.pg_class c
                ON c.oid = a.attrelid
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_sequence s
                ON s.seqrelid = pg_get_serial_sequence(
                    quote_ident(n.nspname) || '.' || quote_ident(c.relname),
                    a.attname
                )::regclass
            WHERE n.nspname = ?
                AND c.relname = ?
                AND a.attidentity != ''
                AND NOT a.attisdropped
            ORDER BY a.attnum
        """
        return (query, [schema, table])

    def get_table_partitions_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get table partition information (PostgreSQL 10+).

        PostgreSQL supports declarative partitioning with RANGE, LIST, and HASH methods.
        """
        query = """
            SELECT
                c.relname AS partition_name,
                pg_catalog.pg_get_expr(c.relpartbound, c.oid, true) AS partition_expression,
                CASE p.partstrat
                    WHEN 'r' THEN 'RANGE'
                    WHEN 'l' THEN 'LIST'
                    WHEN 'h' THEN 'HASH'
                END AS partition_method,
                pg_catalog.pg_get_expr(c.relpartbound, c.oid, true) AS high_value
            FROM pg_catalog.pg_class c
            INNER JOIN pg_catalog.pg_inherits i
                ON i.inhrelid = c.oid
            INNER JOIN pg_catalog.pg_class parent
                ON parent.oid = i.inhparent
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = parent.relnamespace
            LEFT JOIN pg_catalog.pg_partitioned_table p
                ON p.partrelid = parent.oid
            WHERE n.nspname = ?
                AND parent.relname = ?
                AND c.relispartition
            ORDER BY c.relname
        """
        return (query, [schema, table])

    def get_procedures_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get stored procedures using pg_proc (PostgreSQL 11+).

        PostgreSQL added procedures in version 11. Before that, only functions existed.
        """
        query = """
            SELECT
                p.proname AS procedure_name,
                'PROCEDURE' AS procedure_type,
                l.lanname AS language,
                pg_catalog.pg_get_functiondef(p.oid) AS definition,
                pg_catalog.obj_description(p.oid, 'pg_proc') AS comment,
                params.parameter_json,
                CASE p.provolatile
                    WHEN 'i' THEN 'IMMUTABLE'
                    WHEN 's' THEN 'STABLE'
                    WHEN 'v' THEN 'VOLATILE'
                    ELSE NULL
                END AS volatility,
                CASE WHEN p.prosecdef THEN 'YES' ELSE 'NO' END AS security_definer
            FROM pg_catalog.pg_proc p
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = p.pronamespace
            INNER JOIN pg_catalog.pg_language l
                ON l.oid = p.prolang
            LEFT JOIN LATERAL (
                SELECT json_agg(
                    json_build_object(
                        'name', param_name,
                        'data_type', param_type,
                        'mode', param_mode
                    ) ORDER BY ordinality
                )::text AS parameter_json
                FROM (
                    SELECT
                        ordinality,
                        COALESCE(p.proargnames[ordinality], '') AS param_name,
                        pg_catalog.format_type(
                            CASE
                                WHEN p.proallargtypes IS NOT NULL THEN p.proallargtypes[ordinality]
                                ELSE (p.proargtypes::oid[])[ordinality]
                            END,
                            NULL
                        ) AS param_type,
                        CASE
                            WHEN p.proargmodes IS NULL THEN 'IN'
                            ELSE CASE p.proargmodes[ordinality]
                                WHEN 'i' THEN 'IN'
                                WHEN 'o' THEN 'OUT'
                                WHEN 'b' THEN 'INOUT'
                                WHEN 'v' THEN 'VARIADIC'
                                WHEN 't' THEN 'TABLE'
                                ELSE 'IN'
                            END
                        END AS param_mode
                    FROM generate_subscripts(
                        CASE
                            WHEN p.proallargtypes IS NOT NULL THEN p.proallargtypes
                            ELSE p.proargtypes::oid[]
                        END,
                        1
                    ) AS ordinality
                ) param_details
            ) params ON TRUE
            WHERE n.nspname = ?
                AND p.prokind = 'p'
            ORDER BY p.proname
        """
        return (query, [schema])

    def get_functions_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get functions using pg_proc.

        PostgreSQL supports multiple function types (regular functions, aggregate functions, window functions).
        """
        query = """
            SELECT
                p.proname AS function_name,
                pg_catalog.format_type(p.prorettype, NULL) AS return_type,
                l.lanname AS language,
                pg_catalog.pg_get_functiondef(p.oid) AS definition,
                pg_catalog.obj_description(p.oid, 'pg_proc') AS comment,
                CASE p.prokind
                    WHEN 'f' THEN 'FUNCTION'
                    WHEN 'a' THEN 'AGGREGATE'
                    WHEN 'w' THEN 'WINDOW'
                    ELSE 'FUNCTION'
                END AS function_type,
                ext.extname AS extension_name,
                params.parameter_json,
                CASE p.provolatile
                    WHEN 'i' THEN 'IMMUTABLE'
                    WHEN 's' THEN 'STABLE'
                    WHEN 'v' THEN 'VOLATILE'
                    ELSE NULL
                END AS volatility,
                CASE WHEN p.prosecdef THEN 'YES' ELSE 'NO' END AS security_definer
            FROM pg_catalog.pg_proc p
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = p.pronamespace
            INNER JOIN pg_catalog.pg_language l
                ON l.oid = p.prolang
            LEFT JOIN pg_catalog.pg_depend dep
                ON dep.classid = 'pg_proc'::regclass
                AND dep.objid = p.oid
                AND dep.deptype = 'e'
            LEFT JOIN pg_catalog.pg_extension ext
                ON ext.oid = dep.refobjid
            LEFT JOIN LATERAL (
                SELECT json_agg(
                    json_build_object(
                        'name', param_name,
                        'data_type', param_type,
                        'mode', param_mode
                    ) ORDER BY ordinality
                )::text AS parameter_json
                FROM (
                    SELECT
                        ordinality,
                        COALESCE(p.proargnames[ordinality], '') AS param_name,
                        pg_catalog.format_type(
                            CASE
                                WHEN p.proallargtypes IS NOT NULL THEN p.proallargtypes[ordinality]
                                ELSE (p.proargtypes::oid[])[ordinality]
                            END,
                            NULL
                        ) AS param_type,
                        CASE
                            WHEN p.proargmodes IS NULL THEN 'IN'
                            ELSE CASE p.proargmodes[ordinality]
                                WHEN 'i' THEN 'IN'
                                WHEN 'o' THEN 'OUT'
                                WHEN 'b' THEN 'INOUT'
                                WHEN 'v' THEN 'VARIADIC'
                                WHEN 't' THEN 'TABLE'
                                ELSE 'IN'
                            END
                        END AS param_mode
                    FROM generate_subscripts(
                        CASE
                            WHEN p.proallargtypes IS NOT NULL THEN p.proallargtypes
                            ELSE p.proargtypes::oid[]
                        END,
                        1
                    ) AS ordinality
                ) param_details
            ) params ON TRUE
            WHERE n.nspname = ?
                AND p.prokind IN ('f', 'a', 'w')
            ORDER BY p.proname
        """
        return (query, [schema])

    def supports_check_constraints(self) -> bool:
        """PostgreSQL fully supports check constraints."""
        return True

    def supports_sequences(self) -> bool:
        """PostgreSQL fully supports sequences."""
        return True

    def supports_views(self) -> bool:
        """PostgreSQL fully supports views."""
        return True

    def supports_triggers(self) -> bool:
        """PostgreSQL fully supports triggers."""
        return True

    def supports_computed_columns(self) -> bool:
        """PostgreSQL supports generated columns (version 12+)."""
        return True

    def supports_partitions(self) -> bool:
        """PostgreSQL supports declarative partitioning (version 10+)."""
        return True

    def get_materialized_views_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get materialized views using pg_catalog.

        PostgreSQL supports materialized views with refresh capabilities.
        Uses pg_get_viewdef() to get the clean definition.

        Version compatibility:
            - PostgreSQL 9.3+: Materialized views supported

        Grammar-based: Added UNLOGGED detection via pg_class.relpersistence.
        """
        query = """
            SELECT
                c.relname AS materialized_view_name,
                pg_catalog.pg_get_viewdef(c.oid, true) AS view_definition,
                CASE c.relispopulated
                    WHEN true THEN 'YES'
                    ELSE 'NO'
                END AS is_populated,
                CASE c.relpersistence
                    WHEN 'u' THEN 'YES'
                    ELSE 'NO'
                END AS is_unlogged,
                (
                    SELECT json_agg(att.attname ORDER BY att.attnum)::text
                    FROM pg_catalog.pg_attribute att
                    WHERE att.attrelid = c.oid
                      AND NOT att.attisdropped
                      AND att.attnum > 0
                ) AS column_names
            FROM pg_catalog.pg_class c
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            WHERE n.nspname = ?
                AND c.relkind = 'm'
            ORDER BY c.relname
        """
        return (query, [schema])

    def supports_materialized_views(self) -> bool:
        """PostgreSQL supports materialized views (version 9.3+)."""
        return True

    def supports_procedures(self) -> bool:
        """PostgreSQL supports procedures (version 11+)."""
        return True

    def supports_functions(self) -> bool:
        """PostgreSQL fully supports functions."""
        return True

    def get_table_inheritance_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """
        Get table inheritance information (parent tables).

        PostgreSQL supports table inheritance where a table can inherit from one or more parent tables.
        This query returns the list of parent tables.
        """
        query = """
            SELECT
                n.nspname AS parent_schema,
                c.relname AS parent_table
            FROM pg_catalog.pg_inherits i
            INNER JOIN pg_catalog.pg_class c
                ON c.oid = i.inhparent
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            INNER JOIN pg_catalog.pg_class child
                ON child.oid = i.inhrelid
            INNER JOIN pg_catalog.pg_namespace child_nsp
                ON child_nsp.oid = child.relnamespace
            WHERE child_nsp.nspname = ?
                AND child.relname = ?
            ORDER BY n.nspname, c.relname
        """
        return (query, [schema, table])

    def get_table_row_security_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Get row-level security flags for a table."""
        query = """
            SELECT
                CASE WHEN c.relrowsecurity THEN 'YES' ELSE 'NO' END AS row_security,
                CASE WHEN c.relforcerowsecurity THEN 'YES' ELSE 'NO' END AS force_row_security
            FROM pg_catalog.pg_class c
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            WHERE n.nspname = ?
                AND c.relname = ?
            LIMIT 1
        """
        return (query, [schema, table])

    def get_policies_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Get row-level security policies for a table."""
        query = """
            SELECT
                pol.polname AS policy_name,
                pol.polcmd AS policy_command,
                CASE WHEN pol.polpermissive THEN 'YES' ELSE 'NO' END AS is_permissive,
                roles.roles_json AS roles,
                pg_catalog.pg_get_expr(pol.polqual, pol.polrelid, true) AS policy_qual,
                pg_catalog.pg_get_expr(pol.polwithcheck, pol.polrelid, true) AS policy_with_check
            FROM pg_catalog.pg_policy pol
            INNER JOIN pg_catalog.pg_class c
                ON c.oid = pol.polrelid
            INNER JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            LEFT JOIN LATERAL (
                SELECT json_agg(r.rolname ORDER BY r.rolname)::text AS roles_json
                FROM unnest(COALESCE(pol.polroles, ARRAY[]::oid[])) AS role_oid
                LEFT JOIN pg_catalog.pg_roles r
                    ON r.oid = role_oid
            ) roles ON TRUE
            WHERE n.nspname = ?
                AND c.relname = ?
            ORDER BY pol.polname
        """
        return (query, [schema, table])

    def get_user_defined_types_query(self, schema: str) -> tuple[str, List[Any]]:
        """
        Get user-defined types using pg_type.

        Inspired by SQLAlchemy: lib/sqlalchemy/dialects/postgresql/base.py

        BUG-02: include ``base_type`` and ``definition`` for DOMAINs so the
        PostgreSQL generator can emit a complete ``CREATE DOMAIN ... AS
        <base> CHECK (...)`` instead of an empty ``CREATE TYPE "name";``.
        The subquery on ``pg_constraint`` joins all CHECK clauses for the
        domain (``contypid``), so multi-constraint domains round-trip too.

        Batch-5 BUG-01: reject auto-generated row types. Every PostgreSQL
        relation (table, view, matview, partitioned table) creates an
        implicit composite type with ``typrelid != 0``. Exporting those
        as standalone ``CREATE TYPE`` emits duplicate DDL that collides
        with the underlying object on re-import. User-written composites
        have ``relkind = 'c'`` in pg_class; table/view row types do not.
        """
        query = """
            SELECT
                t.typname AS type_name,
                t.typtype AS type_category,
                pg_catalog.obj_description(t.oid, 'pg_type') AS comment,
                CASE WHEN t.typtype = 'd'
                     THEN pg_catalog.format_type(t.typbasetype, t.typtypmod)
                     ELSE NULL END AS base_type,
                CASE WHEN t.typtype = 'd' THEN (
                    SELECT string_agg(pg_get_constraintdef(con.oid, true), ' ')
                    FROM pg_catalog.pg_constraint con
                    WHERE con.contypid = t.oid
                ) ELSE NULL END AS definition
            FROM pg_catalog.pg_type t
            JOIN pg_catalog.pg_namespace nsp ON t.typnamespace = nsp.oid
            LEFT JOIN pg_catalog.pg_class c ON t.typrelid = c.oid
            WHERE nsp.nspname = ?
              AND t.typtype IN ('c', 'e', 'd')  -- composite, enum, domain
              AND t.typname NOT LIKE 'pg_%'     -- Exclude system types
              AND (t.typtype <> 'c' OR c.relkind = 'c')
            ORDER BY t.typname
        """
        return (query, [schema])

    def get_enum_values_query(self, schema: str, type_name: str) -> tuple[str, List[Any]]:
        """
        Get enum values for a specific enum type using pg_enum.

        Inspired by SQLAlchemy: lib/sqlalchemy/dialects/postgresql/base.py
        """
        query = """
            SELECT
                e.enumlabel AS enum_value,
                e.enumsortorder AS sort_order
            FROM pg_catalog.pg_enum e
            JOIN pg_catalog.pg_type t ON e.enumtypid = t.oid
            JOIN pg_catalog.pg_namespace nsp ON t.typnamespace = nsp.oid
            WHERE nsp.nspname = ?
              AND t.typname = ?
            ORDER BY e.enumsortorder
        """
        return (query, [schema, type_name])

    def get_composite_type_attributes_query(
        self, schema: str, type_name: str
    ) -> tuple[str, List[Any]]:
        """
        Get attributes for a composite type using pg_attribute.

        Inspired by SQLAlchemy: lib/sqlalchemy/dialects/postgresql/base.py
        """
        query = """
            SELECT
                a.attname AS attribute_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod) AS data_type,
                a.attnum AS ordinal_position,
                NOT a.attnotnull AS is_nullable
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_type t ON a.attrelid = t.typrelid
            JOIN pg_catalog.pg_namespace nsp ON t.typnamespace = nsp.oid
            WHERE nsp.nspname = ?
              AND t.typname = ?
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
        """
        return (query, [schema, type_name])

    def supports_user_defined_types(self) -> bool:
        """PostgreSQL fully supports user-defined types."""
        return True

    def get_extensions_query(self, schema: Optional[str] = None) -> tuple[str, List[Any]]:
        """
        Get installed extensions using pg_extension.

        Inspired by SQLAlchemy: lib/sqlalchemy/dialects/postgresql/base.py
        """
        query = """
            SELECT
                e.extname AS extension_name,
                e.extversion AS version,
                n.nspname AS schema,
                e.extrelocatable AS relocatable,
                pg_catalog.obj_description(e.oid, 'pg_extension') AS description
            FROM pg_catalog.pg_extension e
            LEFT JOIN pg_catalog.pg_namespace n ON n.oid = e.extnamespace
            WHERE e.extname NOT IN ('plpgsql')  -- Exclude built-in extensions
            ORDER BY e.extname
        """
        return (query, [])

    def supports_extensions(self) -> bool:
        """PostgreSQL supports extensions."""
        return True

    def supports_foreign_data_wrappers(self) -> bool:
        """PostgreSQL is the only dialect with foreign data wrappers."""
        return True

    def supports_foreign_servers(self) -> bool:
        """PostgreSQL is the only dialect with foreign servers."""
        return True

    def get_foreign_data_wrappers_query(self) -> tuple[str, List[Any]]:
        """
        Get foreign data wrappers.
        """
        query = """
            SELECT
                fdw.fdwname AS wrapper_name,
                fdw.fdwoptions AS options,
                pg_catalog.pg_get_userbyid(fdw.fdwowner) AS owner,
                handler.proname AS handler_name,
                handler_ns.nspname AS handler_schema,
                validator.proname AS validator_name,
                validator_ns.nspname AS validator_schema
            FROM pg_catalog.pg_foreign_data_wrapper fdw
            LEFT JOIN pg_catalog.pg_proc handler ON handler.oid = fdw.fdwhandler
            LEFT JOIN pg_catalog.pg_namespace handler_ns ON handler_ns.oid = handler.pronamespace
            LEFT JOIN pg_catalog.pg_proc validator ON validator.oid = fdw.fdwvalidator
            LEFT JOIN pg_catalog.pg_namespace validator_ns ON validator_ns.oid = validator.pronamespace
            ORDER BY fdw.fdwname
        """
        return (query, [])

    def get_foreign_servers_query(self) -> tuple[str, List[Any]]:
        """
        Get foreign servers.
        """
        query = """
            SELECT
                srv.srvname AS server_name,
                fdw.fdwname AS fdw_name,
                srv.srvtype AS server_type,
                srv.srvversion AS server_version,
                srv.srvoptions AS options,
                pg_catalog.pg_get_userbyid(srv.srvowner) AS owner
            FROM pg_catalog.pg_foreign_server srv
            INNER JOIN pg_catalog.pg_foreign_data_wrapper fdw ON fdw.oid = srv.srvfdw
            ORDER BY srv.srvname
        """
        return (query, [])

    def get_partition_scheme_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Get partitioning scheme (method and key columns only, not individual partitions).

        PostgreSQL partitioning types (10+): RANGE, LIST, HASH
        Note: We only track the partitioning strategy, not individual partitions.
        """
        query = """
            SELECT
                pg_get_partkeydef(c.oid) AS partition_definition
            FROM pg_catalog.pg_class c
            INNER JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ?
                AND c.relname = ?
                AND c.relkind = 'p'
        """
        return (query, [schema, table])

    def get_partitioned_tables_query(self, schema: str) -> tuple[str, List[Any]]:
        """Get partitioned tables (relkind='p').

        Returns table names for partitioned tables that need to be added to get_tables() results.
        """
        query = """
            SELECT
                c.relname AS table_name,
                obj_description(c.oid) AS remarks
            FROM pg_catalog.pg_class c
            INNER JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ?
                AND c.relkind = 'p'
            ORDER BY c.relname
        """
        return (query, [schema])

    # ------------------------------------------------------------------
    # Structural metadata — native provider path
    # ------------------------------------------------------------------

    def get_tables_query(self, schema: str) -> tuple[str, List[Any]]:
        """List base table names in *schema* using pg_catalog."""
        query = """
            SELECT c.relname AS table_name
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ?
              AND c.relkind IN ('r', 'p')
            ORDER BY c.relname
        """
        return (query, [schema])

    def get_view_names_query(self, schema: str) -> tuple[str, List[Any]]:
        """List view and materialised-view names in *schema* using pg_catalog."""
        query = """
            SELECT c.relname AS view_name
            FROM pg_catalog.pg_class c
            JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
            WHERE n.nspname = ?
              AND c.relkind IN ('v', 'm')
            ORDER BY c.relname
        """
        return (query, [schema])

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return column metadata with PK detection from pg_catalog."""
        query = """
            SELECT
                a.attname                                              AS column_name,
                pg_catalog.format_type(a.atttypid, a.atttypmod)       AS data_type,
                NOT a.attnotnull                                        AS is_nullable,
                pg_catalog.pg_get_expr(d.adbin, d.adrelid)            AS column_default,
                COALESCE(pk.is_pk, false)                              AS is_primary_key,
                a.attnum                                               AS ordinal_position
            FROM pg_catalog.pg_attribute a
            JOIN pg_catalog.pg_class c
                ON c.oid = a.attrelid
            JOIN pg_catalog.pg_namespace n
                ON n.oid = c.relnamespace
            LEFT JOIN pg_catalog.pg_attrdef d
                ON d.adrelid = a.attrelid AND d.adnum = a.attnum
            LEFT JOIN (
                SELECT conrelid, unnest(conkey) AS attnum, true AS is_pk
                FROM pg_catalog.pg_constraint
                WHERE contype = 'p'
            ) pk
                ON pk.conrelid = a.attrelid AND pk.attnum = a.attnum
            WHERE n.nspname = ?
              AND c.relname = ?
              AND a.attnum > 0
              AND NOT a.attisdropped
            ORDER BY a.attnum
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
            WHERE tc.table_schema      = ?
              AND tc.table_name        = ?
              AND tc.constraint_type   = 'PRIMARY KEY'
            ORDER BY kcu.ordinal_position
        """
        return (query, [schema, table])

    def get_foreign_keys_query(self, schema: str, table: str) -> tuple[str, List[Any]]:
        """Return FK constraint rows for *table* (one row per constrained column).

        Uses pg_catalog instead of information_schema.constraint_column_usage to
        avoid the cross-product bug: CCU has no ordinal position, so joining it by
        constraint name alone on a composite FK (N local cols, N ref cols) produces
        N² rows instead of N.  UNNEST(conkey, confkey) preserves the positional
        mapping between local and referenced columns.
        """
        query = """
            SELECT
                con.conname                 AS name,
                att.attname                 AS column_name,
                ref_ns.nspname              AS ref_schema,
                ref_cl.relname              AS ref_table,
                ref_att.attname             AS ref_column,
                CASE con.confdeltype
                    WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                END                         AS on_delete,
                CASE con.confupdtype
                    WHEN 'a' THEN 'NO ACTION'
                    WHEN 'r' THEN 'RESTRICT'
                    WHEN 'c' THEN 'CASCADE'
                    WHEN 'n' THEN 'SET NULL'
                    WHEN 'd' THEN 'SET DEFAULT'
                END                         AS on_update
            FROM pg_catalog.pg_constraint con
            JOIN pg_catalog.pg_class cl
                ON cl.oid = con.conrelid
            JOIN pg_catalog.pg_namespace ns
                ON ns.oid = cl.relnamespace
            JOIN pg_catalog.pg_class ref_cl
                ON ref_cl.oid = con.confrelid
            JOIN pg_catalog.pg_namespace ref_ns
                ON ref_ns.oid = ref_cl.relnamespace
            CROSS JOIN LATERAL unnest(con.conkey, con.confkey)
                WITH ORDINALITY AS cols(local_attnum, ref_attnum, ord)
            JOIN pg_catalog.pg_attribute att
                ON att.attrelid = cl.oid AND att.attnum = cols.local_attnum
            JOIN pg_catalog.pg_attribute ref_att
                ON ref_att.attrelid = ref_cl.oid AND ref_att.attnum = cols.ref_attnum
            WHERE ns.nspname = ?
              AND cl.relname = ?
              AND con.contype = 'f'
            ORDER BY con.conname, cols.ord
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
