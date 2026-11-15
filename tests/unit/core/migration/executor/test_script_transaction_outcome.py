"""The engine settles a transaction its script ended or left open before recording history."""

from typing import Any, List
from unittest.mock import MagicMock

import pytest

from dblift.core.logger import NullLog
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.db.provider_interfaces import TransactionalProvider, TransactionOutcome


class _Provider(TransactionalProvider):
    canonical_dialect_key = "sqlite"

    def __init__(self, outcome: Any = None) -> None:
        self.events: List[str] = []
        self._outcome = outcome
        self.connection = MagicMock()

    def transaction_outcome(self) -> TransactionOutcome:
        if self._outcome is None:
            return super().transaction_outcome()
        return self._outcome

    def begin_transaction(self) -> None:
        self.events.append("begin")

    def commit_transaction(self) -> None:
        self.events.append("commit")

    def rollback_transaction(self) -> None:
        self.events.append("rollback")

    def check_transaction_state(self) -> None:
        return None

    def execute_statement(self, sql: str, schema=None, params=None) -> int:
        self.events.append("execute")
        return 1

    def execute_query(self, sql: str, params=None):
        return []

    def supports_transactional_ddl(self) -> bool:
        return True


class _History:
    def __init__(self, events: List[str], fail: bool = False) -> None:
        self._events = events
        self._fail = fail

    def record_migration(self, migration, success: bool, execution_time: int) -> None:
        if self._fail:
            raise RuntimeError("history down")
        self._events.append(f"history:{success}")


class _Log(NullLog):
    def __init__(self) -> None:
        super().__init__()
        self.warnings: List[str] = []
        self.errors: List[str] = []

    def warning(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.warnings.append(message)

    def error(self, message: str, *args: Any, **kwargs: Any) -> None:
        self.errors.append(message)


def _run(
    outcome: Any = None, fail_history: bool = False, content: str = "INSERT INTO t VALUES (1);"
):
    provider = _Provider(outcome)
    log = _Log()
    engine = ExecutionEngine(
        provider,
        StatementReader("sqlite", analysis_mode="execution"),
        log,
        history_manager=_History(provider.events, fail_history),
    )
    migration = Migration(
        script_name="V1__x.sql",
        content=content,
        version="1",
        type=MigrationType.SQL,
        checksum=1,
    )
    result = MigrateResult()
    return engine, migration, result, provider, log


@pytest.mark.unit
def test_default_outcome_keeps_todays_sequence():
    engine, migration, result, provider, _ = _run()
    engine.execute_migration(migration, result)
    assert provider.events == ["begin", "execute", "history:True", "commit"]
    assert result.error_message is None


@pytest.mark.unit
def test_ended_releases_and_records_history_in_its_own_transaction():
    engine, migration, result, provider, log = _run(TransactionOutcome.ENDED)
    engine.execute_migration(migration, result)
    assert provider.events == ["begin", "execute", "rollback", "begin", "history:True", "commit"]
    assert result.error_message is None
    assert any("ended its transaction itself" in m for m in log.warnings)


@pytest.mark.unit
def test_open_rolls_back_and_records_a_failed_row():
    engine, migration, result, provider, _ = _run(TransactionOutcome.OPEN)
    engine.execute_migration(migration, result)
    assert provider.events == ["begin", "execute", "rollback", "begin", "history:False", "commit"]
    assert "left a transaction open" in result.error_message


@pytest.mark.unit
def test_ended_with_history_failure_raises_and_says_work_is_committed():
    engine, migration, result, provider, log = _run(TransactionOutcome.ENDED, fail_history=True)
    with pytest.raises(RuntimeError, match="history down"):
        engine.execute_migration(migration, result)
    assert any("already committed" in m for m in log.errors)


@pytest.mark.unit
def test_outcome_that_is_not_an_enum_member_is_intact():
    engine, migration, result, provider, _ = _run(MagicMock())
    engine.execute_migration(migration, result)
    assert provider.events == ["begin", "execute", "history:True", "commit"]


@pytest.mark.unit
def test_script_with_no_statement_does_not_fail():
    engine, migration, result, provider, _ = _run(TransactionOutcome.OPEN, content="-- nothing")
    engine.execute_migration(migration, result)
    assert "left a transaction open" in result.error_message
