import pytest

from dblift.core.migration.sql.lint import lint_script
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts


@pytest.mark.parametrize(
    ("dialect", "path"), [("duckdb", "data.csv"), ("redshift", "s3://bucket/key")]
)
def test_copy_from_file_requires_review(dialect, path):
    sql = f"COPY t FROM '{path}'"
    result = lint_script(f"{sql};", dialect)
    facts = read_statement_facts(sql, dialect=dialect)

    assert result.verdict == "REVIEW"
    assert "copy-server-side" in [finding.code for finding in result.findings]
    assert facts.action == "copy-from-file"


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE STATISTICS dbo.t",
        "UPDATE STATISTICS [WITH]",
        "UPDATE STATISTICS dbo.t ix",
        "UPDATE STATISTICS dbo.t [WITH]",
        "UPDATE STATISTICS [dbo].[t] WITH FULLSCAN",
        "UPDATE STATISTICS dbo.t WITH SAMPLE 50 PERCENT",
    ],
)
def test_sqlserver_update_statistics_is_not_dml_without_where(sql):
    result = lint_script(f"{sql};", "sqlserver")
    facts = read_statement_facts(sql, dialect="tsql")

    assert result.verdict == "SAFE"
    assert "dml-no-where" not in [finding.code for finding in result.findings]
    assert facts.kind != "DML"
    assert facts.events is None


def test_sqlserver_update_without_where_remains_dml():
    result = lint_script("UPDATE dbo.t SET x = 1;", "sqlserver")
    facts = read_statement_facts("UPDATE dbo.t SET x = 1", dialect="tsql")

    assert result.verdict == "REVIEW"
    assert "dml-no-where" in [finding.code for finding in result.findings]
    assert facts.kind == "DML"
    assert facts.events == frozenset({"UPDATE"})


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE STATISTICS WITH",
        "UPDATE STATISTICS SET",
        "UPDATE STATISTICS UPDATE",
        "UPDATE STATISTICS DROP",
        "UPDATE STATISTICS dbo.WITH",
        "UPDATE STATISTICS dbo.t WITH",
        "UPDATE STATISTICS dbo.t SET",
        "UPDATE STATISTICS dbo.t UPDATE",
        "UPDATE STATISTICS dbo.t DROP",
        "UPDATE STATISTICS dbo.t WITH SAMPLE 150 PERCENT",
        "UPDATE STATISTICS dbo.t WITH FULLSCAN UPDATE t SET x = 1",
        "UPDATE STATISTICS dbo.t SET x = 1",
        "UPDATE STATISTICS dbo.t UPDATE t SET x = 1",
        "UPDATE STATISTICS dbo.t\nUPDATE t SET x = 1",
    ],
)
def test_sqlserver_unread_statistics_tail_requires_review(sql):
    result = lint_script(sql, "sqlserver")
    facts = read_statement_facts(sql, dialect="tsql")

    assert result.verdict == "REVIEW"
    assert facts.kind == "UNKNOWN"
    assert facts.events is None
    assert "dml-no-where" not in [finding.code for finding in result.findings]


def test_redshift_copy_expression_is_not_a_literal_file():
    facts = read_statement_facts("COPY t FROM '/tmp/' || 'data.csv'", dialect="redshift")

    assert facts.action is None


def test_duckdb_copy_query_export_keeps_query_facts():
    facts = read_statement_facts("COPY (SELECT id FROM t) TO 'out.csv'", dialect="duckdb")

    assert facts.kind == "QUERY"
    assert facts.events is None
    assert facts.action is None


def test_postgres_copy_from_file_keeps_existing_facts():
    facts = read_statement_facts("COPY t FROM 'data.csv'", dialect="postgres")

    assert facts.kind == "DML"
    assert facts.events == frozenset({"INSERT"})
    assert facts.action is None
