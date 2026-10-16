"""MySQL and MariaDB splitting, analysis and extraction run on the shared lexical engine."""

import importlib.util
import logging

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mariadb.regex_parser import MariaDbRegexParser
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from dblift.db.plugins.mysql.quirks import MysqlQuirks
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC
from dblift.db.provider_registry import ProviderRegistry

SCRIPT = "CREATE TABLE a (x INT);\nDELIMITER //\nSELECT 1; SELECT 2//\nDELIMITER ;\nSELECT 3;\n"
PARSERS = {"mysql": MySqlRegexParser, "mariadb": MariaDbRegexParser}


def test_the_quirks_hand_the_engine_its_spec():
    assert MysqlQuirks().lexical_spec() is MYSQL_SPEC
    assert MariadbQuirks().lexical_spec() is MARIADB_SPEC


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_execution_uses_the_spec_without_constructing_a_regex_parser(monkeypatch, dialect):
    def forbidden(*args, **kwargs):
        raise AssertionError("legacy parser construction reached")

    monkeypatch.setattr(SqlParserFactory, "__init__", forbidden)
    monkeypatch.setattr(SqlParserFactory, "get_parser", forbidden)
    assert StatementSplitter(dialect).split_statements(SCRIPT) == [
        "CREATE TABLE a (x INT)",
        "SELECT 1; SELECT 2",
        "SELECT 3",
    ]


def test_mariadb_reads_its_executable_comment_through_the_analyzer():
    script = "/*M!100500 SELECT 1 */; SELECT 2;"
    assert SqlAnalyzer("mariadb").split_statements(script) == ["/*M!100500 SELECT 1 */", "SELECT 2"]
    assert SqlAnalyzer("mysql").split_statements(script) == ["SELECT 2"]


def test_replaced_scanner_module_is_absent():
    assert importlib.util.find_spec("dblift.db.plugins.mysql.parser._script") is None


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
@pytest.mark.parametrize(
    "entry",
    ["split", "split_statements", "split_for_analysis", "split_for_extraction", "parse_sql"],
)
def test_entry_points_reach_the_engine(monkeypatch, dialect, entry):
    seen = []
    parse = LexicalEngine._parser

    def counting(self, script):
        seen.append(script)
        return parse(self, script)

    monkeypatch.setattr(LexicalEngine, "_parser", counting)
    getattr(PARSERS[dialect](), entry)(SCRIPT)
    assert seen


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
@pytest.mark.parametrize("strict", [False, True])
def test_refusal_cannot_be_softened_at_the_legacy_entry_point(dialect, strict):
    with pytest.raises(
        UnsafeStatementSplitError, match="unterminated string opened at line 1, column 8"
    ):
        PARSERS[dialect]().split_statements("SELECT 'open", strict_tokenizer=strict)
    with pytest.raises(UnsafeStatementSplitError):
        StatementSplitter(dialect).split_statements("SELECT 'open")


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_analysis_and_extraction_project_the_execution_records(dialect):
    parser = PARSERS[dialect]()
    expected = ["CREATE TABLE a (x INT)", "SELECT 1", "SELECT 2", "SELECT 3"]
    assert parser.split_for_analysis(SCRIPT) == expected
    assert parser.split_for_extraction(SCRIPT) == expected
    assert SqlAnalyzer(dialect).split_statements_for_analysis(SCRIPT) == expected


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_nothing_is_logged(caplog, dialect):
    with caplog.at_level(logging.DEBUG):
        PARSERS[dialect]().split(SCRIPT)
        PARSERS[dialect]().split_statements(SCRIPT)
        StatementSplitter(dialect).split_statements(SCRIPT)
    assert [r for r in caplog.records if "lexical" in r.name or "delimiter" in r.name] == []


def test_the_parsers_keep_the_mysql_tokenizer_for_extraction():
    assert MySqlRegexParser.tokenizer_class.__name__ == "MySQLTokenizer"
    assert getattr(MySqlRegexParser(), "lexical_spec", None) is None
    assert getattr(MariaDbRegexParser(), "lexical_spec", None) is None


def test_other_dialects_unchanged():
    expected = {
        "postgresql": POSTGRESQL_SPEC,
        "oracle": ORACLE_SPEC,
        "sqlite": SQLITE_SPEC,
        "sqlserver": SQLSERVER_SPEC,
    }
    for dialect, spec in expected.items():
        assert ProviderRegistry.get_quirks(dialect).lexical_spec() is spec
    for spec in expected.values():
        assert spec.delimiter_script is None and spec.string_quote_doubling is True
