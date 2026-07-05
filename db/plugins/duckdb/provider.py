"""DuckDB provider backed by SQLAlchemy Core (duckdb_engine driver)."""

import time
from typing import Any, Dict, List, Optional

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.provider_interfaces import DroppableObject
from db.sqlalchemy_provider import SqlAlchemyProvider


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


class DuckDBProvider(SqlAlchemyProvider):
    """DuckDB provider implementation using SQLAlchemy (duckdb_engine)."""

    canonical_dialect_key = "duckdb"
    MIGRATION_LOCK_TABLE = "dblift_migration_lock"

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the DuckDB provider."""
        super().__init__(config, log)

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a SQL statement, optionally preparing the schema first."""
        if schema:
            self.create_schema_if_not_exists(schema)
            self.set_current_schema(schema)
        return super().execute_statement(sql, schema=schema, params=params)

    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create a DuckDB schema if it is missing."""
        rows = self.execute_query(
            "SELECT 1 AS present FROM information_schema.schemata WHERE schema_name = ?",
            [schema],
        )
        if rows:
            return
        self.execute_statement(f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(schema)}")

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Return whether a table exists in the given schema."""
        rows = self.execute_query(
            """
            SELECT 1 AS present
            FROM information_schema.tables
            WHERE table_schema = ?
              AND table_name = ?
            """,
            [schema, table_name],
        )
        return bool(rows)

    def get_database_version(self) -> str:
        """Return DuckDB version information."""
        rows = self.execute_query("SELECT version() AS version")
        return str(rows[0]["version"]) if rows else "Unknown DuckDB Version"

    def set_current_schema(self, schema: str) -> None:
        """Set the DuckDB search path for this connection."""
        super().execute_statement(f"SET search_path = {_quote_identifier(schema)}")

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a quoted schema-qualified object name."""
        return f"{_quote_identifier(schema)}.{_quote_identifier(object_name)}"

    # --- clean -----------------------------------------------------------
    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop all objects in a schema (native strategy).

        Order is set by :meth:`get_clean_preview` (views, then tables in
        FK-dependency order, then sequences), so a plain in-order execution
        drops everything.
        """
        summary = self.get_clean_preview(schema)
        for stmt in summary.statements:
            self.execute_statement(stmt)
        return summary

    def _fk_ordered_tables(self, schema: str) -> List[str]:
        """Return base-table names with referencing tables before referenced.

        DuckDB's ``DROP TABLE ... CASCADE`` does not drop foreign keys held by
        *other* tables, so a referenced table can only be dropped once every
        referencing table is gone. Topologically sort so children precede
        parents (both the CLI clean executor and ``clean_schema`` consume this
        order).
        """
        tables = {
            row["table_name"]
            for row in self.execute_query(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = ? AND table_type = 'BASE TABLE'",
                [schema],
            )
        }
        # child -> set of parents it references (within this schema)
        parents: dict[str, set[str]] = {t: set() for t in tables}
        referencers: dict[str, set[str]] = {t: set() for t in tables}
        for row in self.execute_query(
            """
            SELECT DISTINCT kcu.table_name AS child, ref.table_name AS parent
            FROM information_schema.referential_constraints rc
            JOIN information_schema.key_column_usage kcu
                ON kcu.constraint_name = rc.constraint_name
                AND kcu.constraint_schema = rc.constraint_schema
            JOIN information_schema.key_column_usage ref
                ON ref.constraint_name = rc.unique_constraint_name
                AND ref.constraint_schema = rc.unique_constraint_schema
            WHERE rc.constraint_schema = ?
            """,
            [schema],
        ):
            child, parent = row["child"], row["parent"]
            if child in tables and parent in tables and child != parent:
                parents[child].add(parent)
                referencers[parent].add(child)
        # Kahn: emit tables no remaining table references (children first).
        indegree = {t: len(referencers[t]) for t in tables}
        queue = sorted(t for t in tables if indegree[t] == 0)
        ordered: List[str] = []
        while queue:
            table = queue.pop(0)
            ordered.append(table)
            for parent in sorted(parents[table]):
                indegree[parent] -= 1
                if indegree[parent] == 0:
                    queue.append(parent)
        # Any leftover (circular FK) — append deterministically.
        ordered.extend(sorted(t for t in tables if t not in ordered))
        return ordered

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Enumerate droppable DuckDB objects without executing the drops."""
        objects: List[Any] = []
        statements: List[str] = []
        # Views first (they depend on tables), then tables in FK-dependency
        # order, then sequences.
        for row in self.execute_query(
            "SELECT table_name FROM information_schema.tables "
            "WHERE table_schema = ? AND table_type = 'VIEW'",
            [schema],
        ):
            name = row["table_name"]
            objects.append(DroppableObject(name=name, object_type="VIEW", drop_sql=""))
            statements.append(f"DROP VIEW IF EXISTS {self.get_schema_qualified_name(schema, name)}")
        for name in self._fk_ordered_tables(schema):
            objects.append(DroppableObject(name=name, object_type="TABLE", drop_sql=""))
            statements.append(
                f"DROP TABLE IF EXISTS {self.get_schema_qualified_name(schema, name)} CASCADE"
            )
        # DuckDB exposes sequences via the duckdb_sequences() function,
        # not information_schema.sequences.
        for row in self.execute_query(
            "SELECT sequence_name FROM duckdb_sequences() WHERE schema_name = ?",
            [schema],
        ):
            name = row["sequence_name"]
            objects.append(DroppableObject(name=name, object_type="SEQUENCE", drop_sql=""))
            statements.append(
                f"DROP SEQUENCE IF EXISTS {self.get_schema_qualified_name(schema, name)}"
            )
        return CleanExecutionSummary(objects=objects, statements=statements)

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return DuckDB objects in the same order as clean preview."""
        summary = self.get_clean_preview(schema)
        return [
            DroppableObject(name=obj.name, object_type=obj.object_type, drop_sql=drop_sql)
            for obj, drop_sql in zip(summary.objects, summary.statements)
        ]

    # --- locking (table-based; DuckDB has no advisory locks) -------------
    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the DuckDB migration lock table if it is missing."""
        self.create_schema_if_not_exists(schema)
        self.execute_statement(f"""
            CREATE TABLE IF NOT EXISTS {self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE)} (
                lock_name VARCHAR PRIMARY KEY,
                locked_at TIMESTAMP DEFAULT now()
            )
            """)

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Acquire the migration lock by inserting the lock row.

        A primary-key conflict (``IntegrityError``) means the lock is held —
        retry until the timeout. Any other error (connection loss, permissions,
        a dropped lock table) is unexpected and propagates rather than being
        masked as routine contention.
        """
        from sqlalchemy.exc import IntegrityError

        self.create_migration_lock_table_if_not_exists(schema)
        qualified = self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE)
        deadline = time.monotonic() + wait_timeout_seconds
        while True:
            try:
                self.execute_statement(
                    f"INSERT INTO {qualified} (lock_name) VALUES (?)", params=["migration"]
                )
                return True
            except IntegrityError:
                if time.monotonic() >= deadline:
                    return False
                time.sleep(0.2)

    def release_migration_lock(self, schema: str) -> bool:
        """Release the migration lock by deleting the lock row.

        DuckDB reports ``-1`` rowcount for DML, so success is "the DELETE
        executed" rather than a rowcount check.
        """
        qualified = self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE)
        self.execute_statement(f"DELETE FROM {qualified} WHERE lock_name = ?", params=["migration"])
        return True

    # --- migration history ----------------------------------------------
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

    def _history_sequence_name(self, table_name: str) -> str:
        return f"{table_name}_rank_seq"

    def create_migration_history_table_if_not_exists(
        self,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the migration history table (and its rank sequence) if missing."""
        if create_schema:
            self.create_schema_if_not_exists(schema)
        if self.table_exists(schema, table_name):
            if create_schema:
                self._check_baseline_safety(schema, table_name)
            return
        seq = self.get_schema_qualified_name(schema, self._history_sequence_name(table_name))
        self.execute_statement(f"CREATE SEQUENCE IF NOT EXISTS {seq}")
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
        """Record a successful undo operation in DuckDB migration history."""
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
        """Update checksum and success state for an existing migration row.

        DuckDB reports ``-1`` rowcount for DML, so existence is checked with a
        SELECT before the UPDATE to report whether a row was actually repaired.
        """
        if not self.table_exists(schema, table_name):
            return False
        qualified = self.get_schema_qualified_name(schema, table_name)
        if not self.execute_query(f"SELECT 1 FROM {qualified} WHERE script = ?", [script_name]):
            return False
        self.execute_statement(
            f"""
            UPDATE {qualified}
            SET checksum = ?, success = COALESCE(?, success)
            WHERE script = ?
            """,
            params=[checksum, success_value, script_name],
        )
        return True

    def create_history_table(self, schema: str, table_name: str) -> str:
        """Return SQL for the DuckDB migration history table.

        ``installed_rank`` auto-populates from a DuckDB sequence (DuckDB has
        no ``SERIAL``); the sequence is created by
        :meth:`create_migration_history_table_if_not_exists`.
        """
        seq = self.get_schema_qualified_name(schema, self._history_sequence_name(table_name))
        return f"""
            CREATE TABLE IF NOT EXISTS {self.get_schema_qualified_name(schema, table_name)} (
                installed_rank INTEGER PRIMARY KEY DEFAULT nextval('{seq}'),
                version VARCHAR,
                description VARCHAR NOT NULL,
                type VARCHAR NOT NULL,
                script VARCHAR NOT NULL,
                checksum VARCHAR,
                installed_by VARCHAR NOT NULL,
                installed_on TIMESTAMP DEFAULT now(),
                execution_time INTEGER NOT NULL,
                success BOOLEAN NOT NULL
            )
        """


__all__ = ["DuckDBProvider"]
