"""Statement boundaries around block comments match SQL*Plus.

Oracle block comments do not nest: in ``/* outer /* inner */ DROP t; */`` the
first ``*/`` closes the comment, so ``DROP t;`` is live text followed by a
stray ``*/``. SQL*Plus only ends a statement at a ``;`` that is the last
thing on its line, so it never sends ``DROP t`` on its own. Observed with
SQL*Plus against Oracle Free 23.26 (``SET ECHO ON``, then ``user_tables``):

* ``/* outer /* inner */ DROP TABLE keep_me; */`` plus the next line
  ``CREATE TABLE after_comment (id NUMBER);`` is buffered as one statement,
  ``DROP TABLE keep_me; */`` + newline + ``CREATE TABLE after_comment (id
  NUMBER)``. The server rejects it with ORA-03405 at the ``;``: ``keep_me``
  survives and ``after_comment`` is not created.
* ``CREATE TABLE yc (id NUMBER); */`` joins the following lines up to the
  next line ending in ``;`` and is rejected the same way.
* ``CREATE TABLE n1 (id NUMBER); */ CREATE TABLE n2 (id NUMBER);`` is one
  statement and is rejected.
* After such a line, a later line ``CREATE TABLE p2 (...); CREATE TABLE p3
  (...);`` is still part of the same rejected statement: p3 is not run.
* ``/* c */ DROP TABLE xa;`` and ``/* outer /* inner */ CREATE TABLE o1 (id
  NUMBER);`` run normally (the leading comment ends before the statement).
* A comment spanning lines, with ``DROP TABLE m1;`` on a line of its own
  inside it, runs nothing.

dblift must never run a statement SQL*Plus would not, so these cases split
exactly as SQL*Plus buffers them.

SQL*Plus is stricter still: ``DROP TABLE x; /* trailing */``, ``DROP TABLE
x; -- trailing`` and ``a; b;`` on one line are also not terminated at the
first ``;`` there. dblift keeps splitting those, where the text after the
``;`` is only comments or complete statements; the tests pin that as well.
"""

from __future__ import annotations

import pytest

from dblift.db.plugins.oracle.parser._plsql_block import extract_plsql_block
from dblift.db.plugins.oracle.parser._statement_splitter import split_statements_regex
from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser

NESTED = (
    "CREATE TABLE keep_me (id NUMBER);\n"
    "/* outer /* inner */ DROP TABLE keep_me; */\n"
    "CREATE TABLE after_comment (id NUMBER);\n"
)

# (source, statements SQL*Plus sends / dblift must produce)
FAITHFUL_CASES = {
    "nested_comment_hides_nothing": (
        NESTED,
        [
            "CREATE TABLE keep_me (id NUMBER);",
            "DROP TABLE keep_me; */\nCREATE TABLE after_comment (id NUMBER);",
        ],
    ),
    "leading_comment_then_statement": (
        "/* c */ DROP TABLE xa;\n",
        ["DROP TABLE xa;"],
    ),
    "nested_leading_comment_then_statement": (
        "/* outer /* inner */ CREATE TABLE o1 (id NUMBER);\n",
        ["CREATE TABLE o1 (id NUMBER);"],
    ),
    "stray_close_after_statement": (
        "CREATE TABLE yc (id NUMBER); */\nCREATE TABLE after_c (id NUMBER);\n",
        ["CREATE TABLE yc (id NUMBER); */\nCREATE TABLE after_c (id NUMBER);"],
    ),
    "stray_close_then_statement_same_line": (
        "CREATE TABLE n1 (id NUMBER); */ CREATE TABLE n2 (id NUMBER);\n",
        ["CREATE TABLE n1 (id NUMBER); */ CREATE TABLE n2 (id NUMBER);"],
    ),
    "continuation_ends_only_at_line_final_semicolon": (
        "CREATE TABLE p1 (id NUMBER); */\n"
        "CREATE TABLE p2 (id NUMBER); CREATE TABLE p3 (id NUMBER);\n"
        "CREATE TABLE p4 (id NUMBER);\n",
        [
            "CREATE TABLE p1 (id NUMBER); */\n"
            "CREATE TABLE p2 (id NUMBER); CREATE TABLE p3 (id NUMBER);",
            "CREATE TABLE p4 (id NUMBER);",
        ],
    ),
    "multiline_comment_runs_nothing": (
        "/* start\nDROP TABLE m1;\n*/\nCREATE TABLE m2 (id NUMBER);\n",
        ["CREATE TABLE m2 (id NUMBER);"],
    ),
}

# SQL*Plus rejects these; dblift keeps splitting them (see module docstring).
LENIENT_CASES = {
    "trailing_block_comment": (
        "DROP TABLE xb; /* trailing */\nCREATE TABLE after_b (id NUMBER);\n",
        ["DROP TABLE xb;", "CREATE TABLE after_b (id NUMBER);"],
    ),
    "trailing_line_comment": (
        "DROP TABLE xf; -- trailing\nCREATE TABLE after_f (id NUMBER);\n",
        ["DROP TABLE xf;", "CREATE TABLE after_f (id NUMBER);"],
    ),
    "two_statements_one_line": (
        "CREATE TABLE d1 (id NUMBER); CREATE TABLE d2 (id NUMBER);\n",
        ["CREATE TABLE d1 (id NUMBER);", "CREATE TABLE d2 (id NUMBER);"],
    ),
}

ALL_CASES = {**FAITHFUL_CASES, **LENIENT_CASES}


def _normalise(statements):
    """Drop the terminating ``;`` so both split paths compare alike."""
    return [s[:-1].rstrip() if s.endswith(";") else s for s in statements]


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_tokenizer_split_matches_sqlplus(name):
    source, expected = ALL_CASES[name]
    assert OracleParser().split_statements(source) == expected


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(ALL_CASES))
def test_regex_split_matches_sqlplus(name):
    source, expected = ALL_CASES[name]
    statements = split_statements_regex(source, extract_plsql_block=extract_plsql_block)
    assert _normalise(statements) == _normalise(expected)


@pytest.mark.unit
def test_nested_comment_never_yields_a_bare_drop():
    for statements in (
        OracleParser().split_statements(NESTED),
        split_statements_regex(NESTED, extract_plsql_block=extract_plsql_block),
    ):
        assert not any(s.rstrip(";").strip() == "DROP TABLE keep_me" for s in statements)


@pytest.mark.unit
def test_close_marker_inside_string_is_not_stray():
    source = "INSERT INTO t VALUES ('*/');\nCREATE TABLE z (id NUMBER);\n"
    assert OracleParser().split_statements(source) == [
        "INSERT INTO t VALUES ('*/');",
        "CREATE TABLE z (id NUMBER);",
    ]
