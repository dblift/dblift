"""Escape-string delimiters must not become execution statement boundaries."""

import pytest

from dblift.core.migration.sql.statement_splitter import StatementSplitter

pytestmark = pytest.mark.unit

POSTGRESQL_FAMILY = ["postgresql", "duckdb", "cockroachdb", "redshift"]


@pytest.mark.parametrize("dialect", POSTGRESQL_FAMILY)
@pytest.mark.parametrize(
    "literal",
    [r"E'it\'s; x'", r"e'it\'s; x'", r"E'a\\'", "E'it''s; x'"],
    ids=["escaped-quote", "lowercase", "escaped-backslash", "doubled-quote"],
)
def test_escape_string_keeps_internal_semicolon(dialect, literal):
    first = f"INSERT INTO t VALUES ({literal});"

    assert StatementSplitter(dialect).split_statements(first + " SELECT 2;") == [
        first,
        "SELECT 2;",
    ]


@pytest.mark.parametrize("dialect", ["mysql", "mariadb"])
def test_mysql_backslash_escaping_is_unchanged(dialect):
    assert StatementSplitter(dialect).split_statements(
        r"INSERT INTO t VALUES (E'it\'s; x'); SELECT 2;"
    ) == [r"INSERT INTO t VALUES (E'it\'s; x')", "SELECT 2"]


@pytest.mark.parametrize("dialect", ["postgresql", "duckdb", "cockroachdb"])
@pytest.mark.parametrize(
    "expression",
    [r"'C:\'", r"SOME'x\'", r"E 'x\'", r"B'x\'", r"U&'x\'", r"'E'"],
)
def test_standard_strings_do_not_gain_backslash_escapes(dialect, expression):
    statements = StatementSplitter(dialect).split_statements(f"SELECT {expression}; SELECT 2;")

    assert len(statements) == 2
    assert statements[0].endswith(expression[expression.index("'") :] + ";")
    assert statements[1] == "SELECT 2;"


@pytest.mark.parametrize("literal", [r"'it\'s; x'", r"'a\\'", "'it''s; x'", r"'C:\'; inside'"])
def test_redshift_plain_strings_use_backslash_escapes(literal):
    first = f"INSERT INTO t VALUES ({literal});"

    assert StatementSplitter("redshift").split_statements(first + " SELECT 2;") == [
        first,
        "SELECT 2;",
    ]


def test_redshift_escaped_final_quote_does_not_end_the_literal():
    sql = r"SELECT 'C:\'; SELECT 2;"

    # Leave the unterminated literal for the database to reject, rather than
    # inventing a statement boundary inside it.
    assert StatementSplitter("redshift").split_statements(sql) == [sql]


@pytest.mark.parametrize("dialect", ["postgresql", "cockroachdb", "redshift"])
@pytest.mark.parametrize("tag", ["$$", "$body$"])
def test_dollar_quoted_body_keeps_escape_strings_verbatim(dialect, tag):
    first = f"SELECT {tag}" + r"E'it\'s; x'; SELECT 'C:\';" + f"{tag};"

    assert StatementSplitter(dialect).split_statements(first + " SELECT 2;") == [
        first,
        "SELECT 2;",
    ]
