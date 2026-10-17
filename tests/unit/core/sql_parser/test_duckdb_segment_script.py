"""The records, execution strings, analysis texts and blanked text of a DuckDB script in the shared engine.

Expected values were recorded from the scanner this engine replaces.
"""

from dataclasses import replace
from pathlib import Path

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import DuckDBFactsParser
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_RULES, DUCKDB_SPEC
from tests.support.splitter_spec.spec_tables import load_conformance_rows
from tests.support.splitter_spec.splitting import SplitOutcome

BOM, NBSP, VT, NUL = chr(0xFEFF), chr(0xA0), chr(0x0B), chr(0)
ENGINE = LexicalEngine(DUCKDB_SPEC)
SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ROWS = [row for row in load_conformance_rows(SPEC_DIR) if row.dialect == "duckdb"]

# (id, script, records as (text, line, terminator, source_start, source_end) or an error, analysis texts or an error,
# the script with its comments blanked or an error)
CASES = [
    (
        "bom_and_crlf",
        BOM + "SELECT 1;\r\nSELECT 2;\r\n",
        [("SELECT 1", 1, ";", 1, 10), ("SELECT 2", 2, ";", 12, 21)],
        ["SELECT 1", "SELECT 2"],
        "SELECT 1;\r\nSELECT 2;\r\n",
    ),
    (
        "leading_comment_kept",
        "-- c\nSELECT 1; /* b */ SELECT 2;",
        [("-- c\nSELECT 1", 1, ";", 0, 14), ("/* b */ SELECT 2", 2, ";", 15, 32)],
        ["-- c\nSELECT 1", "/* b */ SELECT 2"],
        " \nSELECT 1;   SELECT 2;",
    ),
    (
        "leading_nbsp_kept",
        "SELECT 1;" + NBSP + "SELECT 2",
        [("SELECT 1", 1, ";", 0, 9), ("\xa0SELECT 2", 1, None, 9, 18)],
        ["SELECT 1", "\xa0SELECT 2"],
        "SELECT 1;\xa0SELECT 2",
    ),
    (
        "trailing_nbsp_kept",
        "SELECT 1;SELECT 2" + NBSP,
        [("SELECT 1", 1, ";", 0, 9), ("SELECT 2\xa0", 1, None, 9, 18)],
        ["SELECT 1", "SELECT 2\xa0"],
        "SELECT 1;SELECT 2\xa0",
    ),
    (
        "tail_without_terminator",
        "SELECT 1; SELECT 2",
        [("SELECT 1", 1, ";", 0, 9), ("SELECT 2", 1, None, 10, 18)],
        ["SELECT 1", "SELECT 2"],
        "SELECT 1; SELECT 2",
    ),
    (
        "double_semicolons",
        "SELECT 1;; SELECT 2;;",
        [("SELECT 1", 1, ";", 0, 9), ("SELECT 2", 1, ";", 11, 20)],
        ["SELECT 1", "SELECT 2"],
        "SELECT 1;; SELECT 2;;",
    ),
    (
        "comment_only_tail",
        "SELECT 1; -- bye",
        [("SELECT 1", 1, ";", 0, 9)],
        ["SELECT 1", "-- bye"],
        "SELECT 1;  ",
    ),
    (
        "comment_only_script",
        "-- only a comment\n/* here */",
        [],
        ["-- only a comment\n/* here */"],
        " \n ",
    ),
    (
        "unclosed_comment_last",
        "SELECT 1; /* open\nSELECT 2;",
        [("SELECT 1", 1, ";", 0, 9), ("/* open\nSELECT 2;", 1, None, 10, 27)],
        ["SELECT 1", "/* open\nSELECT 2;"],
        "SELECT 1; /* open\nSELECT 2;",
    ),
    (
        "bom_offsets_and_lines",
        BOM + "\n\n  SELECT 1;\n  -- x\n SELECT 2",
        [("SELECT 1", 3, ";", 5, 14), ("-- x\n SELECT 2", 4, None, 17, 31)],
        ["SELECT 1", "-- x\n SELECT 2"],
        "\n\n  SELECT 1;\n   \n SELECT 2",
    ),
    (
        "lone_cr_lines",
        "SELECT 1;\rSELECT 2;\r",
        [("SELECT 1", 1, ";", 0, 9), ("SELECT 2", 1, ";", 10, 19)],
        ["SELECT 1", "SELECT 2"],
        "SELECT 1;\rSELECT 2;\r",
    ),
    (
        "crlf_blank_lines",
        "\r\n\r\nSELECT 1;\r\n\r\nSELECT 2;\r\n",
        [("SELECT 1", 3, ";", 4, 13), ("SELECT 2", 5, ";", 17, 26)],
        ["SELECT 1", "SELECT 2"],
        "\r\n\r\nSELECT 1;\r\n\r\nSELECT 2;\r\n",
    ),
    (
        "vertical_tab_is_code",
        "SELECT 1 AS a;" + VT + "SELECT 2 AS y;",
        [("SELECT 1 AS a", 1, ";", 0, 14), ("\x0bSELECT 2 AS y", 1, ";", 14, 29)],
        ["SELECT 1 AS a", "\x0bSELECT 2 AS y"],
        "SELECT 1 AS a;\x0bSELECT 2 AS y;",
    ),
    (
        "blank_only_segment",
        "SELECT 1;" + NBSP + ";",
        [("SELECT 1", 1, ";", 0, 9)],
        ["SELECT 1", "\xa0"],
        "SELECT 1;\xa0;",
    ),
    (
        "blank_only_segment_then_statement",
        "SELECT 1;" + NBSP + ";SELECT 2;",
        [("SELECT 1", 1, ";", 0, 9), ("SELECT 2", 1, ";", 11, 20)],
        ["SELECT 1", "\xa0", "SELECT 2"],
        "SELECT 1;\xa0;SELECT 2;",
    ),
    (
        "escape_string_with_semicolon",
        "SELECT E'a\\';b'; SELECT 2;",
        [("SELECT E'a\\';b'", 1, ";", 0, 16), ("SELECT 2", 1, ";", 17, 26)],
        ["SELECT E'a\\';b'", "SELECT 2"],
        "SELECT E'a\\';b'; SELECT 2;",
    ),
    (
        "dollar_body_over_lines",
        "SELECT $$a\n;\nb$$;\nSELECT 2;",
        [("SELECT $$a\n;\nb$$", 1, ";", 0, 17), ("SELECT 2", 4, ";", 18, 27)],
        ["SELECT $$a\n;\nb$$", "SELECT 2"],
        "SELECT $$a\n;\nb$$;\nSELECT 2;",
    ),
    (
        "blank_in_the_middle",
        "SELECT 1;" + BOM + "SELECT 2;",
        [("SELECT 1", 1, ";", 0, 9), ("\ufeffSELECT 2", 1, ";", 9, 19)],
        ["SELECT 1", "\ufeffSELECT 2"],
        "SELECT 1;\ufeffSELECT 2;",
    ),
    ("empty_script", "", [], [], ""),
    ("only_semicolons", ";;;", [], [], ";;;"),
    ("only_blanks", "  \n ", [], [], "  \n "),
    (
        "escape_mode_across_a_blank",
        "SELECT E'a' 'b\\'; SELECT 1 AS y; SELECT 'z';",
        [("SELECT E'a' 'b\\'; SELECT 1 AS y; SELECT 'z';", 1, None, 0, 44)],
        ["SELECT E'a' 'b\\'; SELECT 1 AS y; SELECT 'z';"],
        "SELECT E'a' 'b\\'; SELECT 1 AS y; SELECT 'z';",
    ),
    (
        "digit_letter_before_e",
        "SELECT " + chr(0xB2) + "E'b\\';c' AS x; SELECT 2;",
        [("SELECT \xb2E'b\\';c' AS x", 1, ";", 0, 22), ("SELECT 2", 1, ";", 23, 32)],
        ["SELECT \xb2E'b\\';c' AS x", "SELECT 2"],
        "SELECT \xb2E'b\\';c' AS x; SELECT 2;",
    ),
    (
        "arabic_digit_before_e",
        "SELECT " + chr(0x663) + "E'b\\';c' AS x; SELECT 2;",
        [("SELECT \u0663E'b\\';c' AS x", 1, ";", 0, 22), ("SELECT 2", 1, ";", 23, 32)],
        ["SELECT \u0663E'b\\';c' AS x", "SELECT 2"],
        "SELECT \u0663E'b\\';c' AS x; SELECT 2;",
    ),
    (
        "parameter_swallows_letters",
        "PREPARE p AS SELECT $1a$$x; SELECT 2; SELECT 3 AS y$$;",
        [("PREPARE p AS SELECT $1a$$x; SELECT 2; SELECT 3 AS y$$", 1, ";", 0, 54)],
        ["PREPARE p AS SELECT $1a$$x; SELECT 2; SELECT 3 AS y$$"],
        "PREPARE p AS SELECT $1a$$x; SELECT 2; SELECT 3 AS y$$;",
    ),
    (
        "parameter_swallows_accented_letter",
        "SELECT $1" + chr(0xE9) + "$$x;y$$; SELECT 2;",
        [("SELECT $1\xe9$$x;y$$", 1, ";", 0, 18), ("SELECT 2", 1, ";", 19, 28)],
        ["SELECT $1\xe9$$x;y$$", "SELECT 2"],
        "SELECT $1\xe9$$x;y$$; SELECT 2;",
    ),
    (
        "parameter_swallows_escape_letter",
        "SELECT $1E'a\\';b'; SELECT 2;",
        [("SELECT $1E'a\\'", 1, ";", 0, 15), ("b'; SELECT 2;", 1, None, 15, 28)],
        ["SELECT $1E'a\\'", "b'; SELECT 2;"],
        "SELECT $1E'a\\';b'; SELECT 2;",
    ),
    (
        "nul_on_line_two",
        "SELECT 1;\n" + NUL + "SELECT 2;",
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 2: the engine reads the script up to it and silently drops the rest",
        ),
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 2: the engine reads the script up to it and silently drops the rest",
        ),
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 2: the engine reads the script up to it and silently drops the rest",
        ),
    ),
    (
        "nul_after_a_dot_line",
        ".mode csv\n" + NUL,
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 2: the engine reads the script up to it and silently drops the rest",
        ),
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 2: the engine reads the script up to it and silently drops the rest",
        ),
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 2: the engine reads the script up to it and silently drops the rest",
        ),
    ),
    (
        "nul_after_bom",
        BOM + NUL,
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 1: the engine reads the script up to it and silently drops the rest",
        ),
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 1: the engine reads the script up to it and silently drops the rest",
        ),
        (
            "error",
            "UnsafeStatementSplitError",
            "a NUL character on line 1: the engine reads the script up to it and silently drops the rest",
        ),
    ),
    (
        "dot_first_line",
        ".mode csv\nSELECT 1;",
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
    ),
    (
        "dot_after_statement",
        "SELECT 1;\n.mode csv\nSELECT 2;",
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
    ),
    (
        "dot_after_comment_line",
        "-- c\n.mode csv\nSELECT 1;",
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.mode' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
    ),
    (
        "dot_after_crlf",
        "SELECT 1 AS a;\r\n.print x\r\nSELECT 2;",
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 2: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
    ),
    (
        "dot_after_closed_comment_on_later_line",
        "SELECT 1 AS a;\n/* x\n*/\n.print hi\nSELECT 2;",
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 4: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 4: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 4: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
    ),
    (
        "dot_after_bom",
        BOM + ".print x\nSELECT 1;",
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
    ),
    (
        "dot_is_text_when_pending",
        "SELECT 1\n.mode csv\n;",
        [("SELECT 1\n.mode csv", 1, ";", 0, 20)],
        ["SELECT 1\n.mode csv"],
        "SELECT 1\n.mode csv\n;",
    ),
    (
        "dot_is_text_when_indented",
        "  .mode csv\nSELECT 1;",
        [(".mode csv\nSELECT 1", 1, ";", 2, 21)],
        [".mode csv\nSELECT 1"],
        "  .mode csv\nSELECT 1;",
    ),
    (
        "dot_after_lone_cr_is_text",
        "SELECT 1 AS a;\r.print x\nSELECT 2 AS b;",
        [("SELECT 1 AS a", 1, ";", 0, 14), (".print x\nSELECT 2 AS b", 1, ";", 15, 38)],
        ["SELECT 1 AS a", ".print x\nSELECT 2 AS b"],
        "SELECT 1 AS a;\r.print x\nSELECT 2 AS b;",
    ),
    (
        "dot_word_ends_at_nbsp",
        ".print" + NBSP + "x\nSELECT 1;",
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
        (
            "error",
            "UnsupportedMetaCommandError",
            "duckdb shell command '.print' on line 1: the shell runs it and the engine cannot; dblift does not run client commands",
        ),
    ),
]
IDS = [case[0] for case in CASES]


