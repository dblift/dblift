"""Migration lock lease kept in the relational lock table.

One :class:`SqlLeaseStore` serves every engine whose migration lock is a
committed row; the engine only describes itself with a
:class:`SqlLeaseDialect` (its server clock, interval arithmetic and the
errors that mean "write-locked right now"). Two table shapes exist:

* **row presence** — the primary key is enforced, so the row exists only
  while the lock is held: acquire inserts it, release deletes it. A dblift
  version without the lease writes the same row, so mixed versions still
  exclude each other.
* **seeded row** — the primary key is not enforced (Snowflake), so a single
  row is seeded once and the lease lives in its owner column: acquire sets
  the owner where none is set, release clears it.

Lease timestamps are written and compared with the database server's own
clock in UTC, never with a client timestamp, so client clock skew cannot
make a live lease look expired. Every statement runs on its own connection
and commits on its own, so the heartbeat can renew the lease while a
migration transaction is open on the main connection.
"""

from __future__ import annotations

import contextlib
import sqlite3
import threading
from dataclasses import dataclass
from typing import Callable, Iterable, List, Mapping, Optional, Protocol, Sequence, Tuple, Union

from sqlalchemy.engine import Connection
from sqlalchemy.pool import SingletonThreadPool, StaticPool

from dblift.db.native_connection_manager import NativeConnectionManager
from dblift.db.plugins import lease_lock
from dblift.db.plugins.lease_lock import (
    UNREFRESHED_TOKEN_PREFIX,
    LeaseBusy,
    LeaseLock,
    LeaseStore,
)
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider

#: Column holding the token of the process that holds the lease. Nullable: a
#: row written by a dblift version without the lease has no owner.
OWNER_COLUMN = "owner_token"

#: Type of the owner column; a token is a 32-character hex string.
OWNER_COLUMN_TYPE = "VARCHAR(64)"

_DUPLICATE_KEY_MARKERS = (
    "duplicate",
    "unique constraint",
    "violates unique",
    "ora-00001",
    "sql0803n",
    "23505",
)

_DUPLICATE_COLUMN_MARKERS = (
    "duplicate column",
    "already exists",
    "ora-01430",
    "sql0612n",
)


def is_duplicate_key_error(error: BaseException) -> bool:
    """Whether *error* is a primary-key violation: the lock row is already there."""
    message = str(error).lower()
    return any(marker in message for marker in _DUPLICATE_KEY_MARKERS)


def seconds_literal(seconds: float) -> str:
    """Render *seconds* as a SQL numeric literal (no bind: interval syntax needs a literal)."""
    value = float(seconds)
    return str(int(value)) if value.is_integer() else f"{value:.3f}"


def interval_before(clock: str, seconds: str) -> str:
    """``clock - INTERVAL 'n seconds'`` (PostgreSQL-style interval literal)."""
    return f"{clock} - INTERVAL '{seconds} seconds'"


class LeaseSession(Protocol):
    """A connection that runs each lease statement in its own transaction."""

    def execute(self, sql: str, params: Sequence[object], returning: bool = False) -> int:
        """Run *sql*, commit, and return the number of rows it touched."""

    def close(self) -> None:
        """Release the connection."""


class SqlAlchemyLeaseSession:
    """Lease statements on one SQLAlchemy connection, each committed on its own.

    ``on_close`` closes the connection; ``None`` leaves it open (the
    provider's own connection, used for a private in-memory database). A
    transaction already open on the connection belongs to the caller and is
    neither committed nor rolled back.
    """

    def __init__(
        self, connection: Connection, on_close: Optional[Callable[[Connection], None]] = None
    ) -> None:
        """Bind the session to *connection*."""
        self._connection = connection
        self._on_close = on_close

    def execute(self, sql: str, params: Sequence[object], returning: bool = False) -> int:
        """Run *sql* with ``?`` parameters, commit, and return its row count.

        With *returning*, a driver that reports no row count (DuckDB) is
        answered by counting the rows of the statement's ``RETURNING`` clause.
        """
        connection = self._connection
        opened_here = not connection.in_transaction()
        driver_sql, bound = SqlAlchemyProvider._driver_bind(
            sql, list(params), connection.dialect.paramstyle
        )
        try:
            result = connection.exec_driver_sql(driver_sql, bound)
            count = result.rowcount
            if returning and (count is None or count < 0):
                count = len(result.fetchall())
            if opened_here:
                connection.commit()
        except Exception:
            if opened_here:
                # The statement's own error is the one to report.
                with contextlib.suppress(Exception):
                    connection.rollback()
            raise
        return int(count) if count is not None else -1

    def close(self) -> None:
        """Close the connection when this session owns it."""
        if self._on_close is not None:
            self._on_close(self._connection)


