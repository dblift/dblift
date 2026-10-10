"""Redshift native provider (PostgreSQL-compatible)."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from dblift.core.migration.clean_summary import CleanExecutionSummary
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider


def _is_statement_timeout_error(error: Exception) -> bool:
    message = str(error).lower()
    return "statement_timeout" in message or "statement timeout" in message


class RedshiftProvider(PostgreSqlProvider):
    """Redshift provider with Redshift-specific history and locking SQL."""

    canonical_dialect_key = "redshift"
    #: Redshift does not implement ``SAVEPOINT``, so ``clean`` cannot isolate
    #: a failed drop the way PostgreSQL does — issue the drop directly rather
    #: than sending a statement the engine will reject.
    clean_drop_uses_savepoint: bool = False
    _migration_lock_connection: Any | None = None
    _migration_lock_transaction: Any | None = None

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop Redshift objects without querying PostgreSQL-only catalogs."""
        summary = self.get_clean_preview(schema)
        for sql in summary.statements:
            self.execute_statement(sql)
        return summary

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Preview Redshift objects clean would drop, in drop order.

        Materialized views go first (a view may read one, and one may read a
        view), then views, tables, and finally procedures and functions, which
        nothing the earlier drops need. Redshift has no sequences or user
        types. A catalog that cannot be read is reported and skipped, so the
        rest of the schema is still cleaned.
        """
        summary = CleanExecutionSummary()
        qualified_name = self.get_schema_qualified_name

        materialized = self._optional_clean_rows(
            "materialized view", _MATERIALIZED_VIEWS_QUERY, schema, summary
        )
        materialized_names = {str(row["object_name"]) for row in materialized or []}
        for name in sorted(materialized_names):
            summary.record_drop(
                f"DROP MATERIALIZED VIEW IF EXISTS {qualified_name(schema, name)} CASCADE",
                object_type="materialized view",
                name=name,
                schema=schema,
            )

        views = self._redshift_clean_object_names(_REDSHIFT_VIEWS_QUERY, schema)
        # Late-binding views are absent from information_schema.views.
        late_binding = self._optional_clean_rows(
            "late-binding view", _LATE_BINDING_VIEWS_QUERY, schema, summary
        )
        views += [str(row["object_name"]) for row in late_binding or []]
        for view_name in dict.fromkeys(views):
            if view_name in materialized_names:
                continue
            summary.record_drop(
                f"DROP VIEW IF EXISTS {qualified_name(schema, view_name)} CASCADE",
                object_type="view",
                name=view_name,
                schema=schema,
            )

        for table_name in self._redshift_clean_object_names(_REDSHIFT_TABLES_QUERY, schema):
            summary.record_drop(
                f"DROP TABLE IF EXISTS {qualified_name(schema, table_name)} CASCADE",
                object_type="table",
                name=table_name,
                schema=schema,
            )

        routines = self._optional_clean_rows(
            "routine (function or procedure)", _ROUTINES_QUERY, schema, summary
        )
        for kind in ("procedure", "function"):
            for row in routines or []:
                if _routine_kind(row) != kind:
                    continue
                name = str(row["object_name"])
                signature = f"{name}({row.get('argument_type') or ''})"
                # DROP FUNCTION / DROP PROCEDURE have no IF EXISTS, and need the
                # argument types to tell overloads apart. Only DROP FUNCTION
                # takes CASCADE.
                drop_sql = f"DROP {kind.upper()} {qualified_name(schema, name)}({row.get('argument_type') or ''})"
                summary.record_drop(
                    drop_sql + (" CASCADE" if kind == "function" else ""),
                    object_type=kind,
                    name=signature,
                    schema=schema,
                )

        return summary

    def _optional_clean_rows(
        self,
        kind: str,
        query: str,
        schema: str,
        summary: CleanExecutionSummary,
    ) -> Optional[List[Dict[str, Any]]]:
        """Return the rows of a catalog query clean can do without, or ``None``.

        Older clusters or limited users may not see these catalogs; that must
        not stop the tables and views from being cleaned.
        """
        try:
            return list(self.execute_query(query, [schema] * query.count("?")))
        except Exception as exc:
            message = (
                f"Could not list {kind}s in schema '{schema}'; they will not be dropped: {exc}"
            )
            log = getattr(self, "log", None)
            if log is not None:
                log.warning(message)
            summary.add_error(message)
            try:
                # A failed statement aborts a Redshift transaction block.
                self.rollback_transaction()
            except Exception:
                pass
            return None

    def _redshift_clean_object_names(
        self,
        query: str,
        schema: str,
    ) -> list[str]:
        rows = self.execute_query(query, [schema])
        column_name = "object_name"
        return [
            str(row.get(column_name) or row.get(column_name.upper()))
            for row in rows
            if row.get(column_name) or row.get(column_name.upper())
        ]

    def acquire_migration_lock(
        self,
        schema: str,
        wait_timeout_seconds: int = 60,
    ) -> bool:
        """Acquire a Redshift table lock on a dedicated transaction."""
        if getattr(self, "_migration_lock_transaction", None) is not None:
            return True

        self.create_migration_lock_table_if_not_exists(schema)
        connection = self.engine.connect()
        transaction = connection.begin()
        try:
            timeout_ms = max(1, int(wait_timeout_seconds) * 1000)
            connection.exec_driver_sql(f"SET statement_timeout = {timeout_ms}")
            table = self.MIGRATION_LOCK_TABLE
            qualified_table = self.get_schema_qualified_name(schema, table)
            connection.exec_driver_sql(f"LOCK {qualified_table}")
        except Exception as exc:
            try:
                transaction.rollback()
            finally:
                connection.close()
            if _is_statement_timeout_error(exc):
                return False
            raise

        self._migration_lock_connection = connection
        self._migration_lock_transaction = transaction
        return True

    def release_migration_lock(self, schema: str) -> bool:
        """Release the Redshift migration lock by ending its transaction."""
        transaction = getattr(self, "_migration_lock_transaction", None)
        connection = getattr(self, "_migration_lock_connection", None)
        if transaction is None or connection is None:
            return True

        try:
            transaction.commit()
            return True
        except Exception:
            try:
                transaction.rollback()
            except Exception:
                pass
            return False
        finally:
            try:
                connection.close()
            finally:
                self._migration_lock_connection = None
                self._migration_lock_transaction = None

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Return SQL for the Redshift migration history table."""
        qualified_table = self.get_schema_qualified_name(schema, table_name)
        return f"""
            CREATE TABLE IF NOT EXISTS {qualified_table} (
                installed_rank INTEGER IDENTITY(1,1) PRIMARY KEY,
                version VARCHAR(50),
                description VARCHAR(200) NOT NULL,
                type VARCHAR(20) NOT NULL,
                script VARCHAR(1000) NOT NULL,
                checksum VARCHAR(64),
                installed_by VARCHAR(100) NOT NULL,
                installed_on TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                execution_time INTEGER NOT NULL,
                success BOOLEAN NOT NULL
            )
        """


