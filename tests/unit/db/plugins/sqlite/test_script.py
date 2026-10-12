"""The SQLite scanner: where a statement ends, what the shell would run itself, what is refused.

Every expectation was measured with the ``sqlite3`` shell and ``sqlite3.complete_statement``
(docs/sql-parsing/sqlite.md); the rows of its section 10 are pinned separately by the conformance
test, these tests pin the rules behind them and the records the scanner returns.
"""

from __future__ import annotations

import itertools
import sqlite3
import subprocess
import sys
import time
from pathlib import Path

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.db.plugins.sqlite.parser._script import scan_script

ROOT = Path(__file__).resolve().parents[4]


def texts(script: str) -> list[str]:
    return [unit.text for unit in scan_script(script)]


# ---- the library's rule ----------------------------------------------------------------------

#: One word per token class of ``sqlite3_complete``; the scanner's table is checked against the library.
_CLASSES = [";", "x", "explain", "create", "temp", "trigger", "end"]


def _expected(words: tuple[str, ...]) -> list[str]:
    """The statements ``sqlite3.complete_statement`` says a sequence of words is made of."""
    out: list[str] = []
    segment: list[str] = []
    code, prefix = False, ""
    for word in words:
        prefix += word + " "
        if word == ";" and sqlite3.complete_statement(prefix):
            if code:
                out.append(" ".join(segment))
            segment, code = [], False
            continue
        segment.append(word)
        code = True
    if code:
        out.append(" ".join(segment))
    return out


def test_the_scanner_cuts_where_the_library_says_a_statement_is_complete() -> None:
    """Every sequence of up to 7 token classes (960 799), against the library: the whole table."""
    for length in range(1, 8):
        for words in itertools.product(_CLASSES, repeat=length):
            script = " ".join(words)
            assert texts(script) == _expected(words), script


# ---- strings, identifiers ----------------------------------------------------------------------


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 'a;b'; SELECT 2", ["SELECT 'a;b'", "SELECT 2"]),
        ("SELECT 'it''s;'; SELECT 2", ["SELECT 'it''s;'", "SELECT 2"]),
        ("SELECT 'a\\'; SELECT 2", ["SELECT 'a\\'", "SELECT 2"]),
        ('SELECT "a;b"; SELECT 2', ['SELECT "a;b"', "SELECT 2"]),
        ('SELECT "a""b;c"; SELECT 2', ['SELECT "a""b;c"', "SELECT 2"]),
        ("SELECT [a;b]; SELECT 2", ["SELECT [a;b]", "SELECT 2"]),
        ("SELECT [a]]; SELECT 2", ["SELECT [a]]", "SELECT 2"]),
        ("SELECT `a;b`; SELECT 2", ["SELECT `a;b`", "SELECT 2"]),
        ("SELECT `a``b;c`; SELECT 2", ["SELECT `a``b;c`", "SELECT 2"]),
        ("SELECT X'3B3B'; SELECT 2", ["SELECT X'3B3B'", "SELECT 2"]),
        ('SELECT "it\'s;"; SELECT 2', ['SELECT "it\'s;"', "SELECT 2"]),
        ("SELECT [it's;]; SELECT 2", ["SELECT [it's;]", "SELECT 2"]),
        ("SELECT [a--b;]; SELECT '/*'; SELECT 3", ["SELECT [a--b;]", "SELECT '/*'", "SELECT 3"]),
        ("SELECT 'a;\nb'; SELECT 2", ["SELECT 'a;\nb'", "SELECT 2"]),
    ],
)
def test_a_semicolon_inside_a_lexeme_ends_nothing(script: str, expected: list[str]) -> None:
    assert texts(script) == expected


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 'abc;", ["SELECT 'abc;"]),
        ('SELECT "abc;', ['SELECT "abc;']),
        ("SELECT [abc;", ["SELECT [abc;"]),
        ("SELECT `abc;", ["SELECT `abc;"]),
        ("SELECT 1; SELECT 'abc;\nSELECT 2;", ["SELECT 1", "SELECT 'abc;\nSELECT 2;"]),
    ],
)
def test_an_unterminated_string_or_identifier_is_the_last_statement(
    script: str, expected: list[str]
) -> None:
    assert texts(script) == expected


