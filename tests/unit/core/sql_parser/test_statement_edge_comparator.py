"""The comparator of two statement-edge recordings accepts one class of difference and nothing else.

The class: a character of ``str.isspace()`` that is not one of the dialect's ``text_blanks`` sits at a
statement's edge in the new recording and was trimmed in the old one. Every test builds the pair by hand.
"""

import copy
from typing import Any, Dict, List, Optional

from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from tests.support.statement_edge_comparator import compare_recordings

BLANKS = " \t\n\r"
NBSP = "\xa0"


def recording(
    script: str,
    execution: Any,
    analysis: Any,
    records: Optional[List[Dict[str, Any]]] = None,
    dialect: str = "demo",
) -> Dict[str, Any]:
    return {
        "dialect": dialect,
        "commit": "0" * 40,
        "scripts": {
            "s1": {
                "script": script,
                "execution": execution,
                "analysis": analysis,
                "records": records if records is not None else [],
            }
        },
    }


def record(text: str, start: int, end: int, line: int = 1) -> Dict[str, Any]:
    return {
        "text": text,
        "line": line,
        "terminator": None,
        "kind": "sql",
        "multi": False,
        "repeat": 1,
        "analysis_statements": None,
        "source_start": start,
        "source_end": end,
    }


def test_a_kept_trailing_character_outside_the_blanks_is_the_allowed_difference() -> None:
    script = "DROP TABLE t" + NBSP
    old = recording(
        script,
        ["DROP TABLE t"],
        ["DROP TABLE t"],
        [record("DROP TABLE t", 0, 13)],
    )
    new = recording(
        script,
        ["DROP TABLE t" + NBSP],
        ["DROP TABLE t" + NBSP],
        [record("DROP TABLE t" + NBSP, 0, 13)],
    )
    assert compare_recordings(old, new, BLANKS) == []


def test_a_kept_leading_character_and_its_shifted_line_and_offset_are_allowed() -> None:
    script = NBSP + "\nVALUES 1"
    old = recording(script, ["VALUES 1"], ["VALUES 1"], [record("VALUES 1", 2, 10, line=2)])
    new = recording(
        script,
        [NBSP + "\nVALUES 1"],
        [NBSP + "\nVALUES 1"],
        [record(NBSP + "\nVALUES 1", 0, 10, line=1)],
    )
    assert compare_recordings(old, new, BLANKS) == []


def test_an_identical_pair_has_no_difference() -> None:
    old = recording("SELECT 1", ["SELECT 1"], ["SELECT 1"], [record("SELECT 1", 0, 8)])
    assert compare_recordings(old, copy.deepcopy(old), BLANKS) == []


def test_a_difference_inside_a_statement_is_reported_with_its_offset() -> None:
    old = recording("SELECT 1", ["SELECT 1"], ["SELECT 1"])
    new = recording("SELECT 1", ["SELECT" + NBSP + "1"], ["SELECT 1"])
    [found] = compare_recordings(old, new, BLANKS)
    assert (found.dialect, found.script_id, found.view) == ("demo", "s1", "execution")
    assert (found.statement, found.offset) == (0, 6)


