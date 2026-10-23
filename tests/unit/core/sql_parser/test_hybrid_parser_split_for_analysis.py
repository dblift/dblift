"""The public parser's analysis split is the dialect parser's, not the execution split."""

from tests.support.facts_parser import facts_parser


def test_sqlserver_analysis_split_does_not_repeat_a_go_count():
    parser = facts_parser("sqlserver")
    assert parser.split_for_analysis("SELECT 1;\nSELECT 2;\nGO 2") == ["SELECT 1;", "SELECT 2;"]


def test_postgresql_analysis_split_uses_scanner_constituents():
    parser = facts_parser("postgresql")
    sql = "SELECT 1; SELECT 2;"
    assert parser.split_for_analysis(sql) == ["SELECT 1", "SELECT 2"]
    assert parser.split_statements(sql) == ["SELECT 1;", "SELECT 2;"]
