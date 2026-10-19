"""DuckDB replaces its Unicode blanks in one pass over the whole script before it parses.

The pass skips quoted text, line comments and dollar-quoted strings, knows no block comment, and ends
at a dollar tag or a quote that is never closed; from there a blank is a letter for the parser. Every
expectation here was measured with the Python driver (``extract_statements`` returns the text after
the pass, so the pass can be read directly) and the shell, which agree.
"""

import random

import duckdb
import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
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
    pieces = [
        "$",
        "$$",
        "$a$",
        "a",
        "1",
        "'",
        '"',
        "-",
        "--",
        NB,
        chr(0x3000),
        "\n",
        "\r",
        ";",
        "é",
        " ",
    ]
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


#: scripts whose second piece holds a blank the pass kept in the script and would replace in the piece alone
ALONE = [
    "SELECT 1 AS a$$; DROP TABLE t" + NB + "CASCADE;",
    "/* ' */ SELECT 1; DROP TABLE t" + NB + "CASCADE;",
    "SELECT 1 AS a$t$; DROP TABLE t" + NB + "CASCADE; SELECT 2 AS b$t$;",
    "SELECT 1 AS a$$; DROP TABLE t" + NB + "CASCADE; SELECT 2 AS b$$;",
]


def run_whole(script):
    con = duckdb.connect()
    con.execute("CREATE TABLE t (i INT)")
    try:
        con.execute(script)
    except duckdb.Error:
        pass
    return con


def has_t(con):
    return (
        con.execute("SELECT count(*) FROM duckdb_tables() WHERE table_name = 't'").fetchone()[0]
        == 1
    )


#: after the stop every statement keeps its blanks as letters, so the engine accepts these scripts; a
#: later statement that does not stop the pass by itself reads differently alone, and is refused
ACCEPTED_BY_THE_ENGINE = [
    "/* ' */ SELECT 1 AS e" + NB + "x; SELECT 2 AS f" + NB + "$t$y;" + TAIL + " SELECT 4 AS g",
]


@pytest.mark.parametrize("script", ACCEPTED_BY_THE_ENGINE, ids=["0"])
def test_a_script_the_engine_accepts_is_refused_when_a_statement_reads_differently_alone(script):
    assert len(duckdb.extract_statements(script)) == 5
    with pytest.raises(UnsafeStatementSplitError, match=r"U\+00A0 at line 1, column \d+"):
        ENGINE.split_statements(script)


@pytest.mark.parametrize("script", ALONE, ids=[str(i) for i in range(len(ALONE))])
def test_a_statement_that_reads_differently_alone_is_refused(script):
    assert has_t(run_whole(script))  # the engine rejects the script and the table stays
    at = script.index(NB)
    for split in (ENGINE.split_statements, ENGINE.split, ENGINE.split_for_analysis):
        with pytest.raises(UnsafeStatementSplitError) as raised:
            split(script)
        message = str(raised.value)
        assert f"U+00A0 at line 1, column {at + 1}" in message
        assert "kept in its script, replaced when run alone" in message
        assert message.endswith("remove the character")


def test_a_refusal_names_the_line_and_column_of_the_blank():
    script = "SELECT 1 AS a$$;\n\nSELECT 2\n  FROM t" + NB + "x;"
    with pytest.raises(UnsafeStatementSplitError, match=r"U\+00A0 at line 4, column 9"):
        ENGINE.split_statements(script)


def test_a_kept_blank_that_the_statement_alone_keeps_too_is_not_refused():
    # the unclosed tag is inside the same piece: run alone, the pass stops at it as well
    prefixed = "SELECT 1 AS a$$, 2 AS e" + NB + "$t$x; DROP TABLE t; SELECT 3;"
    pieces = ENGINE.split_statements(prefixed)
    assert len(pieces) == 3 and len(duckdb.extract_statements(prefixed)) == 3
    whole, split = run_whole(prefixed), duckdb.connect()
    split.execute("CREATE TABLE t (i INT)")
    for piece in pieces:
        split.execute(piece)
    assert not has_t(whole) and not has_t(split)


def test_a_kept_blank_in_the_unread_tail_of_a_statement_is_not_refused():
    # alone, the pass never reads the last two bytes, so a final U+00A0 is kept there as well
    script = "/* ' */ SELECT 1 AS e" + NB + "; SELECT 2;"
    assert len(ENGINE.split_statements(script)) == 2


