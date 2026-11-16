"""The engine settles a transaction its script ended or left open before recording history."""

from typing import Any, List
from unittest.mock import MagicMock

import pytest

from dblift.core.exceptions import TransactionLeftOpenError
from dblift.core.logger import NullLog
from dblift.core.logger.results import MigrateResult
from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.migration import Migration, MigrationType
from dblift.core.migration.placeholders.placeholder_service import PlaceholderService
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.db.provider_interfaces import TransactionalProvider, TransactionOutcome
from tests.unit._migration_factory import make_migration


class _Provider(TransactionalProvider):
    canonical_dialect_key = "sqlite"

    def __init__(self, outcome: Any = None, script_session: bool = False) -> None:
        self.events: List[str] = []
        self._script_session = script_session
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

    def supports_script_session(self) -> bool:
        return self._script_session


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
    outcome: Any = None,
    fail_history: bool = False,
    content: str = "INSERT INTO t VALUES (1);",
    script_session: bool = False,
    placeholder_service: Any = None,
):
    provider = _Provider(outcome, script_session)
    log = _Log()
    engine = ExecutionEngine(
        provider,
        StatementReader("sqlite", analysis_mode="execution"),
        log,
        history_manager=_History(provider.events, fail_history),
        placeholder_service=placeholder_service,
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
    assert "the script left a transaction open; it was rolled back" in result.error_message
    assert result.error_message.count(migration.script_name) == 1


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


def _callback(outcome: Any = None):
    engine, _, _, provider, log = _run(outcome)
    callback = make_migration(
        script_name="beforeMigrate__cb.sql",
        content="INSERT INTO t VALUES (1);",
        sql_statements=["INSERT INTO t VALUES (1);"],
    )
    return engine, callback, provider, log


@pytest.mark.unit
def test_callback_default_outcome_commits():
    engine, callback, provider, _ = _callback()
    engine.execute_callback(callback)
    assert provider.events == ["begin", "execute", "commit"]


@pytest.mark.unit
def test_callback_that_ended_its_transaction_is_released_not_committed():
    engine, callback, provider, log = _callback(TransactionOutcome.ENDED)
    engine.execute_callback(callback)
    assert provider.events == ["begin", "execute", "rollback"]
    assert any(
        m.endswith("ended its transaction itself (COMMIT or ROLLBACK in the script)")
        for m in log.warnings
    )
    assert not any("history row" in m for m in log.warnings)


@pytest.mark.unit
def test_callback_that_left_a_transaction_open_fails():
    engine, callback, provider, _ = _callback(TransactionOutcome.OPEN)
    with pytest.raises(TransactionLeftOpenError, match="left a transaction open"):
        engine.execute_callback(callback)
    assert provider.events == ["begin", "execute", "rollback"]


NT = "-- dblift:no-transaction\n"


@pytest.mark.unit
def test_directive_on_a_provider_that_does_not_support_it_is_refused_before_anything_runs():
    engine, migration, result, provider, _ = _run(content=NT + "INSERT INTO t VALUES (1);")
    engine.execute_migration(migration, result)
    assert provider.events == []
    assert result.error_message == (
        "V1__x.sql: -- dblift:no-transaction is not supported on sqlite; "
        "none of its statements were executed"
    )


@pytest.mark.unit
def test_directive_on_a_caller_owned_connection_is_refused():
    engine, migration, result, provider, _ = _run(
        content=NT + "INSERT INTO t VALUES (1);", script_session=True
    )
    provider.is_caller_owned = lambda: True
    engine.execute_migration(migration, result)
    assert provider.events == []
    assert "cannot run on a connection passed to from_sqlalchemy" in result.error_message


@pytest.mark.unit
def test_directive_lifts_the_mixed_mode_refusal_in_previews():
    mixed = "VACUUM;\nINSERT INTO t VALUES (1);"
    engine, migration, result, _, _ = _run(content=mixed)
    assert engine.get_executable_sql_statements(migration, result) == []
    assert "mixes transactional and autocommit-only" in result.error_message
    engine, migration, result, _, _ = _run(content=NT + mixed, script_session=True)
    assert len(engine.get_executable_sql_statements(migration, result)) == 2
    assert result.error_message is None


@pytest.mark.unit
def test_refusal_is_none_without_the_directive_and_for_python_scripts():
    engine, migration, _, _, _ = _run()
    assert engine.script_session_refusal(migration) is None
    python = make_migration(script_name="V2__p.py", content=NT + "pass", version="2")
    assert engine.script_session_refusal(python) is None


@pytest.mark.unit
def test_directive_is_read_from_the_original_text_not_the_substituted_one():
    engine, migration, result, provider, _ = _run(
        content="-- ${mode}\nINSERT INTO t VALUES (1);",
        placeholder_service=PlaceholderService({"mode": "dblift:no-transaction"}),
    )
    engine.execute_migration(migration, result)
    assert provider.events == ["begin", "execute", "history:True", "commit"]
