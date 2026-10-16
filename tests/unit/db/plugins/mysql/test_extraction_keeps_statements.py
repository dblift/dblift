"""MySQL extraction follows the client scanner and its refusals."""

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


def test_parse_sql_reports_a_client_command_refusal() -> None:
    result = MySqlRegexParser().parse_sql(SCRIPT)
    assert not result.success
    assert result.statements == []
    assert any("source" in error for error in result.errors)


def test_the_hybrid_parser_refuses_the_same_client_command() -> None:
    parser = HybridParser("mysql")
    with pytest.raises(UnsupportedMetaCommandError):
        parser.split_for_extraction(SCRIPT)


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


@pytest.mark.parametrize("parser_class", [MySqlRegexParser, MariaDbRegexParser])
def test_each_engine_projects_analysis_from_its_client_records(parser_class: type) -> None:
    parser = parser_class()
    script = "DELIMITER //\nSELECT 1; DROP TABLE t//\nDELIMITER ;"
    assert parser.split_statements(script) == ["SELECT 1; DROP TABLE t"]
    assert parser.split_for_analysis(script) == ["SELECT 1", "DROP TABLE t"]


def test_mariadb_gets_its_own_regex_parser_and_mysql_does_not() -> None:
    assert MariadbQuirks().parser_class("regex") is MariaDbRegexParser
    assert MysqlQuirks().parser_class("regex") is MySqlRegexParser
    assert MariadbQuirks().parser_class("hybrid") is MysqlQuirks().parser_class("hybrid")
    assert issubclass(MariaDbRegexParser, MySqlRegexParser)
    assert (
        MariaDbRegexParser._splitter_spec.name == "mariadb"
        and MySqlRegexParser._splitter_spec.name == "mysql"
    )


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


def test_parse_sql_reports_client_scanner_refusal_without_partial_objects() -> None:
    result = HybridParser("mysql").parse_sql("SOURCE other.sql\nCREATE TABLE a (id INT);\n")
    assert not result.success
    assert result.statements == []
    assert "client command 'SOURCE'" in " ".join(result.errors or [])


def test_extract_objects_refuses_script_when_scanner_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(self: HybridParser, sql_content: str, strict_tokenizer: bool = False) -> list[str]:
        raise UnsupportedMetaCommandError("client command refused")

    monkeypatch.setattr(HybridParser, "split_for_extraction", refuse)
    with pytest.raises(UnsupportedMetaCommandError, match="client command refused"):
        HybridParser("mysql").extract_objects("CREATE TABLE a (id INT);\n")
