"""Per-drop failure isolation for PostgreSQL ``clean``.

PostgreSQL aborts the *entire* transaction when any statement fails, so a
single DROP that could not run — a permission-denied object, a dependency,
an object type the enumeration misclassifies — made every later DROP in
``CleanCommand``'s loop fail with ``InFailedSqlTransaction``. The loop's
``try/except`` caught the Python exception but could not revive the backend
transaction, so the command turned into a total no-op that also left
``dblift_schema_history`` and ``dblift_migration_lock`` behind.

The fake connection below reproduces exactly that backend rule: once a
statement raises, every further statement raises until the transaction is
ended (``COMMIT``/``ROLLBACK``) or unwound to a savepoint. Dialects that do
not roll a whole transaction back on a statement error must not have
savepoint statements emitted against them, so the base provider behaviour is
asserted too.
"""

from typing import List, Optional

import pytest

from dblift.core.migration.commands.clean_command import CleanCommand
from dblift.db.plugins.mysql.provider import MySqlProvider
from dblift.db.plugins.postgresql.provider import PostgreSqlProvider
from dblift.db.plugins.redshift.provider import RedshiftProvider
from dblift.db.provider_interfaces import DroppableObject


class _FakeDialect:
    paramstyle = "pyformat"


class _FakeResult:
    rowcount = 1


class _FakeSavepoint:
    """Stand-in for ``Connection.begin_nested()``'s return value."""

    def __init__(self, connection: "_FakeConnection") -> None:
        self._connection = connection
        self.is_active = True

    def commit(self) -> None:
        """RELEASE SAVEPOINT."""
        if not self.is_active:
            raise AssertionError("released an inactive savepoint")
        self.is_active = False
        self._connection.log.append("release")

    def rollback(self) -> None:
        """ROLLBACK TO SAVEPOINT — clears the aborted state, keeps the transaction."""
        if not self.is_active:
            raise AssertionError("rolled back an inactive savepoint")
        self.is_active = False
        self._connection.aborted = False
        self._connection.log.append("rollback_to_savepoint")


class _FakeConnection:
    """Connection that models PostgreSQL's abort-the-whole-transaction rule."""

    def __init__(self, failing_sql: Optional[List[str]] = None) -> None:
        self.dialect = _FakeDialect()
        self.failing_sql = set(failing_sql or [])
        self.aborted = False
        self.executed: List[str] = []
        self.log: List[str] = []
        self._savepoints: List[_FakeSavepoint] = []

    def begin_nested(self) -> _FakeSavepoint:
        savepoint = _FakeSavepoint(self)
        self._savepoints.append(savepoint)
        self.log.append("savepoint")
        return savepoint

    def exec_driver_sql(self, sql: str, params: Optional[object] = None) -> _FakeResult:
        if self.aborted:
            raise RuntimeError("current transaction is aborted, commands ignored")
        if sql in self.failing_sql:
            self.aborted = True
            raise RuntimeError(f"cannot drop: {sql}")
        self.executed.append(sql)
        return _FakeResult()

    def commit(self) -> None:
        """Ending the transaction deactivates any savepoint taken inside it."""
        self.aborted = False
        for savepoint in self._savepoints:
            savepoint.is_active = False
        self._savepoints.clear()
        self.log.append("commit")


def _bind(provider_class, connection: _FakeConnection):
    """Return a provider of *provider_class* wired to *connection*."""

    class _Bound(provider_class):  # type: ignore[valid-type,misc]
        def __init__(self) -> None:
            self._tx = None
            self._connection = connection

        def _ensure_connection(self):
            return connection

    return _Bound()


def _drop(name: str, object_type: str = "table") -> DroppableObject:
    return DroppableObject(
        name=name,
        object_type=object_type,
        drop_sql=f'DROP {object_type.upper()} IF EXISTS "s"."{name}" CASCADE',
    )