def test_a_line_comment_ends_at_a_carriage_return_for_the_pass():
    script = "-- x\rSELECT 1 AS a$$, 2 AS e" + NB + "$t$x; DROP TABLE t; SELECT 3;"
    pieces = ENGINE.split_statements(script)
    assert len(pieces) == len(duckdb.extract_statements(script)) == 3
    con = duckdb.connect()
    con.execute("CREATE TABLE t (i INT)")
    for piece in pieces:
        con.execute(piece)
    assert not has_t(con) and not has_t(run_whole(script))


#: a final U+00A0 of a statement that the pass of the script replaces (the script goes on after it)
#: and the pass of the statement alone would keep, because it never reads the last two bytes of a
#: text: the statement is sent without it, as the engine reads the script, so nothing differs
KEPT_ALONE = [
    "DROP TABLE IF EXISTS t" + NB + "; SELECT 1;",
    "DROP TABLE IF EXISTS t" + NB + " ; SELECT 1;",
    "SELECT 1 AS x" + NB + "; SELECT 2;",
    "SELECT 1 AS a " + NB + "; SELECT -- '\n$t$\ra$b-- c$\né e $t$x; DROP TABLE t; SELECT 3;",
]


@pytest.mark.parametrize("script", KEPT_ALONE, ids=[str(i) for i in range(len(KEPT_ALONE))])
def test_a_final_blank_kept_alone_and_replaced_in_the_script_is_trimmed_not_refused(script):
    pieces = ENGINE.split_statements(script)
    assert len(pieces) == len(duckdb.extract_statements(script))
    assert pieces[0] == script[: script.index(NB)].rstrip(" ")
    assert tables(run_pieces(pieces)) == tables(whole(script))


@pytest.mark.parametrize(
    "script",
    ["SELECT 1 AS e" + NB, "/* ' */ SELECT 1 AS e" + NB, "SELECT 1;　"],
    ids=["script-end", "script-end-kept-stretch", "wide-after"],
)
def test_a_final_blank_kept_in_the_script_as_well_is_not_refused(script):
    assert len(ENGINE.split_statements(script)) == 1


#: a piece whose own pass stops where the script's pass does not: an opener inside a comment (or a word)
#: closes, for the script, a stretch opened in an earlier piece; the blank after it is replaced there
#: and kept when the piece is run alone (or the reverse)
OPPOSITE = [
    (
        "SELECT 1 AS a$t$; /* $t$ */ DROP TABLE IF EXISTS t" + NB + "CASCADE;",
        "replaced in its script",
    ),
    (
        "SELECT 1 AS a$$; /* $$ */ DROP TABLE IF EXISTS t" + NB + "CASCADE;",
        "replaced in its script",
    ),
    (
        "/* ' */ SELECT 1; /* ' */ DROP TABLE IF EXISTS t" + NB + "CASCADE;",
        "replaced in its script",
    ),
    (
        '/* " */ SELECT 1; /* " */ DROP TABLE IF EXISTS t' + NB + "CASCADE;",
        "replaced in its script",
    ),
    (
        "SELECT 1 AS a$t$;\n/* $t$ */ DROP TABLE IF EXISTS t" + chr(0x3000) + "CASCADE;",
        "replaced in its script",
    ),
    (
        "/* it's */ SELECT 1; /* don't */ CREATE TABLE x(a INT," + NB + "b INT);",
        "replaced in its script",
    ),
    (
        "/* ' */ SELECT 1 AS x" + NB + "y; /* ' */ SELECT 1 AS x" + NB + "y; DROP TABLE t;",
        "replaced in its script",
    ),
]


@pytest.mark.parametrize("script,how", OPPOSITE, ids=[str(i) for i in range(len(OPPOSITE))])
def test_a_blank_kept_in_one_reading_and_replaced_in_the_other_is_refused(script, how):
    at = next(i for i, c in enumerate(script) if c >= "\x80")
    for split in (ENGINE.split_statements, ENGINE.split, ENGINE.split_for_analysis):
        with pytest.raises(UnsafeStatementSplitError) as raised:
            split(script)
        message = str(raised.value)
        assert f"U+{ord(script[at]):04X} at line {script.count(chr(10), 0, at) + 1}" in message
        assert how in message and message.endswith("remove the character")


