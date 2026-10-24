"""A statement the grammar cannot model is classified from its leading words; the name read there
must end where the engine's name ends, or no name is reported."""

from __future__ import annotations

import pytest

from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.db.provider_registry import ProviderRegistry

TRIGGER = "CREATE TRIGGER {n} AFTER INSERT ON t BEGIN SELECT 1; END"

# Characters sqlite reads as part of a name although they are not word characters.
COMBINING_ACCENT = chr(0x0301)
JOINER = chr(0x200D)
SOFT_HYPHEN = chr(0x00AD)


@pytest.mark.parametrize(
    "name",
    [
        "cafe" + COMBINING_ACCENT,
        "a" + JOINER + "b",
        "x" + SOFT_HYPHEN + "z",
        "tr" + COMBINING_ACCENT + "x",
        COMBINING_ACCENT + "tr",
        "tr" + JOINER,
    ],
    ids=[
        "accent-after",
        "joiner-inside",
        "soft-hyphen-inside",
        "accent-inside",
        "accent-before",
        "joiner-after",
    ],
)
@pytest.mark.parametrize(
    "template",
    [
        TRIGGER,
        "CREATE TRIGGER s.{n} AFTER INSERT ON t BEGIN SELECT 1; END",
        "CREATE TRIGGER {n}.tr AFTER INSERT ON t BEGIN SELECT 1; END",
    ],
)
def test_head_name_ends_where_the_engine_name_ends(template, name):
    facts = ProviderRegistry.get_quirks("sqlite").statement_facts(template.format(n=name))

    assert facts.objects == ()
    assert facts.opaque


@pytest.mark.parametrize("control", [chr(0x1C), chr(0x1D), chr(0x1E), chr(0x1F)])
def test_head_name_must_start_after_an_ascii_blank(control):
    facts = read_statement_facts(
        f"CREATE TRIGGER{control}tr AFTER INSERT ON t BEGIN SELECT 1; END", dialect="sqlite"
    )

    assert facts.objects == ()


@pytest.mark.parametrize(
    ("sql", "names"),
    [
        (TRIGGER.format(n="tr"), ["tr"]),
        (TRIGGER.format(n="main.tr"), ["tr"]),
        (TRIGGER.format(n='"tr"'), ["tr"]),
        (TRIGGER.format(n="caf" + chr(0x00E9)), ["caf" + chr(0x00E9)]),
        ("CREATE TRIGGER tr\nAFTER INSERT ON t BEGIN SELECT 1; END", ["tr"]),
        ("CREATE TRIGGER tr\tAFTER INSERT ON t BEGIN SELECT 1; END", ["tr"]),
    ],
)
def test_plain_head_names_are_still_reported(sql, names):
    facts = ProviderRegistry.get_quirks("sqlite").statement_facts(sql)

    assert [o.name for o in facts.objects] == names
