"""The Db2 line pass: every line is classified from its raw text and the active terminator only."""

from dataclasses import replace
from typing import List, Tuple

import pytest

from dblift.core.sql_parser.terminator_lines import Line, read_lines
from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES

VT, FF, NBSP, LS = chr(0x0B), chr(0x0C), chr(0xA0), chr(0x2028)
E_ACUTE, EURO, SMILE = chr(0xE9), chr(0x20AC), chr(0x1F600)


def lines_of(text: str, rules=DB2_RULES) -> List[Line]:
    return read_lines(rules, text)[0]


def summary(text: str, rules=DB2_RULES) -> List[Tuple[int, str, str, str]]:
    """(number, kind, active terminator, the text before the terminator or '' when the line is not a cut)."""
    return [
        (
            ln.number,
            ln.kind,
            ln.terminator,
            text[ln.start : ln.body_end] if ln.body_end >= 0 else "",
        )
        for ln in lines_of(text, rules)
    ]


def test_line_kinds_rows_2_and_24():
    script = (
        "--#SET TERMINATOR @\n"
        "CREATE PROCEDURE p() BEGIN DECLARE x INT; SET x = 1; END@\n"
        "--#SET TERMINATOR ;\n"
        "CALL p();"
    )
    assert summary(script) == [
        (1, "directive", ";", ""),
        (2, "code", "@", "CREATE PROCEDURE p() BEGIN DECLARE x INT; SET x = 1; END"),
        (3, "directive", "@", ""),
        (4, "code", ";", "CALL p()"),
    ]
    mid = "CREATE TABLE t (\n--#SET TERMINATOR @\nid INT)@\nSELECT 1 FROM sysibm.sysdummy1@"
    assert summary(mid) == [
        (1, "code", ";", ""),
        (2, "directive", ";", ""),
        (3, "code", "@", "id INT)"),
        (4, "code", "@", "SELECT 1 FROM sysibm.sysdummy1"),
    ]


def test_line_kinds_comment_block_blank_and_two_character_terminator():
    script = "--#SET TERMINATOR %%\n-- a;\n\n   \t\n(=\nCREATE TABLE t (id INT)%%\n"
    assert [(n, k) for n, k, _, _ in summary(script)] == [
        (1, "directive"),
        (2, "comment"),
        (3, "blank"),
        (4, "blank"),
        (5, "block"),
        (6, "code"),
    ]
    assert summary(script)[5] == (6, "code", "%%", "CREATE TABLE t (id INT)")
    assert summary("  (= x\nVALUES 1;")[0][:2] == (1, "block")


def test_a_lower_case_directive_is_a_comment_line_and_the_terminator_stays():
    script = "--#set terminator @\nCREATE TABLE t (id INT)@\nSELECT 1 FROM sysibm.sysdummy1;"
    assert summary(script) == [
        (1, "comment", ";", ""),
        (2, "code", ";", ""),
        (3, "code", ";", "SELECT 1 FROM sysibm.sysdummy1"),
    ]
    several_blanks = "--#SET  TERMINATOR  @\nCREATE TABLE t (id INT)@\n"
    assert summary(several_blanks)[1] == (2, "code", "@", "CREATE TABLE t (id INT)")


def test_terminator_is_the_last_non_blank_characters():
    assert summary("VALUES 1;  \t \n")[0] == (1, "code", ";", "VALUES 1")
    for gap in (VT, FF, NBSP, LS):
        assert summary(f"VALUES 1;{gap}\n")[0][3] == "", repr(gap)
    assert summary("--#SET TERMINATOR %%\nVALUES 1%\nVALUES 2%%\n")[1:] == [
        (2, "code", "%%", ""),
        (3, "code", "%%", "VALUES 2"),
    ]
    assert summary("VALUES 1;;\n")[0][3] == "VALUES 1;"
    assert summary("VALUES 1; X;\n")[0][3] == "VALUES 1; X"
    assert summary(";\n")[0][3] == ""
    assert lines_of(";\n")[0].body_end == 0


def test_blanks_are_a_field():
    with_vt = replace(DB2_RULES, blanks=" \t" + VT)
    assert summary(f"VALUES 1;{VT}\n", with_vt)[0][3] == "VALUES 1"
    assert summary(f"{VT}-- c;\n", with_vt)[0][:2] == (1, "comment")
    assert summary("\t-- c;\n", replace(DB2_RULES, blanks=" "))[0][:2] == (1, "code")


