"""The comparator of two statement-edge recordings accepts one class of difference and nothing else.

The class: a character of ``str.isspace()`` that is not one of the dialect's ``text_blanks`` sits at a
statement's edge in the new recording and was trimmed in the old one. Every test builds the pair by hand.
"""

import copy
from typing import Any, Dict, List, Optional

from tests.support.statement_edge_comparator import compare_recordings

BLANKS = " \t\n\r"
NBSP = "\xa0"


def recording(
    script: str,
    execution: Any,
    analysis: Any,
    records: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    return {
        "dialect": "demo",
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
