"""Tests that lifecycle callbacks are recorded on the operation result."""

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.exceptions import CallbackExecutionError
from core.logger.results import CallbackExecution, MigrateResult
from core.migration.commands.migrate_command import MigrateCommand
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration


def _command_with_callbacks(callbacks):
    command = MigrateCommand.__new__(MigrateCommand)
    command.log = MagicMock()
    command.execution_engine = MagicMock()
    command.script_manager = MagicMock()
    command.script_manager.get_callbacks_by_event.return_value = callbacks
    return command


@pytest.mark.unit
def test_execute_callbacks_records_phase_and_file():
    callback = SimpleNamespace(script_name="beforeMigrate__seed.sql", description="seed")
    command = _command_with_callbacks([callback])
    result = MigrateResult()

    command._execute_callbacks(Path("migrations"), "beforeMigrate", True, None, None, result)

    assert len(result.callbacks) == 1
    rec = result.callbacks[0]
    assert rec.phase == "beforeMigrate"
    assert rec.name == "seed"
    assert rec.file == "beforeMigrate__seed.sql"
    assert rec.status == "OK"
    command.execution_engine.execute_callback.assert_called_once()


@pytest.mark.unit
def test_execute_callbacks_records_failed_status_then_reraises():
    callback = SimpleNamespace(script_name="beforeMigrate__bad.sql", description="bad")
    command = _command_with_callbacks([callback])
    command.execution_engine.execute_callback.side_effect = RuntimeError("boom")
    result = MigrateResult()

    with pytest.raises(CallbackExecutionError):
        command._execute_callbacks(Path("migrations"), "beforeMigrate", True, None, None, result)

    assert len(result.callbacks) == 1
    assert result.callbacks[0].status == "FAILED"
    assert result.callbacks[0].file == "beforeMigrate__bad.sql"


def _engine_with_query_result(rows):
    from core.migration.executor.execution_engine import ExecutionEngine

    provider = MagicMock()
    sql_analyzer = MagicMock()
    sql_analyzer.dialect = "postgresql"
    mock_ses = MagicMock()
    mock_ses.execute_statement.return_value = (True, rows)
    return ExecutionEngine(
        provider=provider,
        sql_analyzer=sql_analyzer,
        log=MagicMock(),
        sql_execution_service=mock_ses,
        config=SimpleNamespace(database=SimpleNamespace(schema=None)),
    )


def _sql_callback(script_name, description, statement):
    cb = MagicMock(spec=Migration)
    cb.format = MigrationFormat.SQL
    cb.script_name = script_name
    cb.version = None
    cb.description = description
    cb.dialect = "postgresql"
    cb.parse_sql_statements.return_value = [statement]
    return cb


@pytest.mark.unit
def test_execute_callback_stores_statements_and_result_sets_on_record():
    engine = _engine_with_query_result([{"status": "active"}])
    cb = _sql_callback("beforeMigrate__check.sql", "check", "SELECT status FROM jobs")
    result = MigrateResult()
    result.show_query_results = True
    record = CallbackExecution("beforeMigrate", "check", cb.script_name)

    engine.execute_callback(cb, result, record=record)

    assert record.statements == ["SELECT status FROM jobs"]
    assert record.row_count == 1
    assert record.result_sets[0]["columns"] == ["status"]
    assert record.result_sets[0]["rows"] == [["active"]]
    assert record.result_sets[0]["statement"] == "SELECT status FROM jobs"


@pytest.mark.unit
def test_execute_callback_records_zero_row_result_set():
    engine = _engine_with_query_result([])
    cb = _sql_callback(
        "beforeMigrate__empty.sql", "empty", "SELECT status FROM jobs WHERE 1=0"
    )
    record = CallbackExecution("beforeMigrate", "empty", cb.script_name)

    engine.execute_callback(cb, MigrateResult(), record=record)

    assert record.statements == ["SELECT status FROM jobs WHERE 1=0"]
    assert record.row_count == 0
    assert record.result_sets[0]["rows"] == []
