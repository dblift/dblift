"""A statement is empty to the migration layer only when it holds none but its dialect's blanks."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.formats import MigrationFormat
from dblift.core.migration.sql.execution_statement import _position
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

pytestmark = pytest.mark.unit

NBSP = "\xa0"

#: (dialect, statement, sent): Db2 keeps these characters; every other dialect still reads them
#: as white space, so the statement is empty (or a comment) and is skipped, as it always was.
CASES = [
    ("db2", NBSP, True),
    ("db2", "\x0c", True),
    ("db2", "\x0b", True),
    ("db2", " ", True),
    ("db2", "\x85", True),
    ("db2", f"{NBSP} -- c", True),
    ("db2", "\x0c -- c", True),
    ("db2", f"{NBSP}/* c */", True),
    ("db2", " \t -- c", False),
    ("sqlite", "\x0b", False),
    ("sqlite", NBSP, False),
    ("sqlite", f"{NBSP} -- c", False),
    ("duckdb", "\x0b", False),
    ("duckdb", " ", False),
    ("duckdb", "\x85", False),
    ("mysql", NBSP, False),
    ("mysql", f"{NBSP} -- c", False),
    ("mariadb", f"{NBSP} -- c", False),
    ("postgresql", NBSP, False),
]
IDS = [f"{dialect}-{text!r}" for dialect, text, _ in CASES]


def _service() -> MagicMock:
    service = MagicMock()
    service.execute_statement.return_value = (False, 0)
    return service


def _engine(dialect: str) -> ExecutionEngine:
    provider = MagicMock()
    provider.connection = None
    provider.execute_statement.return_value = 0
    return ExecutionEngine(
        provider=provider,
        sql_analyzer=SqlAnalyzer(dialect=dialect),
        log=MagicMock(),
        sql_execution_service=_service(),
    )


def _script(text: str) -> list:
    return ["VALUES 1", text, "VALUES 2"]


def _expected(text: str, sent: bool) -> list:
    return _script(text) if sent else ["VALUES 1", "VALUES 2"]


@pytest.mark.parametrize("dialect, text, sent", CASES, ids=IDS)
def test_the_engine_sends_only_what_the_dialect_does_not_read_as_empty(dialect, text, sent):
    engine = _engine(dialect)
    migration, result = MagicMock(), MagicMock()
    result.has_error.return_value = False
    engine._execute_statements(_script(text), migration, result, 0.0)
    got = [call.args[0] for call in engine.sql_execution_service.execute_statement.call_args_list]
    assert got == _expected(text, sent)


@pytest.mark.parametrize("dialect, text, sent", CASES, ids=IDS)
def test_the_engine_classifies_only_what_the_dialect_does_not_read_as_empty(dialect, text, sent):
    classified = _engine(dialect)._classify_execution_statements(_script(text))
    assert [c.sql for c in classified] == _expected(text, sent)


@pytest.mark.parametrize("dialect, text, sent", CASES, ids=IDS)
def test_the_executable_statements_hold_only_what_the_dialect_does_not_read_as_empty(
    dialect, text, sent
):
    engine = _engine(dialect)
    engine._parse_sql_statements = MagicMock(return_value=_script(text))
    migration = MagicMock()
    migration.format = MigrationFormat.SQL
    assert engine.get_executable_sql_statements(migration, MagicMock()) == _expected(text, sent)


@pytest.mark.parametrize("dialect, text, sent", CASES, ids=IDS)
def test_a_callback_sends_only_what_the_dialect_does_not_read_as_empty(dialect, text, sent):
    engine = _engine(dialect)
    engine._prepare_sql_statements = MagicMock(return_value=_script(text))
    callback = MagicMock()
    callback.format = MigrationFormat.SQL
    engine.execute_callback(callback)
    got = [call.args[0] for call in engine.sql_execution_service.execute_statement.call_args_list]
    assert got == _expected(text, sent)


def test_the_line_of_a_statement_counts_the_record_of_kept_characters_before_it():
    script = f"VALUES 1;\n{NBSP};\nVALUES 2;"
    assert _position(_script(NBSP), 2, "db2", script) == "line 3"
