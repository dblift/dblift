"""Transaction health checks belong to the provider before each SQL send."""

from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import TransactionAbortedError
from dblift.core.logger import NullLog
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.db.provider_interfaces import TransactionalProvider


class _PreBeginConnection:
    def __init__(self) -> None:
        self.probes: list[str] = []

    def getAutoCommit(self) -> bool:
        return True

    def probe(self, sql: str) -> None:
        self.probes.append(sql)


class _HealthOwningProvider(TransactionalProvider):
    canonical_dialect_key = "sqlite"

    def __init__(self) -> None:
        self.events: list[str] = []
        self.begun = False
        self.prebegin_reads = 0
        self.postbegin_reads = 0
        self._connection = _PreBeginConnection()
        self.health_error: Exception | None = None

    @property
    def connection(self) -> _PreBeginConnection:
        # Pre-begin cleanup and session-output setup are outside this contract.
        if not self.begun:
            self.prebegin_reads += 1
        else:
            self.postbegin_reads += 1
        return self._connection

    def begin_transaction(self) -> None:
        self.events.append("begin")
        self.begun = True

    def commit_transaction(self) -> None:
        self.events.append("commit")
        self.begun = False

    def rollback_transaction(self) -> None:
        self.events.append("rollback")
        self.begun = False

    def check_transaction_state(self) -> None:
        self._connection.probe("SELECT 1")
        self.events.append("health")
        if self.health_error is not None:
            raise self.health_error

    def execute_statement(self, sql: str, schema=None, params=None) -> int:
        self.events.append(f"execute:{sql}")
        return 1

    def execute_query(self, sql: str, params=None):
        self.events.append(f"query:{sql}")
        return []

    def supports_transactional_ddl(self) -> bool:
        return True


@pytest.mark.unit
def test_provider_health_hook_precedes_each_statement() -> None:
    provider = _HealthOwningProvider()
    analyzer = StatementReader("sqlite", analysis_mode="execution")
    statements = ["CREATE TABLE t(id INT)", "INSERT INTO t VALUES (1)"]
    engine = ExecutionEngine(provider, analyzer, NullLog())
    migration = Migration(
        script_name="V1__health.sql",
        content="CREATE TABLE t(id INT); INSERT INTO t VALUES (1);",
        version="1",
        type=MigrationType.SQL,
        checksum=1,
    )

    assert engine._prepare_sql_statements(migration) == statements
    provider.check_transaction_state()
    assert provider.events == ["health"]
    assert provider._connection.probes == ["SELECT 1"]
    provider.events.clear()
    provider._connection.probes.clear()

    result = MigrateResult()
    engine.execute_migration(migration, result)

    assert provider.prebegin_reads > 0
    assert result.error_message is None
    assert provider.events == [
        "begin",
        "health",
        "execute:CREATE TABLE t(id INT)",
        "health",
        "execute:INSERT INTO t VALUES (1)",
        "commit",
    ]
    assert provider._connection.probes == ["SELECT 1", "SELECT 1"]
    assert provider.postbegin_reads <= 1


@pytest.mark.unit
def test_typed_health_failure_rolls_back_before_failure_history() -> None:
    provider = _HealthOwningProvider()
    cause = RuntimeError("current transaction is aborted")
    provider.health_error = TransactionAbortedError("transaction is aborted")
    provider.health_error.__cause__ = cause
    analyzer = StatementReader("sqlite", analysis_mode="execution")
    history = MagicMock()
    history.record_migration.side_effect = lambda *args, **kwargs: provider.events.append("history")
    engine = ExecutionEngine(provider, analyzer, NullLog(), history_manager=history)
    migration = Migration(
        script_name="V1__abort.sql",
        content="INSERT INTO t VALUES (1);",
        version="1",
        type=MigrationType.SQL,
        checksum=1,
    )

    result = MigrateResult()
    engine.execute_migration(migration, result)

    assert "Transaction is aborted before executing statement 1: transaction is aborted" in (
        result.error_message or ""
    )
    assert provider.events == ["begin", "health", "rollback", "begin", "history", "commit"]
    history.record_migration.assert_called_once()
    assert history.record_migration.call_args.kwargs["success"] is False
    assert result.failed_history_persisted is True


@pytest.mark.unit
def test_health_hook_precedes_query_send() -> None:
    provider = _HealthOwningProvider()
    analyzer = StatementReader("sqlite", analysis_mode="execution")
    engine = ExecutionEngine(
        provider,
        analyzer,
        NullLog(),
        sql_execution_service=SqlExecutionService(provider, analyzer),
    )
    migration = Migration(
        script_name="V1__query.sql",
        content="SELECT 1;",
        version="1",
        type=MigrationType.SQL,
        checksum=1,
    )

    result = MigrateResult()
    engine.execute_migration(migration, result)

    assert result.error_message is None
    assert provider.events == ["begin", "health", "query:SELECT 1", "commit"]
    assert provider._connection.probes == ["SELECT 1"]
