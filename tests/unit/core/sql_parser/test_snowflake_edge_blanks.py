"""Snowflake reads U+2002 (EN SPACE) as a blank at a statement edge and no other non-ASCII character.

Measured on Snowflake 10.37.102 through the Python connector, 2026-10-19: of 29 candidate Unicode and
C0 characters only U+2002 is read as a blank (trailing, leading, between tokens). The other 28 are
rejected with error 1003 / SQLSTATE 42000, so they stay in the statement text and Snowflake fails.
"""

from __future__ import annotations

import pytest

from tests.support.facts_parser import facts_parser
from tests.support.statement_edge_corpus import record_script

EN_SPACE = chr(0x2002)
REJECTED = [
    chr(c)
    for c in (
        0x0B,
        0x0C,
        0x85,
        0xA0,
        0x1680,
        0x2000,
        0x2001,
        *range(0x2003, 0x200B),
        0x2028,
        0x2029,
        0x202F,
        0x205F,
        0x3000,
        0x200B,
        0xFEFF,
        0x180E,
        *range(0x1C, 0x20),
    )
]


def views(script: str):
    recorded = record_script("snowflake", script)
    return recorded["execution"], recorded["analysis"]


@pytest.mark.parametrize("script", [f"DROP TABLE t{EN_SPACE};", f"DROP TABLE t{EN_SPACE}"])
def test_a_trailing_en_space_is_trimmed_from_both_views(script: str) -> None:
    execution, analysis = views(script)
    assert execution == ["DROP TABLE t"]
    assert analysis == ["DROP TABLE t"]


def test_a_leading_en_space_is_trimmed() -> None:
    execution, analysis = views(f"{EN_SPACE}DROP TABLE t;\nSELECT 1;")
    assert execution == ["DROP TABLE t", "SELECT 1"]
    assert analysis == ["DROP TABLE t", "SELECT 1"]


@pytest.mark.parametrize("script", [f"DROP TABLE t{EN_SPACE};", f"DROP TABLE t{EN_SPACE}"])
def test_the_name_before_a_trailing_en_space_is_read(script: str) -> None:
    parsed = facts_parser("snowflake").parse_sql(script)
    assert [s.names_unread for s in parsed.statements] == [False]
    assert [o.name.lower() for o in facts_parser("snowflake").extract_objects(script)] == ["t"]


def test_an_en_space_between_tokens_is_left_alone() -> None:
    script = f"CREATE{EN_SPACE}TABLE t (i INT);\nSELECT 1;"
    execution, analysis = views(script)
    assert execution == [f"CREATE{EN_SPACE}TABLE t (i INT)", "SELECT 1"]
    assert analysis == execution


@pytest.mark.parametrize("char", REJECTED, ids=lambda c: f"U+{ord(c):04X}")
@pytest.mark.parametrize(
    "template,expected",
    [
        ("DROP TABLE t{c};\nSELECT 1;", "DROP TABLE t{c}"),
        ("SELECT 1;\nDROP TABLE t{c}", "DROP TABLE t{c}"),
        ("{c}DROP TABLE t;\nSELECT 1;", "{c}DROP TABLE t"),
    ],
)
def test_a_character_snowflake_rejects_is_kept_at_the_edge(
    char: str, template: str, expected: str
) -> None:
    execution, analysis = views(template.format(c=char))
    wanted = expected.format(c=char)
    assert wanted in execution
    assert wanted in analysis
