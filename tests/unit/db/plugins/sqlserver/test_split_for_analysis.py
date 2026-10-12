"""A caller that reads a T-SQL script statement by statement gets the batches divided."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.db.plugins.sqlserver.parser.sqlserver_regex_parser import SqlServerRegexParser

SCRIPT = (
    "DECLARE @x INT = 1;\n"
    "SELECT @x;\n"
    "GO\n"
    "CREATE TABLE a (id INT);\n"
    "CREATE INDEX ix_a ON a (id);\n"
)


def test_analysis_divides_each_batch_into_its_statements():
    analyzer = SqlAnalyzer("sqlserver")
    assert len(analyzer.split_statements(SCRIPT)) == 2
    assert analyzer.split_statements_for_analysis(SCRIPT) == [
        "DECLARE @x INT = 1;",
        "SELECT @x;",
        "CREATE TABLE a (id INT);",
        "CREATE INDEX ix_a ON a (id);",
    ]


def test_analysis_does_not_repeat_a_batch_that_go_n_repeats():
    analyzer = SqlAnalyzer("sqlserver")
    script = "INSERT INTO t VALUES (1);\nINSERT INTO t VALUES (2);\nGO 3\n"
    assert len(analyzer.split_statements(script)) == 3
    assert analyzer.split_statements_for_analysis(script) == [
        "INSERT INTO t VALUES (1);",
        "INSERT INTO t VALUES (2);",
    ]


@pytest.mark.parametrize("script", ["SELECT 1\nGO;\n", "SELECT 'abc\nGO\n", "SELECT 1\nGO 5x\n"])
def test_analysis_refuses_what_execution_refuses(script):
    with pytest.raises(UnsafeStatementSplitError):
        SqlAnalyzer("sqlserver").split_statements_for_analysis(script)


def test_other_dialects_analyse_each_executed_constituent():
    script = "CREATE TABLE a (x INT);\nCREATE TABLE b (y INT);\n"
    for dialect in ("postgresql", "mysql", "sqlite", "oracle"):
        analyzer = SqlAnalyzer(dialect)
        assert [
            statement.rstrip(";") for statement in analyzer.split_statements_for_analysis(script)
        ] == ["CREATE TABLE a (x INT)", "CREATE TABLE b (y INT)"]


def test_a_batch_that_go_zero_never_runs_is_not_analysed_either():
    script = "INSERT INTO t VALUES (1);\nGO 0\nSELECT 2;\n"
    assert SqlAnalyzer("sqlserver").split_statements_for_analysis(script) == ["SELECT 2;"]


def test_the_undo_fallback_reverses_each_statement_of_a_batch():
    from dblift.core.logger import DbliftLogger
    from dblift.core.migration.sql.migration_sql_parser import parse_migration_sql

    analyzer = SqlAnalyzer("sqlserver")
    script = "CREATE TABLE a (id INT);\nCREATE TABLE b (id INT);\n"
    log = DbliftLogger()
    assert len(parse_migration_sql(analyzer, script, log)) == 1
    assert len(parse_migration_sql(analyzer, script, log, for_analysis=True)) == 2


def test_validate_sql_counts_statements_not_batches():
    parser = SqlServerRegexParser()
    assert parser.validate_sql("SELECT 1; SELECT 2;") == {
        "valid": True,
        "statements_found": 2,
        "errors": [],
    }
    assert parser.validate_sql("SELECT 1\nGO;\n")["valid"] is False