def outcome(call, script):
    try:
        return call(script)
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as error:
        return ("error", type(error).__name__, str(error))


def fields(record):
    return (record.text, record.line, record.terminator, record.source_start, record.source_end)


@pytest.mark.parametrize("name,script,records,analysis,blanked", CASES, ids=IDS)
def test_records(name, script, records, analysis, blanked):
    assert outcome(lambda s: [fields(r) for r in ENGINE.split(s)], script) == records


@pytest.mark.parametrize("name,script,records,analysis,blanked", CASES, ids=IDS)
def test_execution_strings_are_the_record_texts(name, script, records, analysis, blanked):
    expected = records if records[:1] == ("error",) else [record[0] for record in records]
    assert outcome(ENGINE.split_statements, script) == expected


@pytest.mark.parametrize("name,script,records,analysis,blanked", CASES, ids=IDS)
def test_analysis_view(name, script, records, analysis, blanked):
    assert outcome(ENGINE.split_for_analysis, script) == analysis


@pytest.mark.parametrize("name,script,records,analysis,blanked", CASES, ids=IDS)
def test_blank_comments(name, script, records, analysis, blanked):
    assert outcome(ENGINE.blank_comments, script) == blanked


@pytest.mark.parametrize("name,script,records,analysis,blanked", CASES, ids=IDS)
def test_engine_analysis_view_matches_the_parser(name, script, records, analysis, blanked):
    assert outcome(ENGINE.split_for_analysis, script) == outcome(
        DuckDBFactsParser().split_for_analysis, script
    )


