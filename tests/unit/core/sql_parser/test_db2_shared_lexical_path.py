"""Db2 splitting, analysis and extraction run on the shared lexical engine."""

import importlib.util
import logging

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.statement_splitter import StatementSplitter
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.plugins.db2.parser.lexical_spec import DB2_SPEC
from dblift.db.plugins.db2.quirks import Db2Quirks
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser

SCRIPT = (
    "CREATE TABLE a (x INT);\n--#SET TERMINATOR @\n"
    "CREATE PROCEDURE p()\nBEGIN\n  SET x = 1;\nEND@\n--#SET TERMINATOR ;\nVALUES 3;\n"
)
STATEMENTS = [
    "CREATE TABLE a (x INT)",
    "CREATE PROCEDURE p()\nBEGIN\n  SET x = 1;\nEND",
    "VALUES 3",
]


def test_the_quirks_hand_the_engine_its_spec():
    assert Db2Quirks().lexical_spec() is DB2_SPEC
    assert ProviderRegistry.get_quirks("db2").lexical_spec() is DB2_SPEC


def test_replaced_scanner_module_is_absent():
    scanner = "dblift.db.plugins.db2.parser." + "_script"
    assert importlib.util.find_spec(scanner) is None


@pytest.mark.parametrize(
    "entry", ["split", "split_statements", "split_for_extraction", "parse_sql"]
)
def test_entry_points_reach_the_engine(monkeypatch, entry):
    seen = []
    parse = LexicalEngine._parser

    def counting(self, script):
        seen.append(script)
        return parse(self, script)

    monkeypatch.setattr(LexicalEngine, "_parser", counting)
    getattr(facts_parser("db2"), entry)(SCRIPT)
    assert seen


def test_the_analyzer_reaches_the_engine_and_leaves_directives_out(monkeypatch):
    analyzer = SqlAnalyzer("db2")
    assert analyzer.split_statements(SCRIPT) == STATEMENTS
    assert analyzer.split_statements_for_analysis(SCRIPT) == STATEMENTS
    assert facts_parser("db2").split_for_extraction(SCRIPT) == STATEMENTS


def test_the_refusals_are_the_engine_s_and_not_softened_by_the_splitter():
    with pytest.raises(UnsafeStatementSplitError, match="code after a ';'"):
        StatementSplitter("db2").split_statements("VALUES 1; VALUES 2;")


def test_placeholder_is_code_for_db2():
    with pytest.raises(UnsafeStatementSplitError, match="code after a ';'"):
        facts_parser("db2").split_statements("VALUES ${a;b};\n")
    assert facts_parser("db2").split_statements("VALUES ${a}, ${b:c};\n") == ["VALUES ${a}, ${b:c}"]


def test_nothing_is_logged(caplog):
    with caplog.at_level(logging.DEBUG):
        facts_parser("db2").split(SCRIPT)
        facts_parser("db2").split_statements(SCRIPT)
        StatementSplitter("db2").split_statements(SCRIPT)
    assert [r for r in caplog.records if "lexical" in r.name or "terminator" in r.name] == []


def test_other_dialects_unchanged():
    expected = {
        "postgresql": POSTGRESQL_SPEC,
        "oracle": ORACLE_SPEC,
        "sqlite": SQLITE_SPEC,
        "sqlserver": SQLSERVER_SPEC,
        "mysql": MYSQL_SPEC,
        "mariadb": MARIADB_SPEC,
    }
    for dialect, spec in expected.items():
        assert ProviderRegistry.get_quirks(dialect).lexical_spec() is spec
        assert spec.terminator_script is None
