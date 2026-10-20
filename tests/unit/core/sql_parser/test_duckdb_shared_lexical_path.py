"""DuckDB splitting, analysis, extraction and statement facts run on the shared lexical engine."""

import importlib.util
import logging
from unittest.mock import patch

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.db2.parser.lexical_spec import DB2_SPEC
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import (
    DuckDBFactsParser,
    DuckDBStatementFactsReader,
)
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
from dblift.db.plugins.duckdb.parser.duckdb_tokenizer import DuckDBTokenizer
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC
from dblift.db.plugins.duckdb.provider import DuckDBProvider
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC
from dblift.db.provider_registry import ProviderRegistry
from dblift.db.sqlalchemy_provider import SqlAlchemyProvider

SCRIPT = "CREATE TABLE a (x INT); -- c\nINSERT INTO a VALUES (1) /* n */;\n"
STATEMENTS = ["CREATE TABLE a (x INT)", "-- c\nINSERT INTO a VALUES (1) /* n */"]


def test_the_quirks_hand_the_engine_its_spec():
    assert DuckDBQuirks().lexical_spec() is DUCKDB_SPEC
    assert ProviderRegistry.get_quirks("duckdb").lexical_spec() is DUCKDB_SPEC


def test_execution_uses_the_spec_without_constructing_a_regex_parser(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy parser construction reached")

    monkeypatch.setattr(SqlParserFactory, "__init__", forbidden)
    monkeypatch.setattr(SqlParserFactory, "get_parser", forbidden)
    monkeypatch.setattr(EnhancedRegexParser, "__init__", forbidden)
    assert StatementSplitter("duckdb").split_statements(SCRIPT) == STATEMENTS


def test_replaced_scanner_module_is_absent():
    scanner = "dblift.db.plugins.duckdb.parser." + "_script"
    assert importlib.util.find_spec(scanner) is None


ENTRY_POINTS = {
    "regex split": lambda: DuckDBRegexParser().split(SCRIPT),
    "regex split_statements": lambda: DuckDBRegexParser().split_statements(SCRIPT),
    "regex split_for_analysis": lambda: DuckDBRegexParser().split_for_analysis(SCRIPT),
    "regex split_for_extraction": lambda: DuckDBRegexParser().split_for_extraction(SCRIPT),
    "regex parse_sql": lambda: DuckDBRegexParser().parse_sql(SCRIPT),
    "facts split": lambda: DuckDBFactsParser().split(SCRIPT),
    "facts split_statements": lambda: DuckDBFactsParser().split_statements(SCRIPT),
    "facts split_for_analysis": lambda: DuckDBFactsParser().split_for_analysis(SCRIPT),
    "facts split_for_extraction": lambda: DuckDBFactsParser().split_for_extraction(SCRIPT),
    "facts parse_sql": lambda: DuckDBFactsParser().parse_sql(SCRIPT),
    "facts extract_objects": lambda: DuckDBFactsParser().extract_objects(SCRIPT),
    "facts validate_sql": lambda: DuckDBFactsParser().validate_sql(SCRIPT),
    "facts reader": lambda: DuckDBStatementFactsReader("duckdb").read("SELECT 1 /* c */"),
    "quirks blank_comments": lambda: DuckDBQuirks().blank_comments("SELECT 1 /* c */"),
    "analyzer": lambda: SqlAnalyzer("duckdb").split_statements_for_analysis(SCRIPT),
    "splitter": lambda: StatementSplitter("duckdb").split_statements(SCRIPT),
}


@pytest.mark.parametrize("entry", sorted(ENTRY_POINTS))
def test_entry_points_reach_the_engine(monkeypatch, entry):
    seen = []
    tokenize = LexicalTokenizer.tokenize
    scan_comments = LexicalTokenizer._scan_segment_comments

    def counting(self):
        seen.append(self.spec)
        return tokenize(self)

    def counting_comments(self):
        seen.append(self.spec)
        return scan_comments(self)

    monkeypatch.setattr(LexicalTokenizer, "tokenize", counting)
    monkeypatch.setattr(LexicalTokenizer, "_scan_segment_comments", counting_comments)
    ENTRY_POINTS[entry]()
    assert seen and all(spec is DUCKDB_SPEC for spec in seen)


def test_the_provider_rewrite_reads_the_engine(monkeypatch):
    seen = []
    tokenize = LexicalTokenizer.tokenize
    monkeypatch.setattr(
        LexicalTokenizer, "tokenize", lambda self: (seen.append(self.spec), tokenize(self))[1]
    )

    class Result:
        @staticmethod
        def fetchall():
            return [(1,)]

    provider = object.__new__(DuckDBProvider)
    provider._tx = object()
    with (
        patch.object(DuckDBProvider, "_ensure_connection", lambda self: "c"),
        patch.object(
            SqlAlchemyProvider, "_exec_unbound", staticmethod(lambda connection, text: Result())
        ),
    ):
        assert provider._try_dml_rowcount_via_returning("INSERT INTO t VALUES (1) -- c") == 1
    assert seen and all(spec is DUCKDB_SPEC for spec in seen)


def test_the_refusals_are_the_engine_s_and_not_softened_by_the_splitter():
    with pytest.raises(UnsupportedMetaCommandError, match="duckdb shell command '.mode' on line 1"):
        StatementSplitter("duckdb").split_statements(".mode csv\nSELECT 1;")


def test_placeholder_is_code_for_duckdb():
    assert DuckDBFactsParser().split_statements("SELECT ${a;b};") == ["SELECT ${a", "b}"]


def test_nothing_is_logged(caplog):
    regex, facts, splitter = DuckDBRegexParser(), DuckDBFactsParser(), StatementSplitter("duckdb")
    with caplog.at_level(logging.DEBUG):
        regex.split(SCRIPT)
        facts.split_statements(SCRIPT)
        splitter.split_statements(SCRIPT)
    assert [r for r in caplog.records if r.name.startswith("dblift")] == []


def test_the_parser_keeps_the_nesting_tokenizer_for_extraction():
    assert DuckDBRegexParser.tokenizer_class is DuckDBTokenizer
    assert getattr(DuckDBRegexParser(), "lexical_spec", None) is None
    assert getattr(DuckDBFactsParser(), "lexical_spec", None) is None


def test_the_engine_is_the_one_the_quirks_name():
    assert LexicalEngine(DuckDBQuirks().lexical_spec()).split_statements(SCRIPT) == STATEMENTS


def test_other_dialects_unchanged():
    expected = {
        "postgresql": POSTGRESQL_SPEC,
        "oracle": ORACLE_SPEC,
        "sqlite": SQLITE_SPEC,
        "sqlserver": SQLSERVER_SPEC,
        "mysql": MYSQL_SPEC,
        "mariadb": MARIADB_SPEC,
        "db2": DB2_SPEC,
    }
    for dialect, spec in expected.items():
        assert ProviderRegistry.get_quirks(dialect).lexical_spec() is spec
        assert spec.segment_script is None