# ---- comments ------------------------------------------------------------------------------------


def test_a_block_comment_does_not_nest() -> None:
    assert texts("/* a /* b */ SELECT 1; */ SELECT 2;") == ["/* a /* b */ SELECT 1", "*/ SELECT 2"]


def test_a_cr_does_not_end_a_line_comment() -> None:
    assert texts("SELECT 1; -- c\rSELECT 2;\nSELECT 3;") == [
        "SELECT 1",
        "-- c\rSELECT 2;\nSELECT 3",
    ]


@pytest.mark.parametrize(
    "script", ["SELECT 1; /* open", "/* open\nSELECT 1;", "SELECT 1 /* open ; */ /* again"]
)
def test_an_unterminated_block_comment_is_refused_with_its_line(script: str) -> None:
    with pytest.raises(UnsafeStatementSplitError, match=r"line \d+"):
        scan_script(script)


def test_the_refusal_names_the_line_the_comment_opened_on() -> None:
    with pytest.raises(UnsafeStatementSplitError, match="line 3"):
        scan_script("SELECT 1;\nSELECT 2;\n/* open\nSELECT 3;")


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 1; -- bye", ["SELECT 1"]),
        ("-- only\n/* here */\n", []),
        (";;;", []),
        ("", []),
        (" \n\t\n", []),
        ("SELECT 1;; SELECT 2;", ["SELECT 1", "SELECT 2"]),
        ("SELECT 1; -- c\nSELECT 2;", ["SELECT 1", "-- c\nSELECT 2"]),
        ("-- c\nSELECT 1; /* d */ SELECT 2;", ["-- c\nSELECT 1", "/* d */ SELECT 2"]),
        ("SELECT 1 /* c */;", ["SELECT 1 /* c */"]),
        ("SELECT 1 -- c\n;", ["SELECT 1 -- c"]),
    ],
)
def test_comment_only_and_empty_segments_are_not_statements(
    script: str, expected: list[str]
) -> None:
    assert texts(script) == expected


# ---- terminators and the last statement ---------------------------------------------------------


def test_the_last_statement_needs_no_terminator() -> None:
    units = scan_script("CREATE TABLE t(a);\nINSERT INTO t VALUES(1)")
    assert [(u.text, u.terminator) for u in units] == [
        ("CREATE TABLE t(a)", ";"),
        ("INSERT INTO t VALUES(1)", None),
    ]


def test_a_terminator_on_its_own_line_ends_the_statement_above() -> None:
    assert texts("SELECT 1\n;\nSELECT 2\n;\n") == ["SELECT 1", "SELECT 2"]


# ---- triggers --------------------------------------------------------------------------------------

TRIGGER = "CREATE TRIGGER tr AFTER INSERT ON t BEGIN {body} END"


@pytest.mark.parametrize(
    "head",
    [
        "CREATE TRIGGER tr AFTER INSERT ON t",
        "CREATE TEMP TRIGGER tr AFTER INSERT ON t",
        "CREATE TEMPORARY TRIGGER tr AFTER INSERT ON t",
        "CREATE TRIGGER IF NOT EXISTS main.tr INSTEAD OF UPDATE OF a ON t FOR EACH ROW",
        "create trigger tr after insert on t",
        "CREATE /* c */ TRIGGER -- c\n tr AFTER INSERT ON t",
        "EXPLAIN CREATE TRIGGER tr AFTER INSERT ON t",
    ],
)
def test_a_trigger_head_keeps_its_body_whole(head: str) -> None:
    body = f"{head} BEGIN INSERT INTO u VALUES(1); SELECT CASE WHEN 1 THEN 2 END; END"
    assert texts(f"{body}; SELECT 2;") == [body, "SELECT 2"]


