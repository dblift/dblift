"""SQLite splitting, analysis and masking share one lexical engine."""

import importlib.util

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser
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

    monkeypatch.setattr(SQLiteFactsParser, "split_for_analysis", forbidden)
    assert SqlAnalyzer("sqlite").split_statements_for_analysis("-- note\n") == []


def test_sqlite_masking_uses_the_shared_engine_after_legacy_scanner_removal():
    assert importlib.util.find_spec("dblift.db.plugins.sqlite.parser._script") is None
    assert (
        ProviderRegistry.get_quirks("sqlite").blank_comments("SELECT '-- literal' /* comment */;")
        == "SELECT '-- literal'  ;"
    )


def test_sqlite_masking_refuses_shell_separator_after_two_leading_boms():
    script = "\ufeff\ufeff\n/\n"
    with pytest.raises(UnsafeStatementSplitError, match="line 2 holds only"):
        ProviderRegistry.get_quirks("sqlite").blank_comments(script)


def test_sqlite_masking_still_drops_one_leading_bom():
    assert (
        ProviderRegistry.get_quirks("sqlite").blank_comments("\ufeffSELECT 1 /* c */;")
        == "SELECT 1  ;"
    )
