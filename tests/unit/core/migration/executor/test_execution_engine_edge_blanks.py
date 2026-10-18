"""A statement made only of characters its dialect keeps is executed, not skipped as empty."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.executor.execution_engine import ExecutionEngine

pytestmark = pytest.mark.unit

NBSP = "\xa0"


def _engine() -> ExecutionEngine:
    provider = MagicMock()
    provider.connection = None
    provider.execute_statement.return_value = 0
    sql_analyzer = MagicMock()
    sql_analyzer.dialect = "db2"
    config = MagicMock()
    config.database.type.value = "db2"
    return ExecutionEngine(
        provider=provider, sql_analyzer=sql_analyzer, log=MagicMock(), config=config
    )


def test_the_engine_sends_a_statement_of_kept_characters_to_the_provider() -> None:
    engine = _engine()
    migration = MagicMock()
    migration.script_name = "V1__x.sql"
    result = MagicMock()
    result.has_error.return_value = False
    engine._execute_statements(["VALUES 1", NBSP, "VALUES 2"], migration, result, 0.0)
    sent = [call.args[0] for call in engine.provider.execute_statement.call_args_list]
    assert sent == ["VALUES 1", NBSP, "VALUES 2"]


def test_the_engine_classifies_a_statement_of_kept_characters() -> None:
    engine = _engine()
    assert len(engine._classify_execution_statements(["VALUES 1", NBSP])) == 2