__all__ = ["RedshiftProvider"]


_REDSHIFT_VIEWS_QUERY = """
    SELECT table_name AS object_name
    FROM information_schema.views
    WHERE table_schema = ?
    ORDER BY table_name
"""

_REDSHIFT_TABLES_QUERY = """
    SELECT table_name AS object_name
    FROM information_schema.tables
    WHERE table_schema = ?
      AND table_type = 'BASE TABLE'
    ORDER BY table_name
"""

# SVV_MV_INFO: "a row for every materialized view" (name and schema_name are CHAR).
_MATERIALIZED_VIEWS_QUERY = """
    SELECT TRIM(name) AS object_name
    FROM svv_mv_info
    WHERE database_name = current_database()
      AND TRIM(schema_name) = ?
    ORDER BY 1
"""

# SHOW TABLES lists late-binding and materialized views with table_type VIEW;
# the sub-select leaves out the materialized ones.
_LATE_BINDING_VIEWS_QUERY = """
    SELECT table_name AS object_name
    FROM svv_redshift_tables
    WHERE database_name = current_database()
      AND schema_name = ?
      AND table_type = 'VIEW'
      AND table_name NOT IN (
          SELECT TRIM(name)
          FROM svv_mv_info
          WHERE database_name = current_database()
            AND TRIM(schema_name) = ?
      )
    ORDER BY table_name
"""

# SVV_REDSHIFT_FUNCTIONS: argument_type is the list of input types, as text.
_ROUTINES_QUERY = """
    SELECT function_name AS object_name, function_type, argument_type
    FROM svv_redshift_functions
    WHERE database_name = current_database()
      AND schema_name = ?
    ORDER BY function_name, argument_type
"""


def _routine_kind(row: Dict[str, Any]) -> Optional[str]:
    """Return ``procedure`` or ``function``; aggregates and unknown kinds are left alone."""
    function_type = str(row.get("function_type") or "").upper()
    if "PROCEDURE" in function_type:
        return "procedure"
    if "REGULAR" in function_type:
        return "function"
    return None