class Sqlite3LeaseSession:
    """Lease statements on one ``sqlite3`` connection in autocommit mode."""

    def __init__(self, connection: sqlite3.Connection, owns_connection: bool) -> None:
        """Bind the session; close the connection on :meth:`close` when owned."""
        self._connection = connection
        self._owns_connection = owns_connection

    def execute(self, sql: str, params: Sequence[object], returning: bool = False) -> int:
        """Run *sql*, commit unless a caller's transaction is open, return its row count."""
        connection = self._connection
        opened_here = not connection.in_transaction
        try:
            count = connection.execute(sql, list(params)).rowcount
            if opened_here and connection.in_transaction:
                connection.commit()
        except Exception:
            if opened_here and connection.in_transaction:
                with contextlib.suppress(Exception):
                    connection.rollback()
            raise
        return int(count)

    def close(self) -> None:
        """Close the connection when this session owns it."""
        if self._owns_connection:
            self._connection.close()


@dataclass(frozen=True)
class SqlLeaseDialect:
    """What one engine needs to say about its lock table and clock.

    Attributes:
        table: Schema-qualified, quoted lock table.
        lock_name: Value of the lock-name column for this lock.
        now_utc: Server clock in UTC, as a SQL expression.
        seconds_before: ``(clock, seconds) -> SQL`` for "*seconds* before *clock*".
        is_busy: Whether an error means the store is write-locked right now.
        name_column / timestamp_column / owner_column: Column names.
        legacy_now: Clock rows without an owner were written with; ``None``
            when no such rows exist (seeded-row shape).
        seeded_row: Seeded-row shape instead of row presence.
        insert_values: Extra ``(column, SQL value)`` pairs filled on acquire.
        insert_params: Parameters for ``?`` placeholders in ``insert_values``.
        count_with_returning: The driver reports no row count; count the
            rows of a ``RETURNING`` clause instead.
    """

    table: str
    lock_name: str
    now_utc: str
    seconds_before: Callable[[str, str], str]
    is_busy: Callable[[BaseException], bool]
    name_column: str = "lock_name"
    timestamp_column: str = "locked_at"
    owner_column: str = OWNER_COLUMN
    legacy_now: Optional[str] = None
    seeded_row: bool = False
    insert_values: Tuple[Tuple[str, str], ...] = ()
    insert_params: Tuple[object, ...] = ()
    count_with_returning: bool = False


