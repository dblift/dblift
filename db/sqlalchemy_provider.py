"""Native provider base backed by SQLAlchemy Core.

Implements the provider public surface used by ExecutionEngine,
history/locking/snapshot managers, and plugins. Returns native Python
types directly.

Dialect-specific operations (schema management, migration history, locking)
are left abstract for per-DB subclasses (e.g. SqliteNativeProvider).
"""

import re
from typing import Any, Dict, List, Optional, Tuple

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
        # Prefer any pre-bound open connection (e.g. injected via from_sqlalchemy
        # with connection=) so that the caller's session/transaction is used.
        if self._connection is not None and not self._connection.closed:
            return self._connection
        if self._tx is not None and self._connection is not None and not self._connection.closed:
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
        if self._connection is None or self._connection.closed:
            self.create_connection()
        if self._connection is None:
            raise RuntimeError("SQLAlchemy connection could not be created")
        return self._connection

    def close(self) -> None:
        """Close the active connection and dispose of the engine."""
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
        conn = self._ensure_connection()
        self._tx = conn.begin()

    def commit_transaction(self) -> None:
        """Commit the current explicit transaction."""
        if self._tx is not None:
            self._tx.commit()
            self._tx = None

    def rollback_transaction(self) -> None:
        """Roll back the current explicit transaction."""
        if self._tx is not None:
            self._tx.rollback()
            self._tx = None
        elif self._connection is not None and not getattr(self._connection, "closed", False):
            self._connection.rollback()