def test_the_engine_drops_the_table_the_piece_alone_would_not_name():
    script = OPPOSITE[0][0]
    assert not has_t(run_whole(script))
    alone = duckdb.connect()
    alone.execute("CREATE TABLE t (i INT)")
    alone.execute("/* $t$ */ DROP TABLE IF EXISTS t" + NB + "CASCADE")
    assert has_t(alone)


def run_pieces(pieces):
    con = duckdb.connect()
    setup(con)
    for piece in pieces:
        con.execute(piece)
    return con


def setup(con):
    con.execute("CREATE TABLE t (i INT)")
    con.execute(f'CREATE TABLE "t{NB}" (i INT)')


def tables(con):
    return sorted(r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall())


def whole(script):
    con = duckdb.connect()
    setup(con)
    con.execute(script)
    return con


#: a blank at the edge of a statement that the script's pass replaces is trimmed, so the text sent
#: equals the engine's reading of the script: nothing is read differently, nothing is refused
EDGE_REPLACED = [
    ("DROP TABLE t" + NB + ";\nSELECT 1;", ["DROP TABLE t", "SELECT 1"]),
    ("DROP TABLE t" + NB + "\n\n", ["DROP TABLE t"]),
    ("DROP TABLE t" + NB + " ", ["DROP TABLE t"]),
    ("DROP TABLE IF EXISTS t" + NB + "; SELECT 1;", ["DROP TABLE IF EXISTS t", "SELECT 1"]),
    ("DROP TABLE IF EXISTS t" + NB + " ; SELECT 1;", ["DROP TABLE IF EXISTS t", "SELECT 1"]),
    ("SELECT 1 AS x" + NB + "; SELECT 2;", ["SELECT 1 AS x", "SELECT 2"]),
]


@pytest.mark.parametrize(
    "script,sent", EDGE_REPLACED, ids=[str(i) for i in range(len(EDGE_REPLACED))]
)
def test_an_edge_blank_the_script_replaces_is_trimmed_and_nothing_is_refused(script, sent):
    assert ENGINE.split_statements(script) == sent
    assert [s.text for s in ENGINE.split(script)] == sent


def test_an_edge_blank_the_script_replaces_runs_the_statement_the_engine_runs():
    script = "DROP TABLE t" + NB + ";\nSELECT 1;"
    assert (
        tables(run_pieces(ENGINE.split_statements(script))) == tables(whole(script)) == ["t" + NB]
    )


#: the driver replaces the blank before the final line ending and the shell, which removes that line
#: ending first, keeps it as part of the name: the two read the script differently
DRIVER_AND_SHELL_DISAGREE = [
    "DROP TABLE t" + NB + "\n",
    "DROP TABLE t" + NB + "\r\n",
    "SELECT 1 AS e" + NB + "\n",
]


@pytest.mark.parametrize("script", DRIVER_AND_SHELL_DISAGREE, ids=["lf", "crlf", "alias"])
def test_a_final_blank_before_the_last_line_ending_is_refused_as_the_shell_reads_it_differently(
    script,
):
    for split in (ENGINE.split_statements, ENGINE.split, ENGINE.split_for_analysis):
        with pytest.raises(UnsafeStatementSplitError, match=r"U\+00A0 at line 1, column 13?"):
            split(script)


@pytest.mark.parametrize(
    "script",
    [
        "DROP TABLE t" + NB + "\n\n",  # the shell removes one line ending only
        "DROP TABLE t" + NB + " \n",
        "DROP TABLE t" + NB + "\r",
        "/* ' */ DROP TABLE t" + NB + "\n",  # kept in the script: the shell keeps it too
        "DROP TABLE t;" + NB + "\n",  # the tail carries no statement
    ],
    ids=["two-line-endings", "space-between", "lone-cr", "kept-in-script", "tail"],
)
def test_a_blank_the_driver_and_the_shell_read_alike_is_not_refused(script):
    assert ENGINE.split_statements(script)


#: the engine keeps a final U+00A0 and reads it as a statement of its own that does not parse: the
#: driver rejects the whole script, so the stray blank is refused instead of dropped
STRAY_TAIL = [
    "SELECT 1;" + NB,
    "DROP TABLE t;" + NB + NB,
    "DROP TABLE t;\n" + NB,
    "DROP TABLE t; /* c */" + NB,
    "DROP TABLE t; -- c\n" + NB,
]


