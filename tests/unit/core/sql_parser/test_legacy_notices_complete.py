"""Every announced legacy entry point warns once; canonical paths stay silent."""

from __future__ import annotations

import warnings

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser import _deprecation
from dblift.core.sql_parser.parser_factory import SqlParserFactory


@pytest.fixture(autouse=True)
def fresh_notices():
    with _deprecation._warned_lock:
        saved = set(_deprecation._warned)
        _deprecation._warned.clear()
    yield
    with _deprecation._warned_lock:
        _deprecation._warned.clear()
        _deprecation._warned.update(saved)


def _notices(action):
    with warnings.catch_warnings(record=True) as seen:
        warnings.simplefilter("always")
        action()
    return [str(w.message) for w in seen if w.category is DeprecationWarning]


@pytest.mark.parametrize(
    ("name", "action", "replacement"),
    [
        ("SqlParserFactory", lambda: SqlParserFactory("sqlite"), "StatementSplitter"),
        ("SqlAnalyzer", lambda: SqlAnalyzer("sqlite"), "StatementSplitter"),
        (
            "strict_tokenizer",
            lambda: StatementSplitter("sqlite").split("SELECT 1;", strict_tokenizer=False),
            "StatementSplitter",
        ),
        (
            "strict_tokenizer",
            lambda: SqlAnalyzer.internal("sqlite").split_statements(
                "SELECT 1;", strict_tokenizer=True
            ),
            "StatementSplitter",
        ),
        (
            "strict_tokenizer",
            lambda: SqlAnalyzer.internal("sqlite").split_statements_for_analysis(
                "SELECT 1;", strict_tokenizer=False
            ),
            "StatementSplitter",
        ),
        (
            "strict_tokenizer",
            lambda: SqlParserFactory.internal("sqlite").split_statements(
                "SELECT 1;", strict_tokenizer=False
            ),
            "StatementSplitter",
        ),
    ],
    ids=[
        "factory",
        "analyzer",
        "splitter-strict",
        "analyzer-strict",
        "analysis-strict",
        "factory-strict",
    ],
)
def test_legacy_entry_point_warns_naming_its_replacement(name, action, replacement):
    messages = _notices(action)
    assert len(messages) == 1, messages
    assert name in messages[0]
    assert replacement in messages[0]
    assert "read_statement_facts" in messages[0]


def test_explicit_parser_type_has_its_own_notice():
    messages = _notices(lambda: SqlParserFactory("sqlite", "regex"))
    named = [m for m in messages if "parser_type" in m]
    assert len(named) == 1, messages
    assert "StatementSplitter" in named[0]
    assert "read_statement_facts" in named[0]
    assert _notices(lambda: SqlParserFactory("sqlite")) == []


def test_each_notice_is_once_per_process():
    assert len(_notices(lambda: SqlAnalyzer("sqlite"))) == 1
    assert _notices(lambda: SqlAnalyzer("sqlite")) == []


def test_internal_bridges_are_silent_and_canonical_paths_do_not_warn():
    from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
    from dblift.core.sql_parser.redaction import _dialect_tokenizer, mask_string_literals

    def canonical():
        splitter = StatementSplitter("sqlite")
        splitter.split("SELECT 1;")
        splitter.split_statements("SELECT 1;")
        analyzer = SqlAnalyzer.internal("sqlite")
        analyzer.split_statements("SELECT 1;")
        analyzer.split_statements_for_analysis("SELECT 1;")
        _ = analyzer.parser_factory
        UndoScriptGenerator(dialect="sqlite")
        _dialect_tokenizer("mongodb")
        mask_string_literals("SELECT 'a'", "postgresql")

    assert _notices(canonical) == []


def test_facts_dialects_keep_refusing_the_legacy_parsers():
    from dblift.core.sql_parser.hybrid_parser import HybridParser
    from dblift.core.sql_parser.sqlglot_parser import SqlGlotParser

    for cls in (HybridParser, SqlGlotParser):
        with pytest.raises(ValueError, match="StatementFactsParser"):
            cls("postgresql")
