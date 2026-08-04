"""Native provider base backed by SQLAlchemy Core.

Implements the provider public surface used by ExecutionEngine,
history/locking/snapshot managers, and plugins. Returns native Python
types directly.

Dialect-specific operations (schema management, migration history, locking)
are left abstract for per-DB subclasses (e.g. SqliteNativeProvider).
"""

import re
import threading
from typing import Any, Dict, List, Mapping, Optional, Tuple

from sqlalchemy import text
from sqlalchemy.engine import Connection, Engine, Transaction

from config import DbliftConfig
from core.logger import Log
from db.base_provider import NativeProvider
from db.native_connection_manager import NativeConnectionManager


class _SqlAlchemyQueryExecutor:
    """Adapter exposing query-executor methods for native catalog queries."""

    def __init__(self, provider: "SqlAlchemyProvider") -> None:
        self._provider = provider

    def execute_query(
        self, connection: Connection, sql: str, params: Optional[List[Any]] = None
    ) -> List[Dict[str, Any]]:
        """Execute a vendor metadata query on a SQLAlchemy connection."""
        if params is None:
            driver_sql = SqlAlchemyProvider._escape_driver_percent_literals(
                sql, connection.dialect.paramstyle
            )
            result = connection.exec_driver_sql(driver_sql)
        else:
            driver_sql, bound_params = self._provider._driver_bind(
                sql, params, connection.dialect.paramstyle
            )
            result = connection.exec_driver_sql(driver_sql, bound_params)
        return [dict(row) for row in result.mappings()]

    def execute_statement(
        self, connection: Connection, sql: str, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a vendor statement on a SQLAlchemy connection."""
        if params is None:
            driver_sql = SqlAlchemyProvider._escape_driver_percent_literals(
                sql, connection.dialect.paramstyle
            )
            result = connection.exec_driver_sql(driver_sql)
        else:
            driver_sql, bound_params = self._provider._driver_bind(
                sql, params, connection.dialect.paramstyle
            )
            result = connection.exec_driver_sql(driver_sql, bound_params)
        if (
            getattr(self._provider, "_tx", None) is None
            and not getattr(self._provider, "_external_connection", False)
            and hasattr(connection, "commit")
        ):
            connection.commit()
        return result.rowcount if result.rowcount is not None else -1

    def get_quoted_schema_name(self, schema: str) -> str:
        """Return a quoted schema/database identifier for the provider dialect."""
        open_q, close_q, escape = self._identifier_quote_chars()
        clean_schema = schema.strip().replace(close_q, escape)
        return f"{open_q}{clean_schema}{close_q}"

    def get_schema_qualified_name(self, schema: str, object_name: str) -> str:
        """Return a quoted schema-qualified object name for schema operations."""
        if hasattr(self._provider, "get_schema_qualified_name"):
            return str(self._provider.get_schema_qualified_name(schema, object_name))

        open_q, close_q, escape = self._identifier_quote_chars()
        clean_schema = schema.strip().replace(close_q, escape)
        clean_object = object_name.strip().replace(close_q, escape)
        return f"{open_q}{clean_schema}{close_q}.{open_q}{clean_object}{close_q}"

    def _identifier_quote_chars(self) -> Tuple[str, str, str]:
        """Return (open_quote, close_quote, escaped_close) for identifier quoting.

        Sourced from the provider's quirks (``quote_open`` / ``quote_close``)
        so the framework never branches on the dialect name. The escape
        sequence is the close-quote doubled (`` `` ``, ``]]``, ``""``).
        """
        q = self._provider.quirks
        return q.quote_open, q.quote_close, q.quote_close * 2


class SqlAlchemyProvider(NativeProvider):
    """Abstract SQLAlchemy-backed data-access base.

    Owns connection lifecycle (via NativeConnectionManager), statement
    execution, and transaction management.  Dialect-specific schema
    operations, migration history, and locking are left abstract for
    concrete per-DB subclasses.
    """

    def __init__(
        self,
        config: DbliftConfig,
        log: Optional[Log] = None,
        *,
        engine: Optional[Engine] = None,
        owns_engine: bool = True,
    ) -> None:
        """Initialise with a DbliftConfig and an optional logger.

        Args:
            config: Application configuration (must be a DbliftConfig instance).
            log: Optional logger; defaults to NullLog when omitted.
            engine: Optional external SQLAlchemy Engine to inject (for from_sqlalchemy etc.).
            owns_engine: Whether dblift owns lifecycle of the engine (False for injected).
        """
        super().__init__(config, log)
        self._conn_mgr = NativeConnectionManager(
            config, log=self.log, engine=engine, owns_engine=owns_engine
        )
        self._connection: Optional[Connection] = None
        self._tx: Optional[Transaction] = None
        self.query_executor = _SqlAlchemyQueryExecutor(self)
        # A single Connection is cached on this provider (see create_connection)
        # and reused across calls. SQLAlchemy Connections are not safe for
        # concurrent use from multiple threads, so every method that fetches
        # or executes on it must serialize through this lock — otherwise two
        # threads racing on ``self._connection`` can hand each other a
        # connection that is mid-close, or drive the same live connection's
        # cursor/transaction state concurrently (issue #819).
        self._lock = threading.RLock()

    # Guards the one-time creation of a fallback ``_lock`` in ``__getattr__``
    # below. Must be a class attribute created once at class-definition time
    # (never per-instance) so every thread racing on the same stub-constructed
    # instance synchronizes through the same lock before touching
    # ``self.__dict__``; a per-instance lock would itself be subject to the
    # same unsynchronized check-then-act it is meant to fix.
    _lock_creation_lock = threading.Lock()

    def __getattr__(self, name: str) -> Any:
        """Fall back to a fresh lock for instances built without ``__init__``.

        Several tests construct a provider through a stub ``__init__`` that
        never calls ``SqlAlchemyProvider.__init__`` (e.g. binding a provider
        directly to a fake connection to unit-test one method in isolation).
        Those never see the assignment above and must still work rather than
        raise ``AttributeError`` the first time a locked method runs.
        ``__getattr__`` only fires once normal lookup has already failed, so
        this never shadows the ``__init__``-assigned lock on a normally
        constructed provider.

        Creation is guarded by the class-level ``_lock_creation_lock`` so that
        concurrent first-touch access from multiple threads always converges
        on the same ``RLock`` instance rather than each thread building and
        installing its own.
        """
        if name == "_lock":
            with type(self)._lock_creation_lock:
                if "_lock" not in self.__dict__:
                    self.__dict__["_lock"] = threading.RLock()
                return self.__dict__["_lock"]
        raise AttributeError(f"{type(self).__name__!r} object has no attribute {name!r}")

    @classmethod
    def from_engine(
        cls,
        config: DbliftConfig,
        engine: Engine,
        log: Optional[Log] = None,
        *,
        owns_engine: bool = False,
    ) -> "SqlAlchemyProvider":
        """Create provider that re-uses a caller-owned SQLAlchemy Engine.

        Used by DBLiftClient.from_sqlalchemy to hand off an app's existing
        engine without taking ownership or disposing it on close.
        """
        return cls(config, log=log, engine=engine, owns_engine=owns_engine)

    # ------------------------------------------------------------------
    # ConnectionProvider
    # ------------------------------------------------------------------

    def create_connection(self) -> Connection:
        """Open and return a new SQLAlchemy Connection.

        Returns:
            An open sqlalchemy.engine.Connection.
        """
        with self._lock:
            # Prefer any pre-bound open connection (e.g. injected via
            # from_sqlalchemy with connection=) so that the caller's
            # session/transaction is used.
            if self._connection is not None and not self._connection.closed:
                return self._connection
            if (
                self._tx is not None
                and self._connection is not None
                and not self._connection.closed
            ):
                return self._connection
            self._connection = self._conn_mgr.create_connection()
            return self._connection

    @property
    def connection(self) -> Optional[Connection]:
        """Return the active SQLAlchemy Connection, if one is open."""
        return self._connection

    @property
    def engine(self) -> Engine:
        """Return the SQLAlchemy Engine owned by the connection manager."""
        return self._conn_mgr.engine

    def _ensure_connection(self) -> Connection:
        """Return the active connection, creating one if necessary.

        Returns:
            An open sqlalchemy.engine.Connection.
        """
        with self._lock:
            if self._connection is None or self._connection.closed:
                self.create_connection()
            if self._connection is None:
                raise RuntimeError("SQLAlchemy connection could not be created")
            return self._connection

    def close(self) -> None:
        """Close the active connection and dispose of the engine."""
        with self._lock:
            if self._tx is not None:
                self._tx.rollback()
                self._tx = None
            self._conn_mgr.close()
            self._connection = None

    def is_connected(self) -> bool:
        """Return True if an open connection is held.

        Returns:
            True if connected, False otherwise.
        """
        with self._lock:
            return self._connection is not None and not self._connection.closed

    def connect(self) -> None:
        """Connect to the database (convenience alias for create_connection)."""
        self.create_connection()

    # ------------------------------------------------------------------
    # QueryProvider
    # ------------------------------------------------------------------

    @staticmethod
    def _escape_driver_percent_literals(sql: str, paramstyle: str) -> str:
        """Escape literal percent signs for drivers that use percent placeholders."""
        if paramstyle in ("format", "pyformat"):
            return sql.replace("%", "%%")
        return sql

    @staticmethod
    def _bind(sql: str, params: Optional[List[Any]]) -> Tuple[str, Any]:
        """Translate DBLift ``?`` positional params to SQLAlchemy named params.

        dblift's plugin layer emits ``?`` placeholders with a positional list (the
        DBLift execution contract). SQLAlchemy ``text()`` binds named ``:name`` params from a
        dict, so each ``?`` becomes ``:p0``, ``:p1`` ... and the list is zipped into
        the matching dict. A dict (already-named params) is forwarded unchanged.

        Note:
            Every ``?`` in *sql* is treated as a placeholder, including any inside a
            string literal. dblift's generated SQL never embeds a literal ``?`` in a string
            (LIKE patterns are built with concatenation), so this is safe in practice.
            The number of ``?`` must equal ``len(params)``.

        Args:
            sql: SQL text, possibly containing ``?`` placeholders.
            params: Positional list, a pre-built dict, or None.

        Returns:
            A ``(sql, bound)`` pair for ``Connection.execute(text(sql), bound)``.
        """
        if params is None:
            return sql, {}
        if isinstance(params, dict):
            return sql, params
        names = [f"p{index}" for index in range(len(params))]
        bound = dict(zip(names, params))
        name_iter = iter(names)
        named_sql = re.sub(r"\?", lambda _match: f":{next(name_iter)}", sql)
        return named_sql, bound

    @staticmethod
    def _driver_bind(sql: str, params: Optional[List[Any]], paramstyle: str) -> Tuple[str, Any]:
        """Translate DBLift ``?`` params to the connection's DBAPI paramstyle."""
        if params is None:
            return sql, None
        if isinstance(params, dict):
            return sql, params

        values = tuple(params)
        if paramstyle == "qmark":
            return sql, values
        if paramstyle in ("format", "pyformat"):
            escaped_sql = sql.replace("%", "%%")
            return re.sub(r"\?", "%s", escaped_sql), values
        if paramstyle == "numeric":
            numeric_names = iter(str(index) for index in range(1, len(values) + 1))
            return re.sub(r"\?", lambda _match: f":{next(numeric_names)}", sql), values
        if paramstyle == "numeric_dollar":
            # duckdb_engine's dialect reports ``numeric_dollar`` while its DBAPI
            # (duckdb) accepts qmark; exec_driver_sql goes to the raw DBAPI, so
            # ``$1``/``$2`` positional params bind correctly against a tuple.
            dollar_names = iter(f"${index}" for index in range(1, len(values) + 1))
            return re.sub(r"\?", lambda _match: next(dollar_names), sql), values

        names = [f"p{index}" for index in range(len(values))]
        bound = dict(zip(names, values))
        name_iter = iter(names)
        return re.sub(r"\?", lambda _match: f":{next(name_iter)}", sql), bound

    def execute_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute a SQL statement and return the rowcount.

        When no explicit transaction is open the statement is auto-committed
        so that DDL persists immediately (SQLAlchemy 2.0 begins a transaction
        implicitly on the first execute; we commit it here to mimic
        autocommit-per-statement behaviour).

        Args:
            sql: SQL statement to execute.
            schema: Ignored at this level; present for interface compatibility.
            params: Optional positional or named parameters (dict or list).

        Returns:
            Number of rows affected (-1 if the driver does not report it).
        """
        with self._lock:
            conn = self._ensure_connection()
            if params is None:
                driver_sql = self._escape_driver_percent_literals(sql, conn.dialect.paramstyle)
                result = conn.exec_driver_sql(driver_sql)
            else:
                named_sql, bound_params = self._bind(sql, params)
                result = conn.execute(text(named_sql), bound_params)
            if self._tx is None and not getattr(self, "_external_connection", False):
                conn.commit()
            return result.rowcount if result.rowcount is not None else -1

    def execute_query(self, sql: str, params: Optional[List[Any]] = None) -> List[Dict[str, Any]]:
        """Execute a SQL query and return results as a list of dicts.

        Args:
            sql: SQL SELECT statement.
            params: Optional positional or named parameters (dict or list).

        Returns:
            List of dicts mapping column names to native Python values.
        """
        with self._lock:
            conn = self._ensure_connection()
            if params is None:
                driver_sql = self._escape_driver_percent_literals(sql, conn.dialect.paramstyle)
                result = conn.exec_driver_sql(driver_sql)
            else:
                named_sql, bound_params = self._bind(sql, params)
                result = conn.execute(text(named_sql), bound_params)
            rows = [dict(row) for row in result.mappings()]
            if self._tx is None and not getattr(self, "_external_connection", False):
                conn.commit()
            return rows

    # ------------------------------------------------------------------
    # TransactionalProvider
    # ------------------------------------------------------------------

    def begin_transaction(self) -> None:
        """Begin an explicit database transaction."""
        with self._lock:
            conn = self._ensure_connection()
            self._tx = conn.begin()

    def commit_transaction(self) -> None:
        """Commit the current explicit transaction."""
        with self._lock:
            if self._tx is not None:
                self._tx.commit()
                self._tx = None

    def rollback_transaction(self) -> None:
        """Roll back the current explicit transaction."""
        with self._lock:
            if self._tx is not None:
                self._tx.rollback()
                self._tx = None
            elif self._connection is not None and not getattr(self._connection, "closed", False):
                self._connection.rollback()

    def _end_open_transaction(self, conn: Connection) -> None:
        """Discard any open transaction so the connection sits on a clean boundary."""
        if self._tx is not None:
            self._tx.rollback()
            self._tx = None
        if conn.in_transaction():
            conn.rollback()

    def execute_autocommit_statement(
        self, sql: str, schema: Optional[str] = None, params: Optional[List[Any]] = None
    ) -> int:
        """Execute *sql* with the DBAPI connection genuinely autocommitting.

        :meth:`execute_statement` commits *after* the statement, which is too
        late for DDL the server refuses to run inside a transaction block: at
        SQLAlchemy's default isolation level the DBAPI connection has
        ``autocommit=False``, so the driver opens a block for the statement
        itself and PostgreSQL rejects e.g. ``CREATE INDEX CONCURRENTLY`` before
        the commit is ever reached. ``isolation_level="AUTOCOMMIT"`` is the
        mechanism that actually flips the DBAPI connection.

        The switch is scoped to this single statement: everything around it —
        failure records, history writes, liveness probes — runs at the
        session's normal isolation level, and on the *same* connection, so the
        ``search_path`` set by :meth:`set_current_schema` still applies.

        SQLAlchemy refuses to change the isolation level while a transaction is
        in progress, and will not retroactively autocommit one that is already
        open — hence the rollback to a clean boundary on the way in. The level
        is restored on the way out so surrounding statements keep their
        all-or-nothing rollback; leaving the session autocommitting would
        silently disarm it.
        """
        with self._lock:
            conn = self._ensure_connection()
            self._end_open_transaction(conn)
            previous_execution_options = conn.get_execution_options()
            conn.execution_options(isolation_level="AUTOCOMMIT")
            try:
                return self.execute_statement(sql, schema=schema, params=params)
            finally:
                if not conn.closed:
                    self._end_open_transaction(conn)
                    self._restore_isolation_level(conn, previous_execution_options)

    @staticmethod
    def _restore_isolation_level(conn: Connection, previous: Mapping[str, Any]) -> None:
        """Put *conn* back exactly as it stood before the autocommit switch.

        *previous* is the connection's whole execution-option mapping, captured
        before the switch. ``Connection.get_execution_options()`` hands back the
        live ``immutabledict`` and ``execution_options()`` rebinds it rather
        than mutating it, so keeping that reference is a true snapshot.

        Two things have to go back, and only one of them has a public setter:

        * **The DBAPI connection.** A level the caller set on the connection
          itself is in *previous* and is reapplied through
          ``execution_options``. Otherwise the level came from the engine or the
          dialect default, which no accessor reports:
          ``get_isolation_level()`` reads the *server* level and never returns
          ``AUTOCOMMIT``, so replaying it would downgrade a session handed to
          dblift by ``from_sqlalchemy`` on an engine built with
          ``isolation_level="AUTOCOMMIT"`` and leave it transactional for good.
          SQLAlchemy's ``reset_isolation_level`` restores exactly what the
          connection was configured with, ``AUTOCOMMIT`` included.

        * **The recorded execution option.** ``reset_isolation_level`` touches
          the DBAPI connection only — ``get_execution_options()`` keeps
          reporting ``AUTOCOMMIT`` after it runs — and SQLAlchemy offers no
          supported way to unset an option: ``isolation_level=None`` raises, and
          the mapping is immutable so the key cannot be popped. Left behind, the
          option is read back by the *next* call as though the caller had
          configured it, and the restore reapplies ``AUTOCOMMIT`` permanently:
          the second ``CREATE INDEX CONCURRENTLY`` of an ordinary index
          migration would disarm rollback for every migration after it in the
          same run. Rebinding the private attribute to the captured mapping is
          what puts it back; restoring the mapping wholesale rather than
          editing one key also leaves the caller's unrelated options intact.
        """
        previous_level = previous.get("isolation_level")
        if previous_level is not None:
            conn.execution_options(isolation_level=previous_level)
        else:
            dbapi_connection = conn.connection.dbapi_connection
            if dbapi_connection is not None:
                conn.dialect.reset_isolation_level(dbapi_connection)
        conn._execution_options = previous  # type: ignore[assignment]