@pytest.mark.parametrize("script", STRAY_TAIL, ids=[str(i) for i in range(len(STRAY_TAIL))])
def test_a_stray_no_break_space_after_the_last_statement_is_refused_as_the_driver_rejects_it(
    script,
):
    with pytest.raises(duckdb.ParserException):
        whole(script)
    line = script.count("\n") + 1
    column = len(script) - script.rfind("\n") - 1 if "\n" in script else len(script)
    for split in (ENGINE.split_statements, ENGINE.split, ENGINE.split_for_analysis):
        with pytest.raises(UnsafeStatementSplitError) as raised:
            split(script)
        assert f"U+00A0 at line {line}, column {column}" in str(raised.value)
        assert str(raised.value).endswith("remove the character")


@pytest.mark.parametrize(
    "script",
    [
        "DROP TABLE t;" + NB + "\n",  # the pass replaces it: the driver accepts the script
        "SELECT 1;　",
        "SELECT 1; -- c" + NB,  # inside a comment
        "SELECT 1; /* c" + NB + "*/",
        "DROP TABLE t" + NB,  # the final blank of a statement is a character of its name (row 90a)
        "/* ' */ SELECT 1 AS e" + NB,
    ],
    ids=["replaced", "ideographic", "line-comment", "block-comment", "name", "name-kept-stretch"],
)
def test_a_final_blank_that_is_no_stray_tail_is_not_refused(script):
    assert ENGINE.split_statements(script)


def effect_fuzz(split, seed, count):
    """Run random scripts through the driver whole and through ``split`` one statement at a time.

    Returns accepted, refused, same and differ: a script the driver runs without error is compared
    with the statements ``split`` returns, by the tables left; a refused script is not run.
    """
    rng = random.Random(seed)
    blanks = [NB, NB, "\u3000", "\u205f", "\ufeff", " ", " ", "\n", "\r\n", "", "", ""]
    openers = ["/* ' */", "/* $t$ */", "/* $$ */", "-- '\n", "/* it's */", "", "", "", "", ""]
    templates = [
        "SELECT 1", "SELECT 1 AS x", "DROP TABLE t", "DROP TABLE IF EXISTS t", "SELECT 1 AS a$$",
        "SELECT 1 AS a$t$", "SELECT 2 AS b$t$", "DROP TABLE IF EXISTS t{b}CASCADE",
        "SELECT 1 AS x{b}y", "SELECT 1 AS e{b}", "SELECT 1 e{b}y", "SELECT 1", "DROP TABLE t",
        "DROP TABLE IF EXISTS t", "SELECT 1 AS x", "SELECT 2",
    ]  # fmt: skip
    ends = [";", ";", ";\n", "; ", ";\r\n", ""]
    accepted = refused = same = differ = 0
    for _ in range(count):
        script = ""
        for _ in range(rng.randint(1, 4)):
            statement = rng.choice(templates).format(b=rng.choice(blanks))
            script += rng.choice(openers) + rng.choice(blanks) + statement + rng.choice(blanks)
            script += rng.choice(ends)
        script += rng.choice(blanks)
        try:
            statements = split(script)
        except UnsafeStatementSplitError:
            refused += 1
            continue
        engine = duckdb.connect()
        setup(engine)
        try:
            engine.execute(script)
        except duckdb.ParserException:
            continue  # a script the engine rejects whole runs none of it; dblift runs it per statement
        except duckdb.Error:
            engine_failed = True
        else:
            engine_failed = False
        accepted += 1
        mine = duckdb.connect()
        setup(mine)
        failed = False
        for statement in statements:
            try:
                mine.execute(statement)
            except duckdb.Error:
                failed = True
                break
        if failed == engine_failed and tables(mine) == tables(engine):
            same += 1
        else:
            differ += 1
    return accepted, refused, same, differ


@pytest.mark.parametrize("seed", [1, 2, 3])
def test_no_statement_dblift_runs_has_another_effect_than_the_engine_gives_the_script(seed):
    accepted, refused, same, differ = effect_fuzz(ENGINE.split_statements, seed, 2000)
    assert differ == 0
    assert accepted > 300 and refused > 0 and same == accepted
