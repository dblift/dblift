"""Execution-level SQL analysis does not load presentation or rich parsing."""

import json
import logging
import runpy
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from tests.unit.lightweight_core._support import run_python

_ROWS = json.loads((Path(__file__).parent / "fixtures/splitting.json").read_text())


def test_split_and_classify_without_detailed_analysis_dependencies(tmp_path):
    result = run_python(
        """
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
analyzer = SqlAnalyzer('sqlite')
assert analyzer.get_statement_type('CREATE TABLE t (id INTEGER)') == 'DDL'
assert analyzer.get_statement_type('SELECT 1') == 'QUERY'
assert len(analyzer.split_statements("SELECT 'a;b'; SELECT 2;")) == 2
""",
        blocked=("rich", "jinja2", "sqlglot"),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr
    assert list(tmp_path.iterdir()) == []


def test_real_sqlite_explicit_v_and_u_execute_without_detailed_analysis(tmp_path):
    result = run_python(
        """
from dblift.config import DbliftConfig
from dblift.core.logger import NullLog
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.db.plugins.sqlite.provider import SQLiteProvider

config = DbliftConfig.from_dict({'database': {'type': 'sqlite', 'url': 'sqlite:///:memory:'}})
provider = SQLiteProvider(config, NullLog())
provider.create_connection()
sent = []
execute_statement = provider.execute_statement
execute_query = provider.execute_query
def record_statement(sql, schema=None, params=None):
    sent.append(('statement', sql, params))
    return execute_statement(sql, schema=schema, params=params)
def record_query(sql, params=None):
    sent.append(('query', sql, params))
    return execute_query(sql, params=params)
provider.execute_statement = record_statement
provider.execute_query = record_query
try:
    service = SqlExecutionService(provider, SqlAnalyzer('sqlite'), journal=None)
    assert service.execute_statement('CREATE TABLE t (id INTEGER)')[0] is False
    assert service.execute_statement('INSERT INTO t VALUES (?)', params=[7])[0] is False
    is_query, rows = service.execute_statement('SELECT id FROM t WHERE id = ?', params=[7])
    assert is_query and rows == [{'id': 7}]
    assert service.execute_statement('DROP TABLE t')[0] is False
    assert sent == [
        ('statement', 'CREATE TABLE t (id INTEGER)', None),
        ('statement', 'INSERT INTO t VALUES (?)', [7]),
        ('query', 'SELECT id FROM t WHERE id = ?', [7]),
        ('statement', 'DROP TABLE t', None),
    ], sent
    assert execute_query("SELECT name FROM sqlite_master WHERE name='t'") == []
finally:
    provider.close()
""",
        blocked=("sqlglot",),
        cwd=tmp_path,
    )
    assert result.returncode == 0, result.stderr


def test_explicit_detailed_analysis_still_reports_missing_sqlglot():
    result = run_python(
        """
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
analyzer = SqlAnalyzer('postgresql')
try:
    analyzer.parser_factory.parse_sql('CREATE TABLE t (id INTEGER)')
except ModuleNotFoundError as error:
    assert error.name == 'sqlglot', error.name
else:
    raise AssertionError('detailed analysis unexpectedly succeeded')
""",
        blocked=("sqlglot",),
    )
    assert result.returncode == 0, result.stderr


def test_detailed_parser_factory_is_cached_only_on_explicit_access(monkeypatch):
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
    from dblift.core.sql_parser.parser_factory import SqlParserFactory

    created = []
    original_init = SqlParserFactory.__init__

    def record_init(self, dialect, parser_type="hybrid"):
        created.append(parser_type)
        original_init(self, dialect, parser_type)

    monkeypatch.setattr(SqlParserFactory, "__init__", record_init)
    analyzer = SqlAnalyzer("sqlite")
    assert created and set(created) == {"regex"}
    analyzer.get_statement_type("SELECT 1")
    analyzer.split_statements("SELECT 1;")
    assert set(created) == {"regex"}

    factory = analyzer.parser_factory
    assert isinstance(factory, SqlParserFactory)
    assert factory is analyzer.parser_factory
    assert created.count("hybrid") == 1


def test_injected_and_reassigned_parser_factories_preserve_identity():
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
    from dblift.core.migration.sql.sql_execution_service import SqlExecutionService

    first = MagicMock()
    second = MagicMock()
    second.extract_objects.return_value = []
    analyzer = SqlAnalyzer("sqlite", parser_factory=first)
    assert analyzer.parser_factory is first
    analyzer.parser_factory = second
    assert analyzer.parser_factory is second

    provider = MagicMock(spec=["execute_statement"])
    journal = MagicMock()
    service = SqlExecutionService(provider, analyzer, journal=journal)
    service.execute_statement("CREATE TABLE t (id INTEGER)")
    first.extract_objects.assert_not_called()
    second.extract_objects.assert_called_once_with("CREATE TABLE t (id INTEGER)", None)


@pytest.mark.parametrize("row", _ROWS, ids=lambda row: row["dialect"])
def test_d1_dialect_corpus_without_detailed_analysis_dependencies(row):
    source = f"""
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
analyzer = SqlAnalyzer({row['dialect']!r})
sql = {row['sql']!r}
expected = {row['statements']!r}
error_type = {row['error_type']!r}
if error_type:
    try:
        analyzer.split_statements(sql)
    except Exception as exc:
        assert type(exc).__name__ == error_type, type(exc).__name__
    else:
        raise AssertionError('expected ' + error_type)
else:
    assert analyzer.split_statements(sql) == expected
"""
    result = run_python(source, blocked=("rich", "jinja2", "sqlglot"))
    assert result.returncode == 0, result.stderr