def test_records_keep_every_other_field_at_its_default():
    records = ENGINE.split(BOM + "SELECT 1; -- c\nSELECT 2")
    assert len(records) == 2
    for record in records:
        assert (record.kind, record.multi, record.repeat, record.analysis_statements) == (
            "sql",
            False,
            1,
            None,
        )


def test_comment_only_segments_are_records_only_for_analysis():
    assert [r.text for r in ENGINE.split("SELECT 1; -- bye")] == ["SELECT 1"]
    assert [r.text for r in ENGINE.split("SELECT 1; -- bye", include_comment_only=True)] == [
        "SELECT 1",
        "-- bye",
    ]


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_id)
def test_spec_row_through_the_engine(row):
    if row.status == "to_verify":
        pytest.skip("spec marks this row 'to verify': not a claim yet")
    try:
        result = SplitOutcome(statements=tuple(ENGINE.split_statements(row.script)))
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as error:
        result = SplitOutcome(statements=(), error=type(error).__name__, detail=str(error))
    assert result.matches(row.expectation), (row.row_id, result)


def test_text_blanks_is_read():
    script = "SELECT 1 AS a;" + VT + "SELECT 2 AS y;"
    assert [fields(r) for r in ENGINE.split(script)] == [
        ("SELECT 1 AS a", 1, ";", 0, 14),
        (VT + "SELECT 2 AS y", 1, ";", 14, 29),
    ]
    wide = LexicalEngine(
        replace(DUCKDB_SPEC, segment_script=replace(DUCKDB_RULES, text_blanks=" \t\n\f\r" + VT))
    )
    assert [fields(r) for r in wide.split(script)] == [
        ("SELECT 1 AS a", 1, ";", 0, 14),
        ("SELECT 2 AS y", 1, ";", 15, 29),
    ]
    assert wide.split_for_analysis(script) == ["SELECT 1 AS a", "SELECT 2 AS y"]


def test_a_blank_only_segment_is_an_analysis_record_not_an_execution_record():
    script = "SELECT 1;" + NBSP + ";"
    assert ENGINE.split_statements(script) == ["SELECT 1"]
    assert ENGINE.split_for_analysis(script) == ["SELECT 1", NBSP]


def test_a_refusal_comes_before_any_record():
    for script in (NUL + "SELECT 1;", ".mode csv\nSELECT 1;", ".mode csv\n" + NUL):
        with pytest.raises((UnsafeStatementSplitError, UnsupportedMetaCommandError)):
            ENGINE.split(script)