def test_a_removed_statement_is_reported() -> None:
    old = recording("a;b", ["a", "b"], ["a", "b"])
    new = recording("a;b", ["a"], ["a", "b"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution"
    assert "2 statements" in found.detail and "1" in found.detail


def test_an_added_statement_is_reported() -> None:
    old = recording("a", ["a"], ["a"])
    new = recording("a", ["a", NBSP], ["a"])
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution"]


def test_a_blank_of_the_dialect_kept_at_an_edge_is_reported() -> None:
    old = recording("SELECT 1\t", ["SELECT 1"], ["SELECT 1"])
    new = recording("SELECT 1\t", ["SELECT 1\t"], ["SELECT 1"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution" and found.offset == 8


def test_a_character_that_is_not_whitespace_kept_at_an_edge_is_reported() -> None:
    zero_width_space = "​"
    old = recording("SELECT 1", ["SELECT 1"], ["SELECT 1"])
    new = recording("SELECT 1", ["SELECT 1" + zero_width_space], ["SELECT 1"])
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution"]


def test_a_blank_the_new_text_no_longer_keeps_is_not_a_difference_in_the_other_direction() -> None:
    """Removing a character from the old text's edge that the dialect does not read as a blank is the
    mirror image of the allowed class: the old recording is the one that trimmed, never the new one.
    """
    old = recording("SELECT 1" + NBSP, ["SELECT 1" + NBSP], ["SELECT 1"])
    new = recording("SELECT 1" + NBSP, ["SELECT 1"], ["SELECT 1"])
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution"]


def test_a_changed_record_field_other_than_the_text_and_its_span_is_reported() -> None:
    old = recording("a;", ["a"], ["a"], [record("a", 0, 2)])
    changed = record("a", 0, 2)
    changed["terminator"] = ";"
    new = recording("a;", ["a"], ["a"], [changed])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and "terminator" in found.detail


def test_a_record_span_that_moves_to_cover_other_text_is_reported() -> None:
    script = "SELECT 1; SELECT 2"
    old = recording(script, [], [], [record("SELECT 1", 0, 9)])
    new = recording(script, [], [], [record("SELECT 1", 0, 18)])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and "span" in found.detail


def test_a_changed_line_that_the_kept_leading_text_does_not_explain_is_reported() -> None:
    script = "\n\nSELECT 1"
    old = recording(script, [], [], [record("SELECT 1", 2, 10, line=3)])
    new = recording(script, [], [], [record("SELECT 1", 2, 10, line=1)])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and "line" in found.detail


def test_a_line_shifted_by_a_record_line_break_in_kept_leading_text_is_allowed_only_by_its_count() -> (
    None
):
    script = NBSP + "\n\nSELECT 1"
    old = recording(script, [], [], [record("SELECT 1", 3, 11, line=3)])
    ok = recording(script, [], [], [record(NBSP + "\n\nSELECT 1", 0, 11, line=1)])
    wrong = recording(script, [], [], [record(NBSP + "\n\nSELECT 1", 0, 11, line=2)])
    assert compare_recordings(old, ok, BLANKS) == []
    assert [d.view for d in compare_recordings(old, wrong, BLANKS)] == ["records"]


def test_the_analysis_statements_of_a_record_follow_the_same_rule() -> None:
    old_record = record("a", 0, 3)
    old_record["analysis_statements"] = ["a"]
    kept = record("a" + NBSP, 0, 3)
    kept["analysis_statements"] = ["a" + NBSP]
    mid = record("a" + NBSP, 0, 3)
    mid["analysis_statements"] = ["b"]
    old = recording("a" + NBSP, [], [], [old_record])
    assert compare_recordings(old, recording("a" + NBSP, [], [], [kept]), BLANKS) == []
    [found] = compare_recordings(old, recording("a" + NBSP, [], [], [mid]), BLANKS)
    assert found.view == "records" and "analysis_statements" in found.detail


def test_an_error_must_be_the_same_error() -> None:
    old = recording("x", {"error": ["E", "m"]}, ["x"])
    same = recording("x", {"error": ["E", "m"]}, ["x"])
    other = recording("x", {"error": ["E", "n"]}, ["x"])
    turned_ok = recording("x", ["x"], ["x"])
    assert compare_recordings(old, same, BLANKS) == []
    assert [d.view for d in compare_recordings(old, other, BLANKS)] == ["execution"]
    assert [d.view for d in compare_recordings(old, turned_ok, BLANKS)] == ["execution"]


def test_a_script_missing_from_the_new_recording_is_reported() -> None:
    old = recording("x", ["x"], ["x"])
    new = copy.deepcopy(old)
    new["scripts"] = {}
    [found] = compare_recordings(old, new, BLANKS)
    assert found.script_id == "s1" and found.view == "script"


def test_a_script_text_that_differs_between_recordings_is_reported() -> None:
    old = recording("x", ["x"], ["x"])
    new = recording("y", ["x"], ["x"])
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["script"]


def test_a_difference_that_only_the_analysis_view_holds_is_reported() -> None:
    old = recording("SELECT 1", ["SELECT 1"], ["SELECT 1"])
    new = recording("SELECT 1", ["SELECT 1"], ["SELECT" + NBSP + "1"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "analysis" and found.offset == 6


def test_a_blank_of_the_dialect_kept_at_the_leading_edge_is_reported() -> None:
    old = recording("\tSELECT 1", ["SELECT 1"], ["SELECT 1"])
    new = recording("\tSELECT 1", ["\tSELECT 1"], ["SELECT 1"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution" and found.offset == 0


def test_a_leading_run_shorter_than_the_old_one_is_reported() -> None:
    old = recording(NBSP + "SELECT 1", [NBSP + "SELECT 1"], ["SELECT 1"])
    new = recording(NBSP + "SELECT 1", ["SELECT 1"], ["SELECT 1"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution"


def test_a_kept_run_must_hold_the_characters_the_script_holds() -> None:
    em_space = "\u3000"
    old = recording("DROP TABLE t" + NBSP, ["DROP TABLE t"], ["DROP TABLE t"])
    new = recording("DROP TABLE t" + NBSP, ["DROP TABLE t" + em_space], ["DROP TABLE t"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution" and "script" in found.detail


def test_a_kept_run_may_not_replace_the_run_the_old_text_held() -> None:
    old = recording("t" + NBSP, ["t" + NBSP], ["t" + NBSP])
    new = recording("t" + NBSP, ["t\u3000\u3000"], ["t" + NBSP])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution"


def test_a_leading_run_may_not_replace_the_run_the_old_text_held() -> None:
    old = recording(NBSP + "t", [NBSP + "t"], [NBSP + "t"])
    new = recording(NBSP + "t", ["\u3000t"], [NBSP + "t"])
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution"]


def test_one_character_of_the_script_cannot_be_kept_by_two_statements() -> None:
    script = "SELECT 1\n" + NBSP + "SELECT 2"
    old = recording(script, ["SELECT 1", "SELECT 2"], ["SELECT 1", "SELECT 2"])
    new = recording(script, ["SELECT 1" + NBSP, NBSP + "SELECT 2"], ["SELECT 1", "SELECT 2"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution" and found.statement == 0


def test_a_kept_character_claimed_twice_in_a_row_is_reported() -> None:
    script = "SELECT 1" + NBSP + "SELECT 2"
    old = recording(script, ["SELECT 1", "SELECT 2"], ["SELECT 1", "SELECT 2"])
    new = recording(script, ["SELECT 1" + NBSP, NBSP + "SELECT 2"], ["SELECT 1", "SELECT 2"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution" and found.statement == 1 and "already kept" in found.detail


def test_a_record_whose_text_keeps_a_leading_run_but_whose_span_did_not_move_is_reported() -> None:
    script = NBSP + "\nVALUES 1"
    old = recording(script, [], [], [record("VALUES 1", 2, 10, line=2)])
    new = recording(script, [], [], [record(NBSP + "\nVALUES 1", 2, 10, line=1)])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and "span" in found.detail


def test_a_record_whose_span_moved_but_whose_text_did_not_is_reported() -> None:
    script = NBSP + "\nVALUES 1"
    old = recording(script, [], [], [record("VALUES 1", 2, 10, line=2)])
    new = recording(script, [], [], [record("VALUES 1", 0, 10, line=2)])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and "span" in found.detail


def test_a_span_that_stops_at_the_last_token_is_accepted_when_it_did_before() -> None:
    """A record whose span never held the trailing character keeps not holding it."""
    script = "DROP TABLE t" + NBSP
    old = recording(script, [], [], [record("DROP TABLE t", 0, 12)])
    new = recording(script, [], [], [record("DROP TABLE t" + NBSP, 0, 12)])
    assert compare_recordings(old, new, BLANKS) == []


def test_a_span_that_gains_a_trailing_run_the_text_lacks_is_reported() -> None:
    script = "DROP TABLE t" + NBSP
    old = recording(script, [], [], [record("DROP TABLE t", 0, 12)])
    new = recording(script, [], [], [record("DROP TABLE t", 0, 13)])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and "span" in found.detail


def test_a_terminator_after_the_kept_run_does_not_count_as_part_of_the_span_run() -> None:
    script = "DROP TABLE t" + NBSP + ";"
    old_record = record("DROP TABLE t", 0, 14)
    old_record["terminator"] = ";"
    new_record = record("DROP TABLE t" + NBSP, 0, 14)
    new_record["terminator"] = ";"
    old = recording(script, [], [], [old_record])
    assert compare_recordings(old, recording(script, [], [], [new_record]), BLANKS) == []


def test_a_record_missing_a_field_is_reported_not_raised() -> None:
    old = recording("a", [], [], [record("a", 0, 1)])
    no_terminator = record("a", 0, 1)
    del no_terminator["terminator"]
    no_text = record("a", 0, 1)
    del no_text["text"]
    [first] = compare_recordings(old, recording("a", [], [], [no_terminator]), BLANKS)
    [second] = compare_recordings(old, recording("a", [], [], [no_text]), BLANKS)
    assert first.view == second.view == "records"
    assert "terminator" in first.detail and "text" in second.detail
    [third] = compare_recordings(recording("a", [], [], [no_text]), old, BLANKS)
    assert "text" in third.detail


def test_one_character_of_the_script_cannot_be_kept_by_two_records() -> None:
    script = "SELECT 1" + NBSP + "SELECT 2"
    old = recording(script, [], [], [record("SELECT 1", 0, 8), record("SELECT 2", 9, 17)])
    new = recording(
        script,
        [],
        [],
        [record("SELECT 1" + NBSP, 0, 9), record(NBSP + "SELECT 2", 8, 17)],
    )
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and found.statement == 1


def test_a_span_that_no_longer_reaches_the_text_is_reported_by_its_slice() -> None:
    """The span does not hold the text's core (a record that ends in a comment), so only the slice
    of the script it covers can show that it shrank."""
    script = "SELECT 1" + NBSP
    old = recording(script, [], [], [record("SELECT 1", 0, 9)])
    new = recording(script, [], [], [record("SELECT 1" + NBSP, 0, 3)])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and "span" in found.detail


def test_a_span_that_covered_the_kept_run_may_not_stop_short_of_it() -> None:
    script = "SELECT 1" + NBSP
    old = recording(script, [], [], [record("SELECT 1", 0, 9)])
    new = recording(script, [], [], [record("SELECT 1" + NBSP, 0, 8)])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "records" and "span" in found.detail


def test_a_changed_statement_that_the_script_does_not_hold_is_reported() -> None:
    old = recording("SELECT 1", ["x"], ["x"])
    new = recording("SELECT 1", ["x" + NBSP], ["x"])
    [found] = compare_recordings(old, new, BLANKS)
    assert found.view == "execution" and "not found" in found.detail


def test_an_unchanged_statement_that_the_script_does_not_hold_is_not_a_difference() -> None:
    old = recording("SELECT 1", ["x"], ["x"], [record("x", 0, 1)])
    assert compare_recordings(old, copy.deepcopy(old), BLANKS) == []


def test_a_statement_joined_across_a_psql_combined_separator_is_located() -> None:
    script = "SELECT 1\\;SELECT 2;" + NBSP
    old = recording(script, ["SELECT 1;SELECT 2;"], [])
    kept = recording(script, ["SELECT 1;SELECT 2;" + NBSP], [])
    foreign = recording(script, ["SELECT 1;SELECT 2;\u2003"], [])
    assert compare_recordings(old, kept, BLANKS) == []
    [found] = compare_recordings(old, foreign, BLANKS)
    assert found.view == "execution" and "script" in found.detail


def test_a_foreign_character_appended_to_a_real_psql_combined_recording_is_reported() -> None:
    from tests.support.statement_edge_corpus import record_dialect

    old = record_dialect("postgresql", commit="c" * 40)
    script_id = "psql_combined_leading-U+00A0"
    assert compare_recordings(old, copy.deepcopy(old), BLANKS) == []
    for path in ("execution", "records"):
        new = copy.deepcopy(old)
        entry = new["scripts"][script_id]
        if path == "execution":
            entry["execution"][0] += " "
        else:
            entry["records"][0]["text"] += " "
        found = [d for d in compare_recordings(old, new, BLANKS) if d.script_id == script_id]
        assert [d.view for d in found] == [path], path


def test_a_span_may_hold_the_blanks_and_the_separator_line_around_the_kept_run() -> None:
    vt = "\x0b"
    script = "DROP TABLE t" + vt + "\nGO\n"
    old = record("DROP TABLE t", 0, len(script))
    old["terminator"] = "GO"
    new = record("DROP TABLE t" + vt, 0, len(script))
    new["terminator"] = "GO"
    assert (
        compare_recordings(
            recording(script, [], [], [old]), recording(script, [], [], [new]), BLANKS
        )
        == []
    )


def test_a_span_whose_kept_run_is_not_the_texts_is_still_reported() -> None:
    script = "DROP TABLE t" + NBSP + "\x0b\n"
    old = record("DROP TABLE t", 0, len(script))
    new = record("DROP TABLE t" + NBSP, 0, len(script))
    found = compare_recordings(
        recording(script, [], [], [old]), recording(script, [], [], [new]), BLANKS
    )
    assert [d.detail for d in found] == [
        "span: its trailing characters differ from the text's kept run"
    ]


def test_a_span_may_hold_a_blank_of_the_dialect_before_the_kept_leading_run() -> None:
    script = " " + NBSP + "DROP TABLE t"
    old = record("DROP TABLE t", 0, len(script))
    new = record(NBSP + "DROP TABLE t", 0, len(script))
    assert (
        compare_recordings(
            recording(script, [], [], [old]), recording(script, [], [], [new]), BLANKS
        )
        == []
    )


OUTSIDE_SET_REFUSAL = (
    "UnsafeStatementSplitError",
    "U+00A0 at line 1, column 13 is at the edge of a statement: the driver would strip it",
)


def refused_pair(dialect: str, script: str, refusal: Any) -> List[Any]:
    old = recording(script, ["DROP TABLE t"], ["DROP TABLE t"], dialect=dialect)
    new = recording(script, {"error": list(refusal)}, ["DROP TABLE t"], dialect=dialect)
    return compare_recordings(old, new, BLANKS)


def test_a_refusal_at_the_reported_character_outside_the_blanks_is_declared_for_oracle() -> None:
    assert refused_pair("oracle", "DROP TABLE t" + NBSP, OUTSIDE_SET_REFUSAL) == []


def test_a_refusal_is_not_declared_for_another_dialect() -> None:
    found = refused_pair("postgresql", "DROP TABLE t" + NBSP, OUTSIDE_SET_REFUSAL)
    assert [d.view for d in found] == ["execution"]


def test_a_refusal_that_reports_a_position_holding_another_character_is_reported() -> None:
    wrong_column = (OUTSIDE_SET_REFUSAL[0], OUTSIDE_SET_REFUSAL[1].replace("column 13", "column 5"))
    assert [d.view for d in refused_pair("oracle", "DROP TABLE t" + NBSP, wrong_column)] == [
        "execution"
    ]


def test_a_refusal_at_a_blank_of_the_dialect_is_reported() -> None:
    ideographic = (OUTSIDE_SET_REFUSAL[0], OUTSIDE_SET_REFUSAL[1].replace("U+00A0", "U+3000"))
    script = "DROP TABLE t" + chr(0x3000)
    assert [d.view for d in refused_pair("oracle", script, ideographic)] == ["execution"]


def zero_width_pair(dialect: str) -> List[Any]:
    zwsp = chr(0x200B)
    script = "DROP TABLE t" + zwsp
    old = recording(script, ["DROP TABLE t" + zwsp], ["DROP TABLE t" + zwsp], dialect=dialect)
    new = recording(script, ["DROP TABLE t"], ["DROP TABLE t"], dialect=dialect)
    return compare_recordings(old, new, BLANKS)


def test_a_zero_width_space_stripped_on_the_new_side_is_declared_for_sql_server() -> None:
    assert zero_width_pair("sqlserver") == []


def test_a_zero_width_space_stripped_on_the_new_side_is_reported_for_another_dialect() -> None:
    assert {d.view for d in zero_width_pair("postgresql")} == {"execution", "analysis"}


def test_a_refusal_with_the_providers_full_message_is_declared_for_oracle() -> None:
    full = (
        OUTSIDE_SET_REFUSAL[0],
        "U+00A0 at line 1, column 13 is at the edge of a statement: the driver removes it before "
        "it sends the statement; remove the character",
    )
    assert refused_pair("oracle", "DROP TABLE t" + NBSP, full) == []


def test_a_zero_width_space_is_declared_when_it_is_also_one_of_the_dialects_blanks() -> None:
    zwsp = chr(0x200B)
    script = zwsp + "SELECT 2" + zwsp
    old = recording(script, [script], [script], dialect="sqlserver")
    new = recording(script, ["SELECT 2"], ["SELECT 2"], dialect="sqlserver")
    assert compare_recordings(old, new, BLANKS + zwsp) == []


def refusal_for(char: str, column: int) -> Any:
    return (
        OUTSIDE_SET_REFUSAL[0],
        f"U+{ord(char):04X} at line 1, column {column} is at the edge of a statement: "
        "the driver would strip it",
    )


def span_record(script: str, start: int, end: int) -> Dict[str, Any]:
    return record(script[start:end], start, end)


def edge_refusal_pair(script: str, char: str, column: int) -> List[Any]:
    start, end = len(script) - len(script.lstrip()), len(script.rstrip())
    old = recording(script, ["x"], ["x"], [span_record(script, start, end)], dialect="oracle")
    new = recording(
        script,
        {"error": list(refusal_for(char, column))},
        ["x"],
        [span_record(script, start, end)],
        dialect="oracle",
    )
    return compare_recordings(old, new, BLANKS)


def test_the_oracle_refusal_exception_follows_the_blanks_of_the_oracle_spec() -> None:
    whitespace = [chr(i) for i in range(0x110000) if chr(i).isspace()]
    for char in whitespace:
        found = refused_pair("oracle", "DROP TABLE t" + char, refusal_for(char, 13))
        assert (found != []) == (char in ORACLE_SPEC.text_blanks), f"U+{ord(char):04X}"


def test_a_refusal_at_the_trailing_edge_of_a_record_is_declared() -> None:
    assert edge_refusal_pair("SELECT 1 FROM dual" + NBSP, NBSP, 19) == []


def test_a_refusal_at_the_leading_edge_of_a_record_is_declared() -> None:
    assert edge_refusal_pair(NBSP + "SELECT 1 FROM dual", NBSP, 1) == []


def test_a_refusal_at_an_interior_character_is_reported() -> None:
    script = "SELECT a" + NBSP + "b FROM dual"
    assert [d.view for d in edge_refusal_pair(script, NBSP, 9)] == ["execution"]


def test_a_refusal_naming_a_character_that_is_not_whitespace_is_reported() -> None:
    zwj = chr(0x200D)
    assert [d.view for d in edge_refusal_pair("SELECT 1 FROM dual" + zwj, zwj, 19)] == ["execution"]


def test_a_zero_width_space_kept_by_both_sides_is_not_a_difference_on_sql_server() -> None:
    zwsp = chr(0x200B)
    text = "DROP TABLE t" + zwsp
    rec = recording(text, [text], [text], dialect="sqlserver")
    assert compare_recordings(rec, rec, BLANKS) == []


def test_a_statement_of_kept_characters_that_the_old_recording_dropped_is_a_declared_count_change() -> (
    None
):
    script = f"VALUES 1;\n{NBSP};\nVALUES 2;"
    old = recording(
        script,
        ["VALUES 1", "VALUES 2"],
        ["VALUES 1", "VALUES 2"],
        [record("VALUES 1", 0, 10), record("VALUES 2", 14, 22, line=3)],
        dialect="db2",
    )
    new = recording(
        script,
        ["VALUES 1", NBSP, "VALUES 2"],
        ["VALUES 1", NBSP, "VALUES 2"],
        [
            record("VALUES 1", 0, 10),
            record(NBSP, 10, 13, line=2),
            record("VALUES 2", 14, 22, line=3),
        ],
        dialect="db2",
    )
    assert compare_recordings(old, new, BLANKS) == []


def test_an_added_statement_that_is_not_made_of_kept_characters_is_reported() -> None:
    script = "VALUES 1;\nVALUES 3;\nVALUES 2;"
    old = recording(script, ["VALUES 1", "VALUES 2"], ["VALUES 1", "VALUES 2"])
    new = recording(
        script, ["VALUES 1", "VALUES 3", "VALUES 2"], ["VALUES 1", "VALUES 2"], dialect="db2"
    )
    found = compare_recordings(old, new, BLANKS)
    assert [(d.view, d.detail) for d in found] == [("execution", "old has 2 statements, new has 3")]


def test_an_added_statement_of_kept_characters_that_the_script_does_not_hold_is_reported() -> None:
    script = "VALUES 1;\nVALUES 2;"
    old = recording(script, ["VALUES 1", "VALUES 2"], ["VALUES 1", "VALUES 2"])
    new = recording(script, ["VALUES 1", NBSP, "VALUES 2"], ["VALUES 1", "VALUES 2"], dialect="db2")
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution"]


def test_a_statement_of_kept_characters_is_reported_outside_db2() -> None:
    script = f"VALUES 1;\n{NBSP};\nVALUES 2;"
    old = recording(script, ["VALUES 1", "VALUES 2"], ["VALUES 1", "VALUES 2"])
    new = recording(script, ["VALUES 1", NBSP, "VALUES 2"], ["VALUES 1", NBSP, "VALUES 2"])
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution", "analysis"]


def test_a_statement_of_kept_characters_and_a_comment_is_a_declared_count_change() -> None:
    kept = f"{NBSP} -- c"
    script = f"VALUES 1;\n{kept}\n;\nVALUES 2;"
    old = recording(script, ["VALUES 1", "VALUES 2"], ["VALUES 1", "VALUES 2"], dialect="db2")
    new = recording(
        script,
        ["VALUES 1", kept, "VALUES 2"],
        ["VALUES 1", kept, "VALUES 2"],
        dialect="db2",
    )
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == []


def test_a_statement_of_kept_characters_in_another_place_than_the_script_holds_it_is_reported() -> (
    None
):
    script = f"VALUES 1;\nVALUES 2;\n{NBSP};"
    old = recording(script, ["VALUES 1", "VALUES 2"], ["VALUES 1", "VALUES 2"], dialect="db2")
    new = recording(
        script,
        [NBSP, "VALUES 1", "VALUES 2"],
        [NBSP, "VALUES 1", "VALUES 2"],
        dialect="db2",
    )
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution", "analysis"]


def test_a_statement_of_kept_characters_that_is_part_of_a_name_in_the_script_is_reported() -> None:
    script = f"DROP TABLE t{NBSP};\nVALUES 2;"
    old = recording(
        script, ["DROP TABLE t", "VALUES 2"], ["DROP TABLE t", "VALUES 2"], dialect="db2"
    )
    new = recording(
        script,
        [NBSP, "DROP TABLE t", "VALUES 2"],
        [NBSP, "DROP TABLE t", "VALUES 2"],
        dialect="db2",
    )
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution", "analysis"]


def test_a_statement_of_kept_characters_that_the_script_holds_only_inside_a_name_is_reported() -> (
    None
):
    name = f"DROP TABLE t{NBSP}"
    script = f"VALUES 1;\n{name};\nVALUES 2;"
    old = recording(script, ["VALUES 1", name, "VALUES 2"], ["VALUES 1", name, "VALUES 2"])
    new = recording(
        script,
        ["VALUES 1", name, NBSP, "VALUES 2"],
        ["VALUES 1", name, NBSP, "VALUES 2"],
        dialect="db2",
    )
    assert [d.view for d in compare_recordings(old, new, BLANKS)] == ["execution", "analysis"]
