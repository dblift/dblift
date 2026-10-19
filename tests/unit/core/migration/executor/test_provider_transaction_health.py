"""Transaction health checks belong to the provider before each SQL send."""

from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import Migration, MigrationType
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
    analyzer = MagicMock()
    analyzer.dialect = "sqlite"
    statements = ["CREATE TABLE t(id INT)", "INSERT INTO t VALUES (1)"]
    analyzer.split_statements.return_value = statements
    analyzer.get_statement_type.side_effect = ["DDL", "DML"]
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