class SqlLeaseStore(LeaseStore):
    """The lease slot in a relational lock table (see the module docstring)."""

    def __init__(self, dialect: SqlLeaseDialect, session: LeaseSession) -> None:
        """Keep the dialect description and the session statements run on."""
        self.dialect = dialect
        self._session = session
        # The heartbeat thread and the caller share one connection.
        self._mutex = threading.Lock()

    def _run(self, sql: str, params: Sequence[object]) -> int:
        returning = self.dialect.count_with_returning and not sql.startswith("INSERT")
        if returning:
            sql = f"{sql} RETURNING 1"
        with self._mutex:
            try:
                return self._session.execute(sql, params, returning=returning)
            except Exception as exc:
                if self.dialect.is_busy(exc):
                    raise LeaseBusy(str(exc)) from exc
                raise

    def _where_owned(self) -> str:
        d = self.dialect
        return f"{d.name_column} = ? AND {d.owner_column} = ?"

    def try_acquire(self, token: str) -> bool:
        """Insert the lock row (row presence) or claim the seeded row."""
        d = self.dialect
        if d.seeded_row:
            claimed = self._run(
                f"UPDATE {d.table} SET {d.owner_column} = ?, {d.timestamp_column} = {d.now_utc} "
                f"WHERE {d.name_column} = ? AND {d.owner_column} IS NULL "
                f"AND (SELECT COUNT(*) FROM {d.table} WHERE {d.name_column} = ?) = 1",
                [token, d.lock_name, d.lock_name],
            )
            return claimed == 1
        columns = [d.name_column, d.timestamp_column, d.owner_column]
        values = ["?", d.now_utc, "?"]
        for column, value in d.insert_values:
            columns.append(column)
            values.append(value)
        try:
            self._run(
                f"INSERT INTO {d.table} ({', '.join(columns)}) VALUES ({', '.join(values)})",
                [d.lock_name, token, *d.insert_params],
            )
        except LeaseBusy:
            raise
        except Exception as exc:
            if is_duplicate_key_error(exc):
                return False
            raise
        return True

    def reclaim_expired(self, expiry_seconds: float) -> bool:
        """Free a lease whose timestamp is older than *expiry_seconds* on the server clock.

        A row that is never refreshed is freed only after the legacy expiry:
        a row without an owner (written by a dblift version without the
        lease, measured on the clock it was written with) and a lease held
        without a heartbeat (``UNREFRESHED_TOKEN_PREFIX``, server UTC clock).
        """
        d = self.dialect
        legacy_age = seconds_literal(lease_lock.LEGACY_LEASE_EXPIRY_SECONDS)
        prefix = f"'{UNREFRESHED_TOKEN_PREFIX}%'"
        unrefreshed = f"{d.owner_column} LIKE {prefix}"
        conditions = [
            f"({d.owner_column} NOT LIKE {prefix} AND {d.timestamp_column} < "
            f"{d.seconds_before(d.now_utc, seconds_literal(expiry_seconds))})",
            f"({unrefreshed} AND {d.timestamp_column} < "
            f"{d.seconds_before(d.now_utc, legacy_age)})",
        ]
        if d.legacy_now is not None:
            conditions.append(
                f"({d.owner_column} IS NULL AND {d.timestamp_column} < "
                f"{d.seconds_before(d.legacy_now, legacy_age)})"
            )
        condition = f"({' OR '.join(conditions)})"
        if d.seeded_row:
            sql = (
                f"UPDATE {d.table} SET {d.owner_column} = NULL "
                f"WHERE {d.name_column} = ? AND {condition}"
            )
        else:
            sql = f"DELETE FROM {d.table} WHERE {d.name_column} = ? AND {condition}"
        return self._run(sql, [d.lock_name]) > 0

    def refresh(self, token: str) -> bool:
        """Move the caller's lease timestamp to the server's current time."""
        d = self.dialect
        refreshed = self._run(
            f"UPDATE {d.table} SET {d.timestamp_column} = {d.now_utc} WHERE {self._where_owned()}",
            [d.lock_name, token],
        )
        return refreshed > 0

    def release(self, token: str) -> bool:
        """Free the caller's lease; another holder's lease is left untouched."""
        d = self.dialect
        if d.seeded_row:
            sql = f"UPDATE {d.table} SET {d.owner_column} = NULL WHERE {self._where_owned()}"
        else:
            sql = f"DELETE FROM {d.table} WHERE {self._where_owned()}"
        return self._run(sql, [d.lock_name, token]) > 0

    def close(self) -> None:
        """Close the session's connection."""
        with self._mutex:
            self._session.close()


def _column_names(rows: Iterable[Mapping[str, object]]) -> List[str]:
    return [
        str(value).lower()
        for row in rows
        for key, value in row.items()
        if str(key).lower() in ("column_name", "name")
    ]


def ensure_owner_column(
    execute_query: Callable[..., Sequence[Mapping[str, object]]],
    execute_statement: Callable[[str], object],
    columns_query: Union[str, Tuple[str, Sequence[object]]],
    add_column_sql: str,
    column: str = OWNER_COLUMN,
) -> None:
    """Add the owner column to a lock table created by an earlier dblift.

    For engines without ``ADD COLUMN IF NOT EXISTS``: the catalog is checked
    first, and losing the race to a concurrent run that added the column in
    between is not an error.
    """
    if isinstance(columns_query, tuple):
        rows = execute_query(columns_query[0], columns_query[1])
    else:
        rows = execute_query(columns_query)
    if column.lower() in _column_names(rows):
        return
    try:
        execute_statement(add_column_sql)
    except Exception as exc:
        message = str(exc).lower()
        if not any(marker in message for marker in _DUPLICATE_COLUMN_MARKERS):
            raise


def _close(connection: Connection) -> None:
    connection.close()