@pytest.mark.parametrize(
    "body",
    [
        "SELECT 'END;'; SELECT 'BEGIN';",
        'SELECT 1 AS "end";',
        "SELECT 1 AS [end];",
        "SELECT 1 AS `end`;",
        "SELECT 1 AS end$;",
        "SELECT 1 AS end_x; SELECT 2 AS x_end;",
        "SELECT 1; -- ; END;\nSELECT 2; /* ; END; */",
        "SELECT CASE WHEN 1 THEN 2 END;",
        "SELECT 1; SELECT CASE WHEN 1 THEN 2 END; SELECT 3;",
    ],
)
def test_nothing_but_a_semicolon_then_the_word_end_closes_a_body(body: str) -> None:
    trigger = TRIGGER.format(body=body)
    assert texts(f"{trigger}; SELECT 9;") == [trigger, "SELECT 9"]


@pytest.mark.parametrize(
    "script, expected",
    [
        ("CREATE TABLE trigger_log(a); SELECT 1;", ["CREATE TABLE trigger_log(a)", "SELECT 1"]),
        ("CREATE TABLE t(trigger INT); SELECT 1;", ["CREATE TABLE t(trigger INT)", "SELECT 1"]),
        (
            "CREATE INDEX idx_trigger ON t(a); SELECT 1;",
            ["CREATE INDEX idx_trigger ON t(a)", "SELECT 1"],
        ),
        (
            "SELECT 'CREATE TRIGGER x BEGIN'; SELECT 1;",
            ["SELECT 'CREATE TRIGGER x BEGIN'", "SELECT 1"],
        ),
        (
            "-- CREATE TRIGGER x BEGIN\nSELECT 1; SELECT 2;",
            ["-- CREATE TRIGGER x BEGIN\nSELECT 1", "SELECT 2"],
        ),
        (
            "CREATE TABLE t(begin_at, end_at); SELECT 1;",
            ["CREATE TABLE t(begin_at, end_at)", "SELECT 1"],
        ),
        ("CREATE UNIQUE INDEX i ON t(a); SELECT 1;", ["CREATE UNIQUE INDEX i ON t(a)", "SELECT 1"]),
        ("CREATE VIEW v AS SELECT 1; SELECT 2;", ["CREATE VIEW v AS SELECT 1", "SELECT 2"]),
        (
            "EXPLAIN_X CREATE TRIGGER tr BEGIN SELECT 1; END; SELECT 2;",
            ["EXPLAIN_X CREATE TRIGGER tr BEGIN SELECT 1", "END", "SELECT 2"],
        ),
    ],
)
def test_only_a_trigger_head_opens_a_body(script: str, expected: list[str]) -> None:
    assert texts(script) == expected


def test_a_trigger_is_recognised_at_the_head_of_a_statement_only() -> None:
    assert texts("SELECT 1 CREATE TRIGGER tr BEGIN SELECT 1; END; SELECT 2;") == [
        "SELECT 1 CREATE TRIGGER tr BEGIN SELECT 1",
        "END",
        "SELECT 2",
    ]


def test_transaction_markers_are_plain_statements() -> None:
    assert texts("BEGIN; INSERT INTO t VALUES(1); COMMIT;") == [
        "BEGIN",
        "INSERT INTO t VALUES(1)",
        "COMMIT",
    ]
    assert texts("BEGIN IMMEDIATE TRANSACTION; UPDATE t SET a=2; END TRANSACTION;") == [
        "BEGIN IMMEDIATE TRANSACTION",
        "UPDATE t SET a=2",
        "END TRANSACTION",
    ]


def test_a_trigger_without_its_end_is_the_rest_of_the_script() -> None:
    script = "CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1;\nSELECT 2;\n"
    assert texts(script) == ["CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1;\nSELECT 2;"]


def test_a_trigger_end_without_a_final_semicolon_is_a_statement() -> None:
    script = "CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END"
    assert [(u.text, u.terminator) for u in scan_script(script)] == [(script, None)]


def test_end_followed_by_other_text_goes_back_into_the_body() -> None:
    script = "CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END SELECT 2; END; SELECT 3;"
    assert texts(script) == [
        "CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END SELECT 2; END",
        "SELECT 3",
    ]


