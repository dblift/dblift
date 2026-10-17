"""The Db2 terminator script assembly: records, directives, refusals, equal to the recorded reference.

``db2_terminator_cases.json`` holds, per case, the script and what the established Db2 splitter returned for
it (all records with their bounds, or the exception class and message), recorded before the engine took over.
"""

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any, List

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.statement import analysis_sql
from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES, DB2_SPEC

CASES = json.loads(
    Path(__file__).with_name("db2_terminator_cases.json").read_text(encoding="utf-8")
)
VT, FF = chr(0x0B), chr(0x0C)
PERCENT_SPEC = replace(DB2_SPEC, terminator_script=replace(DB2_RULES, initial="%"))


def outcome(script: str, spec: LexicalSpec = DB2_SPEC) -> List[Any]:
    """Records as (text, line, terminator, kind, source_start, source_end), or the refusal."""
    try:
        records = LexicalEngine(spec).split(script)
    except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as error:
        return ["error", type(error).__name__, str(error)]
    for record in records:
        assert (record.multi, record.repeat, record.analysis_statements) == (False, 1, None)
    return ["records"] + [
        [r.text, r.line, r.terminator, r.kind, r.source_start, r.source_end] for r in records
    ]


def group(name: str):
    cases = CASES[name]
    return pytest.mark.parametrize("case", cases, ids=[c["id"] for c in cases])


def check(case, spec: LexicalSpec = DB2_SPEC) -> None:
    assert outcome(case["script"], spec) == case["expect"]
    if case["expect"][0] == "records":
        statements = [r[0] for r in case["expect"][1:] if r[3] == "sql"]
        assert LexicalEngine(spec).split_statements(case["script"]) == statements


@group("rows")
def test_spec_rows(case):
    check(case)


@group("record_bounds")
def test_record_bounds(case):
    check(case)


@group("lexeme_refusals")
def test_lexeme_refusals(case):
    check(case)


@group("per_line_rules")
def test_per_line_rules(case):
    check(case)


@group("malformed_directive")
def test_malformed_directive(case):
    check(case)


@group("stray_semicolon")
def test_stray_semicolon(case):
    check(case)


@group("semicolon_then_comment")
def test_semicolon_then_comment_ends_the_statement(case):
    check(case)


@group("kept_quirks")
def test_the_kept_quirks(case):
    check(case)


@group("overlap")
def test_overlap_rule(case):
    check(case)


@group("precedence_pairs")
def test_refusals_follow_the_old_precedence(case):
    check(case)


@group("initial_swapped")
def test_initial_drives_three_readers(case):
    check(case, PERCENT_SPEC)


def test_overlap_rule_over_every_terminator_state_and_ending():
    grid = CASES["overlap_grid"]
    codes = iter(grid["codes"])
    for terminator in grid["terminators"]:
        for state in grid["states"]:
            for ending in grid["endings"]:
                script = (
                    f"--#SET TERMINATOR {terminator}\n{state}{ending}{terminator}\n"
                    f"VALUES 9 */ */ */{terminator}\nVALUES 8{terminator}\n"
                )
                code = next(codes)
                result = outcome(script)
                if code[0] == "A":
                    assert result[0] == "records", (script, result)
                    assert (
                        hashlib.sha1(json.dumps(result).encode()).hexdigest()[:8] == code[1:]
                    ), script
                    continue
                assert result[0] == "error" and result[1] == "UnsafeStatementSplitError", (
                    script,
                    result,
                )
                head = f"line {code[4:]} ends with {terminator!r}"
                assert result[2] in (
                    head
                    + ", which is also part of a comment delimiter: the CLP cuts the statement "
                    "there, the splitter cannot tell the two readings apart; put the comment on a line "
                    "of its own",
                    head + " inside a string or a quoted identifier: the CLP cuts the statement "
                    "there and the server rejects both halves; close the literal before the end of "
                    "the line",
                ), (script, result)
    assert next(codes, None) is None


def test_malformed_directive_message_comes_from_spec_data():
    script = "--#SET TERMINATOR\nVALUES 1;\n"
    assert outcome(script)[2].endswith(
        "expected one or two characters after the keyword, separated from it by blanks"
    )
    changed = replace(DB2_SPEC, terminator_script=replace(DB2_RULES, directive_syntax="X"))
    assert (
        outcome(script, changed)[2] == "malformed --#SET TERMINATOR directive on line 1: expected X"
    )
    renamed = replace(DB2_SPEC, terminator_script=replace(DB2_RULES, directive_name="--#X"))
    assert outcome(script, renamed)[2].startswith("malformed --#X directive on line 1")
    inside = "VALUES 'a\n--#SET TERMINATOR @\nb'"
    assert outcome(inside, renamed)[2].startswith("--#X on line 2 stands inside")


