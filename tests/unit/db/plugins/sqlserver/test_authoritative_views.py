import subprocess
import sys

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.statement_reader import StatementReader
from tests.support.facts_parser import facts_parser


def test_batch_analysis_keeps_literals_comments_and_procedure_body_intact() -> None:
    sql = (
        "SELECT 'a;b'; /* ; */ SELECT 2;\nGO\n"
        "CREATE PROCEDURE dbo.p AS\n"
        "BEGIN\n"
        "  SELECT 1;\n"
        "  SELECT 2;\n"
        "END;\nGO\n"
    )

    parser = facts_parser("sqlserver")

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
    parser = facts_parser("sqlserver")
    assert parser.split_for_analysis(first + " SELECT 2;") == [first, "SELECT 2;"]


def test_case_end_does_not_close_a_begin_block() -> None:
    sql = "IF 1=1 BEGIN SELECT CASE WHEN 1=1 THEN 1 ELSE 0 END; DROP TABLE users; END; SELECT 2;"
    assert facts_parser("sqlserver").split_for_analysis(sql) == [
        "IF 1=1 BEGIN SELECT CASE WHEN 1=1 THEN 1 ELSE 0 END; DROP TABLE users; END;",
        "SELECT 2;",
    ]


def test_parse_refusal_reports_original_line_after_leading_blank_lines() -> None:
    parsed = facts_parser("sqlserver").parse_sql("\n\nSELECT 1;\nGO;\n")
    assert any("line 4" in error for error in parsed.errors)


def test_analysis_preserves_tsql_parameters_and_unicode_literal_prefix() -> None:
    sql = "CREATE PROCEDURE p @MinPrice INT AS BEGIN SELECT N'x;y', @MinPrice; END"
    assert facts_parser("sqlserver").split_for_analysis(sql) == [sql]


def test_begin_transaction_and_begin_block_have_distinct_boundaries() -> None:
    parser = facts_parser("sqlserver")
    assert parser.split_for_analysis("BEGIN TRANSACTION; SELECT 1; COMMIT;") == [
        "BEGIN TRANSACTION;",
        "SELECT 1;",
        "COMMIT;",
    ]
    assert parser.split_for_analysis("BEGIN SELECT 1; SELECT 2; END;") == [
        "BEGIN SELECT 1; SELECT 2; END;"
    ]


def test_alter_table_clause_on_next_line_stays_with_its_statement() -> None:
    sql = "ALTER TABLE users\nDROP COLUMN legacy_flag;"
    assert facts_parser("sqlserver").split_for_analysis(sql) == [sql]


@pytest.mark.parametrize(
    "clause",
    ["DROP COLUMN legacy_flag", "DROP CONSTRAINT old_key", "ALTER COLUMN name VARCHAR(50)"],
)
def test_multiline_alter_table_clauses_stay_whole(clause: str) -> None:
    sql = f"ALTER TABLE users\n{clause};"
    assert StatementReader("sqlserver").split_statements_for_analysis(sql) == [sql]


def test_standalone_drop_after_unterminated_alter_table_is_visible_to_analysis() -> None:
    sql = "ALTER TABLE users ADD display_name VARCHAR(50)\nDROP TABLE victims;"
    assert StatementReader("sqlserver").split_statements_for_analysis(sql) == [
        "ALTER TABLE users ADD display_name VARCHAR(50)",
        "DROP TABLE victims;",
    ]
    analysis = analyse_script(sql, "sqlserver")
    assert [statement.operation for statement in analysis.statements] == ["ALTER", "DROP"]
    assert any(caution.level == "destroys" for caution in analysis.cautions)


def test_many_single_line_ddl_words_have_bounded_analysis_cost() -> None:
    probe = (
        "from tests.support.facts_parser import facts_parser\n"
        "facts_parser('sqlserver').split_for_analysis('SELECT 1 ' + 'DROP ' * 100000)\n"
    )
    try:
        subprocess.run([sys.executable, "-c", probe], check=True, timeout=10)
    except subprocess.TimeoutExpired:
        pytest.fail("single-line batch analysis exceeded the 10-second bound")


@pytest.mark.parametrize("sql", ["SELECT 'a'\rGO", "SELECT [x]\rGO"])
def test_lone_carriage_return_before_go_in_code_is_refused(sql: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match="lone carriage return"):
        facts_parser("sqlserver").split_statements(sql)


def test_batch_records_cover_original_client_control_lines_and_bom() -> None:
    script = "\ufeff SELECT 1;\nGO 0 -- skipped\nSELECT 2;\nGO 2\n"
    records = facts_parser("sqlserver").split(script)
    assert [script[record.source_start : record.source_end] for record in records] == [
        " SELECT 1;\nGO 0 -- skipped\n",
        "SELECT 2;\nGO 2\n",
    ]
    assert [record.repeat for record in records] == [0, 2]
