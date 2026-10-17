"""A statement keeps the characters at its edges that its engine does not read as blanks.

``text_blanks`` is the set of characters a record builder may strip from the ends of a statement. It
is measured per engine (docs/sql-parsing/<dialect>.md). The contract tested here: a character of
that set at the edge of a statement is stripped, any other is kept, in the text that is executed and
in the text that is analysed. DuckDB's end-of-text rule is its own (docs/sql-parsing/duckdb.md).
"""

from __future__ import annotations

import warnings
from typing import Dict, List, Optional

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.db.provider_registry import ProviderRegistry
from tests.support.statement_edge_corpus import record_script

ASCII_BLANKS = " \t\n\r"
FORM_FEED, VERTICAL_TAB = chr(0x0C), chr(0x0B)
SQLSERVER_UNICODE = "".join(chr(c) for c in (0x85, 0xA0, 0x2003, 0x200B, 0x2028, 0x3000))
DUCKDB_UNICODE = "".join(
    chr(c) for c in (0xA0, *range(0x2000, 0x200C), 0x202F, 0x205F, 0x2060, 0x3000, 0xFEFF)
)

#: dialect -> the measured set (docs/sql-parsing); Redshift and Snowflake keep the intersection of
#: the measured engines until they are probed.
TEXT_BLANKS: Dict[str, str] = {
    "postgresql": ASCII_BLANKS + FORM_FEED,
    "cockroachdb": ASCII_BLANKS + FORM_FEED,
    "yugabytedb": ASCII_BLANKS + FORM_FEED,
    "redshift": ASCII_BLANKS,
    "mysql": ASCII_BLANKS + VERTICAL_TAB + FORM_FEED,
    "mariadb": ASCII_BLANKS + VERTICAL_TAB + FORM_FEED,
    "db2": ASCII_BLANKS,
    "oracle": ASCII_BLANKS + VERTICAL_TAB + FORM_FEED + chr(0x3000),
    "sqlserver": ASCII_BLANKS + VERTICAL_TAB + FORM_FEED + SQLSERVER_UNICODE,
    "snowflake": ASCII_BLANKS,
    "sqlite": ASCII_BLANKS + FORM_FEED,
    "duckdb": ASCII_BLANKS + FORM_FEED + VERTICAL_TAB + DUCKDB_UNICODE,
}
SPECS = [
    "postgresql",
    "redshift",
    "mysql",
    "mariadb",
    "db2",
    "oracle",
    "sqlserver",
    "sqlite",
    "duckdb",
]


def spec_of(dialect: str) -> Optional[LexicalSpec]:
    return ProviderRegistry.get_quirks(dialect).lexical_spec()


DUCKDB_WIDENING = pytest.mark.xfail(
    strict=True, reason="DuckDB's set is widened together with its record builder"
)


@pytest.mark.parametrize(
    "dialect",
    [
        *(d for d in SPECS if d != "duckdb"),
        "cockroachdb",
        "yugabytedb",
        pytest.param("duckdb", marks=DUCKDB_WIDENING),
    ],
)
def test_every_spec_holds_the_measured_text_blanks(dialect: str) -> None:
    spec = spec_of(dialect)
    assert spec is not None
    assert set(spec.text_blanks) == set(TEXT_BLANKS[dialect])


def test_text_blanks_is_required_and_never_empty() -> None:
    with pytest.raises(TypeError):
        LexicalSpec(name="x")  # type: ignore[call-arg]
    with pytest.raises(ValueError):
        LexicalSpec(name="x", text_blanks="")


