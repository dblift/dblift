"""DB2 native provider backed by SQLAlchemy Core (ibm_db_sa)."""

import os
import socket
import time
from typing import Any, Dict, List, Optional, cast

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.object_naming import get_normalized_object_name
from db.plugins.db2.db2.schema_operations import Db2SchemaOperations
from db.provider_interfaces import DroppableObject
from db.sqlalchemy_provider import SqlAlchemyProvider

DB2_LOCK_STALE_SECONDS = 24 * 60 * 60


def _q(name: str) -> str:
    """Return a double-quoted DB2 identifier."""
    return '"' + name.replace('"', '""') + '"'


def _clean_identifier(name: str) -> str:
    """Return a bare identifier for DB2 catalog lookups."""
    return name.replace('"', "").strip()


def _schema_object(schema: str, obj: str) -> str:
    """Return a quoted schema-qualified DB2 object name."""
    return f"{_q(_clean_identifier(schema))}.{_q(_clean_identifier(obj))}"


def _db2_object_name(name: str) -> str:
    """Return the DB2-normalized object name."""
    return get_normalized_object_name(_clean_identifier(name), "db2")


def _row_value(row: Dict[str, Any], *names: str, default: Any = None) -> Any:
    """Read a value from a DB2 row mapping with case tolerance."""
    for name in names:
        if name in row:
            return row[name]
        upper = name.upper()
        if upper in row:
            return row[upper]
        lower = name.lower()
        if lower in row:
            return row[lower]
    return default


