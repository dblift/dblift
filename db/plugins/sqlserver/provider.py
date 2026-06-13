"""SQL Server native provider backed by SQLAlchemy Core (pymssql)."""

import os
from typing import Any, Dict, List, Optional

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.sqlalchemy_provider import SqlAlchemyProvider


def _q(name: str) -> str:
    """Return a T-SQL bracket-quoted identifier."""
    return "[" + name.replace("]", "]]") + "]"


def _schema_object(schema: str, obj: str) -> str:
    """Return a bracket-quoted schema-qualified name."""
    return f"{_q(schema)}.{_q(obj)}"


class SqlServerProvider(SqlAlchemyProvider):
    """SQL Server provider implementation using native SQLAlchemy/pymssql."""

    canonical_dialect_key = "sqlserver"
    MIGRATION_LOCK_TABLE = "dblift_migration_lock"

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the native SQL Server provider."""
        super().__init__(config, log)

    # ------------------------------------------------------------------
    # SchemaProvider
    # ------------------------------------------------------------------

    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create a SQL Server schema if it does not already exist."""
        rows = self.execute_query(
            "SELECT COUNT(1) AS cnt FROM sys.schemas WHERE name = ?",
            [schema],
        )
        if rows and int(rows[0].get("cnt", 0)) > 0:
            return
        # CREATE SCHEMA must run in its own batch; pymssql handles that fine.
        self.execute_statement(f"CREATE SCHEMA {_q(schema)}")

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a SQL statement, creating the migration schema when requested."""
        if schema:
            self.create_schema_if_not_exists(schema)
        return super().execute_statement(sql, schema=schema, params=params)

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Return whether a table exists in the given schema."""
        rows = self.execute_query(
            """
            SELECT COUNT(1) AS cnt
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = ? AND t.name = ?
            """,
            [schema, table_name],
        )
        return bool(rows and int(rows[0].get("cnt", 0)) > 0)

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a bracket-quoted schema-qualified name."""
        return _schema_object(schema, object_name)

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[str]]:
        """Return a SQL Server catalog query for table columns."""
        return (
            """
            SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type
            FROM INFORMATION_SCHEMA.COLUMNS
            WHERE TABLE_SCHEMA = ? AND TABLE_NAME = ?
            ORDER BY ORDINAL_POSITION
            """,
            [schema, table],
        )

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Return SQL Server DDL to add a column."""
        return f"ALTER TABLE {_schema_object(schema, table)} ADD {_q(column)} {type_def}"

    def get_parameter_placeholders(self, count: int) -> str:
        """Return SQL Server parameter placeholders."""
        return ", ".join(["?" for _ in range(count)])

    def set_current_schema(self, schema: str) -> None:
        """No-op: SQL Server uses schema-qualified names, not session search path."""
        self.log.debug(
            "SQL Server: set_current_schema is a no-op; "
            "schema qualification is embedded in object names."
        )

    # ------------------------------------------------------------------
    # Version
    # ------------------------------------------------------------------

    def get_database_version(self) -> str:
        """Return the first line of @@VERSION."""
        rows = self.execute_query("SELECT @@VERSION AS v")
        if rows:
            return str(rows[0].get("v", "Unknown SQL Server Version")).split("\n")[0]
        return "Unknown SQL Server Version"

    # ------------------------------------------------------------------
    # Locking
    # ------------------------------------------------------------------

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the migration lock table in SQL Server if it is missing."""
        self.create_schema_if_not_exists(schema)
        lock_table = _schema_object(schema, self.MIGRATION_LOCK_TABLE)
        self.execute_statement(
            f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE s.name = ? AND t.name = ?
            )
            CREATE TABLE {lock_table} (
                lock_name NVARCHAR(128) NOT NULL PRIMARY KEY,
                acquired_at DATETIME2 DEFAULT GETDATE() NOT NULL,
                acquired_by NVARCHAR(256) DEFAULT SUSER_NAME() NOT NULL
            )
        """,
            params=[schema, self.MIGRATION_LOCK_TABLE],
        )

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Acquire a session-scoped SQL Server application lock."""
        lock_name = f"dblift_migration_lock_{schema}"
        rows = self.execute_query(
            """
            DECLARE @result INT;
            EXEC @result = sp_getapplock
                @Resource = ?,
                @LockMode = 'Exclusive',
                @LockOwner = 'Session',
                @LockTimeout = ?;
            SELECT @result AS lock_result;
            """,
            [lock_name, wait_timeout_seconds * 1000],
        )
        if not rows:
            return False
        return int(rows[0].get("lock_result", -1)) in (0, 1)

    def release_migration_lock(self, schema: str) -> bool:
        """Release the session-scoped SQL Server application lock."""
        lock_name = f"dblift_migration_lock_{schema}"
        rows = self.execute_query(
            """
            DECLARE @result INT;
            EXEC @result = sp_releaseapplock
                @Resource = ?,
                @LockOwner = 'Session';
            SELECT @result AS release_result;
            """,
            [lock_name],
        )
        if not rows:
            return False
        return int(rows[0].get("release_result", -1)) == 0

    # ------------------------------------------------------------------
    # Migration history
    # ------------------------------------------------------------------

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Return the DDL for the SQL Server migration history table."""
        qualified = _schema_object(schema, table_name)
        return f"""
            CREATE TABLE {qualified} (
                installed_rank INT IDENTITY(1,1) PRIMARY KEY,
                version NVARCHAR(50),
                description NVARCHAR(200) NOT NULL,
                type NVARCHAR(20) NOT NULL,
                script NVARCHAR(1000) NOT NULL,
                checksum INT,
                installed_by NVARCHAR(100) NOT NULL,
                installed_on DATETIME2 NOT NULL DEFAULT GETDATE(),
                execution_time INT NOT NULL,
                success BIT NOT NULL
            )
        """

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
        """Refuse baseline when the history table already has migrations."""
        qualified = _schema_object(schema, table_name)
        rows = self.execute_query(f"SELECT COUNT(1) AS cnt FROM {qualified}")
        count = int(rows[0].get("cnt", 0)) if rows else 0
        if count > 0:
            raise RuntimeError(
                f"Schema {schema} already contains a migration history table "
                f"{table_name} with {count} migration(s). "
                "Baseline cannot be applied to a schema with existing migrations."
            )

    def create_snapshot_table_if_not_exists(
        self, schema: str, table_name: str = "dblift_schema_snapshots"
    ) -> None:
        """Create the schema snapshot table if it is missing."""
        self.create_schema_if_not_exists(schema)
        qualified = _schema_object(schema, table_name)
        self.execute_statement(
            f"""
            IF NOT EXISTS (
                SELECT 1 FROM sys.tables t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE s.name = ? AND t.name = ?
            )
            CREATE TABLE {qualified} (
                snapshot_id NVARCHAR(255) NOT NULL PRIMARY KEY,
                captured_at DATETIME2 DEFAULT GETDATE(),
                checksum NVARCHAR(128),
                model_data NVARCHAR(MAX) NOT NULL
            )
        """,
            params=[schema, table_name],
        )

    def record_migration(
        self,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Insert a migration record into the history table."""
        self.create_migration_history_table_if_not_exists(schema, table_name=table_name)
        qualified = _schema_object(schema, table_name)
        success_val = 1 if migration_info.get("success", True) else 0
        self.execute_statement(
            f"""
            INSERT INTO {qualified}
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
                success_val,
            ],
        )

    def get_applied_migrations(
        self, schema: str, table_name: str = "dblift_schema_history"
    ) -> List[Dict[str, Any]]:
        """Return applied migration rows from the history table."""
        if not self.table_exists(schema, table_name):
            return []
        qualified = _schema_object(schema, table_name)
        return self.execute_query(f"""
            SELECT *
            FROM {qualified}
            ORDER BY installed_rank
        """)

    def record_undo(
        self,
        schema: str,
        version: str,
        table_name: Optional[str] = None,
        script_name: Optional[str] = None,
    ) -> bool:
        """Record a successful undo operation in the SQL Server migration history."""
        undo_script = script_name or f"UNDO_{version}.sql"
        self.record_migration(
            schema,
            {
                "version": version,
                "description": f"Undo migration {version}",
                "type": "UNDO_SQL",
                "script": undo_script,
                "checksum": 0,
                "installed_by": os.environ.get("USER", os.environ.get("USERNAME", "dblift")),
                "execution_time": 0,
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
        qualified = _schema_object(schema, table_name)
        if success_value is None:
            result = self.execute_statement(
                f"UPDATE {qualified} SET checksum = ?, success = 0 WHERE script = ?",
                params=[checksum, script_name],
            )
        else:
            success_bit = 1 if success_value else 0
            result = self.execute_statement(
                f"UPDATE {qualified} SET checksum = ?, success = ? WHERE script = ?",
                params=[checksum, success_bit, script_name],
            )
        return result > 0

    # ------------------------------------------------------------------
    # Schema cleaning
    # ------------------------------------------------------------------

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop all user objects from the SQL Server schema."""
        summary = CleanExecutionSummary()

        # 1. Foreign keys
        fks = self.execute_query(
            """
            SELECT fk.name AS constraint_name, t.name AS table_name
            FROM sys.foreign_keys fk
            JOIN sys.tables t ON fk.parent_object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = ?
            """,
            [schema],
        )
        for row in fks:
            stmt = (
                f"ALTER TABLE {_schema_object(schema, row['table_name'])} "
                f"DROP CONSTRAINT {_q(row['constraint_name'])}"
            )
            try:
                self.execute_statement(stmt)
                summary.add_statement(stmt)
                summary.add_object("foreign_key", row["constraint_name"], schema=schema)
            except Exception as e:
                self.log.warning(f"Failed to drop FK {row['constraint_name']}: {e}")

        # 2. Views
        views = self.execute_query(
            "SELECT TABLE_NAME AS view_name FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA = ?",
            [schema],
        )
        for row in views:
            stmt = f"DROP VIEW {_schema_object(schema, row['view_name'])}"
            try:
                self.execute_statement(stmt)
                summary.add_statement(stmt)
                summary.add_object("view", row["view_name"], schema=schema)
            except Exception as e:
                self.log.warning(f"Failed to drop view {row['view_name']}: {e}")

        # 3. Tables (disable system-versioning first for temporal tables)
        tables = self.execute_query(
            """
            SELECT t.name AS table_name, t.temporal_type
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = ? AND t.type = 'U'
            """,
            [schema],
        )
        for row in tables:
            tname = row["table_name"]
            if row.get("temporal_type") == 2:
                pre = f"ALTER TABLE {_schema_object(schema, tname)} SET (SYSTEM_VERSIONING = OFF)"
                try:
                    self.execute_statement(pre)
                    summary.add_statement(pre)
                except Exception as e:
                    self.log.warning(f"Failed to disable system versioning for {tname}: {e}")
            stmt = f"DROP TABLE {_schema_object(schema, tname)}"
            try:
                self.execute_statement(stmt)
                summary.add_statement(stmt)
                summary.add_object("table", tname, schema=schema)
            except Exception as e:
                self.log.warning(f"Failed to drop table {tname}: {e}")

        # 4. Stored procedures and functions
        routines = self.execute_query(
            """
            SELECT ROUTINE_NAME AS routine_name, ROUTINE_TYPE AS routine_type
            FROM INFORMATION_SCHEMA.ROUTINES
            WHERE ROUTINE_SCHEMA = ?
            """,
            [schema],
        )
        for row in routines:
            rtype = row["routine_type"].upper()
            keyword = "PROCEDURE" if rtype == "PROCEDURE" else "FUNCTION"
            stmt = f"DROP {keyword} {_schema_object(schema, row['routine_name'])}"
            try:
                self.execute_statement(stmt)
                summary.add_statement(stmt)
                summary.add_object(row["routine_type"].lower(), row["routine_name"], schema=schema)
            except Exception as e:
                self.log.warning(f"Failed to drop {keyword} {row['routine_name']}: {e}")

        # 5. Sequences
        try:
            seqs = self.execute_query(
                """
                SELECT s.name AS sequence_name
                FROM sys.sequences s
                JOIN sys.schemas sc ON s.schema_id = sc.schema_id
                WHERE sc.name = ?
                """,
                [schema],
            )
            for row in seqs:
                stmt = f"DROP SEQUENCE {_schema_object(schema, row['sequence_name'])}"
                try:
                    self.execute_statement(stmt)
                    summary.add_statement(stmt)
                    summary.add_object("sequence", row["sequence_name"], schema=schema)
                except Exception as e:
                    self.log.warning(f"Failed to drop sequence {row['sequence_name']}: {e}")
        except Exception as e:
            self.log.debug(f"Could not query sequences: {e}")

        # 6. User-defined types
        try:
            types = self.execute_query(
                """
                SELECT t.name AS type_name
                FROM sys.types t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE s.name = ? AND t.is_user_defined = 1
                """,
                [schema],
            )
            for row in types:
                stmt = f"DROP TYPE {_schema_object(schema, row['type_name'])}"
                try:
                    self.execute_statement(stmt)
                    summary.add_statement(stmt)
                    summary.add_object("type", row["type_name"], schema=schema)
                except Exception as e:
                    self.log.warning(f"Failed to drop type {row['type_name']}: {e}")
        except Exception as e:
            self.log.debug(f"Could not query user-defined types: {e}")

        # 7. Synonyms
        try:
            syns = self.execute_query(
                """
                SELECT s.name AS synonym_name
                FROM sys.synonyms s
                JOIN sys.schemas sc ON s.schema_id = sc.schema_id
                WHERE sc.name = ?
                """,
                [schema],
            )
            for row in syns:
                stmt = f"DROP SYNONYM {_schema_object(schema, row['synonym_name'])}"
                try:
                    self.execute_statement(stmt)
                    summary.add_statement(stmt)
                    summary.add_object("synonym", row["synonym_name"], schema=schema)
                except Exception as e:
                    self.log.warning(f"Failed to drop synonym {row['synonym_name']}: {e}")
        except Exception as e:
            self.log.debug(f"Could not query synonyms: {e}")

        return summary

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return what a clean would drop, without executing anything."""
        summary = CleanExecutionSummary()

        fks = self.execute_query(
            """
            SELECT fk.name AS constraint_name, t.name AS table_name
            FROM sys.foreign_keys fk
            JOIN sys.tables t ON fk.parent_object_id = t.object_id
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = ?
            """,
            [schema],
        )
        for row in fks:
            stmt = (
                f"ALTER TABLE {_schema_object(schema, row['table_name'])} "
                f"DROP CONSTRAINT {_q(row['constraint_name'])}"
            )
            summary.add_statement(stmt)
            summary.add_object("foreign_key", row["constraint_name"], schema=schema)

        views = self.execute_query(
            "SELECT TABLE_NAME AS view_name FROM INFORMATION_SCHEMA.VIEWS WHERE TABLE_SCHEMA = ?",
            [schema],
        )
        for row in views:
            stmt = f"DROP VIEW {_schema_object(schema, row['view_name'])}"
            summary.add_statement(stmt)
            summary.add_object("view", row["view_name"], schema=schema)

        tables = self.execute_query(
            """
            SELECT t.name AS table_name, t.temporal_type
            FROM sys.tables t
            JOIN sys.schemas s ON t.schema_id = s.schema_id
            WHERE s.name = ? AND t.type = 'U'
            """,
            [schema],
        )
        for row in tables:
            tname = row["table_name"]
            if row.get("temporal_type") == 2:
                summary.add_statement(
                    f"ALTER TABLE {_schema_object(schema, tname)} SET (SYSTEM_VERSIONING = OFF)"
                )
            stmt = f"DROP TABLE {_schema_object(schema, tname)}"
            summary.add_statement(stmt)
            summary.add_object("table", tname, schema=schema)

        routines = self.execute_query(
            """
            SELECT ROUTINE_NAME AS routine_name, ROUTINE_TYPE AS routine_type
            FROM INFORMATION_SCHEMA.ROUTINES
            WHERE ROUTINE_SCHEMA = ?
            """,
            [schema],
        )
        for row in routines:
            rtype = row["routine_type"].upper()
            keyword = "PROCEDURE" if rtype == "PROCEDURE" else "FUNCTION"
            stmt = f"DROP {keyword} {_schema_object(schema, row['routine_name'])}"
            summary.add_statement(stmt)
            summary.add_object(row["routine_type"].lower(), row["routine_name"], schema=schema)

        try:
            seqs = self.execute_query(
                """
                SELECT s.name AS sequence_name
                FROM sys.sequences s
                JOIN sys.schemas sc ON s.schema_id = sc.schema_id
                WHERE sc.name = ?
                """,
                [schema],
            )
            for row in seqs:
                stmt = f"DROP SEQUENCE {_schema_object(schema, row['sequence_name'])}"
                summary.add_statement(stmt)
                summary.add_object("sequence", row["sequence_name"], schema=schema)
        except Exception as e:
            self.log.debug(f"Could not query sequences for preview: {e}")

        try:
            types = self.execute_query(
                """
                SELECT t.name AS type_name
                FROM sys.types t
                JOIN sys.schemas s ON t.schema_id = s.schema_id
                WHERE s.name = ? AND t.is_user_defined = 1
                """,
                [schema],
            )
            for row in types:
                stmt = f"DROP TYPE {_schema_object(schema, row['type_name'])}"
                summary.add_statement(stmt)
                summary.add_object("type", row["type_name"], schema=schema)
        except Exception as e:
            self.log.debug(f"Could not query user-defined types for preview: {e}")

        try:
            syns = self.execute_query(
                """
                SELECT s.name AS synonym_name
                FROM sys.synonyms s
                JOIN sys.schemas sc ON s.schema_id = sc.schema_id
                WHERE sc.name = ?
                """,
                [schema],
            )
            for row in syns:
                stmt = f"DROP SYNONYM {_schema_object(schema, row['synonym_name'])}"
                summary.add_statement(stmt)
                summary.add_object("synonym", row["synonym_name"], schema=schema)
        except Exception as e:
            self.log.debug(f"Could not query synonyms for preview: {e}")

        return summary