CHARACTERS = [
    chr(0xA0),
    chr(0x3000),
    chr(0x2003),
    chr(0x200B),
    chr(0xFEFF),
    chr(0x85),
    chr(0x2028),
    chr(0x2029),
    "\t",
    VERTICAL_TAB,
    FORM_FEED,
]
PSQL_LIKE = ("postgresql", "redshift", "cockroachdb", "yugabytedb")
CONTRACT_DIALECTS = [
    *PSQL_LIKE,
    "mysql",
    "mariadb",
    "db2",
    "oracle",
    "sqlserver",
    "snowflake",
    "sqlite",
]
#: where the leading edge of a statement text is a character of the script (the PostgreSQL-family and
#: Oracle tokenizers start a record at its first token, which is outside this lot)
LEADING = ("mysql", "mariadb", "db2", "sqlserver", "snowflake", "sqlite")
POSITIONS = {
    "before_terminator": "DROP TABLE t{c};\nSELECT 1;",
    "end_of_file": "SELECT 1;\nDROP TABLE t{c}",
    "leading": "{c}DROP TABLE t;\nSELECT 1;",
}


#: Dialects whose record builders already strip exactly their text_blanks.
FIXED_DIALECTS = (*PSQL_LIKE, "oracle", "sqlserver")


def keeps_the_terminator_in_the_text(dialect: str, position: str, view: str) -> bool:
    """The character sits inside a text that holds its terminator, so it is not at the text's edge."""
    return position == "before_terminator" and (
        (view == "execution" and dialect in (*PSQL_LIKE, "oracle")) or dialect == "sqlserver"
    )


def stripped_today(dialect: str, position: str, view: str, char: str) -> bool:
    """Whether the splitters, as they are, remove ``char`` from that edge."""
    if position == "leading" and dialect in ("mysql", "mariadb"):
        return char in ASCII_BLANKS + VERTICAL_TAB + FORM_FEED
    if dialect in FIXED_DIALECTS:
        return char in TEXT_BLANKS[dialect]
    if not char.isspace():
        return False
    if dialect == "sqlite":
        return char in ASCII_BLANKS + FORM_FEED
    if keeps_the_terminator_in_the_text(dialect, position, view):
        return False
    return True


def find_statement(statements: List[str]) -> str:
    text = next(s for s in statements if "DROP TABLE" in s)
    return text[:-1] if text.endswith(";") else text


def cases() -> List[object]:
    out = []
    for dialect in CONTRACT_DIALECTS:
        for position in POSITIONS:
            if position == "leading" and dialect not in LEADING:
                continue
            for view in ("execution", "analysis"):
                for char in CHARACTERS:
                    if position == "leading" and char == chr(0xFEFF):
                        continue  # a byte order mark at the start of a script is file encoding
                    inside = char in TEXT_BLANKS[dialect]
                    composite = keeps_the_terminator_in_the_text(dialect, position, view)
                    if composite and inside:
                        continue  # the blank sits inside a text that holds its terminator
                    red = stripped_today(dialect, position, view, char) != inside
                    marks = (
                        [
                            pytest.mark.xfail(
                                strict=True,
                                reason="a record builder strips what text_blanks does not hold, or keeps what it does",
                            )
                        ]
                        if red
                        else []
                    )
                    out.append(
                        pytest.param(
                            dialect,
                            position,
                            view,
                            char,
                            marks=marks,
                            id=f"{dialect}-{position}-{view}-U+{ord(char):04X}",
                        )
                    )
    return out


@pytest.mark.parametrize("dialect,position,view,char", cases())
def test_a_statement_edge_loses_only_the_characters_of_text_blanks(
    dialect: str, position: str, view: str, char: str
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recorded = record_script(dialect, POSITIONS[position].format(c=char))[view]
    inside = char in TEXT_BLANKS[dialect]
    if dialect == "oracle" and char.isspace() and not inside:
        # python-oracledb would strip the character and the engine rejects it: refused, not kept
        assert isinstance(recorded, dict), recorded
        return
    assert not isinstance(recorded, dict), recorded
    text = find_statement(recorded)
    body = "DROP TABLE t"
    expected = body if inside else (char + body if position == "leading" else body + char)
    if dialect == "sqlserver" and view == "execution":  # one batch holds both statements
        text = recorded[0]
        ok = {
            "end_of_file": text.endswith(expected),
            "leading": text.startswith(expected),
            "before_terminator": expected + ";" in text,
        }[position]
    else:
        ok = text == expected
    assert ok, f"U+{ord(char):04X}: got {text!r}, expected {expected!r}"
