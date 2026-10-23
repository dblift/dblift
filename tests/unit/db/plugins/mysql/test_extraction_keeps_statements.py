"""MySQL extraction follows the client scanner and its refusals."""

from __future__ import annotations

import pytest

from dblift.core.exceptions import UnsupportedMetaCommandError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.plugins.mariadb.facts_parser import MariaDbFactsParser
from dblift.db.plugins.mariadb.quirks import MariadbQuirks
from dblift.db.plugins.mysql.parser.mysql_facts_parser import MySqlFactsParser
from dblift.db.plugins.mysql.quirks import MysqlQuirks
from tests.support.facts_parser import facts_parser

SCRIPT = "source other.sql;\nCREATE TABLE a (id INT);\nSELECT 1\\G\nCREATE TABLE b (id INT);\n"


def test_parse_sql_reports_a_client_command_refusal() -> None:
    result = facts_parser("mysql").parse_sql(SCRIPT)
    assert not result.success
    assert result.statements == []
    assert any("source" in error for error in result.errors)


def test_the_hybrid_parser_refuses_the_same_client_command() -> None:
    factory = SqlParserFactory("mysql", "hybrid")
    with pytest.raises(UnsupportedMetaCommandError):
        factory.get_parser().split_for_extraction(SCRIPT)
    with pytest.raises(UnsupportedMetaCommandError):
        factory.extract_objects(SCRIPT)


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


def test_the_dialect_decides_what_the_maria_comment_is() -> None:
    script = "/*M!100500 SET @a = 1 */;\nSELECT 2;\n"
    assert SqlAnalyzer("mysql").split_statements(script) == ["SELECT 2"]
    assert SqlAnalyzer("mariadb").split_statements(script) == [
        "/*M!100500 SET @a = 1 */",
        "SELECT 2",
    ]


def test_the_dialect_name_of_each_regex_parser_is_its_engine() -> None:
    assert facts_parser("mysql").dialect_name == "mysql"
    assert facts_parser("mariadb").dialect_name == "mariadb"


def test_parse_sql_reports_client_scanner_refusal_without_partial_objects() -> None:
    result = SqlParserFactory("mysql", "hybrid").parse_sql(
        "SOURCE other.sql\nCREATE TABLE a (id INT);\n"
    )
    assert not result.success
    assert result.statements == []
    assert "client command 'SOURCE'" in " ".join(result.errors or [])


def test_extract_objects_refuses_script_when_scanner_refuses(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def refuse(
        self: StatementFactsParser, sql_content: str, strict_tokenizer: bool = False
    ) -> list[str]:
        raise UnsupportedMetaCommandError("client command refused")

    monkeypatch.setattr(StatementFactsParser, "split_for_analysis", refuse)
    with pytest.raises(UnsupportedMetaCommandError, match="client command refused"):
        SqlParserFactory("mysql", "hybrid").extract_objects("CREATE TABLE a (id INT);\n")
