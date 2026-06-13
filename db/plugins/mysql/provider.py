"""MySQL native provider backed by SQLAlchemy Core."""

from typing import Any, Dict, List, Optional

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.plugins.mysql.mysql.schema_operations import MySqlSchemaOperations
from db.sqlalchemy_provider import SqlAlchemyProvider


def _quote_identifier(identifier: str) -> str:
    return "`" + identifier.replace("`", "``") + "`"


class MySqlProvider(SqlAlchemyProvider):
    """MySQL provider implementation using native SQLAlchemy connections."""

    canonical_dialect_key = "mysql"
    MIGRATION_LOCK_TABLE = "dblift_migration_lock"

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the native MySQL provider."""
        super().__init__(config, log)

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a SQL statement, optionally preparing the database first."""
        if schema:
            self.create_schema_if_not_exists(schema)
            self.set_current_schema(schema)
        return super().execute_statement(sql, schema=schema, params=params)

    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create a MySQL database if it is missing."""
        exists = self.execute_query(
            """
            SELECT SCHEMA_NAME
            FROM information_schema.SCHEMATA
            WHERE SCHEMA_NAME = ?
            """,
            [schema],
        )
        if exists:
            return
        self.execute_statement(f"CREATE DATABASE IF NOT EXISTS {_quote_identifier(schema)}")

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Return whether a table exists in the given database."""
        rows = self.execute_query(
            """
            SELECT TABLE_NAME
            FROM information_schema.TABLES
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            """,
            [schema, table_name],
        )
        return bool(rows)

    def get_database_version(self) -> str:
        """Return MySQL version information."""
        rows = self.execute_query("SELECT VERSION() AS version")
        return f"MySQL {rows[0]['version']}" if rows else "MySQL Unknown Version"

    def supports_transactional_ddl(self) -> bool:
        """MySQL DDL auto-commits."""
        return False

    def set_current_schema(self, schema: str) -> None:
        """Set the current database for this connection."""
        super().execute_statement(f"USE {_quote_identifier(schema)}")

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a quoted database-qualified object name."""
        return f"{_quote_identifier(schema)}.{_quote_identifier(object_name)}"

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop objects inside a database, returning executed clean statements."""
        connection = self._ensure_connection()
        return MySqlSchemaOperations(self.query_executor, self.log).clean_schema(connection, schema)

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return the MySQL clean preview without executing drop statements."""
        connection = self._ensure_connection()
        return MySqlSchemaOperations(self.query_executor, self.log).get_clean_preview(
            connection, schema
        )

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the MySQL migration lock table if it is missing."""
        self.create_schema_if_not_exists(schema)
        self.execute_statement(f"""
            CREATE TABLE IF NOT EXISTS {self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE)} (
                lock_name VARCHAR(128) NOT NULL,
                acquired_at TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                acquired_by VARCHAR(128) NOT NULL,
                PRIMARY KEY (lock_name)
            ) ENGINE=InnoDB
            """)

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Acquire the MySQL named migration lock."""
        rows = self.execute_query(
            "SELECT GET_LOCK(?, ?) AS lock_result",
            [f"dblift_migration_{schema}", wait_timeout_seconds],
        )
        return bool(rows and rows[0].get("lock_result") == 1)

    def release_migration_lock(self, schema: str) -> bool:
        """Release the MySQL named migration lock."""
        rows = self.execute_query(
            "SELECT RELEASE_LOCK(?) AS lock_result",
            [f"dblift_migration_{schema}"],
        )
        return bool(rows and rows[0].get("lock_result") == 1)

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
        rows = self.execute_query(f"SELECT COUNT(1) AS count FROM {qualified_table}")
        migration_count = int(rows[0].get("count", rows[0].get("COUNT", 0)) or 0) if rows else 0
        if migration_count > 0:
            raise RuntimeError(
                f"Schema {schema} already contains a migration history table "
                f"{table_name} with {migration_count} migration(s). "
                "Baseline cannot be applied to a schema with existing migrations."
            )

    def create_snapshot_table_if_not_exists(
        self, schema: str, table_name: str = "dblift_schema_snapshots"
    ) -> None:
        """Create the schema snapshot table if it is missing."""
        self.create_schema_if_not_exists(schema)
        self.execute_statement(f"""
            CREATE TABLE IF NOT EXISTS {self.get_schema_qualified_name(schema, table_name)} (
                snapshot_id VARCHAR(255) PRIMARY KEY,
                captured_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                checksum VARCHAR(128),
                model_data LONGTEXT NOT NULL
            ) ENGINE=InnoDB
            """)

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Return SQL for the MySQL migration history table."""
        return f"""
            CREATE TABLE {self.get_schema_qualified_name(schema, table_name)} (
                installed_rank INT NOT NULL AUTO_INCREMENT,
                version VARCHAR(50),
                description VARCHAR(200) NOT NULL,
                type VARCHAR(20) NOT NULL,
                script VARCHAR(1000) NOT NULL,
                checksum INT,
                installed_by VARCHAR(100) NOT NULL,
                installed_on TIMESTAMP NOT NULL DEFAULT CURRENT_TIMESTAMP,
                execution_time INT NOT NULL,
                success BOOLEAN NOT NULL,
                PRIMARY KEY (installed_rank)
            ) ENGINE=InnoDB
            """

    def get_applied_migrations(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> List[Dict[str, Any]]:
        """Return applied migration rows from the history table."""
        if not self.table_exists(schema, table_name):
            return []
        rows = self.execute_query(f"""
            SELECT script, installed_rank, version, description,
                   type, checksum, installed_by, installed_on,
                   execution_time, success
            FROM {self.get_schema_qualified_name(schema, table_name)}
            ORDER BY installed_rank
            """)
        for row in rows:
            if "success" in row and row["success"] is not None:
                row["success"] = bool(row["success"])
        return rows

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
                bool(migration_info.get("success", True)),
            ],
        )

    def record_undo(
        self,
        schema: str,
        version: str,
        table_name: Optional[str] = None,
        script_name: Optional[str] = None,
    ) -> bool:
        """Record a successful undo operation in MySQL migration history."""
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

    def get_columns_query(self, schema: str, table: str) -> str:
        """Return a MySQL information_schema columns query."""
        return f"""
            SELECT COLUMN_NAME, DATA_TYPE, IS_NULLABLE, COLUMN_DEFAULT
            FROM information_schema.COLUMNS
            WHERE TABLE_SCHEMA = '{schema}' AND TABLE_NAME = '{table}'
            ORDER BY ORDINAL_POSITION
            """

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Generate MySQL-specific SQL to add a column to a table."""
        return (
            f"ALTER TABLE {self.get_schema_qualified_name(schema, table)} "
            f"ADD COLUMN {_quote_identifier(column)} {type_def}"
        )

    def get_parameter_placeholders(self, count: int) -> str:
        """Return DBLift positional placeholders."""
        return ", ".join(["?"] * count)

    def is_connection_error(self, exception: Any) -> bool:
        """Check if exception indicates a connection error."""
        error_msg = str(exception).lower()
        return any(
            keyword in error_msg
            for keyword in (
                "communications link failure",
                "connection refused",
                "connection reset",
                "connection timed out",
                "no route to host",
                "connection aborted",
            )
        )

    def is_duplicate_object_error(self, exception: Any) -> bool:
        """Check if exception indicates a duplicate object."""
        error_msg = str(exception).lower()
        return "already exists" in error_msg or "duplicate" in error_msg

    def is_object_not_found_error(self, exception: Any) -> bool:
        """Check if exception indicates object not found."""
        error_msg = str(exception).lower()
        return "doesn't exist" in error_msg or "unknown table" in error_msg

    def is_permission_error(self, exception: Any) -> bool:
        """Check if exception indicates permission error."""
        error_msg = str(exception).lower()
        return "access denied" in error_msg or "permission denied" in error_msg


__all__ = ["MySqlProvider"]
