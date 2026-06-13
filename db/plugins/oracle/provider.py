"""Oracle native provider backed by SQLAlchemy Core (python-oracledb)."""

import os
import re
import time
from typing import Any, Dict, List, Optional, Union

from config import DbliftConfig
from core.logger import Log
from core.migration.clean_summary import CleanExecutionSummary
from db.object_naming import get_normalized_object_name
from db.sqlalchemy_provider import SqlAlchemyProvider


def _q(name: str) -> str:
    """Return a double-quoted Oracle identifier."""
    return '"' + name.replace('"', '""') + '"'


def _clean_identifier(name: str) -> str:
    """Return a bare identifier for dictionary lookups."""
    return name.replace('"', "").strip()


def _oracle_name(name: str) -> str:
    """Return DBLift's Oracle-normalized object name."""
    return get_normalized_object_name(name, "oracle")


def _schema_object(schema: str, obj: str) -> str:
    """Return a quoted schema-qualified Oracle name."""
    return f"{_q(_clean_identifier(schema))}.{_q(_clean_identifier(obj))}"


def _row_value(row: Dict[str, Any], *names: str, default: Any = None) -> Any:
    """Read a value from a SQLAlchemy row mapping with Oracle case tolerance."""
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


def _is_already_exists_error(error: Exception) -> bool:
    msg = str(error).lower()
    return (
        "ora-00955" in msg
        or "already exists" in msg
        or "name is already used" in msg
        or "existe déjà" in msg
        or "existe ja" in msg
        or "existe já" in msg
    )