@pytest.mark.unit
class TestPostgreSqlDropObjectIsolation:
    def test_failing_drop_does_not_poison_the_next_drop(self) -> None:
        """The drop after a failure still reaches the backend and succeeds."""
        first, second = _drop("locked"), _drop("dblift_schema_history")
        connection = _FakeConnection(failing_sql=[first.drop_sql])
        provider = _bind(PostgreSqlProvider, connection)

        with pytest.raises(RuntimeError):
            provider.drop_object(first)
        provider.drop_object(second)

        assert connection.executed == [second.drop_sql]

    def test_failure_unwinds_to_the_savepoint_and_re_raises(self) -> None:
        """The original error reaches the caller so clean can still report it."""
        obj = _drop("locked")
        connection = _FakeConnection(failing_sql=[obj.drop_sql])
        provider = _bind(PostgreSqlProvider, connection)

        with pytest.raises(RuntimeError, match="cannot drop"):
            provider.drop_object(obj)

        assert connection.log == ["savepoint", "rollback_to_savepoint"]

    def test_successful_drop_ends_with_a_committed_statement(self) -> None:
        """Auto-commit-per-statement still commits; no stale savepoint is released."""
        obj = _drop("orders")
        connection = _FakeConnection()
        provider = _bind(PostgreSqlProvider, connection)

        provider.drop_object(obj)

        assert connection.executed == [obj.drop_sql]
        assert connection.log == ["savepoint", "commit"]

    def test_savepoint_is_released_when_the_caller_owns_the_transaction(self) -> None:
        """With a caller-owned transaction nothing is committed, so RELEASE runs."""
        obj = _drop("orders")
        connection = _FakeConnection()
        provider = _bind(PostgreSqlProvider, connection)
        provider._external_connection = True

        provider.drop_object(obj)

        assert connection.executed == [obj.drop_sql]
        assert connection.log == ["savepoint", "release"]

    def test_caller_transaction_survives_a_failed_drop(self) -> None:
        """A failure unwinds only to the savepoint — earlier drops are kept."""
        good, bad = _drop("orders"), _drop("locked")
        connection = _FakeConnection(failing_sql=[bad.drop_sql])
        provider = _bind(PostgreSqlProvider, connection)
        provider._external_connection = True

        provider.drop_object(good)
        with pytest.raises(RuntimeError):
            provider.drop_object(bad)
        provider.drop_object(_drop("dblift_migration_lock"))

        assert connection.executed == [
            good.drop_sql,
            'DROP TABLE IF EXISTS "s"."dblift_migration_lock" CASCADE',
        ]
        assert "commit" not in connection.log


@pytest.mark.unit
class TestDialectsWithoutSavepointSupport:
    def test_redshift_emits_no_savepoint(self) -> None:
        """Redshift has no SAVEPOINT statement — it must keep the plain drop."""
        connection = _FakeConnection()
        provider = _bind(RedshiftProvider, connection)

        provider.drop_object(_drop("orders"))

        assert connection.log == ["commit"]

    def test_mysql_emits_no_savepoint(self) -> None:
        """MySQL commits DDL implicitly, so there is no transaction to protect."""
        connection = _FakeConnection()
        provider = _bind(MySqlProvider, connection)

        provider.drop_object(_drop("orders"))

        assert connection.log == ["commit"]


class _CleanProvider(PostgreSqlProvider):
    """PostgreSQL provider whose enumeration is fixed and whose I/O is faked."""

    def __init__(self, connection: _FakeConnection, objects: List[DroppableObject]) -> None:
        self._tx = None
        self._connection = connection
        self._objects = objects

    def _ensure_connection(self):
        return self._connection

    def list_droppable_objects(self, schema: str) -> List[DroppableObject]:
        return list(self._objects)

    def commit_transaction(self) -> None:
        return None


@pytest.mark.unit
class TestCleanCommandWithAFailingDrop:
    def _run(self):
        from unittest.mock import MagicMock

        objects = [
            _drop("moddatetime", "extension"),
            _drop("app_users"),
            _drop("dblift_migration_lock"),
            _drop("dblift_schema_history"),
        ]
        connection = _FakeConnection(failing_sql=[objects[0].drop_sql])
        provider = _CleanProvider(connection, objects)
        config = MagicMock()
        config.database.schema = "s"
        config.clean_disabled = False
        command = CleanCommand(
            config=config,
            log=MagicMock(),
            provider=provider,
            script_manager=MagicMock(),
            history_manager=MagicMock(),
            validator=MagicMock(),
            execution_engine=MagicMock(),
            migration_helpers=MagicMock(),
            state_manager=MagicMock(),
            migration_ui=MagicMock(),
            migration_rules=MagicMock(),
        )
        return command.execute(), connection, objects

    def test_tracking_tables_are_dropped_when_an_earlier_drop_fails(self) -> None:
        _, connection, objects = self._run()

        drops = [sql for sql in connection.executed if sql.startswith("DROP ")]
        assert drops == [obj.drop_sql for obj in objects[1:]]

    def test_clean_still_reports_failure(self) -> None:
        result, _, _ = self._run()

        assert result.success is False
        assert len(result.warnings) == 1

    def test_summary_counts_only_the_drops_that_ran(self) -> None:
        result, _, _ = self._run()

        assert sum(len(names) for names in result.get_objects_by_type().values()) == 3
