"""A DuckDB dollar-quoted string is a string literal: masking replaces it, whatever it holds."""

import pytest

from dblift.core.sql_parser.redaction import mask_string_literals

SECRET = "hunter2"

#: (statement, what the engine reads the quoted part as)
READ_AS_ONE_STRING = [
    ("SELECT $$hunter2$$", "hunter2"),
    ("SELECT $t$hunter2$t$", "hunter2"),
    ("SELECT $$it's hunter2$$", "it's hunter2"),
    ('SELECT $$say "hunter2"$$', 'say "hunter2"'),
    ("SELECT $$line one\nhunter2$$", "line one\nhunter2"),
    ("SELECT $Tag_1$hunter2$Tag_1$", "hunter2"),
    ("SELECT $_$hunter2$_$", "hunter2"),
    ("SELECT $é$hunter2$é$", "hunter2"),
    ("SELECT $a$ $b$ $a$", " $b$ "),
    ("SELECT $a$hunter2; DROP TABLE t; $a$", "hunter2; DROP TABLE t; "),
]


@pytest.mark.parametrize("sql,value", READ_AS_ONE_STRING)
def test_the_engine_reads_the_shape_as_one_string(sql, value):
    duckdb = pytest.importorskip("duckdb")
    assert duckdb.connect().execute(sql).fetchall() == [(value,)]


@pytest.mark.parametrize("sql,value", READ_AS_ONE_STRING)
def test_a_dollar_quoted_string_is_masked(sql, value):
    assert mask_string_literals(sql, "duckdb") == "SELECT '?'"


def test_secret_never_survives_next_to_other_literals():
    sql = "INSERT INTO t VALUES ('a', $k$hunter2$k$, 3, $$it's$$)"
    assert mask_string_literals(sql, "duckdb") == "INSERT INTO t VALUES ('?', '?', 3, '?')"


def test_a_positional_parameter_is_not_a_quote():
    assert mask_string_literals("SELECT $1, $name, 'x' FROM t WHERE a = $2", "duckdb") == (
        "SELECT $1, $name, '?' FROM t WHERE a = $2"
    )


def test_an_unterminated_dollar_quote_is_masked_to_the_end():
    # The engine rejects the statement; the rest of the text is still the quoted value.
    masked = mask_string_literals("SELECT $x$ hunter2; SELECT 'y'", "duckdb")
    assert masked == "SELECT '?'"
    assert SECRET not in masked


@pytest.mark.parametrize("dialect", ["mysql", "sqlite"])
def test_engines_without_dollar_quotes_keep_the_text(dialect):
    assert mask_string_literals("SELECT $t$hunter2$t$", dialect) == "SELECT $t$hunter2$t$"


def test_postgresql_masks_the_same_shape():
    assert mask_string_literals("SELECT $t$hunter2$t$", "postgresql") == "SELECT '?'"


@pytest.mark.parametrize(
    "sql,masked",
    [
        ("SELECT \"x, 'hunter2'", "SELECT '?'"),
        ("INSERT INTO t VALUES (\"a\"\", 'hunter2')", "INSERT INTO t VALUES ('?'"),
        ("SELECT 1 /* open 'hunter2'", "SELECT 1 '?'"),
        ("SELECT 'a' /* open\n 'hunter2'", "SELECT '?' '?'"),
    ],
)
def test_an_unclosed_name_or_comment_hides_nothing_after_it(sql, masked):
    assert mask_string_literals(sql, "duckdb") == masked


def test_closed_names_and_comments_are_kept():
    sql = "SELECT \"a'b\", \"c\"\"d\" /* it's 'fine' */ FROM t -- 'x'"
    assert mask_string_literals(sql, "duckdb") == sql
