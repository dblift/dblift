"""Object extraction keeps reading one statement at a time and never refuses; execution does."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.hybrid_parser import HybridParser
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mariadb.regex_parser import MariaDbRegexParser
from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser
from dblift.db.plugins.mysql.quirks import MysqlQuirks

SCRIPT = "source other.sql;\nCREATE TABLE a (id INT);\nSELECT 1\\G\nCREATE TABLE b (id INT);\n"


def test_parse_sql_still_reads_the_tables_of_a_script_the_execution_split_refuses() -> None:
    result = MySqlRegexParser().parse_sql(SCRIPT)
    assert sorted(o.name for s in result.statements for o in s.objects) == ["a", "b"]


def test_the_hybrid_parser_extracts_through_the_regex_parser_extraction_split() -> None:
    parser = HybridParser("mysql")
    assert parser.split_for_extraction(SCRIPT) == MySqlRegexParser().split_for_extraction(SCRIPT)


def test_statements_for_analysis_are_the_execution_statements() -> None:
    analyzer = SqlAnalyzer("mysql")
    script = "DELIMITER //\nCREATE PROCEDURE p() BEGIN SELECT 1; END//\nDELIMITER ;\nSELECT 2;"
    assert analyzer.split_statements_for_analysis(script) == analyzer.split_statements(script)
    assert analyzer.split_statements(script) == [
        "CREATE PROCEDURE p() BEGIN SELECT 1; END",
        "SELECT 2",
    ]


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_a_script_of_hash_comments_is_no_statement_and_is_not_split_again(dialect: str) -> None:
    assert SqlAnalyzer(dialect).split_statements("# a\n# b ; c\n") == []


def test_the_regex_splitter_of_each_engine_is_authoritative() -> None:
    assert MySqlRegexParser.SPLITS_WITHOUT_FALLBACK is True
    assert MariaDbRegexParser.SPLITS_WITHOUT_FALLBACK is True


def test_mariadb_gets_its_own_regex_parser_and_mysql_does_not() -> None:
    assert MariadbQuirks().parser_class("regex") is MariaDbRegexParser
    assert MysqlQuirks().parser_class("regex") is MySqlRegexParser
    assert MariadbQuirks().parser_class("hybrid") is MysqlQuirks().parser_class("hybrid")
    assert issubclass(MariaDbRegexParser, MySqlRegexParser)
    assert MariaDbRegexParser.MARIADB and not MySqlRegexParser.MARIADB


def test_the_dialect_decides_what_the_maria_comment_is() -> None:
    script = "/*M!100500 SET @a = 1 */;\nSELECT 2;\n"
    assert SqlAnalyzer("mysql").split_statements(script) == ["SELECT 2"]
    assert SqlAnalyzer("mariadb").split_statements(script) == [
        "/*M!100500 SET @a = 1 */",
        "SELECT 2",
    ]


def test_the_dialect_name_of_each_regex_parser_is_its_engine() -> None:
    assert MySqlRegexParser().dialect_name == "mysql"
    assert MariaDbRegexParser().dialect_name == "mariadb"


def test_parse_sql_reports_any_parser_refusal_instead_of_failing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(self: HybridParser, sql_content: str, strict_tokenizer: bool = False) -> list[str]:
        raise UnsupportedMetaCommandError("client command refused")

    monkeypatch.setattr(HybridParser, "split_statements", refuse)
    result = HybridParser("mysql").parse_sql("SELECT 1;\n")
    assert result.success
    assert "client command refused" in " ".join(result.errors or [])