# ---- dot-commands -----------------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script, command, line",
    [
        (".mode csv\nSELECT 1;", ".mode", 1),
        ("CREATE TABLE t(a);\n.print x\nSELECT 1;", ".print", 2),
        ("-- c\n.print x\nSELECT 1;", ".print", 2),
        ("/* c */\n.print x\nSELECT 1;", ".print", 2),
        ("SELECT 1; -- c\n.print x", ".print", 2),
        ("/* a\nb */\n.print x", ".print", 3),
        ("SELECT 1;\n\n\n.exit\nSELECT 2;", ".exit", 4),
        (".shell echo hi", ".shell", 1),
        (".PRINT x", ".PRINT", 1),
        (".5\nSELECT 1;", ".5", 1),
        (".\nSELECT 1;", ".", 1),
        ("CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END;\n.print x", ".print", 2),
        ("CREATE TABLE t(a);\r\n.print x\r\n", ".print", 2),
    ],
)
def test_a_dot_line_with_nothing_pending_is_refused(script: str, command: str, line: int) -> None:
    with pytest.raises(UnsupportedMetaCommandError) as raised:
        scan_script(script)
    assert f"'{command}'" in str(raised.value) and f"line {line}" in str(raised.value)


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 1\n.print x\n;", ["SELECT 1\n.print x"]),
        ("SELECT 1; .print x\nSELECT 2;", ["SELECT 1", ".print x\nSELECT 2"]),
        ("INSERT INTO t VALUES('a\n.print x\nb');", ["INSERT INTO t VALUES('a\n.print x\nb')"]),
        ('CREATE TABLE "a\n.print x\nb"(x);', ['CREATE TABLE "a\n.print x\nb"(x)']),
        ("CREATE TABLE [a\n.print x\nb](x);", ["CREATE TABLE [a\n.print x\nb](x)"]),
        ("/*\n.print x\n*/ SELECT 1;", ["/*\n.print x\n*/ SELECT 1"]),
        ("SELECT 1 /* open\n.print x\n*/ ;", ["SELECT 1 /* open\n.print x\n*/"]),
        ("  .print x\nSELECT 1;", [".print x\nSELECT 1"]),
        ("\t.print x\nSELECT 1;", [".print x\nSELECT 1"]),
        ("/* c */ .print x\nSELECT 1;", ["/* c */ .print x\nSELECT 1"]),
        ("CREATE TRIGGER tr AFTER INSERT ON t BEGIN\n.print x\nSELECT 1; END;", None),
        ("SELECT 1 +\n.5;", ["SELECT 1 +\n.5"]),
    ],
)
def test_a_dot_line_is_text_when_a_statement_is_pending(
    script: str, expected: list[str] | None
) -> None:
    got = texts(script)
    if expected is not None:
        assert got == expected
    else:
        assert len(got) == 1 and ".print x" in got[0]


def test_a_dot_line_after_a_lone_cr_is_not_at_a_line_start() -> None:
    assert texts("SELECT 1;\r.print x\rSELECT 2;\r") == ["SELECT 1", ".print x\rSELECT 2"]


def test_a_form_feed_is_a_blank() -> None:
    trigger = "CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END"
    assert texts(f"\f{trigger}; SELECT 2;") == [trigger, "SELECT 2"]


def test_a_dot_after_a_byte_order_mark_is_refused_the_mark_is_dropped_first() -> None:
    with pytest.raises(UnsupportedMetaCommandError):
        scan_script("﻿.print x\nSELECT 1;")


