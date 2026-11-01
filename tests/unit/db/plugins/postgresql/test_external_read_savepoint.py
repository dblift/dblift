"""A failed read on a caller-owned connection must not abort the caller's transaction.

PostgreSQL aborts the whole transaction on any statement error; on a
connection dblift does not own, nothing of dblift's would ever end it. The read
runs under a savepoint so only the read is undone.
"""

from types import SimpleNamespace
from typing import List, Optional

import pytest

from dblift.db.plugins.duckdb.provider import DuckDBProvider
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.plugins.redshift.provider import RedshiftProvider

pytestmark = pytest.mark.unit


class _Result:
    def mappings(self):
        return [{"n": 1}]


class _Savepoint:
    def __init__(self, connection: "_Connection") -> None:
        self._connection = connection
        self.is_active = True

    def _end(self, event: str) -> None:
        self.is_active = False
        self._connection.log.append(event)

    def commit(self) -> None:
        self._end("release")

    def rollback(self) -> None:
        self._connection.aborted = False
        self._end("rollback_to_savepoint")

    def __enter__(self) -> "_Savepoint":
        return self

    def __exit__(self, exc_type, exc, tb) -> None:
        if exc_type is None:
            self.commit()
        elif self.is_active:
            self.rollback()


class _Connection:
    """Models PostgreSQL's abort-the-whole-transaction rule."""

    closed = False

    def __init__(self, failing: Optional[str] = None, autocommit: bool = False) -> None:
        self.failing = failing
        self.connection = SimpleNamespace(dbapi_connection=SimpleNamespace(autocommit=autocommit))
        self.aborted = False
        self.log: List[str] = []

    def begin_nested(self) -> _Savepoint:
        self.log.append("savepoint")
        return _Savepoint(self)

    def in_transaction(self) -> bool:
        return True

    def exec_driver_sql(self, sql, params=None, execution_options=None) -> _Result:
        if self.aborted:
            raise RuntimeError("current transaction is aborted")
        if sql == self.failing:
            self.aborted = True
            raise RuntimeError("permission denied")
        self.log.append(f"run {sql}")
        return _Result()

    def commit(self) -> None:
        self.log.append("commit")

    def rollback(self) -> None:
        self.aborted = False
        self.log.append("rollback")


def _provider(provider_class, connection: _Connection, *, external=True, tx=None):
    class _Bound(provider_class):  # type: ignore[valid-type,misc]
        def __init__(self) -> None:
            self._tx = tx
            self._connection = connection
            self._external_connection = external

        def _ensure_connection(self):
            return connection

    return _Bound()


def test_failed_read_unwinds_to_the_savepoint_and_re_raises_the_cause():
    connection = _Connection(failing="SELECT bad")
    provider = _provider(PostgreSqlProvider, connection)

    with pytest.raises(RuntimeError, match="permission denied"):
        provider.execute_query("SELECT bad")

    assert connection.log == ["savepoint", "rollback_to_savepoint"]


def test_later_read_reports_its_own_outcome_not_an_aborted_transaction():
    connection = _Connection(failing="SELECT bad")
    provider = _provider(PostgreSqlProvider, connection)
    with pytest.raises(RuntimeError):
        provider.execute_query("SELECT bad")

    assert provider.execute_query("SELECT 1") == [{"n": 1}]
    with pytest.raises(RuntimeError, match="permission denied"):
        provider.execute_query("SELECT bad")


def test_successful_read_releases_the_savepoint_and_never_commits():
    connection = _Connection()
    provider = _provider(PostgreSqlProvider, connection)

    assert provider.execute_query("SELECT 1") == [{"n": 1}]

    assert connection.log == ["savepoint", "run SELECT 1", "release"]


@pytest.mark.parametrize(
    "provider_class, external, tx",
    [
        (PostgreSqlProvider, False, None),  # dblift owns the connection
        (PostgreSqlProvider, True, object()),  # inside dblift's own transaction
        (RedshiftProvider, True, None),  # no SAVEPOINT statement
        (DuckDBProvider, True, None),  # no SAVEPOINT statement
    ],
)
def test_no_savepoint_where_it_does_not_apply(provider_class, external, tx):
    connection = _Connection()
    provider = _provider(provider_class, connection, external=external, tx=tx)

    provider.execute_query("SELECT 1")

    assert "savepoint" not in connection.log


def test_no_savepoint_on_an_autocommit_connection():
    """SAVEPOINT is refused outside a transaction block, and nothing there can abort."""
    connection = _Connection(autocommit=True)
    provider = _provider(PostgreSqlProvider, connection)

    assert provider.execute_query("SELECT 1") == [{"n": 1}]

    assert connection.log == ["run SELECT 1"]


@pytest.mark.parametrize("provider_class", [RedshiftProvider, DuckDBProvider])
def test_without_savepoints_a_failed_read_rolls_the_connection_back(provider_class):
    connection = _Connection(failing="SELECT bad")
    provider = _provider(provider_class, connection)

    with pytest.raises(RuntimeError, match="permission denied"):
        provider.execute_query("SELECT bad")

    assert connection.log == ["rollback"]
    assert provider.execute_query("SELECT 1") == [{"n": 1}]


@pytest.mark.parametrize("provider_class", [RedshiftProvider, DuckDBProvider])
def test_without_savepoints_a_successful_read_changes_nothing(provider_class):
    connection = _Connection()
    provider = _provider(provider_class, connection)

    provider.execute_query("SELECT 1")

    assert connection.log == ["run SELECT 1"]


def test_a_failed_read_inside_dblifts_own_transaction_is_left_to_its_rollback():
    connection = _Connection(failing="SELECT bad")
    provider = _provider(RedshiftProvider, connection, tx=object())

    with pytest.raises(RuntimeError):
        provider.execute_query("SELECT bad")

    assert connection.log == []
