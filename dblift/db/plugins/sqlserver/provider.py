"""SQL Server native provider backed by SQLAlchemy Core (pymssql)."""

import os
from typing import Any, Dict, List, Optional

from dblift.config import DbliftConfig
from dblift.core.constants import DEFAULT_HISTORY_TABLE
from dblift.core.constants import MIGRATION_LOCK_TABLE as _MIGRATION_LOCK_TABLE
from dblift.core.exceptions import ExecutionError
from dblift.core.logger import Log
from dblift.core.migration.clean_summary import CleanExecutionSummary
from dblift.core.migration.sql.execution_statement import classify_execution_statement
from dblift.db.plugins.base_history_manager import UNDO_HISTORY_TYPE, installed_on_to_bind
from dblift.db.plugins.sqlserver.sqlserver.schema_operations import SqlServerSchemaOperations
from dblift.db.provider_interfaces import DroppableObject
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider


def _q(name: str) -> str:
    """Return a T-SQL bracket-quoted identifier."""
    return "[" + name.replace("]", "]]") + "]"


def _schema_object(schema: str, obj: str) -> str:
    """Return a bracket-quoted schema-qualified name."""
    return f"{_q(schema)}.{_q(obj)}"


class SqlServerProvider(SqlAlchemyProvider):
    """SQL Server provider implementation using native SQLAlchemy/pymssql."""

    canonical_dialect_key = "sqlserver"
    MIGRATION_LOCK_TABLE = _MIGRATION_LOCK_TABLE

    #: The schema this connection's login is believed to actually carry right
    #: now — the baseline :meth:`set_current_schema` compares the catalog's
    #: live ``DEFAULT_SCHEMA`` against to detect a concurrent process (or an
    #: earlier migration's own statement) changing it from under dblift.
    #: Deliberately NOT cleared by :meth:`reset_schema_cache`: it must survive
    #: the migration boundary, or a change made during the previous migration
    #: goes undetected on the very call that would report it. Class-level
    #: default so tests constructing via ``object.__new__`` still see ``None``.
    _current_schema_set: Optional[str] = None

    #: Whether the ``ALTER USER`` write for ``_current_schema_set`` has
    #: already been issued on this connection. Separate from
    #: ``_current_schema_set`` because this one *is* cleared by
    #: :meth:`reset_schema_cache` at every migration boundary, so each new
    #: migration/callback still reissues the write — the detection baseline
    #: above must not move for that same reissue to be noticed as a change.
    #: Class-level default so tests constructing via ``object.__new__`` still
    #: see ``None``.
    _schema_applied_for: Optional[str] = None

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the native SQL Server provider."""
        super().__init__(config, log)
        self._current_schema_set = None
        self._schema_applied_for = None

    def reset_schema_cache(self) -> None:
        """Forget that this connection has already written the current schema.

        ``ExecutionEngine`` calls this at the start of every migration and
        callback — the unit boundary — regardless of whether it runs
        transactionally or via autocommit, so the next migration's own
        ``ALTER USER`` is reissued rather than skipped as a cache hit.
        ``_current_schema_set``, the baseline used to detect a schema change
        made by someone else, is untouched: it must survive this boundary or
        that detection goes blind on the very call that would report it.
        """
        self._schema_applied_for = None

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
        """Execute a SQL statement, creating and selecting the migration schema when requested."""
        if schema:
            self.create_schema_if_not_exists(schema)
            self.set_current_schema(schema)
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
        """Align the connecting user's default schema so unqualified DDL lands here.

        SQL Server has no session-scoped search path; unqualified object
        names resolve against the connecting database user's
        DEFAULT_SCHEMA. ``ALTER USER ... WITH DEFAULT_SCHEMA`` takes effect
        immediately within the current session (no reconnect required), so
        it is the real equivalent of PostgreSQL's ``SET search_path`` /
        MySQL's ``USE``. Without this, unqualified DDL (dblift's own
        documented usage pattern) silently lands in whatever schema the
        login already defaults to instead of ``--db-schema``.

        Unlike every other dialect's mechanism, though, DEFAULT_SCHEMA is
        catalog-level state on the login (``sys.database_principals``) —
        not connection-scoped — so it is visible to and overwritable by any
        other connection authenticating as the same login. ``--db-schema``
        is one fixed value for an entire process run, so after the first
        call every later call (i.e. every subsequent statement) asks for
        the *same* schema again — that steady state is exactly when a
        concurrent process sharing this login is most likely to have
        clobbered it. So on a cache hit (the requested schema already
        written on this connection), the login's current DEFAULT_SCHEMA is
        read and compared against what was set last; a mismatch there means
        another process changed it, since nothing on this connection asked
        for anything different, and that is logged loudly. A cache miss —
        most commonly a migration boundary reapplying the configured schema
        — corrects DEFAULT_SCHEMA silently instead. The check only detects
        interference while re-requesting a schema this connection already
        set: on a cache miss it cannot tell a migration's own
        schema-changing statement from a second connection that happens to
        interfere at the same moment, since dblift did not set either value
        and its record disagrees with the catalog identically either way
        (issue #362). A dedicated SQL Server login per ``--db-schema``
        avoids concurrent interference entirely.

        One login can never do this at all: ``dbo``, whose DEFAULT_SCHEMA
        SQL Server refuses to change. That case raises instead of warning —
        see the guard below.
        """
        try:
            rows = self.execute_query(
                "SELECT USER_NAME() AS db_user, DEFAULT_SCHEMA_NAME AS default_schema "
                "FROM sys.database_principals WHERE name = USER_NAME()"
            )
            current_user = rows[0].get("db_user") if rows else None
            if not current_user:
                raise RuntimeError("could not determine the connecting database user")

            catalog_schema = rows[0].get("default_schema") if rows else None

            # The 'dbo' database user is fixed (principal_id 1) and its
            # DEFAULT_SCHEMA cannot be changed - SQL Server rejects
            # ALTER USER [dbo] WITH DEFAULT_SCHEMA = ... with error 15150.
            # Any sysadmin login (e.g. sa) or a database's owner maps to
            # 'dbo', so this is not a query failure to warn and continue
            # past: continuing would run every unqualified statement of the
            # migration against 'dbo' instead of the configured schema
            # while reporting success. Fail fast instead. SQL Server
            # identifiers are case-insensitive, so 'DBO' is still the dbo
            # schema and must not trip this guard — compare case-folded.
            if (
                current_user == "dbo"
                and catalog_schema is not None
                and schema.lower() != catalog_schema.lower()
            ):
                raise ExecutionError(
                    f"SQL Server login '{current_user}' maps to the fixed 'dbo' "
                    f"database user, whose default schema cannot be changed, so "
                    f"unqualified objects cannot be created in schema '{schema}'. "
                    f"Connect with a login mapped to a non-'dbo' database user, or "
                    f"set the schema to 'dbo'."
                )

            if self._schema_applied_for == schema:
                # Cache hit: nothing on this connection asked for a change
                # since the last write, so the catalog has no legitimate
                # reason to differ from it. A mismatch here is the mid-migration
                # interference case this check exists for.
                if (
                    self._current_schema_set is not None
                    and catalog_schema is not None
                    and catalog_schema != self._current_schema_set
                ):
                    self.log.warning(
                        f"SQL Server login '{current_user}' DEFAULT_SCHEMA is "
                        f"'{catalog_schema}' but dblift set it to "
                        f"'{self._current_schema_set}' earlier on this connection — "
                        f"another process changed it. If this login is shared across "
                        f"concurrent dblift runs with different --db-schema values, "
                        f"unqualified DDL placement is not reliable; use a dedicated "
                        f"login per schema."
                    )
                # Already the value this connection wants — skip the
                # redundant catalog WRITE.
                return

            # Cache miss: about to (re)write, most commonly a migration
            # boundary reapplying the configured schema. A catalog value
            # that differs from the baseline here is the previous
            # migration's own doing, not interference, so no warning.
            super().execute_statement(
                f"ALTER USER {_q(current_user)} WITH DEFAULT_SCHEMA = {_q(schema)}"
            )
            self._current_schema_set = schema
            self._schema_applied_for = schema
        except ExecutionError:
            raise
        except Exception as e:
            self.log.warning(
                f"SQL Server: could not set the connecting user's default schema to "
                f"'{schema}'; unqualified object names may resolve against a "
                f"different schema than --db-schema ({e})"
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
        lock_name = f"{_MIGRATION_LOCK_TABLE}_{schema}"
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
        lock_name = f"{_MIGRATION_LOCK_TABLE}_{schema}"
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
        table_name: str = DEFAULT_HISTORY_TABLE,
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

    def record_migration(
        self,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: str = DEFAULT_HISTORY_TABLE,
    ) -> None:
        """Insert a migration record into the history table."""
        self.create_migration_history_table_if_not_exists(schema, table_name=table_name)
        qualified = _schema_object(schema, table_name)
        success_val = 1 if migration_info.get("success", True) else 0
        installed_on = installed_on_to_bind(migration_info.get("installed_on"))
        installed_on_column = ", installed_on" if installed_on is not None else ""
        installed_on_value = ", ?" if installed_on is not None else ""
        params = [
            migration_info.get("version"),
            migration_info.get("description", ""),
            migration_info.get("type", "SQL"),
            migration_info.get("script", ""),
            migration_info.get("checksum"),
            migration_info.get("installed_by", "dblift"),
            migration_info.get("execution_time", 0),
            success_val,
        ]
        if installed_on is not None:
            params.append(installed_on)
        self.execute_statement(
            f"""
            INSERT INTO {qualified}
                (version, description, type, script, checksum,
                 installed_by, execution_time, success{installed_on_column})
            VALUES (?, ?, ?, ?, ?, ?, ?, ?{installed_on_value})
            """,
            params=params,
        )

    def get_applied_migrations(
        self, schema: str, table_name: str = DEFAULT_HISTORY_TABLE
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
                "type": UNDO_HISTORY_TYPE,
                "script": undo_script,
                "checksum": 0,
                "installed_by": os.environ.get("USER", os.environ.get("USERNAME", "dblift")),
                "execution_time": 0,
                "success": True,
            },
            table_name or DEFAULT_HISTORY_TABLE,
        )
        return True

    def repair_migration_history(
        self,
        schema: str,
        script_name: str,
        checksum: Any,
        table_name: str = DEFAULT_HISTORY_TABLE,
        success_value: Optional[Any] = None,
    ) -> bool:
        """Update checksum and success state for an existing migration row."""
        if not self.table_exists(schema, table_name):
            return False
        qualified = _schema_object(schema, table_name)
        success_bit = None if success_value is None else (1 if success_value else 0)
        result = self.execute_statement(
            f"UPDATE {qualified} SET checksum = ?, success = COALESCE(?, success) "
            "WHERE script = ?",
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

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return SQL Server objects in dependency-safe clean order."""
        connection = self._ensure_connection()
        operations = SqlServerSchemaOperations(self.query_executor, self.log)
        objects: List[DroppableObject] = []
        pending_statements: List[str] = []

        for candidate in operations.enumerate_clean_candidates(connection, schema):
            if not candidate.object_type or not candidate.name:
                pending_statements.append(candidate.sql)
                continue

            drop_sql = candidate.sql
            if pending_statements:
                drop_sql = "; ".join([*pending_statements, candidate.sql])
                pending_statements = []
            objects.append(
                DroppableObject(
                    name=candidate.name,
                    object_type=candidate.object_type,
                    drop_sql=drop_sql,
                )
            )

        return objects

    def drop_object(self, obj: DroppableObject) -> None:
        """Drop one object enumerated by :meth:`list_droppable_objects`.

        Most drops run through the base implementation inside the clean
        operation's ambient transaction. ``DROP FULLTEXT CATALOG`` is a
        documented exception (paired with ``CREATE FULLTEXT CATALOG``, see
        ``SqlserverQuirks.non_transactional_sql_patterns``): SQL Server
        refuses to run it inside a transaction block at all, so it has to go
        through :meth:`execute_autocommit_statement` instead of the plain
        transactional ``execute_statement`` the base ``drop_object`` uses.
        """
        statement = classify_execution_statement(obj.drop_sql, dialect=self.canonical_dialect_key)
        if not statement.can_execute_in_transaction:
            self.execute_autocommit_statement(obj.drop_sql)
            return
        super().drop_object(obj)

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