class SqlLeaseLockingProvider(SqlAlchemyProvider):
    """SQLAlchemy provider whose migration lock is a lease in the lock table.

    A subclass describes its lock table with :meth:`_migration_lease_dialect`
    and creates the table (owner column included) in
    ``create_migration_lock_table_if_not_exists``. The lease runs on a
    dedicated connection from the provider's engine; :meth:`close` releases a
    lease still held.
    """

    #: The lease this provider holds, if any. Class-level default so
    #: providers built without ``__init__`` hold none.
    _migration_lease: Optional[LeaseLock] = None

    def _migration_lease_dialect(self, schema: str) -> SqlLeaseDialect:
        """Describe the lock table of *schema* to :class:`SqlLeaseStore`."""
        raise NotImplementedError

    def _migration_lease_is_private(self) -> bool:
        """Whether no other connection can reach this database (in-memory)."""
        return False

    def _migration_lease_on_own_connection(self) -> bool:
        """Whether the lock row must stay on the provider's own connection.

        A private (in-memory) database cannot have contenders on another
        connection. All other databases use a dedicated, committed lease so
        a caller-owned migration transaction cannot prevent its heartbeat.
        """
        return self._migration_lease_is_private()

    def _ensure_migration_lock_table_for_external_connection(self, schema: str) -> None:
        """Prepare the lock table without committing the caller's transaction."""
        if isinstance(self.engine.pool, (StaticPool, SingletonThreadPool)):
            raise RuntimeError(
                "Migration lease requires an independent connection; "
                "the caller's SQLAlchemy pool reuses one DBAPI connection"
            )
        provider = type(self)(self.config, self.log)
        provider._conn_mgr = NativeConnectionManager(
            self.config, self.log, engine=self.engine, owns_engine=False
        )
        try:
            provider.create_migration_lock_table_if_not_exists(schema)
        finally:
            provider.close()

    def _acquire_migration_lease(
        self,
        schema: str,
        session: LeaseSession,
        wait_timeout_seconds: float,
        heartbeat: bool = True,
    ) -> bool:
        """Take the lease in *schema*'s lock table through *session*."""
        store = SqlLeaseStore(self._migration_lease_dialect(schema), session)
        lease = LeaseLock(store, log=self.log, heartbeat=heartbeat)
        if not lease.acquire(wait_timeout_seconds):
            return False
        self._migration_lease = lease
        return True

    def acquire_migration_lock(self, schema: str, wait_timeout_seconds: int = 60) -> bool:
        """Take the migration lock lease, waiting up to *wait_timeout_seconds*.

        A lease left by a process that died is reclaimed once it has not
        been refreshed for one lease window.
        """
        if self._migration_lease is not None:
            return True
        if getattr(self, "_external_connection", False) and not self._migration_lease_is_private():
            self._ensure_migration_lock_table_for_external_connection(schema)
        else:
            self.create_migration_lock_table_if_not_exists(schema)
        if self._migration_lease_on_own_connection():
            session = SqlAlchemyLeaseSession(self._ensure_connection())
            return self._acquire_migration_lease(
                schema, session, wait_timeout_seconds, heartbeat=False
            )
        session = SqlAlchemyLeaseSession(self.engine.connect(), on_close=_close)
        return self._acquire_migration_lease(schema, session, wait_timeout_seconds)

    def _release_migration_lease(self) -> bool:
        lease, self._migration_lease = self._migration_lease, None
        return lease.release() if lease is not None else False

    def release_migration_lock(self, schema: str) -> bool:
        """Release the lease this provider holds; ``True`` when it was removed.

        A lease another process reclaimed is left in place (``False``).
        """
        return self._release_migration_lease()

    def migration_lock_lost(self) -> bool:
        """Whether the held lease was reclaimed or could not be renewed in time."""
        lease = self._migration_lease
        return lease is not None and lease.lost

    def close(self) -> None:
        """Release a migration lock lease still held, then close the connection."""
        try:
            self._release_migration_lease()
        finally:
            super().close()


__all__ = [
    "OWNER_COLUMN",
    "OWNER_COLUMN_TYPE",
    "LeaseSession",
    "SqlAlchemyLeaseSession",
    "Sqlite3LeaseSession",
    "SqlLeaseDialect",
    "SqlLeaseLockingProvider",
    "SqlLeaseStore",
    "ensure_owner_column",
    "interval_before",
    "is_duplicate_key_error",
    "seconds_literal",
]