# ---- go and slash lines ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "script, line",
    [
        ("CREATE TABLE t(a)\ngo\nINSERT INTO t VALUES(1);", 2),
        ("CREATE TABLE t(a)\nGO\n", 2),
        ("CREATE TABLE t(a)\n   go   \n", 2),
        ("SELECT 6\n/\n2;", 2),
        ("SELECT 6\n  /  \n2;", 2),
        ("INSERT INTO t VALUES(6\n/\n2);", 2),
        ("CREATE TABLE t(a)\r\ngo\r\n", 2),
        ("SELECT 1 /* c */\n-- d\n\ngo\n", 4),
        ("CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; END\ngo\n", 2),
        ("SELECT 6\n/ -- c\n2;", 2),
        ("SELECT 6\n/-- c\n2;", 2),
        ("SELECT 6\ngo -- c\n2;", 2),
        ("SELECT 6\ngo --\n2;", 2),
        ("SELECT 6\ngo/**/\n2;", 2),
        ("SELECT 6\n/ /* c */\n2;", 2),
        ("SELECT 6\ngo /* a */ /* b */ -- d\n2;", 2),
        ("SELECT 6\ngo  -- c\r\n2;", 2),
        ("SELECT 6\n\vgo\n2;", 2),
        ("SELECT 6\ngo\v\n2;", 2),
        ("SELECT 6\n\v/\v\n2;", 2),
        ("SELECT 6\n\fgo\n2;", 2),
        ("SELECT 6\n \f/\n2;", 2),
        ("SELECT 6\n\r/\n2;", 2),
        ("SELECT 6 /* c */\n/\n2;", 2),
        ("SELECT 6 -- six\n\n/\n2;", 3),
    ],
)
def test_a_go_or_slash_line_that_would_end_the_statement_is_refused(script: str, line: int) -> None:
    with pytest.raises(UnsafeStatementSplitError, match=f"line {line}"):
        scan_script(script)


@pytest.mark.parametrize(
    "script",
    [
        "go\nSELECT 1;",
        "/\nSELECT 1;",
        "SELECT 1;\n/\nSELECT 2;",
        "INSERT INTO t VALUES('a\ngo\nb');",
        "INSERT INTO t VALUES('a\n/\nb');",
        'CREATE TABLE "a\ngo\nb"(x);',
        "/*\ngo\n*/ SELECT 1;",
        "CREATE TRIGGER tr AFTER INSERT ON t BEGIN\nSELECT 1;\ngo\nSELECT 2; END;",
        "SELECT 1\ngo;\n",
        "SELECT 1\ngo to\n;",
        "SELECT 1\n/ 2\n;",
        "SELECT 6\ngo /* c\n2;\n*/",
        "SELECT 6\ngo /* c */ x\n;",
        "SELECT 6\n/* c */ go\n;",
        "SELECT 6\n/* c */\n;",
        "SELECT 6\n//\n;",
    ],
)
def test_a_go_or_slash_line_is_text_when_it_would_not_end_the_statement(script: str) -> None:
    scan_script(script)


def test_a_go_or_slash_line_after_a_line_comment_is_text_the_appended_semicolon_is_commented_out() -> (
    None
):
    assert texts("SELECT 6 -- six\n/\n2;") == ["SELECT 6 -- six\n/\n2"]
    assert texts("SELECT 6\n-- six\n/\n2;") == ["SELECT 6\n-- six\n/\n2"]
    assert texts("SELECT 6 -- six\n  go\n;") == ["SELECT 6 -- six\n  go"]
    assert texts("SELECT 1\n-- c\ngo\n") == ["SELECT 1\n-- c\ngo"]


# ---- bytes -------------------------------------------------------------------------------------------