def test_cr_of_a_crlf_is_not_part_of_the_line():
    script = "VALUES 1;\r\nVALUES 2;\r\n"
    first, second = lines_of(script)
    assert (first.text, first.end, first.body_end) == ("VALUES 1;", 11, 8)
    assert (second.text, second.start, second.body_end) == ("VALUES 2;", 11, 19)


def test_a_lone_cr_is_a_character_and_so_is_a_cr_run():
    lone = lines_of("VALUES\r1;\n")
    assert [(ln.text, ln.kind) for ln in lone] == [("VALUES\r1;", "code")]
    assert lone[0].body_end == 8
    run = lines_of("VALUES 1;\r\r\n")
    assert run[0].text == "VALUES 1;\r" and run[0].body_end == -1
    ending_script = lines_of("VALUES 1;\r")
    assert ending_script[0].text == "VALUES 1;\r" and ending_script[0].body_end == -1


def test_line_numbers_and_bounds_cover_the_script_without_a_final_empty_line():
    script = "a\n\nb;\nc"
    lines = lines_of(script)
    assert [(ln.number, ln.start, ln.end) for ln in lines] == [
        (1, 0, 2),
        (2, 2, 3),
        (3, 3, 6),
        (4, 6, 7),
    ]
    assert lines_of("") == [] and [ln.kind for ln in lines_of("\n")] == ["blank"]
    assert [(ln.start, ln.end) for ln in lines_of("a;\n")] == [(0, 3)]


@pytest.mark.parametrize(
    "directive, terminator",
    [
        ("--#SET TERMINATOR @", "@"),
        ("   --#SET TERMINATOR @", "@"),
        ("\t--#SET TERMINATOR @", "@"),
        ("--#SET TERMINATOR @\t", "@"),
        ("--#SET TERMINATOR @   ", "@"),
        ("--#SET TERMINATOR @\r", "@"),
        ("--#SET   TERMINATOR    @", "@"),
        ("--#SET TERMINATOR ;;", ";;"),
        ("--#SET TERMINATOR $$", "$$"),
        ('--#SET TERMINATOR "', '"'),
        ("--#SET TERMINATOR --", "--"),
        ("--#SET TERMINATOR '", "'"),
    ],
)
def test_directive_forms_that_are_honoured(directive, terminator):
    lines, _, malformed = read_lines(DB2_RULES, directive + "\nVALUES 1\n")
    assert malformed is None
    assert [ln.kind for ln in lines] == ["directive", "code"]
    assert lines[1].terminator == terminator


@pytest.mark.parametrize(
    "directive",
    [
        "--#SET\tTERMINATOR @",
        "--#set terminator @",
        "--#SET MAXERRORS 1",
        "--#TERMINATOR @",
        "-- #SET TERMINATOR @",
    ],
)
def test_directive_forms_that_are_comments(directive):
    lines, _, malformed = read_lines(DB2_RULES, directive + "\nVALUES 1\n")
    assert malformed is None
    assert [ln.kind for ln in lines] == ["comment", "code"]
    assert lines[1].terminator == ";"


@pytest.mark.parametrize(
    "directive",
    [
        "--#SET TERMINATOR\t@",
        "--#SET TERMINATOR @ -- c",
        "--#SET TERMINATOR",
        "--#SET TERMINATOR ",
        "--#SET TERMINATOR abc",
        "--#SET TERMINATOR@",
        "--#SET TERMINATOR @@@",
        "--#SET TERMINATOR @" + VT,
        "--#SET TERMINATOR @" + NBSP,
    ],
)
def test_malformed_directive_stops_the_pass(directive):
    script = "VALUES 1;\n" + directive + "\nVALUES 2;\nVALUES 3;\n"
    lines, masked, malformed = read_lines(DB2_RULES, script)
    assert malformed == 2
    assert [ln.number for ln in lines] == [1, 2] and lines[1].kind == "directive"
    assert masked == script.replace("VALUES 1;", "VALUES 1 ", 1)


