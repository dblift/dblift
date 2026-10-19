"""The engine sends every statement the splitter returns; the splitter decides what is empty."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.formats import MigrationFormat
from dblift.core.migration.sql.execution_statement import _position
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter

pytestmark = pytest.mark.unit

NBSP = "\xa0"

#: (dialect, piece, sent): whether the splitter returns the piece of a script as a statement of its
#: own. Db2, MySQL, MariaDB, SQLite and DuckDB keep these characters, so the piece is sent; the
#: other dialects read them as white space, so the piece is empty (or a comment) and is no statement.
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
    ("sqlite", "\x0b", True),
    ("sqlite", NBSP, True),
    ("sqlite", f"{NBSP} -- c", True),
    ("duckdb", "\x0b", True),
    ("duckdb", " ", True),
    ("duckdb", "\x85", True),
    ("mysql", NBSP, True),
    ("mysql", "\u3000", True),
    ("mysql", "\u2028", True),
    ("mysql", f"{NBSP} -- c", True),
    ("mysql", "\x1c -- c", True),
    ("mariadb", "\x1c -- c", False),
    ("mariadb", "\x7f /* c */", False),
    ("mariadb", "\x1c SELECT 1", True),
    ("mysql", "\x1c # c", True),
    ("mariadb", "\x1c # c", False),
    ("mariadb", "\x01 # c\n", False),
    ("mariadb", "\x7f # c", False),
    ("mysql", "# c", False),
    ("mariadb", "# c", False),
    ("mysql", "\x0b", False),
    ("mysql", "\x0c -- c", False),
    ("mariadb", NBSP, True),
    ("mariadb", f"{NBSP} -- c", True),
    ("mariadb", "\x0b", False),
    ("postgresql", NBSP, False),
    ("postgresql", "# c", True),
    ("sqlserver", "# c", True),
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


def _script(dialect: str, text: str) -> str:
    """``VALUES 1``, the piece, ``VALUES 2``: separated by ``GO`` where the dialect has batches."""
    if dialect == "sqlserver":
        return f"VALUES 1\nGO\n{text}\n;\nGO\nVALUES 2"
    return f"VALUES 1;\n{text}\n;\nVALUES 2;"


def _split(dialect: str, text: str) -> list:
    return StatementSplitter(dialect).split_statements(_script(dialect, text))


def _expected(dialect: str, text: str, sent: bool) -> list:
    strings = _split(dialect, text)
    assert (len(strings) == 3) is sent
    return strings


@pytest.mark.parametrize("dialect, text, sent", CASES, ids=IDS)
def test_the_engine_sends_every_statement_the_splitter_returns(dialect, text, sent):
    expected = _expected(dialect, text, sent)
    engine = _engine(dialect)
    migration, result = MagicMock(), MagicMock()
    result.has_error.return_value = False
    engine._execute_statements(_split(dialect, text), migration, result, 0.0)
    got = [call.args[0] for call in engine.sql_execution_service.execute_statement.call_args_list]
    assert got == expected


@pytest.mark.parametrize("dialect, text, sent", CASES, ids=IDS)
def test_the_engine_classifies_every_statement_the_splitter_returns(dialect, text, sent):
    expected = _expected(dialect, text, sent)
    classified = _engine(dialect)._classify_execution_statements(_split(dialect, text))
    assert [c.sql for c in classified] == expected


@pytest.mark.parametrize("dialect, text, sent", CASES, ids=IDS)
def test_the_executable_statements_are_the_splitters_list(dialect, text, sent):
    expected = _expected(dialect, text, sent)
    engine = _engine(dialect)
    engine._parse_sql_statements = MagicMock(return_value=_split(dialect, text))
    migration = MagicMock()
    migration.format = MigrationFormat.SQL
    assert engine.get_executable_sql_statements(migration, MagicMock()) == expected


@pytest.mark.parametrize("dialect, text, sent", CASES, ids=IDS)
def test_a_callback_sends_every_statement_the_splitter_returns(dialect, text, sent):
    expected = _expected(dialect, text, sent)
    engine = _engine(dialect)
    engine._prepare_sql_statements = MagicMock(return_value=_split(dialect, text))
    callback = MagicMock()
    callback.format = MigrationFormat.SQL
    engine.execute_callback(callback)
    got = [call.args[0] for call in engine.sql_execution_service.execute_statement.call_args_list]
    assert got == expected


def test_the_line_of_a_statement_counts_the_record_of_kept_characters_before_it():
    script = f"VALUES 1;\n{NBSP};\nVALUES 2;"
    statements = StatementSplitter("db2").split_statements(script)
    assert _position(statements, 1, "db2", script) == "line 2"
    assert _position(statements, 2, "db2", script) == "line 3"
