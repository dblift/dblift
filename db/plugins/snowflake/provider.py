"""Snowflake native provider backed by SQLAlchemy Core."""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy.engine import Connection, Transaction

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.provider_interfaces import DroppableObject
from db.sqlalchemy_provider import SqlAlchemyProvider


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.upper().replace('"', '""') + '"'


def _is_lock_timeout_error(error: Exception) -> bool:
    message = str(error).lower()
    markers = ("lock timeout", "timed out", "timeout")
    return any(marker in message for marker in markers)


class SnowflakeProvider(SqlAlchemyProvider):
    """Snowflake provider using the Snowflake SQLAlchemy dialect."""

    canonical_dialect_key = "snowflake"
    MIGRATION_LOCK_TABLE = "DBLIFT_MIGRATION_LOCK"
    _migration_lock_connection: Connection | None = None
    _migration_lock_transaction: Transaction | None = None

    def __init__(
        self,
        config: DbliftConfig,
        log: Optional[Log] = None,
    ) -> None:
        super().__init__(config, log)

    def execute_statement(
        self,
        sql: str,
        schema: Optional[str] = None,
        params: Optional[List[Any]] = None,
    ) -> int:
        """Execute a SQL statement, optionally preparing the schema first."""
        if schema:
            self.create_schema_if_not_exists(schema)
            self.set_current_schema(schema)
        rowcount: int = super().execute_statement(
            sql,
            schema=schema,
            params=params,
        )
        return rowcount

    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create a Snowflake schema if it is missing."""
        schema_name = _quote_identifier(schema)
        self.execute_statement(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Return whether a table exists in the given schema."""
        rows = self.execute_query(
            """
            SELECT 1 AS present
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = UPPER(?)
              AND TABLE_NAME = UPPER(?)
            """,
            [schema, table_name],
        )
        return bool(rows)

    def get_database_version(self) -> str:
        """Return Snowflake version information."""
        rows = self.execute_query("SELECT CURRENT_VERSION() AS version")
        if rows:
            return f"Snowflake {rows[0]['version']}"
        return "Unknown Snowflake Version"

    def supports_transactional_ddl(self) -> bool:
        """Snowflake DDL auto-commits."""
        return False

    def set_current_schema(self, schema: str) -> None:
        """Set the current Snowflake schema for this session."""
        super().execute_statement(f"USE SCHEMA {_quote_identifier(schema)}")

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a quoted schema-qualified object name."""
        return f"{_quote_identifier(schema)}.{_quote_identifier(object_name)}"

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop Snowflake views, tables, and sequences in a schema."""
        summary = self.get_clean_preview(schema)
        for stmt in summary.statements:
            self.execute_statement(stmt)
        return summary

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return Snowflake objects that clean would drop."""
        summary = CleanExecutionSummary()

        for view_name in self._object_names(_SNOWFLAKE_VIEWS_QUERY, schema):
            qualified = self.get_schema_qualified_name(schema, view_name)
            summary.record_drop(
                f"DROP VIEW IF EXISTS {qualified}",
                object_type="view",
                name=view_name,
                schema=schema,
            )

        for table_name in self._object_names(_SNOWFLAKE_TABLES_QUERY, schema):
            qualified = self.get_schema_qualified_name(schema, table_name)
            summary.record_drop(
                f"DROP TABLE IF EXISTS {qualified} CASCADE",
                object_type="table",
                name=table_name,
                schema=schema,
            )

        sequence_names = self._object_names(_SNOWFLAKE_SEQUENCES_QUERY, schema)
        for sequence_name in sequence_names:
            qualified = self.get_schema_qualified_name(schema, sequence_name)
            summary.record_drop(
                f"DROP SEQUENCE IF EXISTS {qualified}",
                object_type="sequence",
                name=sequence_name,
                schema=schema,
            )

        return summary

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return Snowflake clean candidates in preview order."""
        summary = self.get_clean_preview(schema)
        return [
            DroppableObject(
                name=obj.name,
                object_type=obj.object_type,
                drop_sql=drop_sql,
            )
            for obj, drop_sql in zip(summary.objects, summary.statements)
        ]

    def _object_names(self, query: str, schema: str) -> List[str]:
        rows = self.execute_query(query, [schema])
        return [
            str(row.get("object_name") or row.get("OBJECT_NAME"))
            for row in rows
            if row.get("object_name") or row.get("OBJECT_NAME")
        ]

    def create_migration_lock_table_sql(self, schema: str) -> str:
        """Return the Snowflake migration lock table DDL."""
        qualified = self.get_schema_qualified_name(
            schema,
            self.MIGRATION_LOCK_TABLE,
        )
        return f"""
            CREATE TABLE IF NOT EXISTS {qualified} (
                lock_name VARCHAR(128) NOT NULL,
                locked_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP()
            )
        """

    def acquire_migration_lock_sql(self, schema: str) -> str:
        """Return the DML statement holding the migration lock row."""
        qualified = self.get_schema_qualified_name(
            schema,
            self.MIGRATION_LOCK_TABLE,
        )
        return (
            f"UPDATE {qualified} "
            "SET locked_at = CURRENT_TIMESTAMP() WHERE lock_name = 'migration'"
        )

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create and seed the Snowflake migration lock table."""
        self.create_schema_if_not_exists(schema)
        self.execute_statement(self.create_migration_lock_table_sql(schema))
        lock_table = self.MIGRATION_LOCK_TABLE
        qualified = self.get_schema_qualified_name(schema, lock_table)
        self.execute_statement(f"""
            INSERT INTO {qualified} (lock_name, locked_at)
            SELECT 'migration', CURRENT_TIMESTAMP()
            WHERE NOT EXISTS (
                SELECT 1 FROM {qualified} WHERE lock_name = 'migration'
            )
            """)

    def acquire_migration_lock(
        self,
        schema: str,
        wait_timeout_seconds: int = 60,
    ) -> bool:
        """Acquire the migration lock with a DML transaction."""
        if self._migration_lock_transaction is not None:
            return True

        self.create_migration_lock_table_if_not_exists(schema)
        connection = self.engine.connect()
        try:
            timeout = max(0, int(wait_timeout_seconds))
            set_timeout = f"ALTER SESSION SET LOCK_TIMEOUT = {timeout}"
            connection.exec_driver_sql(set_timeout)
            connection.commit()
            transaction = connection.begin()
            connection.exec_driver_sql(self.acquire_migration_lock_sql(schema))
        except Exception as exc:
            try:
                connection.rollback()
            finally:
                connection.close()
            if _is_lock_timeout_error(exc):
                return False
            raise

        self._migration_lock_connection = connection
        self._migration_lock_transaction = transaction
        return True

    def release_migration_lock(self, schema: str) -> bool:
        """Release the Snowflake migration lock by ending its transaction."""
        transaction = self._migration_lock_transaction
        connection = self._migration_lock_connection
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

    def get_applied_migrations(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> List[Dict[str, Any]]:
        """Return applied migration rows from the history table."""
        normalized_table = table_name.upper()
        if not self.table_exists(schema, normalized_table):
            return []
        rows: List[Dict[str, Any]] = self.execute_query(f"""
            SELECT *
            FROM {self.get_schema_qualified_name(schema, normalized_table)}
            ORDER BY installed_rank
            """)
        return rows

    def create_migration_history_table_if_not_exists(
        self,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the Snowflake migration history table if missing."""
        normalized_table = table_name.upper()
        if create_schema:
            self.create_schema_if_not_exists(schema)
        if self.table_exists(schema, normalized_table):
            if create_schema:
                self._check_baseline_safety(schema, normalized_table)
            return
        create_sql = self.create_history_table(schema, normalized_table)
        self.execute_statement(create_sql)

    def _check_baseline_safety(self, schema: str, table_name: str) -> None:
        """Refuse baseline when history already contains migrations."""
        qualified_table = self.get_schema_qualified_name(schema, table_name)
        count_sql = f"SELECT COUNT(1) AS count FROM {qualified_table}"
        rows = self.execute_query(count_sql)
        migration_count = 0
        if rows:
            count = rows[0].get("count", rows[0].get("COUNT", 0))
            migration_count = int(count or 0)
        if migration_count > 0:
            baseline_error = "Baseline cannot run with existing migrations."
            raise RuntimeError(
                f"Schema {schema} already contains a migration history table "
                f"{table_name} with {migration_count} migration(s). "
                f"{baseline_error}"
            )

    def record_migration(
        self,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Insert a migration record into the Snowflake history table."""
        normalized_table = table_name.upper()
        self.create_migration_history_table_if_not_exists(
            schema,
            table_name=normalized_table,
        )
        qualified_table = self.get_schema_qualified_name(
            schema,
            normalized_table,
        )
        self.execute_statement(
            f"""
            INSERT INTO {qualified_table}
                (version, description, type, script, checksum,
                 installed_by, execution_time, success)
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
        """Record a successful undo in Snowflake migration history."""
        undo_script = script_name or f"UNDO_{version}.sql"
        self.record_migration(
            schema,
            {
                "version": version,
                "description": f"Undo migration {version}",
                "type": "UNDO_SQL",
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
        normalized_table = table_name.upper()
        if not self.table_exists(schema, normalized_table):
            return False
        qualified_table = self.get_schema_qualified_name(
            schema,
            normalized_table,
        )
        result = self.execute_statement(
            f"""
            UPDATE {qualified_table}
            SET checksum = ?, success = COALESCE(?, success)
            WHERE script = ?
            """,
            params=[checksum, success_value, script_name],
        )
        return result > 0

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Return SQL for the Snowflake migration history table."""
        qualified_table = self.get_schema_qualified_name(schema, table_name)
        return f"""
            CREATE TABLE IF NOT EXISTS {qualified_table} (
                installed_rank INTEGER AUTOINCREMENT
                    START 1 INCREMENT 1 PRIMARY KEY,
                version VARCHAR(50),
                description VARCHAR(200) NOT NULL,
                type VARCHAR(20) NOT NULL,
                script VARCHAR(1000) NOT NULL,
                checksum VARCHAR(64),
                installed_by VARCHAR(100) NOT NULL,
                installed_on TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                execution_time INTEGER NOT NULL,
                success BOOLEAN NOT NULL
            )
        """


__all__ = ["SnowflakeProvider"]


_SNOWFLAKE_VIEWS_QUERY = """
    SELECT table_name AS object_name
    FROM INFORMATION_SCHEMA.VIEWS
    WHERE TABLE_SCHEMA = UPPER(?)
    ORDER BY table_name
"""

_SNOWFLAKE_TABLES_QUERY = """
    SELECT table_name AS object_name
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = UPPER(?)
      AND TABLE_TYPE = 'BASE TABLE'
    ORDER BY table_name
"""

_SNOWFLAKE_SEQUENCES_QUERY = """
    SELECT sequence_name AS object_name
    FROM INFORMATION_SCHEMA.SEQUENCES
    WHERE SEQUENCE_SCHEMA = UPPER(?)
    ORDER BY sequence_name
"""
