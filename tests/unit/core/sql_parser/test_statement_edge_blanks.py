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
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.db.provider_registry import ProviderRegistry
from tests.support.statement_edge_corpus import record_script

ASCII_BLANKS = " \t\n\r"
FORM_FEED, VERTICAL_TAB = chr(0x0C), chr(0x0B)
SQLSERVER_UNICODE = "".join(chr(c) for c in (0x85, 0xA0, 0x2003, 0x200B, 0x2028, 0x3000))
DUCKDB_UNICODE = "".join(
    chr(c) for c in (0xA0, *range(0x2000, 0x200C), 0x202F, 0x205F, 0x2060, 0x3000, 0xFEFF)
)

#: dialect -> the measured set (docs/sql-parsing); DuckDB's vertical tab is no blank: the driver rejects it.
TEXT_BLANKS: Dict[str, str] = {
    "postgresql": ASCII_BLANKS + FORM_FEED,
    "cockroachdb": ASCII_BLANKS + FORM_FEED,
    "yugabytedb": ASCII_BLANKS + FORM_FEED,
    "redshift": ASCII_BLANKS + FORM_FEED,
    "mysql": ASCII_BLANKS + VERTICAL_TAB + FORM_FEED,
    "mariadb": ASCII_BLANKS + VERTICAL_TAB + FORM_FEED,
    "db2": ASCII_BLANKS,
    "oracle": ASCII_BLANKS + VERTICAL_TAB + FORM_FEED + chr(0x3000),
    "sqlserver": ASCII_BLANKS + VERTICAL_TAB + FORM_FEED + SQLSERVER_UNICODE,
    "snowflake": ASCII_BLANKS + chr(0x2002),
    "sqlite": ASCII_BLANKS + FORM_FEED,
    "duckdb": ASCII_BLANKS + FORM_FEED + DUCKDB_UNICODE,
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


@pytest.mark.parametrize(
    "dialect",
    [
        *SPECS,
        "cockroachdb",
        "yugabytedb",
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
FIXED_DIALECTS = (*PSQL_LIKE, "mysql", "mariadb", "oracle", "sqlserver", "snowflake", "db2")


def keeps_the_terminator_in_the_text(dialect: str, position: str, view: str) -> bool:
    """The character sits inside a text that holds its terminator, so it is not at the text's edge."""
    return position == "before_terminator" and (
        (view == "execution" and dialect in (*PSQL_LIKE, "oracle")) or dialect == "sqlserver"
    )


def stripped_today(dialect: str, position: str, view: str, char: str) -> bool:
    """Whether the splitters, as they are, remove ``char`` from that edge."""
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


@pytest.mark.parametrize("dialect", PSQL_LIKE)
def test_the_parts_of_a_psql_combined_statement_keep_a_character_outside_the_blanks(
    dialect: str,
) -> None:
    nbsp = chr(0xA0)
    script = f"SELECT 1{nbsp}\;SELECT 2{nbsp};"
    assert SqlAnalyzer(dialect).split_statements_for_analysis(script) == [
        f"SELECT 1{nbsp}",
        f"SELECT 2{nbsp}",
    ]


@pytest.mark.parametrize("dialect", PSQL_LIKE)
def test_a_copy_header_keeps_a_character_outside_the_blanks(dialect: str) -> None:
    script = f"COPY t (a) FROM STDIN{chr(0xA0)};\n1\n\\.\n"
    assert SqlAnalyzer(dialect).split_statements_for_analysis(script) == [
        f"COPY t (a) FROM STDIN{chr(0xA0)}"
    ]


def test_a_routine_batch_keeps_a_character_outside_the_blanks_when_analysis_divides_it() -> None:
    text = f"CREATE PROCEDURE p AS SELECT 1{chr(0x2029)}"
    assert SqlAnalyzer("sqlserver").split_statements_for_analysis(text) == [text]


NBSP = chr(0xA0)
DB2_BLOCK = (
    "--#SET TERMINATOR @\n"
    f"{NBSP}CREATE PROCEDURE p ()\nBEGIN\n  DECLARE x INT;\n  SET x = 1;\nEND{NBSP}@\n"
    f"SELECT 1 FROM t{NBSP} @\n"
)


@pytest.mark.parametrize("view", ["execution", "analysis"])
def test_db2_block_ended_by_a_set_terminator_keeps_a_character_outside_the_blanks(
    view: str,
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recorded = record_script("db2", DB2_BLOCK)[view]
    assert recorded == [
        f"{NBSP}CREATE PROCEDURE p ()\nBEGIN\n  DECLARE x INT;\n  SET x = 1;\nEND{NBSP}",
        f"SELECT 1 FROM t{NBSP}",
    ]


@pytest.mark.parametrize("view", ["execution", "analysis"])
@pytest.mark.parametrize("kept", [NBSP, "\x0c"])
def test_db2_record_made_only_of_kept_characters_is_a_statement(view: str, kept: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recorded = record_script("db2", f"VALUES 1;\n{kept};\nVALUES 2;")[view]
    assert recorded == ["VALUES 1", kept, "VALUES 2"]


def test_db2_comment_only_record_is_still_dropped() -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recorded = record_script("db2", f"VALUES 1;\n-- c{NBSP}\n;\nVALUES 2;")["execution"]
    assert recorded == ["VALUES 1", "VALUES 2"]


@pytest.mark.parametrize("view", ["execution", "analysis"])
@pytest.mark.parametrize(
    "record, script_tail",
    [
        (f"{NBSP} -- c", "\n;"),
        ("\x0c -- c", "\n;"),
        (f"{NBSP}/* c */", ";"),
        (f"/* c */{NBSP}", ";"),
    ],
)
def test_db2_record_of_kept_characters_and_a_comment_is_a_statement(
    view: str, record: str, script_tail: str
) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recorded = record_script("db2", f"VALUES 1;\n{record}{script_tail}\nVALUES 2;")[view]
    assert recorded == ["VALUES 1", record, "VALUES 2"]


@pytest.mark.parametrize("comment", [f"/* {NBSP} */", f"-- {NBSP}"])
def test_db2_kept_character_inside_a_comment_does_not_make_a_statement(comment: str) -> None:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        recorded = record_script("db2", f"VALUES 1;\n{comment}\n;\nVALUES 2;")["execution"]
    assert recorded == ["VALUES 1", "VALUES 2"]


@pytest.mark.parametrize("view", ["execution", "analysis"])
@pytest.mark.parametrize("kept", [NBSP, chr(0x3000), "\x1c"])
@pytest.mark.parametrize(
    "dialect", ["postgresql", "cockroachdb", "yugabytedb", "redshift", "aurora-postgresql"]
)
def test_postgresql_family_record_made_only_of_a_kept_character_is_a_statement(
    dialect: str, kept: str, view: str
) -> None:
    recorded = record_script(dialect, f"SELECT 1;\n{kept};\nSELECT 2;")[view]
    end = ";" if view == "execution" else ""
    assert recorded == [f"SELECT 1{end}", f"{kept}{end}", f"SELECT 2{end}"]


@pytest.mark.parametrize("blank", [" ", "\t", "\f"])
def test_postgresql_record_made_only_of_a_blank_is_still_dropped(blank: str) -> None:
    recorded = record_script("postgresql", f"SELECT 1;\n{blank};\nSELECT 2;")["execution"]
    assert recorded == ["SELECT 1;", "SELECT 2;"]


@pytest.mark.parametrize("dialect", ["postgresql", "cockroachdb", "yugabytedb", "redshift"])
@pytest.mark.parametrize(
    ("script", "execution", "analysis"),
    [
        (
            "SELECT 1;\n{k}\nSELECT 2;",
            ["SELECT 1;", "{k}\nSELECT 2;"],
            ["SELECT 1", "{k}\nSELECT 2"],
        ),
        ("{k}SELECT 1;", ["{k}SELECT 1;"], ["{k}SELECT 1"]),
        ("{k}DROP TABLE t;", ["{k}DROP TABLE t;"], ["{k}DROP TABLE t"]),
        ("SELECT 1;{k}", ["SELECT 1;", "{k}"], ["SELECT 1", "{k}"]),
    ],
)
@pytest.mark.parametrize("kept", [NBSP, chr(0x3000), "\x1c"])
def test_postgresql_family_kept_character_at_statement_edge_is_sent(
    kept: str, script: str, execution: List[str], analysis: List[str], dialect: str
) -> None:
    recorded = record_script(dialect, script.format(k=kept))
    assert recorded["execution"] == [e.format(k=kept) for e in execution]
    assert recorded["analysis"] == [a.format(k=kept) for a in analysis]


@pytest.mark.parametrize("dialect", ["postgresql", "redshift"])
def test_postgresql_family_statement_after_a_kept_character_starts_on_its_line(
    dialect: str,
) -> None:
    records = record_script(dialect, f"SELECT 1;\n{NBSP}\nSELECT 2;")["records"]
    assert [r["line"] for r in records] == [1, 2]


@pytest.mark.parametrize("dialect", ["postgresql", "cockroachdb", "yugabytedb", "redshift"])
@pytest.mark.parametrize("script", ["{f}SELECT 1;", "SELECT 1;{f}", "SELECT 1;\n{f};\nSELECT 2;"])
def test_postgresql_family_form_feed_at_statement_edge_is_still_a_blank(
    dialect: str, script: str
) -> None:
    recorded = record_script(dialect, script.format(f=FORM_FEED))["execution"]
    assert recorded == ["SELECT 1;"] + (["SELECT 2;"] if "SELECT 2" in script else [])