def test_directive_fields_are_read():
    ignoring_case = replace(DB2_RULES, directive=r"(?i)[ \t]*--#SET +TERMINATOR(?!\w)")
    lines, _, malformed = read_lines(ignoring_case, "--#set TERMINATOR @\nVALUES 1@\n")
    assert malformed is None and lines[0].kind == "directive" and lines[1].terminator == "@"
    three = replace(DB2_RULES, directive_value=r" +(\S{1,3})[ \t]*\Z")
    assert read_lines(three, "--#SET TERMINATOR @@@\nVALUES 1@@@\n")[2] is None
    assert read_lines(DB2_RULES, "--#SET TERMINATOR @@@\n")[2] == 1
    assert (
        lines_of("--#SET TERMINATOR @\nx@\n", replace(DB2_RULES, initial="%"))[0].terminator == "%"
    )


def test_masked_text_blanks_consumed_runs_only():
    script = "VALUES 1;\nVALUES 2; -- c\nVALUES 3;;  \nVALUES ';' ; 4\n"
    lines, masked, malformed = read_lines(DB2_RULES, script)
    assert malformed is None and len(masked) == len(script)
    assert masked == "VALUES 1 \nVALUES 2; -- c\nVALUES 3;   \nVALUES ';' ; 4\n"
    two = "--#SET TERMINATOR %%\nVALUES 1%%\nVALUES 2%\nVALUES 3%%  \n"
    assert (
        read_lines(DB2_RULES, two)[1]
        == "--#SET TERMINATOR %%\nVALUES 1  \nVALUES 2%\nVALUES 3    \n"
    )


def test_masked_text_keeps_every_other_character_and_position():
    script = "--#SET TERMINATOR @\nCREATE TABLE \"my@tbl\" (id INT)@\n/* c@ */\nVALUES '@'@\n"
    lines, masked, _ = read_lines(DB2_RULES, script)
    cut = {i for ln in lines if ln.body_end >= 0 for i in range(ln.body_end, ln.tail_end)}
    assert cut and len(masked) == len(script)
    for index, (before, after) in enumerate(zip(script, masked)):
        assert after == (" " if index in cut else before)


def test_a_comment_line_is_never_a_terminator_line():
    script = "VALUES 'x\n-- y;\nz';"
    assert [(ln.kind, ln.body_end) for ln in lines_of(script)] == [
        ("code", -1),
        ("comment", -1),
        ("code", 18),
    ]
    assert [ln.kind for ln in lines_of("-- a;\nCREATE TABLE t (id INT);")] == ["comment", "code"]
    hash_comment = replace(DB2_RULES, line_comment="#")
    assert summary("# a;\n-- b;\n", hash_comment) == [
        (1, "comment", ";", ""),
        (2, "code", ";", "-- b"),
    ]


def test_the_comment_block_opener_is_a_field():
    plus = replace(DB2_RULES, comment_block="(+")
    assert [ln.kind for ln in lines_of("(=\n(+\n", plus)] == ["code", "block"]
    assert [ln.kind for ln in lines_of("(=\n(+\n")] == ["block", "code"]


@pytest.mark.parametrize("value", [E_ACUTE, E_ACUTE * 2, EURO, SMILE, SMILE * 2, E_ACUTE + EURO])
def test_terminator_length_counts_characters(value):
    lines, masked, malformed = read_lines(
        DB2_RULES, f"--#SET TERMINATOR {value}\nVALUES 1{value}\n"
    )
    assert malformed is None
    assert lines[1].terminator == value and lines[1].body_end == len(
        f"--#SET TERMINATOR {value}\nVALUES 1"
    )
    assert masked.endswith("VALUES 1" + " " * len(value) + "\n")


def test_three_characters_are_a_malformed_directive():
    assert read_lines(DB2_RULES, f"--#SET TERMINATOR {E_ACUTE}{EURO}{SMILE}\n")[2] == 1


def test_a_directive_matches_only_at_the_start_of_the_line():
    after_code = "SELECT 1 FROM sysibm.sysdummy1 --#SET TERMINATOR @\n;\nVALUES 2;\n"
    lines, _, malformed = read_lines(DB2_RULES, after_code)
    assert malformed is None
    assert [(ln.kind, ln.terminator, ln.body_end >= 0) for ln in lines] == [
        ("code", ";", False),
        ("code", ";", True),
        ("code", ";", True),
    ]
    in_comment = read_lines(DB2_RULES, "-- x --#SET TERMINATOR @\nVALUES 1;\n")
    assert [(ln.kind, ln.terminator) for ln in in_comment[0]] == [("comment", ";"), ("code", ";")]
    in_string = read_lines(DB2_RULES, "VALUES 'x\n y --#SET TERMINATOR @ \n';\n")
    assert in_string[2] is None and {ln.terminator for ln in in_string[0]} == {";"}
