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
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_SPEC
from dblift.db.plugins.mysql.quirks import MysqlQuirks
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser

SCRIPT = "CREATE TABLE a (x INT);\nDELIMITER //\nSELECT 1; SELECT 2//\nDELIMITER ;\nSELECT 3;\n"


def test_the_quirks_hand_the_engine_its_spec():
    assert MysqlQuirks().lexical_spec() is MYSQL_SPEC
    assert MariadbQuirks().lexical_spec() is MARIADB_SPEC


def test_mariadb_reads_its_executable_comment_through_the_analyzer():
    script = "/*M!100500 SELECT 1 */; SELECT 2;"
    assert SqlAnalyzer("mariadb").split_statements(script) == ["/*M!100500 SELECT 1 */", "SELECT 2"]
    assert SqlAnalyzer("mysql").split_statements(script) == ["SELECT 2"]


def test_replaced_scanner_module_is_absent():
    scanner = "dblift.db.plugins.mysql.parser." + "_script"
    assert importlib.util.find_spec(scanner) is None


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


@pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
def test_blanking_comments_is_not_offered_for_a_delimiter_script(spec):
    with pytest.raises(NotImplementedError, match="own tokenizer"):
        LexicalEngine(spec).blank_comments("SELECT 1 -- c")
