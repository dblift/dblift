"""
SQL Server schema operations and metadata queries.

This module handles SQL Server-specific schema operations including schema creation,
cleaning, and metadata queries for tables, columns, and other database objects.
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from core.logger import Log, NullLog
from core.migration.clean_summary import CleanExecutionSummary
from db.plugins.base_schema_operations import BaseSchemaOperations


@dataclass(frozen=True)
class _CleanCandidate:
    sql: str
    object_type: Optional[str] = None
    name: Optional[str] = None
    details: Optional[Dict[str, str]] = None


class SqlServerSchemaOperations(BaseSchemaOperations):
    """Handles SQL Server schema operations and metadata queries."""

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the schema operations manager.

        Args:
            query_executor: Query executor instance
            log: Optional logger
        """
        self.query_executor = query_executor
        self.log = log if log is not None else NullLog()
        # Schema last applied via set_current_schema — see that method's
        # docstring for why this cache exists (DEFAULT_SCHEMA is catalog-level
        # state on the login, not connection-scoped).
        self._current_schema_set: Optional[str] = None

    def create_schema_if_not_exists(self, connection: Any, schema: str) -> None:
        """Create schema if it doesn't exist in SQL Server.

        Args:
            schema: Schema name to create
        """
        self.log.debug(f"Creating schema if not exists: {schema}")

        try:
            # Check if schema already exists
            check_schema_sql = """
            SELECT COUNT(*) as schema_count
            FROM INFORMATION_SCHEMA.SCHEMATA
            WHERE SCHEMA_NAME = ?
            """

            result = self.query_executor.execute_query(
                connection, check_schema_sql, params=[schema]
            )

            if result and len(result) > 0:
                schema_count = result[0].get("schema_count", result[0].get("SCHEMA_COUNT", 0))

                if schema_count > 0:
                    self.log.debug(f"Schema {schema} already exists")
                    return

            # Schema doesn't exist, create it — route through the centralized
            # quoted-schema helper (which picks `[...]` quoting for SQL Server
            # via _identifier_quote_chars()) so every dblift SQL construction
            # site references schemas identically.
            quoted_schema = self.query_executor.get_quoted_schema_name(schema)
            create_schema_sql = f"CREATE SCHEMA {quoted_schema}"

            try:
                self.query_executor.execute_statement(connection, create_schema_sql)
                # OBS-03: warn so a typo in --db-schema is loud, not silent.
                self.log.warning(
                    f"Schema '{schema}' did not exist — created automatically. "
                    "Check for typos in --db-schema."
                )

            except Exception as e:
                if "already exists" in str(e).lower() or "duplicate" in str(e).lower():
                    self.log.debug(f"Schema {schema} already exists (concurrent creation)")
                else:
                    raise

        except Exception as e:
            error_msg = f"Error creating schema {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def enumerate_clean_candidates(self, connection: Any, schema: str) -> List[_CleanCandidate]:
        """Return the SQL Server objects a clean operation explicitly drops."""
        candidates: List[_CleanCandidate] = []

        # 1. Drop all foreign key constraints first (to avoid dependency issues)
        fk_query = """
        SELECT
            fk.name AS constraint_name,
            SCHEMA_NAME(t.schema_id) AS table_schema,
            t.name AS table_name
        FROM sys.foreign_keys fk
        INNER JOIN sys.tables t ON fk.parent_object_id = t.object_id
        WHERE SCHEMA_NAME(t.schema_id) = ?
        """
        fks = self.query_executor.execute_query(connection, fk_query, params=[schema])
        for fk_row in fks:
            constraint_name = fk_row.get("constraint_name", fk_row.get("CONSTRAINT_NAME"))
            table_name = fk_row.get("table_name", fk_row.get("TABLE_NAME"))
            if constraint_name and table_name:
                qualified_table = self.query_executor.get_schema_qualified_name(schema, table_name)
                candidates.append(
                    _CleanCandidate(
                        sql=f"ALTER TABLE {qualified_table} DROP CONSTRAINT [{constraint_name}]",
                        object_type="foreign_key",
                        name=constraint_name,
                        details={"table": table_name},
                    )
                )

        # 2. Drop all views. Triggers on views are removed implicitly with their parent view.
        views_query = """
        SELECT TABLE_NAME as view_name
        FROM INFORMATION_SCHEMA.VIEWS
        WHERE TABLE_SCHEMA = ?
        """
        views = self.query_executor.execute_query(connection, views_query, params=[schema])
        for view_row in views:
            view_name = view_row.get("view_name", view_row.get("VIEW_NAME"))
            if view_name:
                candidates.append(
                    _CleanCandidate(
                        sql=(
                            "DROP VIEW "
                            f"{self.query_executor.get_schema_qualified_name(schema, view_name)}"
                        ),
                        object_type="view",
                        name=view_name,
                    )
                )

        # 3. Drop all tables. Triggers on tables are removed implicitly with their parent table.
        tables_query = """
        SELECT TABLE_NAME as table_name
        FROM INFORMATION_SCHEMA.TABLES
        WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'
        """
        tables = self.query_executor.execute_query(connection, tables_query, params=[schema])
        temporal_metadata = self._get_temporal_table_metadata(connection, schema)
        for table_row in tables:
            table_name = table_row.get("table_name", table_row.get("TABLE_NAME"))
            if not table_name:
                continue
            qualified_table = self.query_executor.get_schema_qualified_name(schema, table_name)
            table_info = temporal_metadata.get(table_name.lower())
            if table_info and table_info.get("temporal_type") == 2:
                candidates.append(
                    _CleanCandidate(
                        sql=f"ALTER TABLE {qualified_table} SET (SYSTEM_VERSIONING = OFF)"
                    )
                )
            candidates.append(
                _CleanCandidate(
                    sql=f"DROP TABLE {qualified_table}",
                    object_type="table",
                    name=table_name,
                )
            )

        # 4. Drop all stored procedures and functions
        routines_query = """
        SELECT ROUTINE_NAME as routine_name, ROUTINE_TYPE as routine_type
        FROM INFORMATION_SCHEMA.ROUTINES
        WHERE ROUTINE_SCHEMA = ?
        """
        routines = self.query_executor.execute_query(connection, routines_query, params=[schema])
        for routine_row in routines:
            routine_name = routine_row.get("routine_name", routine_row.get("ROUTINE_NAME"))
            routine_type = routine_row.get("routine_type", routine_row.get("ROUTINE_TYPE"))
            if routine_name and routine_type:
                qualified_routine = self.query_executor.get_schema_qualified_name(
                    schema, routine_name
                )
                normalized_type = routine_type.lower()
                drop_keyword = "PROCEDURE" if routine_type.upper() == "PROCEDURE" else "FUNCTION"
                candidates.append(
                    _CleanCandidate(
                        sql=f"DROP {drop_keyword} {qualified_routine}",
                        object_type=normalized_type,
                        name=routine_name,
                    )
                )

        # 5. Drop all sequences (SQL Server 2012+)
        sequences_query = """
        SELECT s.name as sequence_name
        FROM sys.sequences s
        INNER JOIN sys.schemas sc ON s.schema_id = sc.schema_id
        WHERE sc.name = ?
        """
        try:
            sequences = self.query_executor.execute_query(
                connection, sequences_query, params=[schema]
            )
            for seq_row in sequences:
                seq_name = seq_row.get("sequence_name", seq_row.get("SEQUENCE_NAME"))
                if seq_name:
                    candidates.append(
                        _CleanCandidate(
                            sql=(
                                "DROP SEQUENCE "
                                f"{self.query_executor.get_schema_qualified_name(schema, seq_name)}"
                            ),
                            object_type="sequence",
                            name=seq_name,
                        )
                    )
        except Exception as e:
            # Sequences might not be supported in older SQL Server versions
            self.log.debug(
                f"Could not query sequences (might be older SQL Server version): {str(e)}"
            )

        # 6. Drop all user-defined types in the schema
        types_query = """
        SELECT t.name as type_name
        FROM sys.types t
        INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ? AND t.is_user_defined = 1
        """
        try:
            types = self.query_executor.execute_query(connection, types_query, params=[schema])
            for type_row in types:
                type_name = type_row.get("type_name", type_row.get("TYPE_NAME"))
                if type_name:
                    candidates.append(
                        _CleanCandidate(
                            sql=(
                                "DROP TYPE "
                                f"{self.query_executor.get_schema_qualified_name(schema, type_name)}"
                            ),
                            object_type="type",
                            name=type_name,
                        )
                    )
        except Exception as e:
            self.log.debug(f"Could not query user-defined types: {str(e)}")

        # 7. Drop all synonyms
        synonyms_query = """
        SELECT s.name as synonym_name
        FROM sys.synonyms s
        INNER JOIN sys.schemas sc ON s.schema_id = sc.schema_id
        WHERE sc.name = ?
        """
        try:
            synonyms = self.query_executor.execute_query(
                connection, synonyms_query, params=[schema]
            )
            for syn_row in synonyms:
                syn_name = syn_row.get("synonym_name", syn_row.get("SYNONYM_NAME"))
                if syn_name:
                    candidates.append(
                        _CleanCandidate(
                            sql=(
                                "DROP SYNONYM "
                                f"{self.query_executor.get_schema_qualified_name(schema, syn_name)}"
                            ),
                            object_type="synonym",
                            name=syn_name,
                        )
                    )
        except Exception as e:
            self.log.debug(f"Could not query synonyms: {str(e)}")

        # 8. Drop full-text catalogs. Full-text indexes are dropped implicitly
        # when their owning table is dropped (step 3), but the catalog that
        # held them is a separate object that survives the table drop and
        # must be dropped explicitly, after the tables that might reference
        # it. sys.fulltext_catalogs has no schema_id — catalogs are not
        # schema-owned in SQL Server — so it can't be filtered directly like
        # every other object type above. Instead it is scoped indirectly,
        # via the only path that connects a catalog to a schema:
        # sys.fulltext_indexes.object_id -> sys.tables.schema_id ->
        # sys.schemas. Only a catalog referenced by at least one full-text
        # index on a table in the target schema is enumerated here.
        fulltext_catalogs_query = """
        SELECT DISTINCT fc.name AS catalog_name
        FROM sys.fulltext_catalogs fc
        INNER JOIN sys.fulltext_indexes fi ON fi.fulltext_catalog_id = fc.fulltext_catalog_id
        INNER JOIN sys.tables t ON fi.object_id = t.object_id
        INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
        WHERE s.name = ?
        """
        try:
            fulltext_catalogs = self.query_executor.execute_query(
                connection, fulltext_catalogs_query, params=[schema]
            )
            for catalog_row in fulltext_catalogs:
                catalog_name = catalog_row.get("catalog_name", catalog_row.get("CATALOG_NAME"))
                if catalog_name:
                    candidates.append(
                        _CleanCandidate(
                            sql=f"DROP FULLTEXT CATALOG [{catalog_name}]",
                            object_type="fulltext_catalog",
                            name=catalog_name,
                        )
                    )
        except Exception as e:
            # Full-text search might not be installed/enabled on this instance.
            self.log.debug(f"Could not query full-text catalogs: {str(e)}")

        return candidates

    def get_clean_preview(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Return the objects a SQL Server clean would explicitly drop."""
        summary = CleanExecutionSummary()
        for candidate in self.enumerate_clean_candidates(connection, schema):
            summary.add_statement(candidate.sql)
            if candidate.object_type and candidate.name:
                summary.add_object(
                    candidate.object_type,
                    candidate.name,
                    schema=schema,
                    details=candidate.details,
                )
        return summary

    def clean_schema(self, connection: Any, schema: str) -> CleanExecutionSummary:
        """Clean all objects from the specified SQL Server schema.

        This drops all user-created tables, views, stored procedures, functions,
        and other objects in the schema, leaving only the empty schema structure.

        Args:
            schema: Name of the schema to clean

        Returns:
            CleanExecutionSummary containing executed statements and dropped objects.
        """
        self.log.debug(f"Cleaning SQL Server schema: {schema}")

        summary = CleanExecutionSummary()

        try:
            for candidate in self.enumerate_clean_candidates(connection, schema):
                try:
                    self.query_executor.execute_statement(connection, candidate.sql)
                    summary.add_statement(candidate.sql)
                    if candidate.object_type and candidate.name:
                        summary.add_object(
                            candidate.object_type,
                            candidate.name,
                            schema=schema,
                            details=candidate.details,
                        )
                        self.log.debug(f"Dropped {candidate.object_type}: {candidate.name}")
                    elif "SYSTEM_VERSIONING" in candidate.sql.upper():
                        self.log.debug(f"Executed clean prerequisite: {candidate.sql}")
                except Exception as e:
                    label = candidate.name or candidate.sql
                    self.log.warning(f"Failed to drop {label}: {str(e)}")

            self.log.debug(
                f"Schema cleanup completed. Executed {len(summary.statements)} statements."
            )
            return summary

        except Exception as e:
            error_msg = f"Error cleaning schema {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def _get_temporal_table_metadata(
        self, connection: Any, schema: str
    ) -> Dict[str, Dict[str, Any]]:
        """Retrieve temporal metadata for tables in the schema.

        Args:
            connection: Active database connection (provided by Provider)
            schema: Schema name
        """
        query = """
        SELECT
            t.name AS table_name,
            t.temporal_type,
            ht.name AS history_table,
            hs.name AS history_schema
        FROM sys.tables t
        INNER JOIN sys.schemas s ON t.schema_id = s.schema_id
        LEFT JOIN sys.tables ht ON t.history_table_id = ht.object_id
        LEFT JOIN sys.schemas hs ON ht.schema_id = hs.schema_id
        WHERE s.name = ?
        """

        metadata: Dict[str, Dict[str, Any]] = {}
        try:
            rows = self.query_executor.execute_query(connection, query, params=[schema])
            for row in rows or []:
                table_name = row.get("table_name", row.get("TABLE_NAME"))
                if not table_name:
                    continue
                metadata[table_name.lower()] = {
                    "temporal_type": row.get("temporal_type", row.get("TEMPORAL_TYPE")),
                    "history_table": row.get("history_table", row.get("HISTORY_TABLE")),
                    "history_schema": row.get("history_schema", row.get("HISTORY_SCHEMA")),
                }
        except Exception as e:
            self.log.warning(f"Failed to read temporal metadata for schema {schema}: {str(e)}")

        return metadata

    def get_database_version(self, connection: Any) -> str:
        """Get SQL Server database version information.

        Returns:
            str: SQL Server database version string
        """
        try:
            # Query SQL Server system function for version information
            version_query = "SELECT @@VERSION as version"

            result = self.query_executor.execute_query(connection, version_query)

            if result and len(result) > 0:
                version = result[0].get("version", result[0].get("VERSION", "Unknown"))
                return str(version).split("\n")[0]  # Get just the first line
            else:
                return "Unknown SQL Server Version"

        except Exception as e:
            self.log.warning(f"Could not determine SQL Server version: {str(e)}")
            return "Unknown SQL Server Version"

    def set_current_schema(self, connection: Any, schema: str) -> None:
        """Align the connecting user's default schema so unqualified DDL lands here.

        SQL Server has no session-scoped search path; unqualified object
        names resolve against the connecting database user's
        DEFAULT_SCHEMA. ``ALTER USER ... WITH DEFAULT_SCHEMA`` takes effect
        immediately within the current session (no reconnect required).

        Unlike every other dialect's mechanism, DEFAULT_SCHEMA is
        catalog-level state on the login (``sys.database_principals``), not
        connection-scoped, so it is visible to and overwritable by any other
        connection authenticating as the same login. To limit the blast
        radius of that: (1) a call with the same schema already applied is a
        no-op — no repeated writes to the shared catalog row; (2) before
        writing, the login's current DEFAULT_SCHEMA is compared against what
        was set here last — a mismatch means another process sharing this
        login changed it, which is logged loudly since unqualified DDL
        placement is no longer reliable in that case. A dedicated SQL Server
        login per ``--db-schema`` avoids this entirely.

        Args:
            schema: Schema name to make the connecting user's default
        """
        if self._current_schema_set == schema:
            return
        try:
            rows = self.query_executor.execute_query(connection, "SELECT USER_NAME() AS db_user")
            current_user = rows[0].get("db_user") if rows else None
            if not current_user:
                raise RuntimeError("could not determine the connecting database user")

            catalog_rows = self.query_executor.execute_query(
                connection,
                "SELECT DEFAULT_SCHEMA_NAME AS default_schema "
                "FROM sys.database_principals WHERE name = ?",
                params=[current_user],
            )
            catalog_schema = catalog_rows[0].get("default_schema") if catalog_rows else None
            if (
                self._current_schema_set is not None
                and catalog_schema is not None
                and catalog_schema != self._current_schema_set
            ):
                self.log.warning(
                    f"SQL Server login '{current_user}' DEFAULT_SCHEMA is '{catalog_schema}' "
                    f"but dblift set it to '{self._current_schema_set}' earlier on this "
                    f"connection — another process changed it. If this login is shared across "
                    f"concurrent dblift runs with different --db-schema values, unqualified DDL "
                    f"placement is not reliable; use a dedicated login per schema."
                )

            quoted_user = self.query_executor.get_quoted_schema_name(current_user)
            quoted_schema = self.query_executor.get_quoted_schema_name(schema)
            self.query_executor.execute_statement(
                connection, f"ALTER USER {quoted_user} WITH DEFAULT_SCHEMA = {quoted_schema}"
            )
            self._current_schema_set = schema
        except Exception as e:
            self.log.warning(
                f"SQL Server: could not set the connecting user's default schema to "
                f"'{schema}'; unqualified object names may resolve against a "
                f"different schema than --db-schema ({e})"
            )

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[str]]:
        """Get a SQL Server-specific query to retrieve column information from a table.

        Args:
            schema: Schema name
            table: Table name

        Returns:
            tuple: (sql, params) with ? placeholders — no f-string interpolation
        """
        sql = """
        SELECT COLUMN_NAME as column_name, DATA_TYPE as data_type
        FROM INFORMATION_SCHEMA.COLUMNS
        WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
        ORDER BY ORDINAL_POSITION
        """
        return (sql, [schema, table])

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate SQL Server-specific SQL to add a column to a table.

        Args:
            schema: Schema name
            table: Table name
            column: Column name to add
            type_def: Column data type definition

        Returns:
            str: SQL for adding the column
        """
        qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
        return f"ALTER TABLE {qualified_table} ADD [{column}] {type_def}"

    def get_parameter_placeholders(self, count: int) -> str:
        """Get SQL Server-specific parameter placeholders for prepared statements.

        Args:
            count: Number of parameters

        Returns:
            str: Parameter placeholders string
        """
        # SQL Server uses ? placeholders
        return ", ".join(["?" for _ in range(count)])

    def get_tables(self, connection: Any, schema: str) -> List[str]:
        """Get list of table names in the specified schema.

        Args:
            schema: Schema name

        Returns:
            List of table names in the schema
        """
        self.log.debug(f"Getting tables in schema: {schema}")

        try:
            # Use INFORMATION_SCHEMA to get table names
            query = """
            SELECT TABLE_NAME as table_name
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = ? AND TABLE_TYPE = 'BASE TABLE'
            ORDER BY TABLE_NAME
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
        """Get list of schema names available in the SQL Server database.

        Returns:
            List of schema names that the current user can access
        """
        self.log.debug("Getting available schemas from SQL Server")

        try:
            # Query to get schemas that the current user can access
            # Exclude system schemas
            query = """
            SELECT SCHEMA_NAME as schema_name
            FROM INFORMATION_SCHEMA.SCHEMATA
            WHERE SCHEMA_NAME NOT IN (
                'information_schema', 'sys', 'db_owner', 'db_accessadmin',
                'db_securityadmin', 'db_ddladmin', 'db_backupoperator',
                'db_datareader', 'db_datawriter', 'db_denydatareader',
                'db_denydatawriter', 'guest'
            )
            ORDER BY SCHEMA_NAME
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
