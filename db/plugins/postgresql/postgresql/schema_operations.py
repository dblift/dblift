"""
PostgreSQL schema operations and metadata queries.

This module handles PostgreSQL-specific schema operations including schema creation,
cleaning, and metadata queries for tables, columns, and other database objects.
"""

from typing import Any, List, Optional, Tuple

from core.logger import Log, NullLog
from core.migration.clean_summary import CleanExecutionSummary
from db.plugins.base_schema_operations import BaseSchemaOperations


class PostgreSqlSchemaOperations(BaseSchemaOperations):
    """Handles PostgreSQL schema operations and metadata queries."""

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the schema operations manager.

        Args:
            query_executor: Query executor instance
            log: Optional logger
        """
        self.query_executor: Any = query_executor
        self.log: Log = log if log is not None else NullLog()

    def create_schema_if_not_exists(self, connection: Any, schema: str) -> None:
        """Create schema if it doesn't exist in PostgreSQL.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name to create
        """
        self.log.debug(f"Creating schema if not exists: {schema}")

        try:
            # OBS-03: pre-check existence so a typo in --db-schema yields a
            # warning instead of silent fresh-history creation.
            # BUG-01: read-only commands (info/validate/diff/check-connection)
            # must not require CREATE privilege on the database. When the
            # schema already exists, skip the DDL entirely — PostgreSQL parses
            # and ACL-checks ``CREATE SCHEMA IF NOT EXISTS`` even though it is
            # a no-op, which forces every read-only call to need CREATE rights.
            check_sql = "SELECT 1 FROM pg_namespace WHERE nspname = ?"
            existed = bool(
                self.query_executor.execute_query(connection, check_sql, params=[schema])
            )

            if existed:
                self.log.debug(f"Schema {schema} already exists")
                return

            self.log.warning(
                f"Schema '{schema}' did not exist — created automatically. "
                "Check for typos in --db-schema."
            )
            quoted_schema = self.query_executor.get_quoted_schema_name(schema)
            create_schema_sql = f"CREATE SCHEMA IF NOT EXISTS {quoted_schema}"
            self.query_executor.execute_statement(connection, create_schema_sql)

        except Exception as e:
            # Handle case where schema already exists
            if "already exists" in str(e).lower():
                self.log.debug(f"Schema {schema} already exists")
            else:
                error_msg = f"Error creating schema {schema}: {str(e)}"
                self.log.error(error_msg)
                raise

    def clean_schema(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Clean all objects from the specified PostgreSQL schema.

        This drops all user-created tables, views, sequences, functions,
        and other objects in the schema, leaving only the empty schema structure.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Name of the schema to clean

        Returns:
            CleanExecutionSummary: Statements executed and objects removed.
        """
        self.log.debug(f"Cleaning PostgreSQL schema: {schema}")

        summary = CleanExecutionSummary()

        try:
            # 1. Drop all extensions first (they own functions that can't be dropped individually)
            # NOTE: Only drops extensions installed in this specific schema, not database-wide extensions
            self.log.debug("Dropping schema-specific extensions...")

            extensions_query = """
            SELECT extname as extension_name
            FROM pg_extension e
            JOIN pg_namespace n ON e.extnamespace = n.oid
            WHERE n.nspname = ?
            ORDER BY extname
            """

            try:
                extensions = self.query_executor.execute_query(
                    connection, extensions_query, params=[schema]
                )
                for ext_row in extensions:
                    ext_name = ext_row.get("extension_name", ext_row.get("EXTENSION_NAME"))
                    if ext_name:
                        drop_sql = f'DROP EXTENSION IF EXISTS "{ext_name}" CASCADE'
                        try:
                            self.query_executor.execute_statement(connection, drop_sql)
                            summary.record_drop(
                                drop_sql, object_type="extension", name=ext_name, schema=schema
                            )
                            self.log.debug(f"Dropped extension: {ext_name}")
                        except Exception as e:
                            self.log.warning(f"Failed to drop extension {ext_name}: {str(e)}")
            except Exception as e:
                self.log.debug(f"Could not query extensions: {str(e)}")

            # 2. Drop all views (they may depend on tables)
            self.log.debug("Dropping all views...")
            self._drop_views(connection, schema, summary)

            # 3. Drop all tables (with CASCADE to handle dependencies)
            self.log.debug("Dropping all tables...")

            tables_query = """
            SELECT tablename as table_name
            FROM pg_tables
            WHERE schemaname = ?
            ORDER BY tablename
            """

            # OBS-04: clean drops the lock table along with history and snapshots.
            # The lock manager auto-creates ``dblift_migration_lock`` on the next
            # ``acquire_migration_lock`` call, so the table reappears on demand.
            tables = self.query_executor.execute_query(connection, tables_query, params=[schema])
            for table_row in tables:
                table_name = table_row.get("table_name", table_row.get("TABLE_NAME"))
                if table_name:
                    qualified_table = self.query_executor.get_schema_qualified_name(
                        schema, table_name
                    )
                    drop_sql = f"DROP TABLE IF EXISTS {qualified_table} CASCADE"
                    try:
                        self.query_executor.execute_statement(connection, drop_sql)
                        summary.record_drop(
                            drop_sql, object_type="table", name=table_name, schema=schema
                        )
                        self.log.debug(f"Dropped table: {table_name}")
                    except Exception as e:
                        self.log.warning(f"Failed to drop table {table_name}: {str(e)}")

            # 4. Drop all sequences
            self.log.debug("Dropping all sequences...")
            self._drop_sequences(connection, schema, summary)

            # 5. Drop all functions and procedures
            self.log.debug("Dropping all functions and procedures...")

            functions_query = """
            SELECT routine_name, routine_type
            FROM information_schema.routines
            WHERE routine_schema = ?
            ORDER BY routine_name
            """

            functions = self.query_executor.execute_query(
                connection, functions_query, params=[schema]
            )
            for func_row in functions:
                func_name = func_row.get("routine_name", func_row.get("ROUTINE_NAME"))
                func_type = func_row.get("routine_type", func_row.get("ROUTINE_TYPE"))
                if func_name and func_type:
                    qualified_func = self.query_executor.get_schema_qualified_name(
                        schema, func_name
                    )
                    if func_type.upper() == "FUNCTION":
                        drop_sql = f"DROP FUNCTION IF EXISTS {qualified_func} CASCADE"
                    else:  # PROCEDURE
                        drop_sql = f"DROP PROCEDURE IF EXISTS {qualified_func} CASCADE"

                    try:
                        self.query_executor.execute_statement(connection, drop_sql)
                        summary.record_drop(
                            drop_sql,
                            object_type=func_type.lower(),
                            name=func_name,
                            schema=schema,
                        )
                        self.log.debug(f"Dropped {func_type.lower()}: {func_name}")
                    except Exception as e:
                        self.log.warning(
                            f"Failed to drop {func_type.lower()} {func_name}: {str(e)}"
                        )

            # 6. Drop all user-defined types (after tables to handle dependencies)
            self.log.debug("Dropping all user-defined types...")

            # OBS-04: no tables are preserved during clean — lock table is
            # dropped too. The list stays empty so the prefix-based type
            # filter below becomes a no-op.
            preserved_tables: List[str] = []

            types_query = """
            SELECT typname as type_name, typtype
            FROM pg_type t
            JOIN pg_namespace n ON t.typnamespace = n.oid
            WHERE n.nspname = ?
              AND t.typtype IN ('c', 'e', 'd')
              AND t.typname NOT LIKE 'pg_%'
            ORDER BY typname
            """

            type_drop_failures = []
            try:
                types = self.query_executor.execute_query(connection, types_query, params=[schema])
                for type_row in types:
                    type_name = type_row.get("type_name", type_row.get("TYPE_NAME"))
                    if type_name:
                        # Check if this type is used by any preserved tables
                        # Use prefix matching to cover type name variants (e.g. dblift_migration_lock_status)
                        type_used_by_preserved = False
                        for preserved_table in preserved_tables:
                            if type_name.lower().startswith(preserved_table.lower()):
                                type_used_by_preserved = True
                                self.log.debug(
                                    f"Preserving type {type_name} (used by preserved table {preserved_table})"
                                )
                                break

                        if type_used_by_preserved:
                            continue

                        # Determine whether it's a DOMAIN or TYPE based on typtype
                        type_category = type_row.get("typtype", "c")
                        qualified_type = self.query_executor.get_schema_qualified_name(
                            schema, type_name
                        )
                        if type_category == "d":
                            drop_sql = f"DROP DOMAIN IF EXISTS {qualified_type} CASCADE"
                            recorded_type = "domain"
                        else:  # 'c' (composite) or 'e' (enum)
                            drop_sql = f"DROP TYPE IF EXISTS {qualified_type} CASCADE"
                            recorded_type = "type"

                        try:
                            self.query_executor.execute_statement(connection, drop_sql)
                            summary.record_drop(
                                drop_sql,
                                object_type=recorded_type,
                                name=type_name,
                                schema=schema,
                            )
                            self.log.debug(f"Dropped {recorded_type}: {type_name}")
                        except Exception as e:
                            error_msg = f"Failed to drop type {type_name}: {str(e)}"
                            type_drop_failures.append(error_msg)
                            self.log.warning(error_msg)
            except Exception as e:
                self.log.debug(f"Could not query user-defined types: {str(e)}")

            # Check for critical failures and fail the operation if necessary
            if type_drop_failures:
                # If we have type drop failures, check if they're due to dependency issues
                critical_failures = []
                for failure in type_drop_failures:
                    # Check if this is a dependency issue that should be handled differently
                    if "cannot drop type" in failure.lower() and "requires it" in failure.lower():
                        # This is a dependency issue - we should have dropped the dependent objects first
                        critical_failures.append(failure)

                if critical_failures:
                    error_msg = (
                        f"Critical failures during schema cleanup: {'; '.join(critical_failures)}"
                    )
                    self.log.error(error_msg)
                    raise Exception(error_msg)

            self.log.debug(
                f"Schema cleanup completed. Executed {len(summary.statements)} statements."
            )

            # Note: Removed explicit commit - let transaction management handle this
            return summary

        except Exception as e:
            error_msg = f"Error cleaning schema {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_clean_preview(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Return the objects a PG clean would drop, without executing the DROPs.

        BUG-03: ``clean --dry-run`` previously fell back to
        ``SchemaIntrospector.get_tables()`` which hides dblift-internal tables.
        Implementing this hook here makes dry-run mirror ``clean_schema``
        exactly — no introspector fallback, no hidden objects.

        Mirrors ``clean_schema`` enumeration: extensions, views, tables,
        sequences, functions/procedures, types/domains.
        """
        summary = CleanExecutionSummary()
        relation_type_names = set()

        # Extensions
        extensions_query = """
        SELECT extname as extension_name
        FROM pg_extension e
        JOIN pg_namespace n ON e.extnamespace = n.oid
        WHERE n.nspname = ?
        ORDER BY extname
        """
        try:
            extensions = self.query_executor.execute_query(
                connection, extensions_query, params=[schema]
            )
            for ext_row in extensions:
                ext_name = ext_row.get("extension_name", ext_row.get("EXTENSION_NAME"))
                if ext_name:
                    drop_sql = f'DROP EXTENSION IF EXISTS "{ext_name}" CASCADE'
                    summary.record_drop(
                        drop_sql, object_type="extension", name=ext_name, schema=schema
                    )
        except Exception as e:
            self.log.debug(f"Could not query extensions for preview: {str(e)}")

        # Views
        views_query = """
        SELECT viewname as view_name
        FROM pg_views
        WHERE schemaname = ?
        ORDER BY viewname
        """
        try:
            views = self.query_executor.execute_query(connection, views_query, params=[schema])
            for row in views:
                name = row.get("view_name", row.get("VIEW_NAME"))
                if name:
                    relation_type_names.add(str(name).lower())
                    qualified = self.query_executor.get_schema_qualified_name(schema, name)
                    drop_sql = f"DROP VIEW IF EXISTS {qualified} CASCADE"
                    summary.record_drop(drop_sql, object_type="view", name=name, schema=schema)
        except Exception as e:
            self.log.debug(f"Could not query views for preview: {str(e)}")

        # Materialized views
        matviews_query = """
        SELECT matviewname as matview_name
        FROM pg_matviews
        WHERE schemaname = ?
        ORDER BY matviewname
        """
        try:
            matviews = self.query_executor.execute_query(
                connection, matviews_query, params=[schema]
            )
            for row in matviews:
                name = row.get("matview_name", row.get("MATVIEW_NAME", row.get("matviewname")))
                if name:
                    relation_type_names.add(str(name).lower())
                    qualified = self.query_executor.get_schema_qualified_name(schema, name)
                    drop_sql = f"DROP MATERIALIZED VIEW IF EXISTS {qualified} CASCADE"
                    summary.record_drop(
                        drop_sql, object_type="materialized_view", name=name, schema=schema
                    )
        except Exception as e:
            self.log.debug(f"Could not query materialized views for preview: {str(e)}")

        # Tables
        tables_query = """
        SELECT tablename as table_name
        FROM pg_tables
        WHERE schemaname = ?
        ORDER BY tablename
        """
        try:
            table_names = set()
            tables = self.query_executor.execute_query(connection, tables_query, params=[schema])
            for row in tables:
                name = row.get("table_name", row.get("TABLE_NAME"))
                if name:
                    table_names.add(str(name).lower())
                    relation_type_names.add(str(name).lower())
                    qualified = self.query_executor.get_schema_qualified_name(schema, name)
                    drop_sql = f"DROP TABLE IF EXISTS {qualified} CASCADE"
                    summary.record_drop(drop_sql, object_type="table", name=name, schema=schema)
        except Exception as e:
            self.log.debug(f"Could not query tables for preview: {str(e)}")

        # Sequences
        sequences_query = """
        SELECT sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = ?
        ORDER BY sequence_name
        """
        try:
            sequences = self.query_executor.execute_query(
                connection, sequences_query, params=[schema]
            )
            for row in sequences:
                name = row.get("sequence_name", row.get("SEQUENCE_NAME"))
                if name:
                    qualified = self.query_executor.get_schema_qualified_name(schema, name)
                    drop_sql = f"DROP SEQUENCE IF EXISTS {qualified} CASCADE"
                    summary.record_drop(drop_sql, object_type="sequence", name=name, schema=schema)
        except Exception as e:
            self.log.debug(f"Could not query sequences for preview: {str(e)}")

        # Functions / Procedures
        functions_query = """
        SELECT routine_name, routine_type
        FROM information_schema.routines
        WHERE routine_schema = ?
        ORDER BY routine_name
        """
        try:
            functions = self.query_executor.execute_query(
                connection, functions_query, params=[schema]
            )
            for row in functions:
                fname = row.get("routine_name", row.get("ROUTINE_NAME"))
                ftype = row.get("routine_type", row.get("ROUTINE_TYPE"))
                if fname and ftype:
                    qualified = self.query_executor.get_schema_qualified_name(schema, fname)
                    if ftype.upper() == "FUNCTION":
                        drop_sql = f"DROP FUNCTION IF EXISTS {qualified} CASCADE"
                    else:
                        drop_sql = f"DROP PROCEDURE IF EXISTS {qualified} CASCADE"
                    summary.record_drop(
                        drop_sql, object_type=ftype.lower(), name=fname, schema=schema
                    )
        except Exception as e:
            self.log.debug(f"Could not query routines for preview: {str(e)}")

        # Types / Domains
        types_query = """
        SELECT typname as type_name, typtype
        FROM pg_type t
        JOIN pg_namespace n ON t.typnamespace = n.oid
        WHERE n.nspname = ?
          AND t.typtype IN ('c', 'e', 'd')
          AND t.typname NOT LIKE 'pg_%'
        ORDER BY typname
        """
        try:
            types = self.query_executor.execute_query(connection, types_query, params=[schema])
            for row in types:
                tname = row.get("type_name", row.get("TYPE_NAME"))
                tcat = row.get("typtype", "c")
                if tname:
                    if tcat == "c" and str(tname).lower() in relation_type_names:
                        continue
                    qualified = self.query_executor.get_schema_qualified_name(schema, tname)
                    if tcat == "d":
                        drop_sql = f"DROP DOMAIN IF EXISTS {qualified} CASCADE"
                        recorded_type = "domain"
                    else:
                        drop_sql = f"DROP TYPE IF EXISTS {qualified} CASCADE"
                        recorded_type = "type"
                    summary.record_drop(
                        drop_sql, object_type=recorded_type, name=tname, schema=schema
                    )
        except Exception as e:
            self.log.debug(f"Could not query types for preview: {str(e)}")

        return summary

    def _drop_views(self, connection: Any, schema: str, summary: CleanExecutionSummary) -> None:
        """Drop all views in the schema."""
        views_query = """
        SELECT viewname as view_name
        FROM pg_views
        WHERE schemaname = ?
        ORDER BY viewname
        """
        self._drop_objects_by_type(
            connection,
            "view",
            views_query,
            [schema],
            "view_name",
            lambda n: (
                f"DROP VIEW IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)} CASCADE"
            ),
            summary,
            schema=schema,
        )

    def _drop_sequences(self, connection: Any, schema: str, summary: CleanExecutionSummary) -> None:
        """Drop all sequences in the schema."""
        sequences_query = """
        SELECT sequence_name
        FROM information_schema.sequences
        WHERE sequence_schema = ?
        ORDER BY sequence_name
        """
        self._drop_objects_by_type(
            connection,
            "sequence",
            sequences_query,
            [schema],
            "sequence_name",
            lambda n: (
                f"DROP SEQUENCE IF EXISTS "
                f"{self.query_executor.get_schema_qualified_name(schema, n)} CASCADE"
            ),
            summary,
            schema=schema,
        )

    def get_database_version(self, connection: Any) -> str:
        """Get PostgreSQL database version information.

        Args:
            connection: Active database connection (provided by Provider)

        Returns:
            str: PostgreSQL database version string
        """
        try:
            # Query PostgreSQL system function for version information
            version_query = "SELECT version() as version"

            result = self.query_executor.execute_query(connection, version_query)

            if result and len(result) > 0:
                version = result[0].get("version", result[0].get("VERSION", "Unknown"))
                return str(version).split(" on ")[0]  # Get just the version part
            else:
                return "Unknown PostgreSQL Version"

        except Exception as e:
            self.log.warning(f"Could not determine PostgreSQL version: {str(e)}")
            return "Unknown PostgreSQL Version"

    def set_current_schema(self, connection: Any, schema: str) -> None:
        """Set the current schema for the session.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name to set as current
        """
        self.log.debug(f"Setting current schema to: {schema}")

        try:
            # SET search_path MUST be executed via createStatement().execute(),
            # not via a prepared update statement.  The PostgreSQL driver
            # driver uses server-side prepared-statement caching for
            # prepareStatement calls; SET commands sent through that path are
            # parsed but may not propagate the session change reliably.
            # createStatement uses the simple-query protocol (same as psql),
            # which guarantees the session-level SET takes effect immediately —
            # analogous to Oracle's ALTER SESSION SET CURRENT_SCHEMA.
            quoted_schema = self.query_executor.get_quoted_schema_name(schema)
            set_schema_sql = f"SET search_path TO {quoted_schema}, public"
            stmt = connection.createStatement()
            try:
                stmt.execute(set_schema_sql)
            finally:
                stmt.close()

            self.log.debug(f"Successfully set current schema to: {schema}")

        except Exception as e:
            error_msg = f"Error setting current schema to {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_columns_query(self, schema: str, table: str) -> Tuple[str, List[Any]]:
        """Get a PostgreSQL-specific query to retrieve column information from a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            tuple: (sql_query, params) using parameterized query to prevent SQL injection
        """
        query = """
        SELECT column_name, data_type
        FROM information_schema.columns
        WHERE table_schema = ? AND table_name = ?
        ORDER BY ordinal_position
        """
        return (query, [schema, table])

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate PostgreSQL-specific SQL to add a column to a table.

        Args:
            schema: Schema name
            table: Table name
            column: Column name to add
            type_def: Column data type definition

        Returns:
            str: SQL for adding the column
        """
        qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
        return f'ALTER TABLE {qualified_table} ADD COLUMN "{column}" {type_def}'

    def get_parameter_placeholders(self, count: int) -> str:
        """Get PostgreSQL-specific parameter placeholders for prepared statements.

        Args:
            count: Number of parameters

        Returns:
            str: Parameter placeholders string
        """
        # Use standard positional placeholders
        return ", ".join(["?"] * count)

    def get_tables(self, connection: Any, schema: str) -> List[str]:
        """Get list of table names in the specified schema.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name

        Returns:
            List of table names in the schema
        """
        self.log.debug(f"Getting tables in schema: {schema}")

        try:
            # Use information_schema to get table names
            query = """
            SELECT table_name
            FROM information_schema.tables
            WHERE table_schema = ? AND table_type = 'BASE TABLE'
            ORDER BY table_name
            """

            result = self.query_executor.execute_query(connection, query, params=[schema])
            tables = [
                str(row["table_name"] if "table_name" in row else row["TABLE_NAME"])
                for row in result
            ]

            self.log.debug(f"Found {len(tables)} tables in schema {schema}: {tables}")

            return tables
        except Exception as e:
            error_msg = f"Error getting tables in schema {schema}: {str(e)}"
            self.log.error(error_msg)
            return []

    def get_schemas(self, connection: Any) -> List[str]:
        """Get list of schema names available in the PostgreSQL database.

        Args:
            connection: Active database connection (provided by Provider)

        Returns:
            List of schema names that the current user can access
        """
        self.log.debug("Getting available schemas from PostgreSQL")

        try:
            # Query to get schemas that the current user can access
            # Exclude system schemas
            query = """
            SELECT schema_name
            FROM information_schema.schemata
            WHERE schema_name NOT IN (
                'information_schema', 'pg_catalog', 'pg_toast',
                'pg_temp_1', 'pg_toast_temp_1'
            )
            AND schema_name NOT LIKE 'pg_temp_%'
            AND schema_name NOT LIKE 'pg_toast_temp_%'
            ORDER BY schema_name
            """

            result = self.query_executor.execute_query(connection, query)
            schemas = [
                str(row["schema_name"] if "schema_name" in row else row["SCHEMA_NAME"])
                for row in result
            ]

            self.log.debug(f"Found {len(schemas)} accessible schemas")

            return schemas
        except Exception as e:
            error_msg = f"Error getting schemas: {str(e)}"
            self.log.error(error_msg)
            return []
