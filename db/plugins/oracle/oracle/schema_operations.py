"""
Oracle schema operations and metadata queries.

This module handles Oracle-specific schema operations including schema creation,
cleaning, and metadata queries for tables, columns, and other database objects.
"""

import re
import secrets
from typing import Any, Dict, List, Optional, Set

from core.logger import Log, NullLog
from core.migration.clean_summary import CleanExecutionSummary
from db.exceptions import DB_OPERATION_EXCEPTIONS
from db.plugins.base_schema_operations import BaseSchemaOperations


class OracleSchemaOperations(BaseSchemaOperations):
    """Handles Oracle schema operations and metadata queries."""

    def __init__(self, query_executor: Any, log: Optional[Log] = None) -> None:
        """Initialize the schema operations manager.

        Args:
            query_executor: Query executor instance
            log: Optional logger
        """
        self.query_executor = query_executor
        self.log = log if log is not None else NullLog()

    @staticmethod
    def _to_int(value: Any) -> int:
        """Coerce driver numeric types (including BigDecimal) or strings to int safely."""
        try:
            if value is None:
                return 0
            # driver BigDecimal exposes toString; fall back to str then float->int
            if hasattr(value, "intValue"):
                return int(value.intValue())
            if isinstance(value, (int,)):
                return int(value)
            if isinstance(value, float):
                return int(value)
            s = str(value).strip()
            if s == "":
                return 0
            # Some drivers return decimal strings like '1' or '1.0'
            if "." in s:
                return int(float(s))
            return int(s)
        except DB_OPERATION_EXCEPTIONS:
            # Intentional: non-numeric Oracle count value falls back to 0
            return 0

    def create_schema_if_not_exists(self, connection: Any, schema: str) -> None:
        """Create schema (user) if it doesn't exist in Oracle.

        In Oracle, schemas are users, so we create a user if it doesn't exist.
        This requires appropriate privileges (typically DBA privileges).

        Args:
            schema: Schema/user name to create
        """
        self.log.debug(f"Creating schema (user) if not exists: {schema}")

        try:
            # Check if user already exists.
            # Use case-sensitive matching: dblift always creates the user via a
            # double-quoted identifier (see get_quoted_schema_name below), which
            # preserves the exact case the caller supplied. Oracle's ALL_USERS
            # view stores the owner with the exact case the CREATE USER DDL
            # recorded, so we must match that case exactly — otherwise we'd
            # report "DBO already exists" when the caller asked for a distinct
            # lowercase "dbo" schema.
            clean_schema = schema.replace('"', "").strip()
            check_user_sql = """
            SELECT COUNT(*) as user_count
            FROM ALL_USERS
            WHERE username = ?
            """
            result = self.query_executor.execute_query(
                connection, check_user_sql, params=[clean_schema]
            )

            if result and len(result) > 0:
                raw_count = result[0].get("user_count", result[0].get("USER_COUNT", 0))
                user_count = self._to_int(raw_count)
                if user_count > 0:
                    self.log.debug(f"Schema (user) {schema} already exists")
                    return

            # User doesn't exist, try to create it with various privilege levels.
            # Use the centralized quoted-schema helper so the user is created
            # with the exact case the caller supplied (case-preserving via
            # double-quoted identifier), and every other dblift SQL
            # construction site references it identically.
            # OBS-03: warn so a typo in --db-schema is loud, not silent.
            self.log.warning(
                f"Schema (user) '{schema}' did not exist — creating automatically. "
                "Check for typos in --db-schema."
            )
            quoted_schema = self.query_executor.get_quoted_schema_name(clean_schema)

            # Keep generated quoted passwords below Oracle's 30-byte identifier limit.
            temp_password = secrets.token_urlsafe(12)

            # Try full privileges first
            try:
                create_user_sql = f"""
                CREATE USER {quoted_schema}
                IDENTIFIED BY "{temp_password}"
                DEFAULT TABLESPACE USERS
                TEMPORARY TABLESPACE TEMP
                QUOTA UNLIMITED ON USERS
                """
                self.query_executor.execute_statement(connection, create_user_sql)

                # Grant full privileges
                # Note: RESOURCE role includes CREATE TABLE, CREATE PROCEDURE, CREATE TRIGGER, CREATE TYPE, CREATE SEQUENCE
                # Note: CREATE MATERIALIZED VIEW requires explicit CREATE TABLE grant (not through RESOURCE role)
                grant_sql = f"GRANT CONNECT, RESOURCE, CREATE TABLE, CREATE VIEW, CREATE MATERIALIZED VIEW, CREATE DATABASE LINK TO {quoted_schema}"
                self.query_executor.execute_statement(connection, grant_sql)

                self.log.debug(f"Successfully created schema (user) with full privileges: {schema}")
                return

            except DB_OPERATION_EXCEPTIONS as e1:
                self.log.debug(f"Could not create user with full privileges: {e1}")

            # Try minimal privileges
            try:
                create_user_sql = f"""
                CREATE USER {quoted_schema}
                IDENTIFIED BY "{temp_password}"
                DEFAULT TABLESPACE USERS
                TEMPORARY TABLESPACE TEMP
                """
                self.query_executor.execute_statement(connection, create_user_sql)

                # Grant minimal privileges, quota, and required object privileges
                grant_sql = f"GRANT CONNECT, CREATE ANY TABLE, CREATE ANY VIEW, CREATE ANY PROCEDURE, CREATE SEQUENCE, CREATE MATERIALIZED VIEW, CREATE DATABASE LINK, UNLIMITED TABLESPACE TO {quoted_schema}"
                self.query_executor.execute_statement(connection, grant_sql)

                self.log.debug(
                    f"Successfully created schema (user) with minimal privileges: {schema}"
                )
                return

            except DB_OPERATION_EXCEPTIONS as e2:
                self.log.debug(f"Could not create user with minimal privileges: {e2}")

            # Try to grant privileges to existing user
            try:
                # Try to grant privileges and quota to existing user
                try:
                    # Note: RESOURCE includes CREATE PROCEDURE, CREATE TABLE, CREATE TRIGGER, CREATE TYPE, CREATE SEQUENCE
                    # Note: CREATE MATERIALIZED VIEW requires explicit CREATE TABLE grant (not through RESOURCE role)
                    grant_sql = f"GRANT CONNECT, RESOURCE, CREATE TABLE, CREATE VIEW, CREATE MATERIALIZED VIEW, CREATE DATABASE LINK, UNLIMITED TABLESPACE TO {quoted_schema}"
                    self.query_executor.execute_statement(connection, grant_sql)

                    self.log.debug(
                        f"Granted privileges and quota to existing schema (user): {schema}"
                    )
                    return
                except DB_OPERATION_EXCEPTIONS as e4:
                    self.log.debug(f"Could not grant privileges and quota: {e4}")

                # Try to grant just required object privileges and quota (in case user has other privileges)
                try:
                    grant_sql = f"GRANT CREATE ANY TABLE, CREATE ANY VIEW, CREATE ANY PROCEDURE, CREATE SEQUENCE, CREATE MATERIALIZED VIEW, CREATE DATABASE LINK, UNLIMITED TABLESPACE TO {quoted_schema}"
                    self.query_executor.execute_statement(connection, grant_sql)

                    self.log.debug(
                        f"Granted object privileges and quota to existing schema (user): {schema}"
                    )
                    return
                except DB_OPERATION_EXCEPTIONS as e5:
                    self.log.debug(f"Could not grant object privileges and quota: {e5}")

                # Try to grant just UNLIMITED TABLESPACE (in case user has all needed privileges)
                try:
                    grant_sql = f"GRANT UNLIMITED TABLESPACE TO {quoted_schema}"
                    self.query_executor.execute_statement(connection, grant_sql)

                    self.log.debug(
                        f"Granted UNLIMITED TABLESPACE to existing schema (user): {schema}"
                    )
                    return
                except DB_OPERATION_EXCEPTIONS as e6:
                    self.log.debug(f"Could not grant UNLIMITED TABLESPACE: {e6}")

            except DB_OPERATION_EXCEPTIONS as e3:
                if "insufficient privileges" in str(e3).lower():
                    self.log.warning(
                        f"Cannot create or grant privileges to schema {schema}. "
                        f"Please create the user manually or run as DBA."
                    )
                else:
                    self.log.warning(f"Unexpected error granting privileges: {e3}")
                # Continue without error - we might still be able to create objects in this schema

        except DB_OPERATION_EXCEPTIONS as e:
            error_msg = f"Error creating schema {schema}: {str(e)}"
            self.log.error(error_msg)
            # Don't raise for schema creation failures - they're often permission-related
            # and not critical for migration operations on existing schemas

    def clean_schema(self, connection: Any, schema_name: str) -> CleanExecutionSummary:
        """Clean all objects from the specified Oracle schema.

        This drops all user-created tables, views, sequences, procedures, functions,
        packages, triggers, and other objects in the schema, leaving only the
        empty schema structure.

        Args:
            schema_name: Name of the schema to clean

        Returns:
            CleanExecutionSummary: Executed statements and dropped object metadata.
        """
        self.log.debug(f"Cleaning Oracle schema: {schema_name}")

        summary = CleanExecutionSummary()
        # Remove quotes if present for queries (Oracle data dictionary queries)
        clean_schema = schema_name.replace('"', "").strip()

        try:
            # Set current schema for the cleanup operations
            self.set_current_schema(connection, schema_name)

            # Execute all 8 phases in order
            self._drop_db_links(connection, schema_name, clean_schema, summary)
            self._drop_views(connection, schema_name, clean_schema, summary)
            self._drop_materialized_views(connection, schema_name, clean_schema, summary)
            self._drop_tables(connection, schema_name, clean_schema, summary)
            self._drop_sequences(connection, schema_name, clean_schema, summary)
            self._drop_program_objects(connection, schema_name, clean_schema, summary)
            self._drop_synonyms(connection, schema_name, clean_schema, summary)
            self._drop_remaining_objects(connection, schema_name, clean_schema, summary)

            self.log.debug(
                f"Schema cleanup completed. Executed {len(summary.statements)} statements."
            )

            return summary

        except DB_OPERATION_EXCEPTIONS as e:
            error_msg = f"Error cleaning schema {schema_name}: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_clean_preview(self, connection: Any, schema_name: str) -> CleanExecutionSummary:
        """Return the objects an Oracle clean would drop, without executing the DROPs.

        BUG-03: dry-run must mirror ``clean_schema`` so the user sees every
        object — including dblift-internal tables (history / lock).
        Enumerates the same 8 categories ``clean_schema`` covers
        (DB links, views, materialized views, tables, sequences, program
        objects, synonyms, remaining objects).
        """
        summary = CleanExecutionSummary()
        clean_schema = schema_name.replace('"', "").strip()

        # 1. DB links (no schema param — owned by SESSION_USER)
        try:
            rows = self.query_executor.execute_query(
                connection,
                """SELECT db_link FROM ALL_DB_LINKS
                   WHERE owner = SYS_CONTEXT('USERENV', 'SESSION_USER')
                   ORDER BY db_link""",
            )
            for row in rows:
                name = row.get("db_link", row.get("DB_LINK"))
                if name:
                    clean_name = name.replace('"', "").strip()
                    summary.record_drop(
                        f'DROP DATABASE LINK "{clean_name}"',
                        "database_link",
                        name,
                        schema=schema_name,
                    )
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query DB links for preview: {str(e)}")

        # 2. Views
        try:
            rows = self.query_executor.execute_query(
                connection,
                "SELECT view_name FROM ALL_VIEWS WHERE owner = ? ORDER BY view_name",
                params=[clean_schema],
            )
            for row in rows:
                name = row.get("view_name", row.get("VIEW_NAME"))
                if name:
                    qualified = self.query_executor.get_schema_qualified_name(schema_name, name)
                    summary.record_drop(f"DROP VIEW {qualified}", "view", name, schema=schema_name)
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query views for preview: {str(e)}")

        # 3. Materialized views
        try:
            rows = self.query_executor.execute_query(
                connection,
                "SELECT mview_name FROM ALL_MVIEWS WHERE owner = ? ORDER BY mview_name",
                params=[clean_schema],
            )
            for row in rows:
                name = row.get("mview_name", row.get("MVIEW_NAME"))
                if name:
                    qualified = self.query_executor.get_schema_qualified_name(schema_name, name)
                    summary.record_drop(
                        f"DROP MATERIALIZED VIEW {qualified}",
                        "materialized_view",
                        name,
                        schema=schema_name,
                    )
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query materialized views for preview: {str(e)}")

        # 4. Tables
        try:
            rows = self.query_executor.execute_query(
                connection,
                (
                    "SELECT t.table_name FROM ALL_TABLES t "
                    "WHERE t.owner = ? AND t.table_name NOT LIKE 'BIN$%' "
                    "AND NOT EXISTS ("
                    "    SELECT 1 FROM ALL_MVIEWS mv "
                    "    WHERE mv.owner = t.owner "
                    "      AND mv.mview_name = t.table_name"
                    ") "
                    "ORDER BY t.table_name"
                ),
                params=[clean_schema],
            )
            for row in rows:
                name = row.get("table_name", row.get("TABLE_NAME"))
                if name:
                    qualified = self.query_executor.get_schema_qualified_name(schema_name, name)
                    summary.record_drop(
                        f"DROP TABLE {qualified} CASCADE CONSTRAINTS",
                        "table",
                        name,
                        schema=schema_name,
                    )
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query tables for preview: {str(e)}")

        # 5. Sequences (skip system-generated identity sequences, same as clean_schema)
        try:
            rows = self.query_executor.execute_query(
                connection,
                "SELECT sequence_name FROM ALL_SEQUENCES WHERE sequence_owner = ? ORDER BY sequence_name",
                params=[clean_schema],
            )
            for row in rows:
                name = row.get("sequence_name", row.get("SEQUENCE_NAME"))
                if name and not self.is_system_generated_sequence(connection, schema_name, name):
                    qualified = self.query_executor.get_schema_qualified_name(schema_name, name)
                    summary.record_drop(
                        f"DROP SEQUENCE {qualified}", "sequence", name, schema=schema_name
                    )
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query sequences for preview: {str(e)}")

        # 6. Program objects (procedures, functions, packages, types)
        try:
            rows = self.query_executor.execute_query(
                connection,
                (
                    "SELECT object_name, object_type FROM ALL_OBJECTS WHERE owner = ? "
                    "AND object_type IN ('PROCEDURE', 'FUNCTION', 'PACKAGE', "
                    "'PACKAGE BODY', 'TYPE', 'TYPE BODY') "
                    "AND object_name NOT LIKE 'BIN$%' "
                    "ORDER BY DECODE(object_type, 'PACKAGE BODY', 1, 'TYPE BODY', 1, 2), object_name"
                ),
                params=[clean_schema],
            )
            for row in rows:
                name = row.get("object_name", row.get("OBJECT_NAME"))
                otype = row.get("object_type", row.get("OBJECT_TYPE"))
                if name and otype:
                    qualified = self.query_executor.get_schema_qualified_name(schema_name, name)
                    if otype == "TYPE":
                        drop_sql = f"DROP {otype} {qualified} FORCE"
                    else:
                        drop_sql = f"DROP {otype} {qualified}"
                    summary.record_drop(
                        drop_sql,
                        otype.lower().replace(" ", "_"),
                        name,
                        schema=schema_name,
                    )
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query program objects for preview: {str(e)}")

        # 7. Synonyms
        try:
            rows = self.query_executor.execute_query(
                connection,
                "SELECT synonym_name FROM ALL_SYNONYMS WHERE owner = ? ORDER BY synonym_name",
                params=[clean_schema],
            )
            for row in rows:
                name = row.get("synonym_name", row.get("SYNONYM_NAME"))
                if name:
                    qualified = self.query_executor.get_schema_qualified_name(schema_name, name)
                    summary.record_drop(
                        f"DROP SYNONYM {qualified}", "synonym", name, schema=schema_name
                    )
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query synonyms for preview: {str(e)}")

        # 8. Remaining objects (triggers, etc.)
        try:
            rows = self.query_executor.execute_query(
                connection,
                (
                    "SELECT object_name, object_type FROM ALL_OBJECTS WHERE owner = ? "
                    "AND object_type IN ('PROCEDURE', 'FUNCTION', 'PACKAGE', "
                    "'PACKAGE BODY', 'TYPE', 'TYPE BODY', 'TRIGGER') "
                    "AND object_name NOT LIKE 'BIN$%' ORDER BY object_name"
                ),
                params=[clean_schema],
            )
            for row in rows:
                name = row.get("object_name", row.get("OBJECT_NAME"))
                otype = row.get("object_type", row.get("OBJECT_TYPE"))
                if name and otype:
                    qualified = self.query_executor.get_schema_qualified_name(schema_name, name)
                    summary.record_drop(
                        f"DROP {otype} {qualified}",
                        otype.lower().replace(" ", "_"),
                        name,
                        schema=schema_name,
                    )
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query remaining objects for preview: {str(e)}")

        return summary

    def _drop_db_links(
        self,
        connection: Any,
        schema_name: str,
        clean_schema: str,
        summary: CleanExecutionSummary,
    ) -> None:
        """Drop private database links owned by the current session user.

        Note: clean_schema is not used in the WHERE clause (DB links are scoped to
        SESSION_USER, not a schema parameter); it is accepted for signature consistency.
        """
        self.log.debug("Dropping private database links...")

        db_links_query = """
        SELECT db_link, owner
        FROM ALL_DB_LINKS
        WHERE owner = SYS_CONTEXT('USERENV', 'SESSION_USER')
        ORDER BY db_link
        """

        try:
            db_links = self.query_executor.execute_query(connection, db_links_query)
            self.log.debug(f"Found {len(db_links)} database links to drop")
            for link_row in db_links:
                link_name = link_row.get("db_link", link_row.get("DB_LINK"))
                owner = link_row.get("owner", link_row.get("OWNER", "unknown"))
                self.log.debug(f"Processing database link: {link_name} (owner: {owner})")
                if link_name:
                    clean_link_name = link_name.replace('"', "").strip()
                    drop_sql = f'DROP DATABASE LINK "{clean_link_name}"'
                    try:
                        self.query_executor.execute_statement(connection, drop_sql)
                        summary.record_drop(
                            drop_sql, "database_link", link_name, schema=schema_name
                        )
                        self.log.debug(f"Dropped private database link: {link_name}")
                    except DB_OPERATION_EXCEPTIONS as e:
                        error_msg = f"Failed to drop database link {link_name}: {str(e)}"
                        summary.add_error(error_msg)
                        self.log.warning(error_msg)
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query private database links: {str(e)}")

    def _drop_views(
        self,
        connection: Any,
        schema_name: str,
        clean_schema: str,
        summary: CleanExecutionSummary,
    ) -> None:
        """Drop all views in the schema."""
        self.log.debug("Dropping all views...")

        views_query = """
        SELECT view_name
        FROM ALL_VIEWS
        WHERE owner = ?
        ORDER BY view_name
        """

        views = self.query_executor.execute_query(connection, views_query, params=[clean_schema])
        for view_row in views:
            view_name = view_row.get("view_name", view_row.get("VIEW_NAME"))
            if view_name:
                qualified_view = self.query_executor.get_schema_qualified_name(
                    schema_name, view_name
                )
                drop_sql = f"DROP VIEW {qualified_view}"
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    summary.record_drop(drop_sql, "view", view_name, schema=schema_name)
                    self.log.debug(f"Dropped view: {view_name}")
                except DB_OPERATION_EXCEPTIONS as e:
                    error_msg = f"Failed to drop view {view_name}: {str(e)}"
                    summary.add_error(error_msg)
                    self.log.warning(error_msg)

    def _drop_materialized_views(
        self,
        connection: Any,
        schema_name: str,
        clean_schema: str,
        summary: CleanExecutionSummary,
    ) -> None:
        """Drop all materialized views in the schema."""
        self.log.debug("Dropping all materialized views...")

        mviews_query = """
        SELECT mview_name
        FROM ALL_MVIEWS
        WHERE owner = ?
        ORDER BY mview_name
        """

        mviews = self.query_executor.execute_query(connection, mviews_query, params=[clean_schema])
        for mview_row in mviews:
            mview_name = mview_row.get("mview_name", mview_row.get("MVIEW_NAME"))
            if mview_name:
                qualified_mview = self.query_executor.get_schema_qualified_name(
                    schema_name, mview_name
                )
                drop_sql = f"DROP MATERIALIZED VIEW {qualified_mview}"
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    summary.record_drop(
                        drop_sql, "materialized_view", mview_name, schema=schema_name
                    )
                    self.log.debug(f"Dropped materialized view: {mview_name}")
                except DB_OPERATION_EXCEPTIONS as e:
                    error_msg = f"Failed to drop materialized view {mview_name}: {str(e)}"
                    summary.add_error(error_msg)
                    self.log.warning(error_msg)

    def _drop_tables(
        self,
        connection: Any,
        schema_name: str,
        clean_schema: str,
        summary: CleanExecutionSummary,
    ) -> None:
        """Drop all tables, handling reference-partitioned children before parents."""
        self.log.debug("Dropping all tables...")

        # Identify reference-partitioned table relationships
        ref_partition_query = """
        SELECT DISTINCT
            c.table_name AS child_table,
            p.table_name AS parent_table
        FROM all_constraints c
        JOIN all_constraints p
            ON c.r_owner = p.owner
            AND c.r_constraint_name = p.constraint_name
        JOIN all_part_tables cpt
            ON c.owner = cpt.owner
            AND c.table_name = cpt.table_name
        WHERE c.owner = ?
            AND c.constraint_type = 'R'
            AND p.constraint_type = 'P'
            AND cpt.ref_ptn_constraint_name IS NOT NULL
        """
        try:
            ref_partitions = self.query_executor.execute_query(
                connection, ref_partition_query, params=[clean_schema]
            )
            parent_to_children: Dict[str, List[str]] = {}
            children_tables: Set[str] = set()
            for ref_row in ref_partitions:
                child = ref_row.get("child_table", ref_row.get("CHILD_TABLE"))
                parent = ref_row.get("parent_table", ref_row.get("PARENT_TABLE"))
                if child and parent:
                    if parent not in parent_to_children:
                        parent_to_children[parent] = []
                    parent_to_children[parent].append(child)
                    children_tables.add(child)
        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Could not query reference-partitioned table relationships: {str(e)}")
            parent_to_children = {}
            children_tables = set()

        tables_query = """
        SELECT t.table_name
        FROM ALL_TABLES t
        WHERE t.owner = ?
        AND t.table_name NOT LIKE 'BIN$%'
        AND NOT EXISTS (
            SELECT 1
            FROM ALL_MVIEWS mv
            WHERE mv.owner = t.owner
            AND mv.mview_name = t.table_name
        )
        ORDER BY t.table_name
        """

        tables = self.query_executor.execute_query(connection, tables_query, params=[clean_schema])

        all_table_names: List[str] = []
        for table_row in tables:
            table_name = table_row.get("table_name", table_row.get("TABLE_NAME"))
            if table_name:
                all_table_names.append(table_name)

        # First pass: drop reference-partitioned children
        for table_name in all_table_names:
            if table_name in children_tables:
                qualified_table = self.query_executor.get_schema_qualified_name(
                    schema_name, table_name
                )
                drop_sql = f"DROP TABLE {qualified_table} CASCADE CONSTRAINTS"
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    summary.record_drop(drop_sql, "table", table_name, schema=schema_name)
                    self.log.debug(f"Dropped reference-partitioned child table: {table_name}")
                except DB_OPERATION_EXCEPTIONS as e:
                    error_msg = f"Failed to drop table {table_name}: {str(e)}"
                    summary.add_error(error_msg)
                    self.log.warning(error_msg)

        # Second pass: drop parent tables and other tables
        for table_name in all_table_names:
            if table_name not in children_tables:
                qualified_table = self.query_executor.get_schema_qualified_name(
                    schema_name, table_name
                )
                drop_sql = f"DROP TABLE {qualified_table} CASCADE CONSTRAINTS"
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    summary.record_drop(drop_sql, "table", table_name, schema=schema_name)
                    self.log.debug(f"Dropped table: {table_name}")
                except DB_OPERATION_EXCEPTIONS as e:
                    error_msg = f"Failed to drop table {table_name}: {str(e)}"
                    summary.add_error(error_msg)
                    self.log.warning(error_msg)

    def _drop_sequences(
        self,
        connection: Any,
        schema_name: str,
        clean_schema: str,
        summary: CleanExecutionSummary,
    ) -> None:
        """Drop all sequences except system-generated ones for identity columns."""
        self.log.debug("Dropping all sequences...")

        sequences_query = """
        SELECT sequence_name
        FROM ALL_SEQUENCES
        WHERE sequence_owner = ?
        ORDER BY sequence_name
        """

        sequences = self.query_executor.execute_query(
            connection, sequences_query, params=[clean_schema]
        )
        for seq_row in sequences:
            seq_name = seq_row.get("sequence_name", seq_row.get("SEQUENCE_NAME"))
            if seq_name and not self.is_system_generated_sequence(
                connection, schema_name, seq_name
            ):
                qualified_sequence = self.query_executor.get_schema_qualified_name(
                    schema_name, seq_name
                )
                drop_sql = f"DROP SEQUENCE {qualified_sequence}"
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    summary.record_drop(drop_sql, "sequence", seq_name, schema=schema_name)
                    self.log.debug(f"Dropped sequence: {seq_name}")
                except DB_OPERATION_EXCEPTIONS as e:
                    error_msg = f"Failed to drop sequence {seq_name}: {str(e)}"
                    summary.add_error(error_msg)
                    self.log.warning(error_msg)

    def _drop_program_objects(
        self,
        connection: Any,
        schema_name: str,
        clean_schema: str,
        summary: CleanExecutionSummary,
    ) -> None:
        """Drop all procedures, functions, packages, and types."""
        self.log.debug("Dropping all procedures, functions, and packages...")

        objects_query = """
        SELECT object_name, object_type
        FROM ALL_OBJECTS
        WHERE owner = ?
        AND object_type IN ('PROCEDURE', 'FUNCTION', 'PACKAGE', 'PACKAGE BODY', 'TYPE', 'TYPE BODY')
        AND object_name NOT LIKE 'BIN$%'
        ORDER BY DECODE(object_type, 'PACKAGE BODY', 1, 'TYPE BODY', 1, 2), object_name
        """

        objects = self.query_executor.execute_query(
            connection, objects_query, params=[clean_schema]
        )
        for obj_row in objects:
            obj_name = obj_row.get("object_name", obj_row.get("OBJECT_NAME"))
            obj_type = obj_row.get("object_type", obj_row.get("OBJECT_TYPE"))
            if obj_name and obj_type:
                qualified_obj = self.query_executor.get_schema_qualified_name(schema_name, obj_name)
                if obj_type == "TYPE":
                    drop_sql = f"DROP {obj_type} {qualified_obj} FORCE"
                else:
                    drop_sql = f"DROP {obj_type} {qualified_obj}"
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    normalized_type = obj_type.lower().replace(" ", "_")
                    summary.record_drop(drop_sql, normalized_type, obj_name, schema=schema_name)
                    self.log.debug(f"Dropped {obj_type.lower()}: {obj_name}")
                except DB_OPERATION_EXCEPTIONS as e:
                    error_msg = f"Failed to drop {obj_type.lower()} {obj_name}: {str(e)}"
                    summary.add_error(error_msg)
                    self.log.warning(error_msg)

    def _drop_synonyms(
        self,
        connection: Any,
        schema_name: str,
        clean_schema: str,
        summary: CleanExecutionSummary,
    ) -> None:
        """Drop all synonyms in the schema."""
        self.log.debug("Dropping all synonyms...")

        synonyms_query = """
        SELECT synonym_name
        FROM ALL_SYNONYMS
        WHERE owner = ?
        ORDER BY synonym_name
        """

        synonyms = self.query_executor.execute_query(
            connection, synonyms_query, params=[clean_schema]
        )
        for syn_row in synonyms:
            syn_name = syn_row.get("synonym_name", syn_row.get("SYNONYM_NAME"))
            if syn_name:
                qualified_synonym = self.query_executor.get_schema_qualified_name(
                    schema_name, syn_name
                )
                drop_sql = f"DROP SYNONYM {qualified_synonym}"
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    summary.record_drop(drop_sql, "synonym", syn_name, schema=schema_name)
                    self.log.debug(f"Dropped synonym: {syn_name}")
                except DB_OPERATION_EXCEPTIONS as e:
                    error_msg = f"Failed to drop synonym {syn_name}: {str(e)}"
                    summary.add_error(error_msg)
                    self.log.warning(error_msg)

    def _drop_remaining_objects(
        self,
        connection: Any,
        schema_name: str,
        clean_schema: str,
        summary: CleanExecutionSummary,
    ) -> None:
        """Drop any remaining objects including triggers (best-effort, debug-only logging)."""
        self.log.debug("Dropping any remaining objects...")

        remaining_objects_query = """
        SELECT object_name, object_type
        FROM ALL_OBJECTS
        WHERE owner = ?
        AND object_type IN ('PROCEDURE', 'FUNCTION', 'PACKAGE', 'PACKAGE BODY', 'TYPE', 'TYPE BODY', 'TRIGGER')
        AND object_name NOT LIKE 'BIN$%'
        ORDER BY object_name
        """

        remaining_objects = self.query_executor.execute_query(
            connection, remaining_objects_query, params=[clean_schema]
        )
        for obj_row in remaining_objects:
            obj_name = obj_row.get("object_name", obj_row.get("OBJECT_NAME"))
            obj_type = obj_row.get("object_type", obj_row.get("OBJECT_TYPE"))
            if obj_name and obj_type:
                qualified_obj = self.query_executor.get_schema_qualified_name(schema_name, obj_name)
                drop_sql = f"DROP {obj_type} {qualified_obj}"
                try:
                    self.query_executor.execute_statement(connection, drop_sql)
                    normalized_type = obj_type.lower().replace(" ", "_")
                    summary.record_drop(drop_sql, normalized_type, obj_name, schema=schema_name)
                    self.log.debug(f"Dropped remaining {obj_type.lower()}: {obj_name}")
                except DB_OPERATION_EXCEPTIONS as e:
                    self.log.debug(f"Could not drop {obj_type.lower()} {obj_name}: {e}")

    def is_system_generated_sequence(
        self, connection: Any, schema: str, sequence_name: str
    ) -> bool:
        """Check if a sequence is system-generated (e.g., for identity columns).

        Oracle 12c+ generates sequences automatically for identity columns.
        These typically have names like ISEQ$$_[number] or similar patterns.

        Args:
            schema: Schema name
            sequence_name: Sequence name to check

        Returns:
            bool: True if sequence appears to be system-generated
        """
        if not sequence_name:
            return False

        # Common patterns for system-generated sequences in Oracle.
        # BUG-03: ``SQ_``/``SEQ_`` removed — those are the most common *user*
        # naming conventions (``SEQ_ORDERS``, ``SQ_INVOICE_ID``) and excluding
        # them silently dropped legitimate sequences from ``clean``. Oracle
        # identity sequences are already covered by ``ISEQ$$_`` and the
        # authoritative ALL_TAB_IDENTITY_COLS lookup below.
        system_patterns = [
            "ISEQ$$_",  # Identity column sequences (12c+)
            "HIBERNATE_",  # Hibernate ORM sequences
            "JPA_",  # JPA sequences
        ]

        # Check for system patterns (case-insensitive)
        sequence_upper = sequence_name.upper()

        # Check for system patterns
        for pattern in system_patterns:
            if sequence_upper.startswith(pattern):
                return True

        # Check if it's associated with an identity column
        try:
            # Query to check if sequence is used by an identity column
            # Use exact case matching to prevent incorrect matches
            clean_schema = schema.replace('"', "").strip()
            identity_check_sql = """
            SELECT COUNT(*) as identity_count
            FROM ALL_TAB_IDENTITY_COLS
            WHERE owner = ? AND sequence_name = ?
            """

            result = self.query_executor.execute_query(
                connection, identity_check_sql, params=[clean_schema, sequence_name]
            )

            if result and len(result) > 0:
                raw_count = result[0].get("identity_count", result[0].get("IDENTITY_COUNT", 0))
                count = self._to_int(raw_count)
                return count > 0

        except DB_OPERATION_EXCEPTIONS as e:
            self.log.debug(f"Identity column query failed, using heuristics: {e}")

        return False

    def set_current_schema(self, connection: Any, schema: str) -> None:
        """Set the current schema for the session.

        Args:
            schema: Schema name to set as current (will be quoted to preserve case)
        """
        self.log.debug(f"Setting current schema to: {schema}")

        try:
            # Oracle's ALTER SESSION SET CURRENT_SCHEMA command
            # Use quoted identifier to preserve case
            clean_schema = schema.replace('"', "").strip()

            # Validate schema name against Oracle identifier whitelist before using in DDL
            # Oracle DDL (ALTER SESSION) does not support parameter binding,
            # so whitelist validation + double-quote quoting is the only safe approach
            if not re.match(r"^[A-Za-z][A-Za-z0-9_#$]{0,127}$", clean_schema):
                error_msg = (
                    f"Invalid Oracle identifier for schema '{clean_schema}': "
                    "must start with a letter and contain only [A-Za-z0-9_#$]"
                )
                self.log.error(error_msg)
                raise ValueError(error_msg)

            quoted_schema = self.query_executor.get_quoted_schema_name(clean_schema)
            set_schema_sql = f"ALTER SESSION SET CURRENT_SCHEMA = {quoted_schema}"
            self.query_executor.execute_statement(connection, set_schema_sql)

            self.log.debug(f"Successfully set current schema to: {schema}")

        except DB_OPERATION_EXCEPTIONS as e:
            error_msg = f"Error setting current schema to {schema}: {str(e)}"
            self.log.error(error_msg)
            raise

    def get_database_version(self, connection: Any) -> str:
        """Get Oracle database version information.

        Returns:
            str: Oracle database version string
        """
        try:
            # Query Oracle system view for version information
            version_query = "SELECT banner FROM v$version WHERE rownum = 1"

            result = self.query_executor.execute_query(connection, version_query)

            if result and len(result) > 0:
                version = result[0].get("banner", result[0].get("BANNER", "Unknown"))
                return str(version)
            else:
                return "Unknown Oracle Version"

        except DB_OPERATION_EXCEPTIONS as e:
            self.log.warning(f"Could not determine Oracle version: {str(e)}")
            return "Unknown Oracle Version"

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[str]]:
        """Get an Oracle-specific query to retrieve column information from a table.

        Args:
            schema: Schema name (will be matched with exact case)
            table: Table name (will be matched with exact case)

        Returns:
            tuple[str, List[str]]: SQL query and parameters [schema, table]
        """
        # Since we always use quoted identifiers, match exact case
        # Remove quotes if present for the query
        clean_schema = schema.replace('"', "").strip()
        clean_table = table.replace('"', "").strip()
        query = """
        SELECT column_name, data_type
        FROM all_tab_columns
        WHERE owner = ? AND table_name = ?
        ORDER BY column_id
        """
        return (query, [clean_schema, clean_table])

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate Oracle-specific SQL to add a column to a table.

        Args:
            schema: Schema name (will be quoted to preserve case)
            table: Table name (will be quoted to preserve case)
            column: Column name to add (will be quoted to preserve case)
            type_def: Column data type definition

        Returns:
            str: SQL for adding the column
        """
        # Use quoted identifiers for all names
        qualified_table = self.query_executor.get_schema_qualified_name(schema, table)
        clean_column = column.replace('"', "").strip()
        return f'ALTER TABLE {qualified_table} ADD ("{clean_column}" {type_def})'

    def get_parameter_placeholders(self, count: int) -> str:
        """Get Oracle-specific parameter placeholders for prepared statements.

        Args:
            count: Number of parameters

        Returns:
            str: Parameter placeholders string
        """
        # Oracle uses :1, :2, etc.
        return ", ".join([f":{i+1}" for i in range(count)])

    def get_tables(self, connection: Any, schema: str) -> List[str]:
        """Get list of table names in the specified schema.

        Returns table names with their actual case as stored in Oracle.
        Since we use quoted identifiers, Oracle preserves the exact case.

        Args:
            schema: Schema name (will be matched with exact case)

        Returns:
            List of table names in the schema with correct case
        """
        self.log.debug(f"Getting tables in schema: {schema}")

        try:
            # Remove quotes if present for the query
            clean_schema = schema.replace('"', "").strip()

            # Use ALL_TABLES view to get table names with actual case
            query = """
            SELECT table_name
            FROM ALL_TABLES
            WHERE owner = ?
            ORDER BY table_name
            """

            result = self.query_executor.execute_query(connection, query, params=[clean_schema])
            # Oracle returns table names with their actual case from data dictionary
            tables = [
                str(row["table_name"] if "table_name" in row else row["TABLE_NAME"])
                for row in result
            ]

            self.log.debug(f"Found {len(tables)} tables in schema {schema}: {tables}")

            return tables
        except DB_OPERATION_EXCEPTIONS as e:
            error_msg = f"Error getting tables in schema {schema}: {str(e)}"
            self.log.error(error_msg)
            return []

    def get_schemas(self, connection: Any) -> List[str]:
        """Get list of schema names (users) available in the Oracle database.

        Returns:
            List of schema names (Oracle users) that the current user can access
        """
        self.log.debug("Getting available schemas (users) from Oracle")

        try:
            # Query to get schemas/users that the current user can access
            # Using DBA_USERS if available, otherwise ALL_USERS
            query = """
            SELECT username AS schema_name
            FROM ALL_USERS
            WHERE username NOT IN (
                'SYS', 'SYSTEM', 'SYSMAN', 'DBSNMP', 'OUTLN', 'TSMSYS',
                'DIP', 'ORACLE_OCM', 'APPQOSSYS', 'WMSYS', 'EXFSYS',
                'CTXSYS', 'ANONYMOUS', 'XDB', 'XS$NULL', 'OJVMSYS',
                'LBACSYS', 'FLOWS_FILES', 'APEX_030200', 'APEX_PUBLIC_USER',
                'FLOWS_030100', 'HR', 'OE', 'PM', 'IX', 'SH', 'BI'
            )
            ORDER BY username
            """

            result = self.query_executor.execute_query(connection, query)
            schemas = [
                str(row["schema_name"] if "schema_name" in row else row["SCHEMA_NAME"])
                for row in result
            ]

            self.log.debug(f"Found {len(schemas)} accessible schemas (users)")

            return schemas
        except DB_OPERATION_EXCEPTIONS as e:
            error_msg = f"Error getting schemas: {str(e)}"
            self.log.error(error_msg)
            return []