class _Db2ProviderQueryExecutor:
    """Adapt native provider methods to the DB2 schema-operations query API."""

    def __init__(self, provider: "Db2Provider") -> None:
        self.provider = provider

    def execute_query(
        self, _connection: Any, sql: str, params: Optional[List[Any]] = None
    ) -> List[Any]:
        """Execute a query through the native provider."""
        return list(self.provider.execute_query(sql, params))

    def execute_statement(
        self, _connection: Any, sql: str, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a statement through the native provider."""
        return int(self.provider.execute_statement(sql, params=params))

    def get_quoted_schema_name(self, schema: str) -> str:
        """Return a quoted DB2 schema identifier."""
        return _q(_clean_identifier(schema))

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return the provider's quoted schema-qualified object name."""
        return str(self.provider.get_schema_qualified_name(schema, object_name))

    def table_exists(self, _connection: Any, schema: str, table_name: str) -> bool:
        """Return whether a table exists through the native provider."""
        return bool(self.provider.table_exists(schema, table_name))


class _Db2NativeSchemaOperations(Db2SchemaOperations):
    """DB2 provider-backed schema operations."""

    def __init__(self, provider: "Db2Provider") -> None:
        self._provider = provider
        super().__init__(_Db2ProviderQueryExecutor(provider), getattr(provider, "log", None))

    def create_schema_if_not_exists(self, _connection: Any, schema: str) -> None:
        """Create a DB2 schema through the native provider."""
        self._provider.create_schema_if_not_exists(schema)


class Db2Provider(SqlAlchemyProvider):
    """DB2 provider implementation using native SQLAlchemy/ibm_db_sa."""

    canonical_dialect_key = "db2"
    provider_transport = "native"
    MIGRATION_LOCK_TABLE = "DBLIFT_MIGRATION_LOCK"

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the native DB2 provider."""
        super().__init__(config, log)
        self.schema_operations = _Db2NativeSchemaOperations(self)

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute SQL, stripping DB2 statement terminators for driver execution."""
        if schema:
            self.create_schema_if_not_exists(schema)
            self.set_current_schema(schema)
        stmt = sql.strip()
        while stmt.endswith(";"):
            stmt = stmt[:-1].rstrip()
        return super().execute_statement(stmt, schema=schema, params=params)

    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create a DB2 schema if it is missing."""
        clean_schema = _clean_identifier(schema)
        rows = self.execute_query(
            "SELECT SCHEMANAME FROM SYSCAT.SCHEMATA WHERE SCHEMANAME = ?",
            [clean_schema],
        )
        if rows:
            return
        self.execute_statement(f"CREATE SCHEMA {_q(clean_schema)}")

    def set_current_schema(self, schema: str) -> None:
        """Set the DB2 current schema for this connection."""
        self.execute_statement(f"SET SCHEMA {_q(_clean_identifier(schema))}")

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Return whether a table exists in the given DB2 schema."""
        rows = self.execute_query(
            """
            SELECT TABNAME
            FROM SYSCAT.TABLES
            WHERE UPPER(TABSCHEMA) = UPPER(?) AND UPPER(TABNAME) = UPPER(?)
            """,
            [_clean_identifier(schema), _clean_identifier(table_name)],
        )
        return bool(rows)

    def get_database_version(self) -> str:
        """Return DB2 version information.

        Reads ``dbms_ver``/``dbms_name`` off the driver's own connection
        handle (populated from the CLI handshake at connect time) instead of
        querying ``SYSIBMADM.ENV_INST_INFO`` — that admin view is backed by
        a fenced stored procedure and raises SQL1646N whenever the fenced
        user can't reach the instance's ``sqllib`` directory (common on
        minimal/containerized installs), which broke version lookup on
        every single command.
        """
        try:
            raw = self._ensure_connection().connection
            dbms_ver = getattr(raw, "dbms_ver", None)
            if dbms_ver:
                return f"DB2 {dbms_ver}"
            rows = self.execute_query("SELECT CURRENT SERVER AS DB_NAME FROM SYSIBM.SYSDUMMY1")
            if rows:
                return f"DB2 {_row_value(rows[0], 'DB_NAME', default='Unknown')}"
        except Exception as e:
            self.log.warning(f"Error getting DB2 version: {e}")
        return "DB2 Unknown Version"

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a quoted schema-qualified DB2 object name."""
        return _schema_object(schema, object_name)

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[str]]:
        """Return a DB2 catalog query for table columns."""
        return (
            """
            SELECT COLNAME AS column_name, TYPENAME AS data_type
            FROM SYSCAT.COLUMNS
            WHERE UPPER(TABSCHEMA) = UPPER(?) AND UPPER(TABNAME) = UPPER(?)
            ORDER BY COLNO
            """,
            [_clean_identifier(schema), _clean_identifier(table)],
        )

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Return DB2 DDL to add a column."""
        return f"ALTER TABLE {_schema_object(schema, table)} ADD COLUMN {_q(column)} {type_def}"

    def get_parameter_placeholders(self, count: int) -> str:
        """Return DB2 parameter placeholders."""
        return ", ".join(["?" for _ in range(count)])

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the DB2 migration lock table if it is missing."""
        self.create_schema_if_not_exists(schema)
        if self.table_exists(schema, self.MIGRATION_LOCK_TABLE):
            return
        self.execute_statement(f"""
            CREATE TABLE {_schema_object(schema, self.MIGRATION_LOCK_TABLE)} (
                LOCK_NAME VARCHAR(128) NOT NULL PRIMARY KEY,
                ACQUIRED_AT TIMESTAMP NOT NULL,
                ACQUIRED_BY VARCHAR(128) NOT NULL
            )
            """)

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Acquire a table-backed DB2 migration lock."""
        self.create_migration_lock_table_if_not_exists(schema)
        lock_identity = (
            f"{os.environ.get('USER', os.environ.get('USERNAME', 'unknown'))}"
            f"@{socket.gethostname()}:{os.getpid()}"
        )
        timeout = max(0, int(wait_timeout_seconds))
        deadline = time.monotonic() + timeout
        stale_cleanup_sql = (
            f"DELETE FROM {_schema_object(schema, self.MIGRATION_LOCK_TABLE)} "
            "WHERE LOCK_NAME = ? "
            f"AND ACQUIRED_AT < CURRENT TIMESTAMP - {DB2_LOCK_STALE_SECONDS} SECONDS"
        )
        insert_sql = f"""
            INSERT INTO {_schema_object(schema, self.MIGRATION_LOCK_TABLE)}
                (LOCK_NAME, ACQUIRED_AT, ACQUIRED_BY)
            VALUES (?, CURRENT TIMESTAMP, ?)
            """

        try:
            self.execute_statement(stale_cleanup_sql, params=["migration"])
        except Exception as e:
            self.log.debug(f"Could not clean stale DB2 migration locks: {e}")

        while True:
            try:
                self.execute_statement(
                    insert_sql,
                    params=["migration", lock_identity],
                )
                return True
            except Exception as e:
                connection = getattr(self, "_connection", None)
                if connection is not None:
                    try:
                        connection.rollback()
                    except Exception as rollback_error:
                        self.log.debug(f"Could not rollback DB2 lock attempt: {rollback_error}")
                if time.monotonic() >= deadline:
                    self.log.debug(f"Could not acquire DB2 migration lock: {e}")
                    return False
                time.sleep(min(1, max(0, deadline - time.monotonic())))

    def release_migration_lock(self, schema: str) -> bool:
        """Release the table-backed DB2 migration lock."""
        if not self.table_exists(schema, self.MIGRATION_LOCK_TABLE):
            return True
        affected = self.execute_statement(
            f"DELETE FROM {_schema_object(schema, self.MIGRATION_LOCK_TABLE)} WHERE LOCK_NAME = ?",
            params=["migration"],
        )
        return affected > 0

    def create_migration_history_table_if_not_exists(
        self,
        schema: str,
        create_schema: bool = False,
        table_name: str = "DBLIFT_SCHEMA_HISTORY",
    ) -> None:
        """Create the DB2 migration history table if it is missing."""
        table_name = _db2_object_name(table_name)
        if create_schema:
            self.create_schema_if_not_exists(schema)
        if self.table_exists(schema, table_name):
            if create_schema:
                self._check_baseline_safety(schema, table_name)
            return
        self.create_schema_if_not_exists(schema)
        self.execute_statement(self.create_history_table(schema, table_name))

    def _check_baseline_safety(self, schema: str, table_name: str) -> None:
        rows = self.execute_query(
            f"SELECT COUNT(1) AS COUNT FROM {_schema_object(schema, table_name)}"
        )
        count = int(_row_value(rows[0], "COUNT", default=0)) if rows else 0
        if count > 0:
            raise RuntimeError(
                f"Schema {schema} already contains a migration history table "
                f"{table_name} with {count} migration(s). "
                "Baseline cannot be applied to a schema with existing migrations."
            )

    def create_history_table(self, schema: str, table_name: str = "DBLIFT_SCHEMA_HISTORY") -> str:
        """Return SQL for the DB2 migration history table."""
        table_name = _db2_object_name(table_name)
        return f"""
            CREATE TABLE {_schema_object(schema, table_name)} (
                INSTALLED_RANK INTEGER NOT NULL GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                VERSION VARCHAR(50),
                DESCRIPTION VARCHAR(200) NOT NULL,
                TYPE VARCHAR(20) NOT NULL,
                SCRIPT VARCHAR(1000) NOT NULL,
                CHECKSUM INTEGER,
                INSTALLED_BY VARCHAR(100) NOT NULL,
                INSTALLED_ON TIMESTAMP DEFAULT CURRENT TIMESTAMP NOT NULL,
                EXECUTION_TIME INTEGER NOT NULL,
                SUCCESS SMALLINT NOT NULL
            )
        """

    def get_applied_migrations(
        self, schema: str, table_name: str = "DBLIFT_SCHEMA_HISTORY"
    ) -> List[Dict[str, Any]]:
        """Return applied migration rows from the DB2 history table."""
        table_name = _db2_object_name(table_name)
        if not self.table_exists(schema, table_name):
            return []
        rows = self.execute_query(f"""
            SELECT SCRIPT, INSTALLED_RANK, VERSION, DESCRIPTION, TYPE, CHECKSUM,
                   INSTALLED_BY, INSTALLED_ON, EXECUTION_TIME, SUCCESS
            FROM {_schema_object(schema, table_name)}
            ORDER BY INSTALLED_RANK
            """)
        normalized = []
        for row in rows:
            item = {str(key).lower(): value for key, value in row.items()}
            if item.get("success") is not None:
                item["success"] = bool(int(item["success"]))
            normalized.append(item)
        return normalized

    def record_migration(
        self, schema: str, migration_info: Dict[str, Any], table_name: str = "DBLIFT_SCHEMA_HISTORY"
    ) -> None:
        """Insert a migration record into the DB2 history table."""
        table_name = _db2_object_name(table_name)
        self.create_migration_history_table_if_not_exists(schema, table_name=table_name)
        self.execute_statement(
            f"""
            INSERT INTO {_schema_object(schema, table_name)}
                (VERSION, DESCRIPTION, TYPE, SCRIPT, CHECKSUM, INSTALLED_BY, EXECUTION_TIME, SUCCESS)
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
                1 if migration_info.get("success", True) else 0,
            ],
        )

    def record_undo(
        self,
        schema: str,
        version: str,
        table_name: Optional[str] = None,
        script_name: Optional[str] = None,
    ) -> bool:
        """Record a successful DB2 undo operation."""
        self.record_migration(
            schema,
            {
                "version": version,
                "description": f"Undo migration {version}",
                "type": "UNDO_SQL",
                "script": script_name or f"UNDO_{version}.sql",
                "checksum": 0,
                "execution_time": 0,
                "success": True,
            },
            table_name or "DBLIFT_SCHEMA_HISTORY",
        )
        return True

    def repair_migration_history(
        self,
        schema: str,
        script_name: str,
        checksum: Any,
        table_name: str = "DBLIFT_SCHEMA_HISTORY",
        success_value: Optional[Any] = None,
    ) -> bool:
        """Update checksum and success state for an existing DB2 migration row."""
        table_name = _db2_object_name(table_name)
        if not self.table_exists(schema, table_name):
            return False
        if success_value is None:
            affected = self.execute_statement(
                f"UPDATE {_schema_object(schema, table_name)} SET CHECKSUM = ?, SUCCESS = 0 "
                "WHERE SCRIPT = ?",
                params=[checksum, script_name],
            )
        else:
            affected = self.execute_statement(
                f"UPDATE {_schema_object(schema, table_name)} SET CHECKSUM = ?, SUCCESS = ? "
                "WHERE SCRIPT = ?",
                params=[checksum, 1 if success_value else 0, script_name],
            )
        return affected > 0

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop user objects from the DB2 schema."""
        connection = self._ensure_connection()
        return self._schema_operations().clean_schema(connection, schema)

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return what DB2 clean would drop without executing drops."""
        connection = self._ensure_connection()
        return self._schema_operations().get_clean_preview(connection, schema)

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return DB2 objects in the same order clean preview reports them."""
        summary = self.get_clean_preview(schema)
        return [
            DroppableObject(name=obj.name, object_type=obj.object_type, drop_sql=drop_sql)
            for obj, drop_sql in zip(summary.objects, summary.statements)
        ]

    def _schema_operations(self) -> Db2SchemaOperations:
        ops = getattr(self, "schema_operations", None)
        if ops is not None and hasattr(ops, "clean_schema") and hasattr(ops, "get_clean_preview"):
            return cast(Db2SchemaOperations, ops)
        ops = _Db2NativeSchemaOperations(self)
        self.schema_operations = ops
        return ops
