"""The public parser's analysis split is the dialect parser's, not the execution split."""

from dblift.core.sql_parser import SqlParserFactory


def test_sqlserver_analysis_split_does_not_repeat_a_go_count():
    parser = SqlParserFactory("sqlserver").get_parser()
    assert parser.split_for_analysis("SELECT 1;\nSELECT 2;\nGO 2") == ["SELECT 1;", "SELECT 2;"]


def test_postgresql_analysis_split_uses_scanner_constituents():
    parser = SqlParserFactory("postgresql").get_parser()
    sql = "SELECT 1; SELECT 2;"
    assert parser.split_for_analysis(sql) == ["SELECT 1", "SELECT 2"]
    assert parser.split_statements(sql) == ["SELECT 1;", "SELECT 2;"]