def test_the_block_line_message_names_the_spec_data():
    changed = replace(DB2_SPEC, terminator_script=replace(DB2_RULES, comment_block="(+"))
    assert outcome("(+\n", changed)[2].startswith("CLP comment block '(+' on line 1")
    assert outcome("(=\n", changed)[0] == "records"


def test_client_name_and_driver_name_come_from_the_spec():
    named = replace(
        DB2_SPEC, client_name="X", terminator_script=replace(DB2_RULES, driver_name="drv")
    )
    assert outcome("(=\n", named)[2].startswith(
        "X comment block '(=' on line 1: the X skips it, dblift does not run X input"
    )
    stray = outcome("VALUES 1; VALUES 2;\n", named)[2]
    assert (
        "the X sends it whole" in stray
        and "the drv driver runs only the text" in stray
        and "CLP" not in stray
    )
    assert "CLP" not in outcome("VALUES 'a;\nb';\n", named)[2]
    assert "CLP" not in outcome("REORG TABLE t;\n", named)[2]


def test_blanks_field_is_read_by_the_assembly():
    script = "VALUES 1;" + VT + "-- c\nVALUES 2;\n"
    assert outcome(script)[:2] == ["error", "UnsafeStatementSplitError"]
    assert outcome(script)[2].startswith("line 2 has code after a ';'")
    wide = replace(DB2_SPEC, terminator_script=replace(DB2_RULES, blanks=" \t" + VT))
    assert outcome(script, wide) == [
        "records",
        ["VALUES 1", 1, ";", "sql", 0, 15],
        ["VALUES 2", 2, ";", "sql", 15, 25],
    ]


def test_line_comment_field_is_read_by_the_overlap_rule():
    script = "--#SET TERMINATOR /*\nVALUES 1 #/*\nVALUES 2/*\n"
    other = replace(DB2_SPEC, terminator_script=replace(DB2_RULES, line_comment="#"))
    refused = outcome(script, other)
    assert refused[:2] == ["error", "UnsafeStatementSplitError"]
    assert refused[2].startswith("line 3 ends with '/*', which is also part of a comment delimiter")
    assert outcome(script)[2].startswith("line 2 ends with '/*', which is also part")


def test_blanks_field_is_read_for_the_statement_start():
    script = VT + "VALUES 1;\n"
    assert outcome(script) == ["records", ["VALUES 1", 1, ";", "sql", 0, 11]]
    wide = replace(DB2_SPEC, terminator_script=replace(DB2_RULES, blanks=" \t" + VT))
    assert outcome(script, wide) == ["records", ["VALUES 1", 1, ";", "sql", 1, 11]]


def test_line_comment_field_is_read_by_the_semicolon_ending():
    script = "VALUES 1; -- c\nVALUES 2;\n"
    assert [r[0] for r in outcome(script)[1:]] == ["VALUES 1", "VALUES 2"]
    other = replace(DB2_SPEC, terminator_script=replace(DB2_RULES, line_comment="#"))
    assert outcome(script, other)[:2] == ["error", "UnsafeStatementSplitError"]
    assert outcome(script, other)[2].startswith("line 2 has code after a ';'")


def test_engine_analysis_view_matches_the_parser():
    engine = LexicalEngine(DB2_SPEC)
    for case in CASES["rows"]:
        if case["id"] in ("row24", "row13a", "row27", "row22a", "row15", "row1"):
            records = engine.split(case["script"])
            assert engine.split_for_analysis(case["script"]) == analysis_sql(records)
            assert engine.split_for_analysis(case["script"]) == [
                r.text for r in records if r.kind == "sql"
            ]
    script = "--#SET TERMINATOR @\nVALUES 1@\nVALUES 2;\n"
    assert any(r.kind == "directive" for r in engine.split(script))
    assert engine.split_for_analysis(script) == ["VALUES 1", "VALUES 2;"]


def test_blank_comments_refuses_terminator_specs():
    with pytest.raises(NotImplementedError):
        LexicalEngine(DB2_SPEC).blank_comments("VALUES 1;")


def test_split_statements_are_the_sql_texts_without_terminators():
    engine = LexicalEngine(DB2_SPEC)
    assert engine.split_statements(
        "--#SET TERMINATOR @\nVALUES 1@\n--#SET TERMINATOR ;\nVALUES 2 -- c\n;\nQUIT;\n"
    ) == [
        "VALUES 1",
        "VALUES 2 -- c",
    ]


def test_core_modules_carry_no_client_text():
    root = Path(__file__).resolve().parents[4] / "dblift" / "core"
    needles = ("CLP", "ibm_db", "TERMINATOR", "QUIT", "one or two", "db2", "Db2", "DB2")
    for name in ("terminator_lines.py", "terminator_script.py"):
        source = (root / "sql_parser" / name).read_text(encoding="utf-8")
        assert [n for n in needles if n in source] == [], name