class OracleProvider(SqlAlchemyProvider):
    """Oracle provider implementation using native SQLAlchemy/python-oracledb."""

    canonical_dialect_key = "oracle"
    provider_transport = "native"
    LOCK_X_MODE = 6
    MIGRATION_LOCK_TABLE = "DBLIFT_MIGRATION_LOCK"

    def __init__(self, config: DbliftConfig, log: Optional[Log] = None) -> None:
        """Initialize the native Oracle provider."""
        super().__init__(config, log)
        self._lock_handles: Dict[str, Optional[Any]] = {}

    @staticmethod
    def get_lock_name(schema: str) -> str:
        """Return the Oracle application-lock name for a schema."""
        prefix = "DBLIFT_MIG_LOCK_"
        max_schema_len = 30 - len(prefix)
        return f"{prefix}{_clean_identifier(schema).upper()[:max_schema_len]}"

    @classmethod
    def get_lock_key(cls, schema: str) -> str:
        """Return the in-memory key used for lock handles."""
        return cls.get_lock_name(schema)

    def _ensure_schema_ready(self, schema: Optional[str]) -> None:
        """Ensure Oracle schema/user exists when possible and set it current."""
        if not schema:
            return
        clean_schema = _clean_identifier(schema)
        if clean_schema.upper() in ("SYS", "SYSTEM"):
            return
        try:
            self.create_schema_if_not_exists(clean_schema)
        except Exception as e:
            self.log.debug(f"Oracle: could not create schema {schema} (non-fatal): {e}")
        try:
            self.set_current_schema(clean_schema)
        except Exception as e:
            self.log.warning(f"Oracle: could not set current schema to {schema}: {e}")

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute SQL, preserving PL/SQL block semicolons and stripping plain SQL ones."""
        self._ensure_schema_ready(schema)
        stmt = sql.strip()
        if not stmt:
            return 0
        stmt_upper = stmt.upper()
        is_plsql_block = (
            re.match(
                r"^CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:NON)?EDITIONABLE\s+)?"
                r"(?:PACKAGE(?:\s+BODY)?|PROCEDURE|FUNCTION|TRIGGER|TYPE(?:\s+BODY)?)\b",
                stmt_upper,
            )
            or stmt_upper.startswith("DECLARE")
            or stmt_upper.startswith("BEGIN")
        )
        if not is_plsql_block and stmt.endswith(";"):
            stmt = stmt[:-1].rstrip()
        return super().execute_statement(stmt, schema=schema, params=params)

    def execute_query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Execute Oracle query SQL after stripping plain trailing semicolons."""
        stmt = sql.strip()
        if stmt.endswith(";"):
            stmt = stmt[:-1].rstrip()
        return super().execute_query(stmt, params=params)

    def create_schema_if_not_exists(self, schema: str) -> None:
        """Create an Oracle schema/user if it does not already exist."""
        clean_schema = _clean_identifier(schema)
        rows = self.execute_query(
            "SELECT COUNT(*) AS user_count FROM ALL_USERS WHERE username = ?",
            [clean_schema],
        )
        count = int(_row_value(rows[0], "user_count", default=0)) if rows else 0
        quoted_schema = _q(clean_schema)
        if count == 0:
            temp_password = os.urandom(16).hex()
            create_user_statements = [
                f"""
                CREATE USER {quoted_schema}
                IDENTIFIED BY "{temp_password}"
                DEFAULT TABLESPACE USERS
                TEMPORARY TABLESPACE TEMP
                QUOTA UNLIMITED ON USERS
                """,
                f"""
                CREATE USER {quoted_schema}
                IDENTIFIED BY "{temp_password}"
                DEFAULT TABLESPACE USERS
                TEMPORARY TABLESPACE TEMP
                """,
            ]
            for create_user_sql in create_user_statements:
                try:
                    self.execute_statement(create_user_sql)
                    break
                except Exception as e:
                    msg = str(e).lower()
                    if "ora-01920" in msg or "ora-01921" in msg or "already exists" in msg:
                        break
                    self.log.debug(f"Could not create Oracle schema/user {schema}: {e}")
            else:
                self.log.warning(
                    f"Cannot create Oracle schema/user {schema}; " "continuing if it already exists"
                )

        configured_user = getattr(getattr(self.config, "database", None), "username", None)
        if (
            configured_user
            and _clean_identifier(str(configured_user)).upper() == clean_schema.upper()
        ):
            return

        grant_statements = [
            f"GRANT CONNECT, RESOURCE, CREATE TABLE, CREATE VIEW, "
            f"CREATE MATERIALIZED VIEW, CREATE DATABASE LINK TO {quoted_schema}",
            f"GRANT CONNECT, CREATE ANY TABLE, CREATE ANY VIEW, CREATE ANY PROCEDURE, "
            f"CREATE SEQUENCE, CREATE MATERIALIZED VIEW, CREATE DATABASE LINK, "
            f"UNLIMITED TABLESPACE TO {quoted_schema}",
            f"GRANT CREATE ANY TABLE, CREATE ANY VIEW, CREATE ANY PROCEDURE, "
            f"CREATE SEQUENCE, CREATE MATERIALIZED VIEW, CREATE DATABASE LINK, "
            f"UNLIMITED TABLESPACE TO {quoted_schema}",
            f"GRANT UNLIMITED TABLESPACE TO {quoted_schema}",
        ]
        for grant_sql in grant_statements:
            try:
                self.execute_statement(grant_sql)
                return
            except Exception as e:
                self.log.debug(f"Could not grant Oracle privileges for {schema}: {e}")
        self.log.warning(
            f"Cannot grant Oracle privileges to schema/user {schema}; "
            "continuing if privileges are already sufficient"
        )

    def set_current_schema(self, schema: str) -> None:
        """Set Oracle CURRENT_SCHEMA for the session."""
        self.execute_statement(
            f"ALTER SESSION SET CURRENT_SCHEMA = {_q(_clean_identifier(schema))}"
        )

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Return whether a table exists in the given Oracle schema."""
        rows = self.execute_query(
            """
            SELECT COUNT(*) AS cnt
            FROM ALL_TABLES
            WHERE OWNER = ? AND TABLE_NAME = ?
            """,
            [_clean_identifier(schema), _oracle_name(table_name)],
        )
        return bool(rows and int(_row_value(rows[0], "cnt", default=0)) > 0)

    def get_actual_object_name(
        self, schema: str, object_name: str, object_type: str = "TABLE"
    ) -> Optional[str]:
        """Return the actual Oracle dictionary object name, if present."""
        rows = self.execute_query(
            """
            SELECT OBJECT_NAME
            FROM ALL_OBJECTS
            WHERE OWNER = ? AND UPPER(OBJECT_NAME) = UPPER(?) AND OBJECT_TYPE = ?
            FETCH FIRST 1 ROWS ONLY
            """,
            [_clean_identifier(schema), _clean_identifier(object_name), object_type.upper()],
        )
        if not rows:
            return None
        value = _row_value(rows[0], "object_name")
        return str(value) if value is not None else None

    def is_system_generated_sequence(self, schema: str, sequence_name: str) -> bool:
        """Return True for Oracle identity-column generated sequences."""
        rows = self.execute_query(
            """
            SELECT COUNT(*) AS cnt
            FROM ALL_TAB_IDENTITY_COLS
            WHERE OWNER = ? AND SEQUENCE_NAME = ?
            """,
            [_clean_identifier(schema), _clean_identifier(sequence_name)],
        )
        return bool(rows and int(_row_value(rows[0], "cnt", default=0)) > 0)

    def get_database_version(self) -> str:
        """Return Oracle database version information."""
        rows = self.execute_query("SELECT BANNER AS banner FROM V$VERSION WHERE ROWNUM = 1")
        if rows:
            return str(_row_value(rows[0], "banner", default="Unknown Oracle Version"))
        return "Unknown Oracle Version"

    def supports_transactional_ddl(self) -> bool:
        """Oracle DDL causes implicit commits."""
        return False

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a quoted Oracle schema-qualified name."""
        return _schema_object(schema, object_name)

    def get_columns_query(self, schema: str, table: str) -> tuple[str, List[str]]:
        """Return an Oracle catalog query for table columns."""
        return (
            """
            SELECT COLUMN_NAME AS column_name, DATA_TYPE AS data_type
            FROM ALL_TAB_COLUMNS
            WHERE OWNER = ? AND TABLE_NAME = ?
            ORDER BY COLUMN_ID
            """,
            [_clean_identifier(schema), _oracle_name(table)],
        )

    def get_add_column_sql(self, schema: str, table: str, column: str, type_def: str) -> str:
        """Return Oracle DDL to add a column."""
        return f"ALTER TABLE {_schema_object(schema, table)} ADD ({_q(column)} {type_def})"

    def get_parameter_placeholders(self, count: int) -> str:
        """Return Oracle parameter placeholders."""
        return ", ".join(["?" for _ in range(count)])

    def get_tables(self, schema: str) -> List[str]:
        """Return table names in an Oracle schema."""
        rows = self.execute_query(
            """
            SELECT TABLE_NAME AS table_name
            FROM ALL_TABLES
            WHERE OWNER = ? AND TABLE_NAME NOT LIKE 'BIN$%'
            ORDER BY TABLE_NAME
            """,
            [_clean_identifier(schema)],
        )
        return [str(_row_value(row, "table_name")) for row in rows]

    def get_schemas(self) -> List[str]:
        """Return available Oracle usernames/schemas."""
        rows = self.execute_query("SELECT USERNAME AS username FROM ALL_USERS ORDER BY USERNAME")
        return [str(_row_value(row, "username")) for row in rows]

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create the fallback Oracle migration lock table if missing."""
        self.create_schema_if_not_exists(schema)
        table = self.MIGRATION_LOCK_TABLE
        if self.table_exists(schema, table):
            return
        try:
            self.execute_statement(f"""
                CREATE TABLE {_schema_object(schema, table)} (
                    LOCK_NAME VARCHAR2(128) NOT NULL PRIMARY KEY,
                    ACQUIRED_AT TIMESTAMP DEFAULT CURRENT_TIMESTAMP NOT NULL,
                    ACQUIRED_BY VARCHAR2(256) DEFAULT USER NOT NULL,
                    SESSION_ID NUMBER DEFAULT SYS_CONTEXT('USERENV','SID') NOT NULL,
                    PROCESS_ID VARCHAR2(64),
                    LOCK_MODE NUMBER DEFAULT {self.LOCK_X_MODE} NOT NULL
                )
                """)
        except Exception as e:
            if _is_already_exists_error(e):
                self.log.debug(f"Migration lock table already exists in schema: {schema}")
                return
            raise

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Acquire an Oracle migration lock using DBMS_LOCK with table fallback."""
        lock_name = self.get_lock_name(schema)
        lock_key = self.get_lock_key(schema)
        try:
            rows = self.execute_query(
                "SELECT DBMS_UTILITY.GET_HASH_VALUE(?, 0, 1073741823) AS lock_hash FROM DUAL",
                [lock_name],
            )
            lock_handle = _row_value(rows[0], "lock_hash") if rows else hash(lock_name) & 0x7FFFFFFF
            start_time = time.time()
            while time.time() - start_time < wait_timeout_seconds:
                result = self.execute_query(
                    "SELECT DBMS_LOCK.REQUEST(?, ?, ?) AS result FROM DUAL",
                    [lock_handle, self.LOCK_X_MODE, 5],
                )
                result_code = int(_row_value(result[0], "result", default=-1)) if result else -1
                if result_code in (0, 4):
                    self._lock_handles[lock_key] = lock_handle
                    return True
                if result_code == 1:
                    time.sleep(1)
                    continue
                break
            else:
                self.log.warning(
                    f"Failed to acquire migration lock for schema {schema} "
                    f"within {wait_timeout_seconds} seconds"
                )
                return False
        except Exception as e:
            self.log.debug(f"Oracle DBMS_LOCK unavailable; falling back to table lock: {e}")

        return self._acquire_table_lock(schema, lock_name, lock_key, wait_timeout_seconds)

    def _acquire_table_lock(
        self, schema: str, lock_name: str, lock_key: str, wait_timeout_seconds: int
    ) -> bool:
        """Acquire the fallback table-based Oracle migration lock."""
        self.create_migration_lock_table_if_not_exists(schema)
        start_time = time.time()
        process_id = str(os.getpid())
        while time.time() - start_time < wait_timeout_seconds:
            try:
                self.execute_statement(
                    f"""
                    INSERT INTO {_schema_object(schema, self.MIGRATION_LOCK_TABLE)}
                    (LOCK_NAME, ACQUIRED_AT, ACQUIRED_BY, SESSION_ID, PROCESS_ID, LOCK_MODE)
                    VALUES (?, CURRENT_TIMESTAMP, USER, SYS_CONTEXT('USERENV','SID'), ?, ?)
                    """,
                    params=[lock_name, process_id, self.LOCK_X_MODE],
                )
                self._lock_handles[lock_key] = None
                return True
            except Exception as e:
                msg = str(e).lower()
                if "unique" in msg or "ora-00001" in msg or "integrity" in msg:
                    time.sleep(1)
                    continue
                self.log.warning(f"Table-based Oracle lock insert failed: {e}")
                return False
        return False

    def release_migration_lock(self, schema: str) -> bool:
        """Release DBMS_LOCK or fallback table lock for a schema."""
        lock_name = self.get_lock_name(schema)
        lock_key = self.get_lock_key(schema)
        lock_handle = self._lock_handles.get(lock_key)
        released = False

        if lock_handle is not None:
            try:
                rows = self.execute_query(
                    "SELECT DBMS_LOCK.RELEASE(?) AS result FROM DUAL", [lock_handle]
                )
                released = bool(rows and int(_row_value(rows[0], "result", default=-1)) == 0)
            except Exception as e:
                self.log.debug(f"Could not release Oracle DBMS_LOCK: {e}")

        try:
            if self.table_exists(schema, self.MIGRATION_LOCK_TABLE):
                affected = self.execute_statement(
                    f"DELETE FROM {_schema_object(schema, self.MIGRATION_LOCK_TABLE)} "
                    "WHERE LOCK_NAME = ?",
                    params=[lock_name],
                )
                released = released or affected > 0
        except Exception as e:
            self.log.debug(f"Could not release Oracle table lock: {e}")

        self._lock_handles.pop(lock_key, None)
        return released

    def create_history_table(self, schema: str, table_name: str = "dblift_schema_history") -> str:
        """Return the DDL for the Oracle migration history table."""
        table = _oracle_name(table_name)
        return f"""
            CREATE TABLE {_schema_object(schema, table)} (
                INSTALLED_RANK NUMBER GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
                VERSION VARCHAR2(50),
                DESCRIPTION VARCHAR2(200) NOT NULL,
                TYPE VARCHAR2(20) NOT NULL,
                SCRIPT VARCHAR2(1000) NOT NULL,
                CHECKSUM NUMBER,
                INSTALLED_BY VARCHAR2(100) NOT NULL,
                INSTALLED_ON TIMESTAMP DEFAULT SYSTIMESTAMP NOT NULL,
                EXECUTION_TIME NUMBER NOT NULL,
                SUCCESS NUMBER(1) NOT NULL
            )
        """

    def create_migration_history_table_if_not_exists(
        self,
        schema: str,
        create_schema: bool = False,
        table_name: str = "dblift_schema_history",
    ) -> None:
        """Create the Oracle migration history table if missing."""
        if create_schema:
            self.create_schema_if_not_exists(schema)
        table = _oracle_name(table_name)
        if self.table_exists(schema, table):
            if create_schema:
                self._check_baseline_safety(schema, table)
            return
        self.create_schema_if_not_exists(schema)
        self.execute_statement(self.create_history_table(schema, table))

    def _check_baseline_safety(self, schema: str, table_name: str) -> None:
        """Refuse baseline when the history table already contains migrations."""
        rows = self.execute_query(
            f"SELECT COUNT(1) AS count FROM {_schema_object(schema, table_name)}"
        )
        count = int(_row_value(rows[0], "count", default=0)) if rows else 0
        if count > 0:
            raise RuntimeError(
                f"Schema {schema} already contains a migration history table "
                f"{table_name} with {count} migration(s). "
                "Baseline cannot be applied to a schema with existing migrations."
            )

    def create_snapshot_table_if_not_exists(
        self, schema: str, table_name: str = "dblift_schema_snapshots"
    ) -> None:
        """Create the Oracle schema snapshot table if missing."""
        self.create_schema_if_not_exists(schema)
        table = _oracle_name(table_name)
        if self.table_exists(schema, table):
            return
        self.execute_statement(f"""
            CREATE TABLE {_schema_object(schema, table)} (
                SNAPSHOT_ID VARCHAR2(255) PRIMARY KEY,
                CAPTURED_AT TIMESTAMP DEFAULT SYSTIMESTAMP,
                CHECKSUM VARCHAR2(128),
                MODEL_DATA CLOB NOT NULL
            )
            """)

    def record_migration(
        self,
        schema: str,
        migration_info: Dict[str, Any],
        table_name: Optional[str] = None,
    ) -> None:
        """Insert a migration row into Oracle history."""
        raw_table = table_name or "dblift_schema_history"
        table = _oracle_name(raw_table)
        self.create_migration_history_table_if_not_exists(schema, table_name=raw_table)
        success_value = 1 if migration_info.get("success", True) else 0
        self.execute_statement(
            f"""
            INSERT INTO {_schema_object(schema, table)} (
                VERSION, DESCRIPTION, TYPE, SCRIPT,
                CHECKSUM, INSTALLED_BY, INSTALLED_ON, EXECUTION_TIME, SUCCESS
            ) VALUES (?, ?, ?, ?, ?, ?, SYSDATE, ?, ?)
            """,
            params=[
                migration_info.get("version"),
                migration_info.get("description", ""),
                migration_info.get("type", "SQL"),
                migration_info.get("script", ""),
                migration_info.get("checksum"),
                migration_info.get("installed_by", "dblift"),
                migration_info.get("execution_time", 0),
                success_value,
            ],
        )

    def get_applied_migrations(
        self, schema: str, table_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """Return applied Oracle migration rows with normalized keys."""
        raw_table = table_name or "dblift_schema_history"
        table = _oracle_name(raw_table)
        if not self.table_exists(schema, table):
            return []
        rows = self.execute_query(f"""
            SELECT SCRIPT, INSTALLED_RANK, VERSION, DESCRIPTION,
                   TYPE, CHECKSUM, INSTALLED_BY, INSTALLED_ON,
                   EXECUTION_TIME, SUCCESS
            FROM {_schema_object(schema, table)}
            ORDER BY INSTALLED_RANK
            """)
        normalized: List[Dict[str, Any]] = []
        for row in rows:
            item = {str(key).lower(): value for key, value in row.items()}
            if item.get("success") is not None:
                item["success"] = bool(int(item["success"]))
            item["status"] = "SUCCESS" if item.get("success") else "FAILED"
            normalized.append(item)
        return normalized

    def record_undo(
        self,
        schema: str,
        version: str,
        table_name: Optional[str] = None,
        script_name: Optional[str] = None,
    ) -> bool:
        """Record a successful Oracle undo operation."""
        self.record_migration(
            schema,
            {
                "version": version,
                "description": f"Undo migration {version}",
                "type": "UNDO_SQL",
                "script": script_name or f"UNDO_{version}.sql",
                "checksum": 0,
                "installed_by": os.environ.get("USER", os.environ.get("USERNAME", "dblift")),
                "execution_time": 0,
                "success": True,
            },
            table_name,
        )
        return True

    def repair_migration_history(
        self,
        schema: str,
        script_name: str,
        checksum: Union[int, str],
        table_name: str = "dblift_schema_history",
        success_value: Optional[Any] = None,
    ) -> bool:
        """Update an Oracle migration history row."""
        table = _oracle_name(table_name)
        if not self.table_exists(schema, table):
            return False
        if success_value is None:
            affected = self.execute_statement(
                f"UPDATE {_schema_object(schema, table)} SET CHECKSUM = ?, SUCCESS = 0 "
                "WHERE SCRIPT = ?",
                params=[checksum, script_name],
            )
        else:
            affected = self.execute_statement(
                f"UPDATE {_schema_object(schema, table)} SET CHECKSUM = ?, SUCCESS = ? "
                "WHERE SCRIPT = ?",
                params=[checksum, 1 if success_value else 0, script_name],
            )
        return affected > 0

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop user objects from the Oracle schema."""
        return self._clean_schema(schema, execute=True)

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return what Oracle clean would drop without executing drops."""
        return self._clean_schema(schema, execute=False)

    def _clean_schema(self, schema: str, execute: bool) -> CleanExecutionSummary:
        """Shared Oracle clean implementation for execution and preview."""
        summary = CleanExecutionSummary()
        clean_schema = _clean_identifier(schema)

        try:
            rows = self.execute_query("""
                SELECT DB_LINK AS object_name
                FROM ALL_DB_LINKS
                WHERE OWNER = SYS_CONTEXT('USERENV', 'SESSION_USER')
                ORDER BY DB_LINK
                """)
        except Exception as e:
            self.log.debug(f"Could not query Oracle database links: {e}")
            rows = []
        for row in rows:
            name = _row_value(row, "object_name", "db_link")
            if not name:
                continue
            stmt = f"DROP DATABASE LINK {_q(_clean_identifier(str(name)))}"
            if execute:
                try:
                    self.execute_statement(stmt)
                except Exception as e:
                    summary.add_error(f"Failed to drop database_link {name}: {e}")
                    continue
            summary.record_drop(stmt, "database_link", str(name), schema=schema)

        object_queries = [
            (
                "view",
                "DROP VIEW",
                "SELECT VIEW_NAME AS object_name FROM ALL_VIEWS WHERE OWNER = ? ORDER BY VIEW_NAME",
                "",
            ),
            (
                "materialized_view",
                "DROP MATERIALIZED VIEW",
                "SELECT MVIEW_NAME AS object_name FROM ALL_MVIEWS WHERE OWNER = ? ORDER BY MVIEW_NAME",
                "",
            ),
            (
                "table",
                "DROP TABLE",
                "SELECT TABLE_NAME AS object_name FROM ALL_TABLES "
                "WHERE OWNER = ? AND TABLE_NAME NOT LIKE 'BIN$%' ORDER BY TABLE_NAME",
                " CASCADE CONSTRAINTS",
            ),
            (
                "sequence",
                "DROP SEQUENCE",
                "SELECT SEQUENCE_NAME AS object_name FROM ALL_SEQUENCES "
                "WHERE SEQUENCE_OWNER = ? ORDER BY SEQUENCE_NAME",
                "",
            ),
        ]

        for object_type, drop_prefix, query, suffix in object_queries:
            try:
                rows = self.execute_query(query, [clean_schema])
            except Exception as e:
                self.log.debug(f"Could not query Oracle {object_type}s: {e}")
                continue
            for row in rows:
                name = _row_value(row, "object_name")
                if not name:
                    continue
                if object_type == "sequence" and self.is_system_generated_sequence(
                    schema, str(name)
                ):
                    continue
                stmt = f"{drop_prefix} {_schema_object(schema, str(name))}{suffix}"
                if execute:
                    try:
                        self.execute_statement(stmt)
                    except Exception as e:
                        summary.add_error(f"Failed to drop {object_type} {name}: {e}")
                        continue
                summary.record_drop(stmt, object_type, str(name), schema=schema)

        try:
            rows = self.execute_query(
                """
                SELECT OBJECT_NAME AS object_name, OBJECT_TYPE AS object_type
                FROM ALL_OBJECTS
                WHERE OWNER = ?
                  AND OBJECT_TYPE IN ('PROCEDURE', 'FUNCTION', 'PACKAGE', 'PACKAGE BODY',
                                      'TYPE', 'TYPE BODY', 'TRIGGER')
                  AND OBJECT_NAME NOT LIKE 'BIN$%'
                ORDER BY DECODE(OBJECT_TYPE, 'PACKAGE BODY', 1, 'TYPE BODY', 1, 2),
                         OBJECT_NAME
                """,
                [clean_schema],
            )
        except Exception as e:
            self.log.debug(f"Could not query Oracle program objects: {e}")
            rows = []

        for row in rows:
            name = _row_value(row, "object_name")
            object_type = str(_row_value(row, "object_type", default="")).upper()
            if not name or not object_type:
                continue
            suffix = " FORCE" if object_type == "TYPE" else ""
            stmt = f"DROP {object_type} {_schema_object(schema, str(name))}{suffix}"
            normalized_type = object_type.lower().replace(" ", "_")
            if execute:
                try:
                    self.execute_statement(stmt)
                except Exception as e:
                    summary.add_error(f"Failed to drop {normalized_type} {name}: {e}")
                    continue
            summary.record_drop(stmt, normalized_type, str(name), schema=schema)

        try:
            rows = self.execute_query(
                "SELECT SYNONYM_NAME AS object_name FROM ALL_SYNONYMS WHERE OWNER = ? "
                "ORDER BY SYNONYM_NAME",
                [clean_schema],
            )
        except Exception as e:
            self.log.debug(f"Could not query Oracle synonyms: {e}")
            rows = []
        for row in rows:
            name = _row_value(row, "object_name")
            if not name:
                continue
            stmt = f"DROP SYNONYM {_schema_object(schema, str(name))}"
            if execute:
                try:
                    self.execute_statement(stmt)
                except Exception as e:
                    summary.add_error(f"Failed to drop synonym {name}: {e}")
                    continue
            summary.record_drop(stmt, "synonym", str(name), schema=schema)

        return summary
