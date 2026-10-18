"""DuckDB replaces its Unicode blanks in one pass over the whole script before it parses.

The pass skips quoted text, line comments and dollar-quoted strings, knows no block comment, and ends
at a dollar tag or a quote that is never closed; from there a blank is a letter for the parser. Every
expectation here was measured with the Python driver (``extract_statements`` returns the text after
the pass, so the pass can be read directly) and the shell, which agree.
"""

import random

import duckdb
import pytest

from dblift.core.sql_parser.blank_pass import kept_stretches
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_RULES, DUCKDB_SPEC

ENGINE = LexicalEngine(DUCKDB_SPEC)
NB = chr(0xA0)
BLANKS = DUCKDB_RULES.blanks
FOLD = {ord(c): " " for c in BLANKS}
TAIL = " DROP TABLE t; SELECT 3;"

#: script, the statements DuckDB cuts (all accepted by the driver; the table t is dropped by the second)
CUTS = [
    ("SELECT 1 AS a$$, 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ("/* don't */ SELECT 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ('/* "q */ SELECT 2 AS e' + NB + "$t$x;" + TAIL, 3),
    ("/* $$ */ SELECT 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ("SELECT E'a\\'b' AS c, 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ("SELECT E'\\'' AS c, 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ("SELECT 1 AS a$$x$$$, 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ("/* $a$x$a$$b$ */ SELECT 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ("/* $" + NB + "$ */ SELECT 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ("/* $$ $$$ */ SELECT 2 AS e" + NB + "$t$x;" + TAIL, 3),
    ("SELECT 1 AS a$b$, 2 AS e" + NB + "$t$x;" + TAIL, 3),
    # after the stop every statement keeps its blanks as letters
    (
        "/* ' */ SELECT 1 AS e" + NB + "x; SELECT 2 AS f" + NB + "$t$y;" + TAIL + " SELECT 4 AS g",
        5,
    ),
    # a stretch the pass reads as a string holds code for the parser: its blanks are kept too
    ("/* it's */ SELECT 1 AS e" + NB + "$t$x;" + TAIL + " SELECT 'q'; SELECT 4;", 5),
]

#: scripts the pass does not stop on (DuckDB rejects the unterminated dollar string): one piece, as before
NO_STOP = [
    "SELECT 'a$$' AS a, 2 AS e" + NB + "$t$x;" + TAIL,
    'SELECT 1 AS "a$$", 2 AS e' + NB + "$t$x;" + TAIL,
    "-- $$\nSELECT 2 AS e" + NB + "$t$x;" + TAIL,
    "SELECT $$x$$ AS a, 2 AS e" + NB + "$t$x;" + TAIL,
    "/* $a$x$a$ */ SELECT 2 AS e" + NB + "$t$x;" + TAIL,
    "SELECT 1 AS a$1, 2 AS e" + NB + "$t$x;" + TAIL,
]


def cut(statements):
    return [s.translate(FOLD).strip().rstrip(";").strip() for s in statements]


@pytest.mark.parametrize("script,count", CUTS, ids=[str(i) for i in range(len(CUTS))])
def test_the_splitter_cuts_where_duckdb_does(script, count):
    ours = ENGINE.split_statements(script)
    theirs = [q.query for q in duckdb.extract_statements(script)]
    assert len(theirs) == count
    assert cut(ours) == cut(theirs)


@pytest.mark.parametrize("script", NO_STOP, ids=[str(i) for i in range(len(NO_STOP))])
def test_a_pass_that_has_not_stopped_leaves_the_script_as_one_piece(script):
    with pytest.raises(duckdb.Error):
        duckdb.extract_statements(script)
    assert len(ENGINE.split_statements(script)) == 1


def test_blanks_before_the_stop_end_a_word():
    script = "SELECT 1 AS a" + NB + "$t$x; SELECT 2;"
    assert len(ENGINE.split_statements(script)) == 1  # a dollar string opens, as DuckDB reads it
    with pytest.raises(duckdb.Error):
        duckdb.extract_statements(script)


def stretches(script):
    last = max(script.rfind(b) for b in BLANKS)
    return kept_stretches(script, 0, last, DUCKDB_RULES.line_comment_ends, DUCKDB_RULES.blank_pass)


def predicted(script):
    """The script after the pass, from the stretches."""
    found = stretches(script)
    out = []
    for at, char in enumerate(script):
        kept = any(found[i] <= at < found[i + 1] for i in range(0, len(found), 2))
        out.append(" " if char in BLANKS and char >= "\x80" and not kept else char)
    return "".join(out)


def test_the_stretches_are_the_text_duckdb_keeps():
    rng = random.Random(7)
    pieces = ["$", "$$", "$a$", "a", "1", "'", '"', "-", "--", NB, chr(0x3000), "\n", "\r", ";", "é", " "]
    compared = 0
    for _ in range(4000):
        body = "".join(rng.choice(pieces) for _ in range(rng.randint(1, 12)))
        script = "/*" + body + "*/ SELECT 1 AS x   "
        try:
            theirs = ";".join(q.query for q in duckdb.extract_statements(script))
        except duckdb.Error:
            continue
        compared += 1
        assert predicted(script) == theirs, ascii(script)
    assert compared > 3000


def test_stretches_are_quoted_text_comments_failed_tags_and_the_rest_after_a_stop():
    assert stretches("SELECT 'a', 2" + NB) == [7, 10]
    assert stretches("SELECT 'a'" + NB + " 'b" + NB) == [7, 10, 12, 15]
    assert stretches("SELECT 1 -- c" + NB + "\n" + NB) == [9, 14]
    assert stretches("SELECT a$b" + NB + "c" + NB) == [8, 13]
    assert stretches("SELECT a$$ " + NB) == [8, 12]
