"""A statement is empty to the migration layer only when it holds none but its dialect's blanks."""

from unittest.mock import MagicMock

import pytest

from dblift.core.migration.executor.execution_engine import ExecutionEngine
from dblift.core.migration.formats import MigrationFormat
from dblift.core.migration.sql.execution_statement import _position
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

pytestmark = pytest.mark.unit

NBSP = "\xa0"

#: (dialect, statement, sent): Db2, MySQL and MariaDB keep these characters; every other dialect
#: still reads them as white space, so the statement is empty (or a comment) and is skipped, as it always was.
#: DuckDB is the exception to "every other": the driver rejects a script holding a VT, NEL, U+2028 or U+001F
#: statement (and keeps a no-break space after a quote opener in a comment), so skipping it would let a
#: migration succeed that the engine refuses; only ASCII blanks are empty to it.
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
    ("duckdb", "\x0b", True),
    ("duckdb", " ", True),
    ("duckdb", "\x85", True),
    ("duckdb", "\x1f", True),
    ("duckdb", f"{NBSP} -- c", True),
    ("duckdb", " \t\n", False),
    ("duckdb", " \t -- c", False),
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


@pytest.mark.parametrize(
    "dialect, expected",
    [("mysql", True), ("mariadb", True), ("postgresql", False), ("sqlserver", False)],
)
def test_only_mysql_and_mariadb_read_a_hash_as_a_line_comment(dialect, expected):
    from dblift.db.provider_registry import ProviderRegistry

    assert ProviderRegistry.get_quirks(dialect).hash_line_comments() is expected


def test_a_statement_of_hash_comments_is_empty_only_when_asked():
    from dblift.core.migration.sql.execution_statement import is_comment_only_statement

    assert is_comment_only_statement("# c\n# d", hash_comments=True)
    assert not is_comment_only_statement("# c\n# d")
    assert not is_comment_only_statement("# c\nSELECT 1", hash_comments=True)
