"""SQLite splitting, analysis and masking share one lexical engine."""

import importlib.util

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser
from dblift.db.provider_registry import ProviderRegistry


def test_sqlite_execution_does_not_construct_the_legacy_parser(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy parser construction reached")

    monkeypatch.setattr(SqlParserFactory, "__init__", forbidden)
    script = "CREATE TRIGGER tr AFTER INSERT ON x BEGIN INSERT INTO y VALUES(1); END; SELECT 1;"
    assert StatementSplitter("sqlite").split_statements(script) == [
        "CREATE TRIGGER tr AFTER INSERT ON x BEGIN INSERT INTO y VALUES(1); END",
        "SELECT 1",
    ]


def test_sqlite_analysis_does_not_call_the_legacy_scanner(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy analysis scanner reached")

    monkeypatch.setattr(SQLiteRegexParser, "split_for_analysis", forbidden)
    assert SqlAnalyzer("sqlite").split_statements_for_analysis("-- note\n") == ["-- note"]


def test_sqlite_masking_uses_the_shared_engine_after_legacy_scanner_removal():
    assert importlib.util.find_spec("dblift.db.plugins.sqlite.parser._script") is None
    assert (
        ProviderRegistry.get_quirks("sqlite").blank_comments("SELECT '-- literal' /* comment */;")
        == "SELECT '-- literal'  ;"
    )
