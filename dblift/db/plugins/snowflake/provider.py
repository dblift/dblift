"""Snowflake native provider backed by SQLAlchemy Core."""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set, Tuple

from sqlalchemy.engine import Connection

from dblift.config import DbliftConfig
from dblift.core.constants import DEFAULT_HISTORY_TABLE
from dblift.core.constants import MIGRATION_LOCK_TABLE as _MIGRATION_LOCK_TABLE
from dblift.core.logger import Log
from dblift.core.migration.clean_summary import CleanExecutionSummary
from dblift.db.plugins.base_history_manager import UNDO_HISTORY_TYPE, installed_on_to_bind
from dblift.db.plugins.sql_lease_store import (
    OWNER_COLUMN,
    OWNER_COLUMN_TYPE,
    SqlAlchemyLeaseSession,
    SqlLeaseDialect,
    SqlLeaseLockingProvider,
)
from dblift.db.provider_interfaces import DroppableObject


def _quote_identifier(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def _caller_identifier(name: str) -> str:
    """Return the identifier a caller-supplied name refers to, as Snowflake reads it.

    A name that is entirely one quoted identifier (``"flyway_schema_history"``,
    inner quotes doubled) keeps the text inside the quotes; anything else is
    unquoted, so it is upper-cased (``app`` is ``APP``). Names read from the
    catalog never go through this: they are already the exact stored spelling.
    """
    if len(name) >= 2 and name[0] == '"' and name[-1] == '"':
        inner = name[1:-1]
        if '"' not in inner.replace('""', ""):
            return inner.replace('""', '"')
    return name.upper()


def _routine_argument_types(name: str, arguments: str) -> str:
    """Return the parenthesised DROP signature from a SHOW ``arguments`` value.

    ``arguments`` reads ``NAME(NUMBER, DEFAULT VARCHAR) RETURN NUMBER``. The
    routine name is removed first (it may itself contain spaces, parentheses
    or the word RETURN), then the argument list is read up to its matching
    parenthesis. DROP takes bare types, so a ``DEFAULT`` marker is removed.
    """
    start = len(name)
    if not arguments.startswith(name) or arguments[start : start + 1] != "(":
        raise RuntimeError(f"Cannot read the argument types of {name!r}: {arguments!r}")
    depth = 0
    parts: List[str] = []
    current = ""
    for char in arguments[start:]:
        if char == "(":
            depth += 1
            if depth == 1:
                continue
        elif char == ")":
            depth -= 1
            if depth == 0:
                break
        elif char == "," and depth == 1:
            parts.append(current)
            current = ""
            continue
        current += char
    else:
        raise RuntimeError(f"Cannot read the argument types of {name!r}: {arguments!r}")
    parts.append(current)
    types = []
    for part in parts:
        text = part.strip()
        if text.upper().startswith("DEFAULT "):
            text = text[len("DEFAULT ") :].strip()
        if text:
            types.append(text)
    return "(" + ", ".join(types) + ")"


#: Objects dropped before dynamic tables, views and tables: ``(type, SHOW, DROP)``.
_CLEAN_EARLY_KINDS = (
    ("pipe", "PIPES", "PIPE"),
    ("task", "TASKS", "TASK"),
    ("alert", "ALERTS", "ALERT"),
    ("stream", "STREAMS", "STREAM"),
)

#: Tags and policies go after the tables and views they are attached to.
_CLEAN_GOVERNANCE_KINDS = (
    ("tag", "TAGS", "TAG"),
    ("masking_policy", "MASKING POLICIES", "MASKING POLICY"),
    ("row_access_policy", "ROW ACCESS POLICIES", "ROW ACCESS POLICY"),
    ("password_policy", "PASSWORD POLICIES", "PASSWORD POLICY"),
    ("session_policy", "SESSION POLICIES", "SESSION POLICY"),
)

_CLEAN_STORAGE_KINDS = (
    ("stage", "STAGES", "STAGE"),
    ("file_format", "FILE FORMATS", "FILE FORMAT"),
)

#: Functions may reference secrets and network rules, so these go last.
_CLEAN_LAST_KINDS = (
    ("secret", "SECRETS", "SECRET"),
    ("network_rule", "NETWORK RULES", "NETWORK RULE"),
)


#: Kinds that also appear in ``SHOW OBJECTS`` under a table or view kind.
_TABLE_LIKE_KINDS = frozenset(
    {
        "table",
        "view",
        "dynamic_table",
        "materialized_view",
        "external_table",
        "event_table",
        "stream",
    }
)


def _row_value(row: Dict[str, Any], key: str) -> Any:
    """Read a result column whichever case the driver reports it in."""
    for name, value in row.items():
        if str(name).lower() == key:
            return value
    return None


def _seconds_before(clock: str, seconds: str) -> str:
    return f"DATEADD(second, -{seconds}, {clock})"


def _is_lock_timeout_error(error: BaseException) -> bool:
    message = " ".join(
        str(value or "").lower()
        for value in (
            getattr(error, "msg", None),
            getattr(error, "raw_msg", None),
            str(error),
        )
    )
    markers = (
        "lock timeout",
        "lock wait timeout",
        "waiting for this lock",
        "waited too long for a lock",
    )
    return any(marker in message for marker in markers)


class SnowflakeProvider(SqlLeaseLockingProvider):
    """Snowflake provider using the Snowflake SQLAlchemy dialect."""

    canonical_dialect_key = "snowflake"
    MIGRATION_LOCK_TABLE = _MIGRATION_LOCK_TABLE.upper()

    #: Schema this session was last ``USE SCHEMA``'d into. Lets
    #: :meth:`set_current_schema` skip re-issuing ``USE SCHEMA`` on every
    #: statement of a migration, so a ``USE SCHEMA`` the migration itself
    #: runs is not immediately overwritten. Cleared by
    #: :meth:`reset_schema_cache` — called by ``ExecutionEngine`` at the
    #: start of every migration/callback, before either one starts a
    #: transaction — so each one still starts from the configured schema.
    #: Class-level default so tests constructing via ``object.__new__``
    #: still see ``None``.
    _schema_applied_for: Optional[str] = None

    #: History tables whose rank identity was already checked (qualified
    #: names). Class-level default so tests constructing via
    #: ``object.__new__`` still see ``None``.
    _history_rank_checked: Optional[Set[str]] = None

    #: ``(schema, drop statements)`` of the last :meth:`list_droppable_objects`.
    #: Nothing is armed by listing alone (a dry run lists and never drops).
    _clean_listing: Optional[Tuple[str, Set[str]]] = None

    #: ``(schema, drops still to run)`` once :meth:`drop_object` has started
    #: executing a listing; the residual check runs when the last one is done.
    _clean_run: Optional[Tuple[str, Set[str]]] = None

    def __init__(
        self,
        config: DbliftConfig,
        log: Optional[Log] = None,
    ) -> None:
        super().__init__(config, log)
        self._schema_applied_for = None

    def reset_schema_cache(self) -> None:
        """Forget the schema this session was last ``USE SCHEMA``'d into.

        ``ExecutionEngine`` calls this at the start of every migration and
        callback — the unit boundary — so each one still starts from the
        configured schema.
        """
        self._schema_applied_for = None

    def create_connection(self) -> Connection:
        """Reject session settings that change identifier or TIMESTAMP alias meaning."""
        connection = super().create_connection()
        active_transaction = connection.in_transaction()
        try:
            settings = {}
            for name in ("QUOTED_IDENTIFIERS_IGNORE_CASE", "TIMESTAMP_TYPE_MAPPING"):
                rows = (
                    connection.exec_driver_sql(f"SHOW PARAMETERS LIKE '{name}' IN SESSION")
                    .mappings()
                    .all()
                )
                settings[name] = str(rows[0]["value"]).upper() if len(rows) == 1 else None
        finally:
            if not active_transaction and connection.in_transaction():
                connection.rollback()
        if settings["QUOTED_IDENTIFIERS_IGNORE_CASE"] != "FALSE":
            raise RuntimeError("Snowflake QUOTED_IDENTIFIERS_IGNORE_CASE must be FALSE for DBLift")
        if settings["TIMESTAMP_TYPE_MAPPING"] != "TIMESTAMP_NTZ":
            raise RuntimeError("Snowflake TIMESTAMP_TYPE_MAPPING must be TIMESTAMP_NTZ for DBLift")
        return connection

    def execute_statement(
        self,
        sql: str,
        schema: Optional[str] = None,
        params: Optional[List[Any]] = None,
    ) -> int:
        """Execute a SQL statement, optionally preparing the schema first."""
        session_change = re.search(
            r"\bALTER\s+SESSION\s+SET\b[\s\S]*\b"
            r"(QUOTED_IDENTIFIERS_IGNORE_CASE|TIMESTAMP_TYPE_MAPPING)\s*=",
            sql,
            flags=re.IGNORECASE,
        )
        if session_change:
            raise RuntimeError(
                f"Snowflake {session_change.group(1).upper()} "
                "cannot change during a DBLift migration"
            )
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
        schema_name = _quote_identifier(_caller_identifier(schema))
        self.execute_statement(f"CREATE SCHEMA IF NOT EXISTS {schema_name}")

    def table_exists(self, schema: str, table_name: str) -> bool:
        """Return whether a table exists in the given schema."""
        rows = self.execute_query(
            """
            SELECT 1 AS present
            FROM INFORMATION_SCHEMA.TABLES
            WHERE TABLE_SCHEMA = ?
              AND TABLE_NAME = ?
            """,
            [_caller_identifier(schema), _caller_identifier(table_name)],
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
        """Set the current Snowflake schema for this session.

        A no-op once this session already has *schema* selected, so a
        ``USE SCHEMA`` the migration itself runs later is not immediately
        reset back — see ``_schema_applied_for``. Unverified: there is no
        local Snowflake engine to confirm this against.
        """
        schema = _caller_identifier(schema)
        if self._schema_applied_for == schema:
            return
        super().execute_statement(f"USE SCHEMA {_quote_identifier(schema)}")
        self._schema_applied_for = schema

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a quoted schema-qualified object name.

        Both names are caller-supplied: unquoted ones are upper-cased, a name
        wrapped in double quotes keeps the text inside the quotes.
        """
        return self._literal_qualified_name(schema, _caller_identifier(object_name))

    @staticmethod
    def _literal_qualified_name(schema: str, object_name: str) -> str:
        """Qualify *object_name* exactly as given, for names read from the catalog.

        *schema* is still the caller's and is resolved; *object_name* is not.
        """
        return f"{_quote_identifier(_caller_identifier(schema))}.{_quote_identifier(object_name)}"

    def clean_schema(self, schema: str) -> CleanExecutionSummary:
        """Drop the schema's Snowflake objects, in dependency order."""
        summary = self.get_clean_preview(schema)
        for stmt in summary.statements:
            self.execute_statement(stmt)
        if summary.statements:
            self._warn_about_clean_survivors(schema)
        return summary

    def get_clean_preview(self, schema: str) -> CleanExecutionSummary:
        """Return Snowflake objects that clean would drop.

        Objects are listed in the order they can be dropped: pipes, tasks,
        alerts and streams first (they read from tables and stages), then
        dynamic tables, materialized views, views, tables (external and event
        tables included) and sequences, then tags and policies (attached to
        those tables), then functions, procedures, stages and file formats,
        and finally secrets and network rules (functions may reference them).

        A schema that does not exist has nothing to clean. Views, tables and
        sequences must be listable; any other kind that cannot be listed is
        skipped with a warning.
        """
        return self._build_clean_preview(schema, warn=True)[0]

    def _schema_exists(self, schema: str) -> bool:
        rows = self.execute_query(
            "SELECT 1 AS present FROM INFORMATION_SCHEMA.SCHEMATA WHERE SCHEMA_NAME = ?",
            [_caller_identifier(schema)],
        )
        return bool(rows)

    def _build_clean_preview(
        self, schema: str, warn: bool
    ) -> Tuple[CleanExecutionSummary, List[str]]:
        """Return the clean preview and the kinds that could not be listed."""
        summary = CleanExecutionSummary()
        unlisted: List[str] = []
        if not self._schema_exists(schema):
            return summary, unlisted
        scope = self._show_scope(schema)

        def names(show_kind: str) -> List[str]:
            rows = self._show_rows(show_kind, scope, unlisted, warn)
            found = (_row_value(row, "name") for row in rows)
            return [str(name) for name in found if name]

        for object_type, show_kind, drop_kind in _CLEAN_EARLY_KINDS:
            self._record_named_drops(summary, schema, object_type, drop_kind, names(show_kind))

        # These also appear in the table and view catalogs, but only their own
        # DROP statement removes them.
        dynamic_tables = names("DYNAMIC TABLES")
        materialized_views = names("MATERIALIZED VIEWS")
        event_tables = names("EVENT TABLES")
        external_tables = names("EXTERNAL TABLES")
        self._record_named_drops(summary, schema, "dynamic_table", "DYNAMIC TABLE", dynamic_tables)
        self._record_named_drops(
            summary, schema, "materialized_view", "MATERIALIZED VIEW", materialized_views
        )

        for view_name in self._object_names(_SNOWFLAKE_VIEWS_QUERY, schema):
            if view_name in materialized_views:
                continue
            qualified = self._literal_qualified_name(schema, view_name)
            summary.record_drop(
                f"DROP VIEW IF EXISTS {qualified}",
                object_type="view",
                name=view_name,
                schema=schema,
            )

        separate_kinds = set(dynamic_tables) | set(event_tables) | set(external_tables)
        for table_name in self._object_names(_SNOWFLAKE_TABLES_QUERY, schema):
            if table_name in separate_kinds:
                continue
            qualified = self._literal_qualified_name(schema, table_name)
            summary.record_drop(
                f"DROP TABLE IF EXISTS {qualified} CASCADE",
                object_type="table",
                name=table_name,
                schema=schema,
            )
        self._record_named_drops(
            summary, schema, "external_table", "EXTERNAL TABLE", external_tables
        )
        self._record_named_drops(summary, schema, "event_table", "EVENT TABLE", event_tables)

        for sequence_name in self._object_names(_SNOWFLAKE_SEQUENCES_QUERY, schema):
            qualified = self._literal_qualified_name(schema, sequence_name)
            summary.record_drop(
                f"DROP SEQUENCE IF EXISTS {qualified}",
                object_type="sequence",
                name=sequence_name,
                schema=schema,
            )

        for object_type, show_kind, drop_kind in _CLEAN_GOVERNANCE_KINDS:
            self._record_named_drops(summary, schema, object_type, drop_kind, names(show_kind))

        for object_type, show_kind in (
            ("function", "USER FUNCTIONS"),
            ("procedure", "USER PROCEDURES"),
        ):
            for row in self._show_rows(show_kind, scope, unlisted, warn):
                name = _row_value(row, "name")
                if not name:
                    continue
                arguments = str(_row_value(row, "arguments") or "")
                signature = _routine_argument_types(str(name), arguments)
                qualified = self._literal_qualified_name(schema, str(name))
                summary.record_drop(
                    f"DROP {object_type.upper()} IF EXISTS {qualified}{signature}",
                    object_type=object_type,
                    name=f"{name}{signature}",
                    schema=schema,
                )

        for object_type, show_kind, drop_kind in _CLEAN_STORAGE_KINDS + _CLEAN_LAST_KINDS:
            self._record_named_drops(summary, schema, object_type, drop_kind, names(show_kind))

        return summary, unlisted

    def _show_scope(self, schema: str) -> str:
        """Return the ``<database>.<schema>`` scope SHOW commands list objects in."""
        rows = self.execute_query("SELECT CURRENT_DATABASE() AS db")
        database = _row_value(rows[0], "db") if rows else None
        quoted_schema = _quote_identifier(_caller_identifier(schema))
        return f"{_quote_identifier(str(database))}.{quoted_schema}" if database else quoted_schema

    def _show_rows(
        self, show_kind: str, scope: str, unlisted: List[str], warn: bool
    ) -> List[Dict[str, Any]]:
        """List one optional kind; a SHOW that fails skips the kind with a warning."""
        try:
            return self.execute_query(f"SHOW {show_kind} IN SCHEMA {scope}")
        except Exception as exc:
            kind = show_kind.lower()
            unlisted.append(kind)
            if warn:
                self.log.warning(
                    f"Snowflake clean could not list {kind}; "
                    f"objects of this kind were not cleaned: {exc}"
                )
            return []

    def _record_named_drops(
        self,
        summary: CleanExecutionSummary,
        schema: str,
        object_type: str,
        drop_kind: str,
        names: List[str],
    ) -> None:
        for name in names:
            qualified = self._literal_qualified_name(schema, name)
            summary.record_drop(
                f"DROP {drop_kind} IF EXISTS {qualified}",
                object_type=object_type,
                name=name,
                schema=schema,
            )

    def _clean_residue(self, schema: str) -> Tuple[List[Tuple[str, str]], List[str], List[str]]:
        """Return ``(survivors, temporary tables, unlisted kinds)`` for the schema.

        Survivors are ``(kind, name)`` pairs. Session temporary tables are
        listed by ``SHOW OBJECTS`` but clean never drops them, so they are
        returned separately.
        """
        summary, unlisted = self._build_clean_preview(schema, warn=False)
        survivors = [(obj.object_type, obj.name) for obj in summary.objects]
        listed = {name for kind, name in survivors if kind in _TABLE_LIKE_KINDS}
        temporary: List[str] = []
        for row in self.execute_query(f"SHOW OBJECTS IN SCHEMA {self._show_scope(schema)}"):
            name = _row_value(row, "name")
            if not name:
                continue
            raw_kind = str(_row_value(row, "kind") or "object")
            flag = str(_row_value(row, "is_temporary") or "").upper()
            if "TEMPORARY" in raw_kind.upper() or flag in {"Y", "YES", "TRUE"}:
                temporary.append(str(name))
                continue
            kind = raw_kind.lower().replace(" ", "_")
            if str(name) in listed or (kind, str(name)) in survivors:
                continue
            survivors.append((kind, str(name)))
        return survivors, temporary, unlisted

    def _warn_about_clean_survivors(self, schema: str) -> None:
        """Say so when objects remain after clean instead of implying an empty schema."""
        try:
            survivors, temporary, unlisted = self._clean_residue(schema)
        except Exception as exc:
            self.log.debug(f"Could not check the schema for objects left after clean: {exc}")
            return
        quoted = _quote_identifier(_caller_identifier(schema))
        if temporary:
            self.log.info(
                f"Session temporary tables in schema {quoted} are not managed by clean: "
                f"{', '.join(temporary)}."
            )
        parts = []
        if survivors:
            listing = ", ".join(f"{kind} {name}" for kind, name in survivors)
            parts.append(f"{len(survivors)} object(s) remain: {listing}")
        if unlisted:
            parts.append(
                f"kinds that could not be listed and were not cleaned: {', '.join(unlisted)}"
            )
        if parts:
            self.log.warning(f"Schema {quoted} after clean: " + "; ".join(parts) + ".")

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        """Return Snowflake clean candidates in preview order."""
        summary = self.get_clean_preview(schema)
        objects = [
            DroppableObject(
                name=obj.name,
                object_type=obj.object_type,
                drop_sql=drop_sql,
            )
            for obj, drop_sql in zip(summary.objects, summary.statements)
        ]
        self._clean_run = None
        self._clean_listing = (schema, {obj.drop_sql for obj in objects}) if objects else None
        return objects

    def drop_object(self, obj: DroppableObject) -> None:
        """Drop one object; after the last one of a listing, check for survivors.

        The first drop that belongs to the last listing starts the clean, so a
        dry run (listing without drops) and a drop unrelated to a listing never
        trigger the check.
        """
        run = self._clean_run
        if run is None and self._clean_listing and obj.drop_sql in self._clean_listing[1]:
            schema, drops = self._clean_listing
            run = self._clean_run = (schema, set(drops))
            self._clean_listing = None
        try:
            super().drop_object(obj)
        finally:
            if run is not None:
                run[1].discard(obj.drop_sql)
                if not run[1]:
                    self._clean_run = None
                    self._warn_about_clean_survivors(run[0])

    def _object_names(self, query: str, schema: str) -> List[str]:
        rows = self.execute_query(query, [_caller_identifier(schema)])
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
                locked_at TIMESTAMP_NTZ DEFAULT CURRENT_TIMESTAMP(),
                {OWNER_COLUMN} {OWNER_COLUMN_TYPE}
            )
        """

    def acquire_migration_lock_sql(self, schema: str) -> str:
        """Return the DML statement earlier dblift versions held the lock row with.

        Such a version keeps this statement's row lock in an open transaction
        for the whole migration; the lease waits for it (see
        :meth:`acquire_migration_lock`).
        """
        qualified = self.get_schema_qualified_name(
            schema,
            self.MIGRATION_LOCK_TABLE,
        )
        return (
            f"UPDATE {qualified} "
            "SET locked_at = CURRENT_TIMESTAMP() WHERE lock_name = 'migration'"
        )

    def _lock_table_setup_statements(self, schema: str) -> List[str]:
        """Return the statements that create and seed the migration lock table."""
        qualified = self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE)
        # Snowflake accepts UNIQUE/PRIMARY KEY syntax on standard tables but
        # does not enforce it, so seed the singleton lock row with one MERGE.
        seed = f"""
            MERGE INTO {qualified} target
            USING (
                SELECT
                    'migration' AS lock_name,
                    CURRENT_TIMESTAMP() AS locked_at
            ) source
            ON target.lock_name = source.lock_name
            WHEN NOT MATCHED THEN
                INSERT (lock_name, locked_at)
                VALUES (source.lock_name, source.locked_at)
            """
        return [
            f"CREATE SCHEMA IF NOT EXISTS {_quote_identifier(_caller_identifier(schema))}",
            self.create_migration_lock_table_sql(schema),
            # A table created before the lease lacks the owner column.
            f"ALTER TABLE {qualified} ADD COLUMN IF NOT EXISTS {OWNER_COLUMN} {OWNER_COLUMN_TYPE}",
            seed,
        ]

    def create_migration_lock_table_if_not_exists(self, schema: str) -> None:
        """Create and seed the Snowflake migration lock table."""
        for statement in self._lock_table_setup_statements(schema):
            self.execute_statement(statement)

    def acquire_migration_lock(
        self,
        schema: str,
        wait_timeout_seconds: int = 60,
    ) -> bool:
        """Acquire the migration lock as a committed lease on the seeded lock row.

        The lease runs on its own session with ``LOCK_TIMEOUT`` set, so a
        wait behind an earlier dblift version holding the row lock in an
        open transaction stays bounded. The lock table is created and seeded
        on that session too: the seeding MERGE also waits behind such a
        holder, and on any other session it would wait for the 12 hour
        default instead of the requested timeout.
        """
        if self._migration_lease is not None:
            return True

        connection = self.engine.connect()
        prior_timeout: Optional[str] = None
        try:
            timeout = max(0, int(wait_timeout_seconds))
            prior_timeout = self._session_lock_timeout(connection)
            connection.exec_driver_sql(f"ALTER SESSION SET LOCK_TIMEOUT = {timeout}")
            connection.commit()
            for statement in self._lock_table_setup_statements(schema):
                connection.exec_driver_sql(statement)
            connection.commit()
        except Exception as exc:
            try:
                connection.rollback()
            except Exception as rollback_error:
                self.log.debug(f"Rollback of the lock session failed: {rollback_error}")
            self._close_lock_connection(connection, prior_timeout)
            if _is_lock_timeout_error(exc):
                return False
            raise

        def close_session(lock_connection: Connection) -> None:
            self._close_lock_connection(lock_connection, prior_timeout)

        session = SqlAlchemyLeaseSession(connection, on_close=close_session)
        return self._acquire_migration_lease(schema, session, wait_timeout_seconds)

    def _migration_lease_dialect(self, schema: str) -> SqlLeaseDialect:
        """Describe the seeded Snowflake lock row (``SYSDATE()`` is UTC)."""
        return SqlLeaseDialect(
            table=self.get_schema_qualified_name(schema, self.MIGRATION_LOCK_TABLE),
            lock_name="migration",
            now_utc="SYSDATE()",
            seconds_before=_seconds_before,
            is_busy=_is_lock_timeout_error,
            seeded_row=True,
        )

    @staticmethod
    def _session_lock_timeout(connection: Connection) -> Optional[str]:
        """Return the session's current ``LOCK_TIMEOUT`` value, if it reports one."""
        rows = (
            connection.exec_driver_sql("SHOW PARAMETERS LIKE 'LOCK_TIMEOUT' IN SESSION")
            .mappings()
            .all()
        )
        return str(rows[0]["value"]) if len(rows) == 1 else None

    def _close_lock_connection(self, connection: Connection, prior_timeout: Optional[str]) -> None:
        """Put the session's ``LOCK_TIMEOUT`` back, then close the lock connection.

        The connection returns to the engine's pool, so a timeout left on it
        would apply to whatever statement borrows it next; when the restore
        fails the connection is invalidated instead of being returned.
        ``prior_timeout`` ``None`` means unknown, so the parameter is unset.
        """
        try:
            if prior_timeout is None:
                connection.exec_driver_sql("ALTER SESSION UNSET LOCK_TIMEOUT")
            else:
                connection.exec_driver_sql(f"ALTER SESSION SET LOCK_TIMEOUT = {int(prior_timeout)}")
        except Exception as exc:
            self.log.debug(f"Could not restore session LOCK_TIMEOUT: {exc}")
            # A session still carrying the short timeout must not be reused.
            connection.invalidate()
        finally:
            connection.close()

    def close(self) -> None:
        """Close SQLAlchemy resources and release any held migration lock."""
        self._clean_listing = None
        self._clean_run = None
        super().close()

    def get_applied_migrations(
        self, schema: str, table_name: str = DEFAULT_HISTORY_TABLE
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
        table_name: str = DEFAULT_HISTORY_TABLE,
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

    def _warn_if_rank_identity_unordered(
        self, schema: str, qualified_table: str, table_name: str
    ) -> None:
        """Warn once per history table whose ``installed_rank`` identity is NOORDER.

        Such a table (created without ``ORDER``) hands out unique ranks that
        need not follow the order migrations were applied in, and it cannot be
        converted in place (``ALTER COLUMN ... SET ORDER`` is rejected). Rows
        are left as they are; this only tells the operator. A failing check
        never blocks the insert.
        """
        if self._history_rank_checked is None:
            self._history_rank_checked = set()
        if qualified_table in self._history_rank_checked:
            return
        self._history_rank_checked.add(qualified_table)
        try:
            rows = self.execute_query(
                """
                SELECT identity_ordered
                FROM INFORMATION_SCHEMA.COLUMNS
                WHERE TABLE_SCHEMA = ?
                  AND TABLE_NAME = ?
                  AND COLUMN_NAME = 'INSTALLED_RANK'
                """,
                [_caller_identifier(schema), table_name],
            )
        except Exception as exc:
            self.log.debug(f"Could not check the rank identity of {qualified_table}: {exc}")
            return
        flag = ""
        if rows:
            flag = str(_row_value(rows[0], "identity_ordered") or "")
        if flag.upper() == "NO":
            self.log.warning(
                f"The rank identity of history table {qualified_table} is not ordered "
                "(AUTOINCREMENT without ORDER): its installed_rank values are unique but "
                "may not follow application order. Existing rows are left unchanged. To "
                "check, run: SELECT installed_rank, installed_on, script FROM "
                f"{qualified_table} ORDER BY installed_on, and confirm installed_rank "
                "only increases."
            )

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
        table_name: str = DEFAULT_HISTORY_TABLE,
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
        installed_on = installed_on_to_bind(migration_info.get("installed_on"))
        params = [
            migration_info.get("version"),
            migration_info.get("description", ""),
            migration_info.get("type", "SQL"),
            migration_info.get("script", ""),
            migration_info.get("checksum"),
            migration_info.get("installed_by", "dblift"),
            migration_info.get("execution_time", 0),
            migration_info.get("success", True),
        ]
        columns = (
            "version, description, type, script, checksum, " "installed_by, execution_time, success"
        )
        if installed_on is not None:
            # import-flyway carries the source row's own timestamp; otherwise
            # the column default stamps the row.
            columns += ", installed_on"
            params.append(installed_on)
        placeholders = ", ".join("?" for _ in params)
        self._warn_if_rank_identity_unordered(
            schema, qualified_table, _caller_identifier(normalized_table)
        )
        self.execute_statement(
            f"""
            INSERT INTO {qualified_table} ({columns})
            VALUES ({placeholders})
            """,
            params=params,
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
                "type": UNDO_HISTORY_TYPE,
                "script": undo_script,
                "checksum": 0,
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
                    START 1 INCREMENT 1 ORDER PRIMARY KEY,
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
    WHERE TABLE_SCHEMA = ?
    ORDER BY table_name
"""

_SNOWFLAKE_TABLES_QUERY = """
    SELECT table_name AS object_name
    FROM INFORMATION_SCHEMA.TABLES
    WHERE TABLE_SCHEMA = ?
      AND TABLE_TYPE = 'BASE TABLE'
    ORDER BY table_name
"""

_SNOWFLAKE_SEQUENCES_QUERY = """
    SELECT sequence_name AS object_name
    FROM INFORMATION_SCHEMA.SEQUENCES
    WHERE SEQUENCE_SCHEMA = ?
    ORDER BY sequence_name
"""
