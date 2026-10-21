"""A name inside a block comment is never read: the head reader blanks comments as the engine does.

PostgreSQL, Redshift and DuckDB nest block comments (``/* a /* b */ c */`` is one comment);
MySQL, MariaDB and Oracle end one at the first ``*/``. The trailing ``BOGUS (`` keeps each
statement out of the full grammar so the head reader is the one that names the target.
"""

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts

NESTING = ["postgres", "redshift", "duckdb"]
FLAT = ["mysql", "oracle"]


def _names(sql, dialect):
    facts = read_statement_facts(sql, dialect=dialect)
    return tuple(o.name.lower() for o in facts.objects), facts


@pytest.mark.parametrize("dialect", NESTING)
@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO /* a /* b */ c */ t VALUES (1) BOGUS (",
        "DROP TABLE /* a /* b */ c */ t BOGUS (",
        "UPDATE /* a /* b */ c */ t SET a = 1 BOGUS (",
    ],
)
def test_nested_comment_hides_the_name_it_contains(sql, dialect):
    objects, _ = _names(sql, dialect)
    assert "c" not in objects
    assert "t" in objects


@pytest.mark.parametrize("dialect", FLAT)
def test_flat_comment_ends_at_the_first_close(dialect):
    # The comment ends at the first ``*/``: ``c`` is the table and ``*/ t`` is trailing text.
    objects, _ = _names("DROP TABLE /* a /* b */ c BOGUS (", dialect)
    assert "c" in objects


@pytest.mark.parametrize(
    "sql, unread",
    [
        ("CREATE TABLE t (a int REFERENCES [p](id))", "p"),
        ("ALTER TABLE t RENAME TO [x]", "x"),
        ("CREATE TABLE t (LIKE [s])", "s"),
        ("CREATE TABLE t (a int, FOREIGN KEY (a) REFERENCES [p](id))", "p"),
        ("DROP TABLE a, [b]", "b"),
    ],
)
def test_redshift_bracketed_name_outside_the_guard_is_never_misread(sql, unread):
    # Redshift drops the brackets, so ``[p]`` is ``p``. Where the guard does not look, the grammar
    # refuses the statement: the reader must carry a diagnostic and never put ``[p]`` in a name.
    facts = read_statement_facts(sql, dialect="redshift")
    assert facts.diagnostic
    assert all("[" not in o.name and o.name != unread for o in facts.objects)


def test_redshift_bracketed_name_after_a_name_is_still_a_subscript():
    facts = read_statement_facts("SELECT a[0] FROM t", dialect="redshift")
    assert facts.diagnostic is None
    assert [o.name for o in facts.objects] == ["t"]


@pytest.mark.parametrize("dialect", NESTING + ["tsql"])
def test_unterminated_nested_comment_is_an_error_not_an_empty_statement(dialect):
    # Blanked with the engine's nesting, the whole text is one open comment and nothing remains:
    # that must stay the tokenizer error, not read as a statement with nothing in it.
    facts = read_statement_facts("/* a /* b */ DROP TABLE x;", dialect=dialect)
    assert facts.error
