import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser


def test_batch_analysis_keeps_literals_comments_and_procedure_body_intact() -> None:
    sql = (
        "SELECT 'a;b'; /* ; */ SELECT 2;\nGO\n"
        "CREATE PROCEDURE dbo.p AS\n"
        "BEGIN\n"
        "  SELECT 1;\n"
        "  SELECT 2;\n"
        "END;\nGO\n"
    )

    parser = SqlServerRegexParser()

    assert len(parser.split_statements(sql)) == 2
    assert parser.split_for_analysis(sql) == [
        "SELECT 'a;b';",
        "/* ; */ SELECT 2;",
        "CREATE PROCEDURE dbo.p AS\nBEGIN\n  SELECT 1;\n  SELECT 2;\nEND;",
    ]


@pytest.mark.parametrize(
    "first",
    [
        "SELECT [a;b];",
        'SELECT "a;b";',
        "SELECT 'a;b';",
        "SELECT 1 /* a;b */;",
        "SELECT 1 -- a;b\n;",
    ],
)
def test_quoted_or_commented_semicolon_does_not_hide_next_statement(first: str) -> None:
    parser = SqlServerRegexParser()
    assert parser.split_for_analysis(first + " SELECT 2;") == [first, "SELECT 2;"]


def test_case_end_does_not_close_a_begin_block() -> None:
    sql = "IF 1=1 BEGIN SELECT CASE WHEN 1=1 THEN 1 ELSE 0 END; DROP TABLE users; END; SELECT 2;"
    assert SqlServerRegexParser().split_for_analysis(sql) == [
        "IF 1=1 BEGIN SELECT CASE WHEN 1=1 THEN 1 ELSE 0 END; DROP TABLE users; END;",
        "SELECT 2;",
    ]


def test_parse_refusal_reports_original_line_after_leading_blank_lines() -> None:
    parsed = SqlServerRegexParser().parse_sql("\n\nSELECT 1;\nGO;\n")
    assert any("line 4" in error for error in parsed.errors)


def test_analysis_preserves_tsql_parameters_and_unicode_literal_prefix() -> None:
    sql = "CREATE PROCEDURE p @MinPrice INT AS BEGIN SELECT N'x;y', @MinPrice; END"
    assert SqlServerRegexParser().split_for_analysis(sql) == [sql]


def test_begin_transaction_and_begin_block_have_distinct_boundaries() -> None:
    parser = SqlServerRegexParser()
    assert parser.split_for_analysis("BEGIN TRANSACTION; SELECT 1; COMMIT;") == [
        "BEGIN TRANSACTION;", "SELECT 1;", "COMMIT;"
    ]
    assert parser.split_for_analysis("BEGIN SELECT 1; SELECT 2; END;") == [
        "BEGIN SELECT 1; SELECT 2; END;"
    ]


@pytest.mark.parametrize("sql", ["SELECT 'a'\rGO", "SELECT [x]\rGO"])
def test_lone_carriage_return_before_go_in_code_is_refused(sql: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="lone carriage return"):
        SqlServerRegexParser().split_statements(sql)
