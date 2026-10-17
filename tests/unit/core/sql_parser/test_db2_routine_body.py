"""Routine bodies of a Db2 script: kept whole, as the established splitter keeps them.

``db2_routine_cases.json`` holds, per case, the script and what the established Db2 splitter returned
for it. A field case names a field of the routine rules, the value to give it, the script, what the
established splitter returns once the words the field names are renamed to match (``expect``), and
what the default data returns for that script (``default``).
"""

import json
from dataclasses import fields, replace
from pathlib import Path

import pytest

from dblift.core.sql_parser.lexical_spec import RoutineRules
from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES, DB2_SPEC
from tests.unit.core.sql_parser.test_db2_terminator_script import check, outcome

CASES = json.loads(Path(__file__).with_name("db2_routine_cases.json").read_text(encoding="utf-8"))
SHAPES = {case["id"]: case for case in CASES["cases"]["shapes"]}
SINGLE_WORD_FIELDS = {
    "create_verb",
    "replace_word",
    "package_kind",
    "alter_verb",
    "body_open",
    "body_close",
    "case_word",
}


def pick(*ids):
    return pytest.mark.parametrize("case", [SHAPES[i] for i in ids], ids=list(ids))


def spec_with(**changes):
    routine = replace(DB2_RULES.routine, **changes)
    return replace(DB2_SPEC, terminator_script=replace(DB2_RULES, routine=routine))


@pytest.mark.parametrize(
    "case", CASES["cases"]["rows"], ids=[c["id"] for c in CASES["cases"]["rows"]]
)
def test_spec_rows_with_bodies(case):
    check(case)


@pick(
    "directive_in_body_under_at",
    "labelled_nested_under_at",
    "end_alone_then_terminator_line",
    "for_loop_under_at",
    "nested_begin_under_semicolon",
    "body_under_semicolon",
    "body_under_at_with_semicolons",
    "end_at_without_newline",
    "one_line_body",
    "nested_three_levels",
    "two_routines",
    "body_with_crlf",
    "bom_routine",
    "routine_then_command",
    "routine_epilogue",
    "terminator_in_comment_inside_body",
    "semicolon_after_body_then_comment",
    "begin_atomic_trailing_comment_ending",
)
def test_bodies_under_each_terminator(case):
    check(case)


@pick(
    "create_or_alter_procedure",
    "create_or_any_word_procedure",
    "create_or_replace_function",
    "create_or_only",
    "begin_not_atomic",
    "begin_lower_case",
    "begin_inside_parentheses",
    "begin_as_parameter_name",
    "begin_in_parameter_default",
    "specific_clause",
    "function_return_no_body",
    "function_return_case_expression",
    "create_module",
    "alter_module_add",
    "alter_module_publish",
    "alter_table",
    "trigger_begin_atomic",
    "method",
    "begin_as_column_name_is_head_of_create_table",
    "begin_led_word_boundary",
    "create_without_kind",
    "alter_without_kind",
    "begin_after_comment",
    "begin_after_directive_mid",
    "declaration_section_kept_old_shape",
    "label_compound_under_semicolon",
)
def test_routine_heads(case):
    check(case)


@pick(
    "end_qualifier_if",
    "end_qualifier_while",
    "end_qualifier_for",
    "end_qualifier_loop",
    "end_qualifier_repeat",
    "end_comment_between_qualifier",
    "end_label",
    "end_case_statement",
    "case_expression_in_body",
    "end_at_line_end_then_if_next_line",
    "end_at_line_end_then_label_next_line",
    "end_then_symbol",
    "end_then_string",
    "end_then_string_then_qualifier",
    "end_then_word_begin",
)
def test_end_qualifiers_and_labels(case):
    check(case)


@pick(
    "words_in_strings",
    "words_in_quoted_identifiers",
    "words_in_comments",
    "qualified_end_column",
)
def test_words_in_lexemes_count_for_nothing(case):
    check(case)


@pick("package_as", "package_body_is", "package_is", "package_in_parentheses_opener")
def test_package_opens_at_as_or_is(case):
    check(case)


@pick(
    "body_closed_then_stray",
    "stray_inside_body_ok",
    "stray_after_body",
)
def test_the_stray_terminator_character_around_bodies(case):
    check(case)


@pick(
    "unclosed_body",
    "unclosed_body_second_statement",
    "unclosed_body_nested",
    "unclosed_comment_before_body",
    "unclosed_body_then_directive",
    "ends_with_begin_word_only",
)
def test_an_unclosed_body_is_refused_after_an_unclosed_comment(case):
    check(case)
    if case["expect"][0] == "error":
        assert case["expect"][2].startswith(
            ("the routine body starting on line", "the block comment")
        )


FIELD_CASES = CASES["fields"]


@pytest.mark.parametrize("case", FIELD_CASES, ids=[c["id"] for c in FIELD_CASES])
def test_each_routine_rule_is_read(case):
    value = case["value"] if case["field"] in SINGLE_WORD_FIELDS else frozenset(case["value"])
    spec = spec_with(**{case["field"]: value})
    assert outcome(case["script"], spec) == case["expect"]
    assert outcome(case["script"]) == case["default"]
    assert case["expect"] != case["default"]


def test_every_routine_rule_has_a_case():
    named = {c["field"] for c in FIELD_CASES} | {"case_word"}
    assert named == {f.name for f in fields(RoutineRules)}


def test_case_word_closes_the_case_it_counted():
    script = (
        "CREATE PROCEDURE p()\nBEGIN\n  CASE x WHEN 0 THEN SET x = 1; END CASE;\n  SET y = 1;\nEND;\n"
        "VALUES 1;\n"
    )
    default = outcome(script)
    assert [r[0] for r in default[1:]] == [script.split("\nVALUES")[0][:-1], "VALUES 1"]
    other = outcome(script, spec_with(case_word="SWITCH"))
    assert other == [
        "error",
        "UnsafeStatementSplitError",
        "the routine body starting on line 1 is not closed before the end of the script",
    ]
