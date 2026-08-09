"""PostgreSQL native provider backed by SQLAlchemy Core."""

import time
from typing import Any, Dict, List, Optional

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.plugins.base_history_manager import UNDO_HISTORY_TYPE
from db.plugins.postgresql._provider_query_executor import ProviderQueryExecutor
from db.plugins.postgresql.postgresql._lock_key import _get_advisory_lock_key
from db.plugins.postgresql.postgresql.schema_operations import PostgreSqlSchemaOperations
from db.plugins.postgresql.search_path import search_path_schemas
from db.provider_interfaces import DroppableObject
from db.sqlalchemy_provider import SqlAlchemyProvider


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class PostgreSqlProvider(SqlAlchemyProvider):
    """PostgreSQL provider implementation using native SQLAlchemy connections."""

    canonical_dialect_key = "postgresql"
    MIGRATION_LOCK_TABLE = "dblift_migration_lock"

    #: Wrap every ``clean`` drop in a savepoint — see :meth:`drop_object`.
    #: Redshift inherits this provider but has no ``SAVEPOINT`` statement,
    #: so it turns this off.
    clean_drop_uses_savepoint: bool = True

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the native PostgreSQL provider."""
        super().__init__(config, log)

    def drop_object(self, obj: DroppableObject) -> None:
        """Drop one object without letting a failure abort the whole clean.

        ``CleanCommand`` logs a failed drop and moves on to the next object.
        On PostgreSQL that only works with a savepoint: the backend aborts the
        *entire* transaction on any statement error, so catching the Python
        exception leaves the connection unusable and every later DROP fails
        with ``InFailedSqlTransaction`` — including dblift's own history and
        lock tables. Statement-level rollback is the norm elsewhere (Oracle,
        DB2 and SQL Server keep the transaction alive, MySQL commits DDL
        implicitly), which is why the base provider issues the drop directly.

        The savepoint is released only while it is still active. In the
        provider's default auto-commit-per-statement mode a successful drop
        commits the transaction outright, which ends the savepoint with it —
        a stronger guarantee than a release, and SQLAlchemy raises if an
        already-finished nested transaction is committed again.
        """
        if not self.clean_drop_uses_savepoint:
            super().drop_object(obj)
            return

        savepoint = self._ensure_connection().begin_nested()
        try:
            super().drop_object(obj)
        except Exception:
            if savepoint.is_active:
                savepoint.rollback()
            raise
        if savepoint.is_active:
            savepoint.commit()

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a SQL statement, optionally preparing the schema first."""
        if schema:
            self.create_schema_if_not_exists(schema)
            self.set_current_schema(schema)
        return super().execute_statement(sql, schema=schema, params=params)

    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create a PostgreSQL schema if it is missing."""
        exists = self.execute_query(
            "SELECT EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = ?) AS exists",
            [schema],
        )
        if exists and exists[0].get("exists"):
            return
        try:
            self.execute_statement(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(schema)}")
        except Exception as exc:
            # Any failure here aborts the current transaction, so roll back
            # before deciding how to handle it -- otherwise the connection is
            # left in a failed-transaction state for whatever runs next.
            self._rollback_failed_create_race("schema")
            if "already exists" not in str(exc).lower():
                raise
            # Two racing processes against a genuinely nonexistent schema can
            # both pass the SELECT EXISTS check above before either one
            # creates it. PostgreSQL can answer the loser with a unique
            # violation on pg_namespace instead of silently no-op'ing -- the
            # schema is there either way, so treat the rolled-back race as
            # success rather than failing the caller.

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Return whether a table exists in the given schema."""
        rows = self.execute_query(
            """
            SELECT EXISTS (
                SELECT 1
                FROM information_schema.tables
                WHERE table_schema = ?
                  AND table_name = ?
            ) AS exists
            """,
            [schema, table_name],
        )
        return bool(rows and rows[0].get("exists"))

    def get_database_version(self) -> str:
        """Return PostgreSQL version information."""
        rows = self.execute_query("SELECT version() AS version")
        return str(rows[0]["version"]) if rows else "Unknown PostgreSQL Version"

    def set_current_schema(self, schema: str) -> None:
        """Set the PostgreSQL search path for this connection.

        ``public`` follows the target schema so extension functions installed
        there stay callable unqualified — see
        :mod:`db.plugins.postgresql.search_path`.
        """
        path = ", ".join(_quote_identifier(name) for name in search_path_schemas(schema))
        super().execute_statement(f"SET search_path TO {path}")

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a quoted schema-qualified object name."""
        return f"{_quote_identifier(schema)}.{_quote_identifier(object_name)}"

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop objects inside a schema, returning executed clean statements."""
        return self._schema_operations().clean_schema(None, schema)

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return the native PostgreSQL clean summary without executing drops."""
        return self._schema_operations().get_clean_preview(None, schema)

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return PostgreSQL objects in the same order as clean preview."""
        summary = self.get_clean_preview(schema)
        return [
            DroppableObject(name=obj.name, object_type=obj.object_type, drop_sql=drop_sql)
            for obj, drop_sql in zip(summary.objects, summary.statements)
        ]

    def _schema_operations(self) -> PostgreSqlSchemaOperations:
        return PostgreSqlSchemaOperations(ProviderQueryExecutor(self), getattr(self, "log", None))

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the PostgreSQL migration lock table if it is missing."""
        self.create_schema_if_not_exists(schema)
        try:
            self.execute_statement(f"""
                CREATE TABLE IF NOT EXISTS {self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE)} (
                    lock_name VARCHAR(255) PRIMARY KEY,
                    locked_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
                )
                """)
        except Exception as exc:
            # Any failure here aborts the current transaction, so roll back
            # before deciding how to handle it -- otherwise the connection is
            # left in a failed-transaction state for whatever runs next.
            self._rollback_failed_create_race("migration-lock-table")
            if "already exists" not in str(exc).lower():
                raise
            # Two first-ever migrate() calls can both reach this statement
            # before either wins the advisory lock below. PostgreSQL can
            # answer the loser with a duplicate-object error on the table's
            # implicit row type instead of silently no-op'ing — the table is
            # there either way, so treat the rolled-back race as success
            # rather than failing the migration.

    def _rollback_failed_create_race(self, what: str) -> None:
        connection = getattr(self, "_connection", None)
        if connection is not None and not getattr(connection, "closed", False):
            try:
                connection.rollback()
            except Exception as exc:
                message = f"Could not rollback failed {what} create"
                raise RuntimeError(message) from exc

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Acquire the PostgreSQL advisory migration lock."""
        self.create_migration_lock_table_if_not_exists(schema)
        lock_key = _get_advisory_lock_key(schema)
        deadline = time.monotonic() + wait_timeout_seconds
        while True:
            rows = self.execute_query(f"SELECT pg_try_advisory_lock({lock_key}) AS acquired")
            if rows and rows[0].get("acquired"):
                return True
            if time.monotonic() >= deadline:
                return False
            time.sleep(0.2)

    def release_migration_lock(self, schema: str) -> bool:
        """Release the PostgreSQL advisory migration lock."""
        lock_key = _get_advisory_lock_key(schema)
        rows = self.execute_query(f"SELECT pg_advisory_unlock({lock_key}) AS released")
        return bool(rows and rows[0].get("released"))

    def get_applied_migrations(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> List[Dict[str, Any]]:
        """Return applied migration rows from the history table."""
        if not self.table_exists(schema, table_name):
            return []
        return self.execute_query(f"""
            SELECT *
            FROM {self.get_schema_qualified_name(schema, table_name)}
            ORDER BY installed_rank
            """)

    def create_migration_history_table_if_not_exists(
        self,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the migration history table if it is missing."""
        if create_schema:
            self.create_schema_if_not_exists(schema)
        if self.table_exists(schema, table_name):
            if create_schema:
                self._check_baseline_safety(schema, table_name)
            return
        self.execute_statement(self.create_history_table(schema, table_name))

    def _check_baseline_safety(self, schema: str, table_name: str) -> None:
        """Refuse baseline when the history table already contains migrations."""
        qualified_table = self.get_schema_qualified_name(schema, table_name)
        rows = self.execute_query(f"SELECT COUNT(1) as count FROM {qualified_table}")
        migration_count = 0
        if rows:
            migration_count = int(rows[0].get("count", rows[0].get("COUNT", 0)) or 0)
        if migration_count > 0:
            raise RuntimeError(
                f"Schema {schema} already contains a migration history table "
                f"{table_name} with {migration_count} migration(s). "
                "Baseline cannot be applied to a schema with existing migrations."
            )

    def record_migration(
        self, schema: str, migration_info: Dict[str, Any], table_name: str = "dblift_schema_history"
    ) -> None:
        """Insert a migration record into the history table."""
        self.create_migration_history_table_if_not_exists(schema, table_name=table_name)
        self.execute_statement(
            f"""
            INSERT INTO {self.get_schema_qualified_name(schema, table_name)}
                (version, description, type, script, checksum, installed_by, execution_time, success)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            params=[
                migration_info.get("version"),
                migration_info.get("description", ""),
                migration_info.get("type", "SQL"),
                migration_info.get("script", ""),
                migration_info.get("checksum"),
                migration_info.get("installed_by", "dblift"),
                migration_info.get("execution_time", 0),
                migration_info.get("success", True),
            ],
        )

    def record_undo(
        self,
        schema: str,
        version: str,
        table_name: Optional[str] = None,
        script_name: Optional[str] = None,
    ) -> bool:
        """Record a successful undo operation in PostgreSQL migration history."""
        undo_script = script_name or f"UNDO_{version}.sql"
        self.record_migration(
            schema,
            {
                "version": version,
                "description": f"Undo migration {version}",
                "type": UNDO_HISTORY_TYPE,
                "script": undo_script,
                "checksum": 0,
                "success": True,
            },
            table_name or "dblift_schema_history",
        )
        return True

    def repair_migration_history(
        self,
        schema: str,
        script_name: str,
        checksum: Any,
        table_name: str = "dblift_schema_history",
        success_value: Optional[Any] = None,
    ) -> bool:
        """Update checksum and success state for an existing migration row."""
        if not self.table_exists(schema, table_name):
            return False
        result = self.execute_statement(
            f"""
            UPDATE {self.get_schema_qualified_name(schema, table_name)}
            SET checksum = ?, success = COALESCE(?, success)
            WHERE script = ?
            """,
            params=[checksum, success_value, script_name],
        )
        return result > 0

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Return SQL for the PostgreSQL migration history table."""
        return f"""
            CREATE TABLE IF NOT EXISTS {self.get_schema_qualified_name(schema, table_name)} (
                installed_rank SERIAL PRIMARY KEY,
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