def test_a_leading_byte_order_mark_is_dropped_and_a_later_one_is_text() -> None:
    assert texts("﻿SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]
    assert texts("SELECT 1;\n﻿SELECT 2;") == ["SELECT 1", "﻿SELECT 2"]


def test_crlf_and_lone_cr_are_kept_in_the_text() -> None:
    assert texts("SELECT 'x\r\ny';\r\nSELECT 2;\r\n") == ["SELECT 'x\r\ny'", "SELECT 2"]
    assert texts("SELECT 1\rFROM t;\rSELECT 2;") == ["SELECT 1\rFROM t", "SELECT 2"]


def test_only_the_sqlite_blanks_are_trimmed_from_a_statement() -> None:
    assert texts(" SELECT 1 ;") == [" SELECT 1 "]


# ---- records -----------------------------------------------------------------------------------------


def test_each_record_has_the_line_of_the_first_character_of_its_text() -> None:
    script = "\n\nCREATE TABLE t(a);\n-- c\n\nINSERT INTO t\nVALUES(1);\n\n;SELECT 3"
    assert [(u.line, u.text) for u in scan_script(script)] == [
        (3, "CREATE TABLE t(a)"),
        (4, "-- c\n\nINSERT INTO t\nVALUES(1)"),
        (9, "SELECT 3"),
    ]


def test_a_comment_line_before_a_statement_counts_for_its_line() -> None:
    assert [u.line for u in scan_script("-- one\n-- two\nSELECT 1;")] == [1]


def test_lines_are_counted_across_strings_comments_and_identifiers() -> None:
    script = "SELECT 'a\nb';\n/* c\nd */ SELECT [e\nf];\nSELECT 3;"
    assert [u.line for u in scan_script(script)] == [1, 3, 6]


# ---- cost ---------------------------------------------------------------------------------------------


def _best_of(script: str, rounds: int = 5) -> float:
    best = float("inf")
    for _ in range(rounds):
        start = time.perf_counter()
        scan_script(script)
        best = min(best, time.perf_counter() - start)
    return best


@pytest.mark.parametrize(
    "unit",
    [
        "INSERT INTO t VALUES('a;b', \"c;d\", [e;f]); -- c\n",
        "CREATE TRIGGER tr AFTER INSERT ON t BEGIN SELECT 1; SELECT CASE WHEN 1 THEN 2 END; END;\n",
        "SELECT 1\n-- comment\n/* block\ncomment */\n;\n",
    ],
)
def test_scanning_cost_grows_linearly(unit: str) -> None:
    small, large = _best_of(unit * 2_000), _best_of(unit * 8_000)  # a 4x step
    assert large / small <= 8, (small, large)


@pytest.mark.parametrize(
    "tail",
    ["x", "/* open"],
    ids=["closed comments then text", "closed comments then an unclosed one"],
)
def test_a_slash_line_with_many_comments_costs_one_pass(tail: str) -> None:
    """A line is read once: 500 comments after the slash must not make the check explode."""
    line = "/ " + "/* c */ " * 500 + tail
    code = (
        "from dblift.db.plugins.sqlite.parser._script import scan_script\n"
        "try:\n"
        f"    scan_script({('SELECT 6' + chr(10) + line + chr(10) + '2;')!r})\n"
        "except Exception:\n"
        "    pass\n"
    )
    # the bound is far above the linear cost (milliseconds) and far below a backtracking one (minutes)
    subprocess.run([sys.executable, "-c", code], check=True, timeout=10, cwd=ROOT)


def test_a_huge_literal_and_a_huge_comment_cost_one_pass() -> None:
    assert texts("SELECT '" + "x;" * 200_000 + "';") == ["SELECT '" + "x;" * 200_000 + "'"]
    assert texts("/*" + " ; END ;" * 100_000 + "*/ SELECT 1;") == [
        "/*" + " ; END ;" * 100_000 + "*/ SELECT 1"
    ]


# ---- the segments of comments only, for the callers that read a script -------------------------------


def test_comment_only_segments_are_units_of_their_own_when_asked() -> None:
    units = scan_script("SELECT 1; -- bye", comment_only=True)
    assert [(u.text, u.line, u.terminator) for u in units] == [
        ("SELECT 1", 1, ";"),
        ("-- bye", 1, None),
    ]
    assert [u.text for u in scan_script("-- only\n/* here */\n", comment_only=True)] == [
        "-- only\n/* here */"
    ]
    assert [u.text for u in scan_script("SELECT 1;\n-- one\n;\n-- two\n", comment_only=True)] == [
        "SELECT 1",
        "-- one",
        "-- two",
    ]


def test_nothing_but_terminators_and_blanks_is_never_a_unit() -> None:
    assert scan_script(";;;\n ; \n", comment_only=True) == []
    assert scan_script("", comment_only=True) == []


def test_a_comment_before_a_statement_stays_with_it_in_both_modes() -> None:
    script = "-- c\nSELECT 1; /* d */ SELECT 2;"
    assert texts(script) == ["-- c\nSELECT 1", "/* d */ SELECT 2"]
    assert [u.text for u in scan_script(script, comment_only=True)] == texts(script)


def test_the_refusals_do_not_depend_on_the_mode() -> None:
    for script, error in (
        ("SELECT 1; /* open", UnsafeStatementSplitError),
        (".mode csv\nSELECT 1;", UnsupportedMetaCommandError),
        ("SELECT 6\n/\n2;", UnsafeStatementSplitError),
    ):
        with pytest.raises(error):
            scan_script(script, comment_only=True)
