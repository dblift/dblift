"""The delimiter, DELIMITER lines and the records of a mysql or mariadb client script."""

import dataclasses
from dataclasses import replace
from pathlib import Path
from typing import List, Tuple

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.delimiter_script import DelimiterScript
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.statement import Statement
from dblift.db.plugins.mariadb.lexical_spec import MARIADB_SPEC
from dblift.db.plugins.mysql.parser.lexical_spec import MYSQL_RULES, MYSQL_SPEC
from tests.support.splitter_spec.spec_tables import load_conformance_rows
from tests.support.splitter_spec.splitting import SplitOutcome

BOTH = pytest.mark.parametrize("spec", [MYSQL_SPEC, MARIADB_SPEC], ids=["mysql", "mariadb"])
SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ROW_ORDER = (
    list(range(1, 4))
    + list(range(8, 15))
    + list(range(17, 20))
    + [23, 24]
    + list(range(26, 42))
    + list(range(43, 48))
    + [53, 55, 75]
    + list(range(80, 83))
)
WANTED = {str(n) for n in ROW_ORDER}
MYSQL_ONLY_ROWS = {"39a"}


def wanted(row_id: str) -> bool:
    base = row_id.rstrip("abcdefghijklmnopqrstuvwxyz")
    return base in WANTED or row_id in ("M1", "M2", "M7")


ROWS = [
    row
    for row in load_conformance_rows(SPEC_DIR)
    if row.dialect in ("mysql", "mariadb") and wanted(row.row_id)
]
RUNS = [
    pytest.param(
        MYSQL_SPEC if row.dialect == "mysql" else MARIADB_SPEC,
        row,
        id=f"{row.dialect}-{row.row_id}",
    )
    for row in ROWS
] + [
    pytest.param(MARIADB_SPEC, row, id=f"mariadb-on-mysql-{row.row_id}")
    for row in ROWS
    if row.dialect == "mysql" and row.row_id not in MYSQL_ONLY_ROWS
]


def outcome(spec: LexicalSpec, script: str) -> SplitOutcome:
    try:
        return SplitOutcome(statements=tuple(LexicalEngine(spec).split_statements(script)))
    except Exception as exc:  # noqa: BLE001 - the class is what the row expects
        return SplitOutcome(statements=(), error=type(exc).__name__, detail=str(exc))


def statements(script: str, spec: LexicalSpec = MYSQL_SPEC) -> List[str]:
    return LexicalEngine(spec).split_statements(script)


def refusal(script: str, spec: LexicalSpec = MYSQL_SPEC) -> str:
    with pytest.raises(UnsafeStatementSplitError) as caught:
        LexicalEngine(spec).split(script)
    return str(caught.value)


@pytest.mark.parametrize("spec, row", RUNS)
def test_spec_rows_are_read_by_the_engine(spec, row):
    assert outcome(spec, row.script).matches(row.expectation), (row.row_id, row.script)


def test_the_wanted_rows_are_there():
    assert len({row.row_id for row in ROWS if row.dialect == "mysql"}) >= 45
    assert {"85", "85a", "85b"}.isdisjoint({row.row_id for row in ROWS})


@BOTH
@pytest.mark.parametrize(
    "script, expected",
    [
        ("DELIMITER \"'$\"\nSELECT 'a''$\nSELECT 2'$", ["SELECT 'a'", "SELECT 2"]),
        ("DELIMITER '`x'\nSELECT 1 AS `a``x\nSELECT 2`x", ["SELECT 1 AS `a`", "SELECT 2"]),
        ('DELIMITER \'"x\'\nSELECT "a""x\nSELECT 2"x', ['SELECT "a"', "SELECT 2"]),
    ],
    ids=["85", "85a", "85b"],
)
def test_a_delimiter_led_by_a_quote_meets_a_doubled_quote(spec, script, expected):
    assert statements(script, spec) == expected


@BOTH
@pytest.mark.parametrize(
    "script, expected",
    [
        ("DELIMITER GO\nSELECT AGOB 1GO\n", ["SELECT A", "B 1"]),
        ("DELIMITER //\nSELECT 1///\nSELECT 2//\n", ["SELECT 1", "/\nSELECT 2"]),
        (
            "DELIMITER //\nSELECT '//' AS a, `//` AS b /* // */ # //\n, 2//\n",
            ["SELECT '//' AS a, `//` AS b /* // */ # //\n, 2"],
        ),
        ("DELIMITER //\nSELECT 1 -- //\n//\n", ["SELECT 1 -- //"]),
        ("DELIMITER //\nSELECT 1 /*! // */ + 1//\n", ["SELECT 1 /*!", "*/ + 1"]),
        ("DELIMITER //\nSELECT 1//SELECT 2//", ["SELECT 1", "SELECT 2"]),
        ("DELIMITER //\nSELECT 1//\nDELIMITER $$\nSELECT 2//3$$\n", ["SELECT 1", "SELECT 2//3"]),
    ],
)
def test_delimiter_is_a_plain_string(spec, script, expected):
    assert statements(script, spec) == expected


@BOTH
def test_delimiter_cache_resets_on_each_delimiter_line(spec):
    script = "DELIMITER AB\nSELECT 1AB\nDELIMITER B\nSELECT xABy B\n"
    assert statements(script, spec) == ["SELECT 1", "SELECT xA", "y"]


@BOTH
def test_delimiter_is_matched_before_blanks(spec):
    assert statements("delimiter\x0b\nSELECT 1\x0bSELECT 2", spec) == ["SELECT 1", "SELECT 2"]


@BOTH
@pytest.mark.parametrize("blank", [" ", "\t", "\r", "\x0b", "\x0c"], ids=repr)
def test_each_blank_of_the_client_is_skipped_before_a_delimiter(spec, blank):
    assert statements(f"{blank};SELECT 1;", spec) == ["SELECT 1"]


@BOTH
def test_blank_delimiter_quirks_are_kept(spec):
    assert statements("delimiter\x0b\nSELECT 1;", spec) == ["SELECT 1;"]
    assert statements("DELIMITER \x0c\nSELECT 1;", spec) == ["SELECT 1;"]


def test_delimiter_argument_rules():
    assert statements("DELIMITER 'a b'\nSELECT 1a b\n") == ["SELECT 1"]
    assert statements('DELIMITER "//" x\nSELECT 1//\n') == ["SELECT 1"]
    assert statements("DELIMITER `$$`\nSELECT 1$$\n") == ["SELECT 1"]
    assert statements("DELIMITER //\t x\nSELECT 1//\n") == ["SELECT 1//"]
    assert statements("DELIMITER\t//\nSELECT 1//\n") == ["SELECT 1"]
    assert statements("DELIMITER ;\nSELECT 1;") == ["SELECT 1"]
    assert statements("DELIMITER //\nSELECT 1 DELIMITER ;\n") == ["SELECT 1 DELIMITER ;"]

    def with_rules(**changes: object) -> LexicalSpec:
        return replace(MYSQL_SPEC, delimiter_script=replace(MYSQL_RULES, **changes))

    renamed = with_rules(command="DELIM")
    assert statements("DELIM //\nSELECT 1//\n", renamed) == ["SELECT 1"]
    assert statements("DELIMITER //\nSELECT 1//\n", renamed) == ["DELIMITER //\nSELECT 1//"]
    assert statements("SELECT 1$$SELECT 2;$$", with_rules(initial="$$")) == [
        "SELECT 1",
        "SELECT 2;",
    ]
    assert statements("SELECT 1;SELECT 2$$", with_rules(initial="$$")) == ["SELECT 1;SELECT 2"]
    under_initial = LexicalEngine(with_rules(initial="$$")).split("SELECT 1; SELECT 2$$")
    assert under_initial[0].analysis_statements is None
    assert statements("DELIMITER `$$`\nSELECT 1$$\n", with_rules(argument_quotes="'\"")) == [
        "SELECT 1$$"
    ]
    assert statements("DELIMITER 'a b'\nSELECT 1a b\n", with_rules(argument_quotes="`")) == [
        "SELECT 1a b"
    ]


@BOTH
def test_delimiter_length_limit(spec):
    assert statements("DELIMITER xxxxxxxxxxxxxxx\nSELECT 1xxxxxxxxxxxxxxx\n", spec) == ["SELECT 1"]
    message = (
        f"DELIMITER on line 1 is longer than 15 characters: the {spec.client_name} "
        "client silently keeps only the first ones"
    )
    assert refusal("DELIMITER xxxxxxxxxxxxxxxx\nSELECT 1;", spec) == message
    longer = replace(spec, delimiter_script=replace(spec.delimiter_script, max_length=16))
    assert statements("DELIMITER xxxxxxxxxxxxxxxx\nSELECT 1xxxxxxxxxxxxxxxx\n", longer) == [
        "SELECT 1"
    ]


@BOTH
def test_delimiter_refusals_in_order(spec):
    client = spec.client_name
    assert refusal("DELIMITER a\rb\nSELECT 1;", spec) == (
        "DELIMITER on line 1 has a carriage return that is not part of a line end: "
        f"the {client} client reads the rest of the script as part of that line and sends nothing"
    )
    no_argument = (
        "DELIMITER on line 1 has no argument (or an empty or unclosed quoted one): "
        f"the {client} client does not set a delimiter from it"
    )
    assert refusal("DELIMITER\nSELECT 1;", spec) == no_argument
    assert refusal("DELIMITER ''\nSELECT 1;", spec) == no_argument
    assert refusal("DELIMITER;\nSELECT 1;", spec) == no_argument
    backslash = (
        "DELIMITER on line 1 contains a backslash: "
        f"the {client} client refuses it, backslash is the escape character"
    )
    assert refusal("DELIMITER a\\b\nSELECT 1;", spec) == backslash
    # the backslash is met before the length
    assert refusal("DELIMITER \\ \x0bxxxxxxxxxxxxxxxxx\nSELECT 1;", spec) == backslash
    assert refusal("SELECT 1;\n\nDELIMITER\n", spec).startswith(
        "DELIMITER on line 3 has no argument"
    )


@BOTH
def test_delimiter_not_first_on_its_line_is_refused(spec):
    message = (
        f"DELIMITER is not the first word of line {{}}: the {spec.client_name} client silently "
        "drops the statements that follow"
    )
    assert refusal("SELECT 1; DELIMITER //\nSELECT 2;", spec) == message.format(1)
    assert refusal("/* c */ DELIMITER //\nSELECT 2;", spec) == message.format(1)
    assert refusal("SELECT 1;\nSELECT 2; delimiter //\n", spec) == message.format(2)
    assert refusal("SELECT 1; DELIMITER\rx;", spec) == message.format(1)
    # a line that follows a multi-line comment is not a line head
    assert refusal("/* x\n*/DELIMITER //\nSELECT 1//", spec) == message.format(2)
    # pending code makes the line text, and a delimiter word is not a command inside a lexeme
    assert statements("SELECT 1\nDELIMITER //\n", spec) == ["SELECT 1\nDELIMITER //"]
    assert statements("SELECT 1 /* x\n*/ DELIMITER //\n", spec) == [
        "SELECT 1 /* x\n*/ DELIMITER //"
    ]


def fields(record: Statement) -> Tuple[object, ...]:
    return tuple(getattr(record, f.name) for f in dataclasses.fields(record))


RecordTuple = Tuple[object, ...]
D = "directive"
S = "sql"
BOUNDS: List[Tuple[str, str, List[RecordTuple]]] = [
    (
        "bom",
        "\ufeffDELIMITER //\nSELECT 1//\nDELIMITER ;\nSELECT 2;",
        [
            ("DELIMITER //", 1, None, D, False, 1, None, 1, 14),
            ("SELECT 1", 2, "//", S, False, 1, None, 14, 24),
            ("DELIMITER ;", 3, None, D, False, 1, None, 25, 37),
            ("SELECT 2", 4, ";", S, False, 1, None, 37, 46),
        ],
    ),
    (
        "crlf",
        "DELIMITER //\r\nSELECT 'a\r\nb'//\r\nDELIMITER ;\r\nSELECT 2;\r\n",
        [
            ("DELIMITER //", 1, None, D, False, 1, None, 0, 14),
            ("SELECT 'a\nb'", 2, "//", S, False, 1, None, 14, 29),
            ("DELIMITER ;", 4, None, D, False, 1, None, 31, 44),
            ("SELECT 2", 5, ";", S, False, 1, None, 44, 53),
        ],
    ),
    (
        "leading comment",
        "-- c\n/* d */ SELECT 1;\n",
        [("SELECT 1", 2, ";", S, False, 1, None, 13, 22)],
    ),
    (
        "directive on the last line",
        "SELECT 1;\nDELIMITER $$",
        [
            ("SELECT 1", 1, ";", S, False, 1, None, 0, 9),
            ("DELIMITER $$", 2, None, D, False, 1, None, 10, 22),
        ],
    ),
    (
        "tail without a delimiter",
        "SELECT 1; SELECT 2",
        [
            ("SELECT 1", 1, ";", S, False, 1, None, 0, 9),
            ("SELECT 2", 1, None, S, False, 1, None, 10, 18),
        ],
    ),
    (
        "terminators of several characters",
        "DELIMITER ;;\nSELECT 1;;\nDELIMITER $$\nSELECT 2$$\n",
        [
            ("DELIMITER ;;", 1, None, D, False, 1, None, 0, 13),
            ("SELECT 1", 2, ";;", S, False, 1, None, 13, 23),
            ("DELIMITER $$", 3, None, D, False, 1, None, 24, 37),
            ("SELECT 2", 4, "$$", S, False, 1, None, 37, 47),
        ],
    ),
    (
        "two directive lines in a row",
        "DELIMITER //\nDELIMITER ;\nSELECT 1;",
        [
            ("DELIMITER //", 1, None, D, False, 1, None, 0, 13),
            ("DELIMITER ;", 2, None, D, False, 1, None, 13, 25),
            ("SELECT 1", 3, ";", S, False, 1, None, 25, 34),
        ],
    ),
    (
        "directive text keeps what is no blank",
        "DELIMITER // x\xa0\nSELECT 1//",
        [
            ("DELIMITER // x\xa0", 1, None, D, False, 1, None, 0, 16),
            ("SELECT 1", 2, "//", S, False, 1, None, 16, 26),
        ],
    ),
    (
        "crlf before a tail record",
        "SELECT 1;\r\nSELECT 2",
        [
            ("SELECT 1", 1, ";", S, False, 1, None, 0, 9),
            ("SELECT 2", 2, None, S, False, 1, None, 11, 19),
        ],
    ),
    (
        "a command word followed by a carriage return is text",
        "  DELIMITER\rx;",
        [("DELIMITER\rx", 1, ";", S, False, 1, None, 2, 14)],
    ),
    (
        "blanks around the directive",
        "  DELIMITER   //  \nSELECT 1//",
        [
            ("DELIMITER   //", 1, None, D, False, 1, None, 2, 19),
            ("SELECT 1", 2, "//", S, False, 1, None, 19, 29),
        ],
    ),
]


@BOTH
@pytest.mark.parametrize("name, script, expected", BOUNDS, ids=[b[0] for b in BOUNDS])
def test_record_bounds_match_the_recorded_values(spec, name, script, expected):
    assert [fields(r) for r in LexicalEngine(spec).split(script)] == expected


@BOTH
def test_a_refusal_after_a_bom_counts_columns_without_it(spec):
    with_bom = "\ufeffDELIMITER //\r\nSELECT 'a"
    assert with_bom[0] == "\ufeff"
    expected = "unterminated string opened at line 2, column 8"
    assert refusal(with_bom, spec) == expected
    assert refusal(with_bom[1:], spec) == expected
    assert refusal("\ufeffSELECT 'a", spec) == "unterminated string opened at line 1, column 8"
    # the offsets, not the columns, see the byte order mark
    assert LexicalEngine(spec).split(with_bom[:-9] + "\r\nSELECT 1//")[0].source_start == 1


@BOTH
def test_execution_strings_have_no_terminator(spec):
    script = "SELECT 1;\nDELIMITER //\nSELECT 2//\nDELIMITER ;\nSELECT 3;"
    assert statements(script, spec) == ["SELECT 1", "SELECT 2", "SELECT 3"]
    assert [r.terminator for r in LexicalEngine(spec).split(script) if r.kind == "sql"] == [
        ";",
        "//",
        ";",
    ]


@BOTH
def test_analysis_fragments_under_a_custom_delimiter(spec):
    script = "DELIMITER //\nSELECT 1; SELECT 2//\nSELECT 3/*! ; */; SELECT 4//\nSELECT 5; /* ; */ SELECT 6 # ;\n; SELECT 7//\n"
    records = [r for r in LexicalEngine(spec).split(script) if r.kind == "sql"]
    assert [r.analysis_statements for r in records] == [
        ("SELECT 1", "SELECT 2"),
        ("SELECT 3/*! ; */", "SELECT 4"),
        ("SELECT 5", "/* ; */ SELECT 6 # ;", "SELECT 7"),
    ]
    # a record without a semicolon of its own has no fragments to give
    plain = LexicalEngine(spec).split("DELIMITER //\nSELECT 1//\n")
    assert plain[1].analysis_statements is None


@BOTH
def test_comment_only_and_empty_fragments_give_nothing_to_analyse(spec):
    records = LexicalEngine(spec).split("DELIMITER //\nSELECT 1; /* c */; # x\n; SELECT 2//\n")
    assert records[1].analysis_statements == ("SELECT 1", "SELECT 2")
    records = LexicalEngine(spec).split("DELIMITER //\nSELECT 1;; SELECT 2//")
    assert records[1].analysis_statements == ("SELECT 1", "SELECT 2")


ANALYSIS_ORACLE = {"24": ["SELECT 1 AS A", "B"], "27": ["SELECT 1", "SELECT 2"]}


@BOTH
@pytest.mark.parametrize("row_id", ["24", "27"])
def test_engine_analysis_view_matches_the_recorded_parser_view(spec, row_id):
    script = next(r.script for r in ROWS if r.dialect == "mysql" and r.row_id == row_id)
    assert LexicalEngine(spec).split_for_analysis(script) == ANALYSIS_ORACLE[row_id]


@BOTH
def test_analysis_view_leaves_out_delimiter_lines_and_comment_only_records(spec):
    script = "DELIMITER //\n/* c */ //\nSELECT 1; SELECT 2//\nDELIMITER ;\n"
    assert LexicalEngine(spec).split_for_analysis(script) == ["SELECT 1", "SELECT 2"]


@BOTH
def test_placeholder_is_code_for_mysql(spec):
    assert statements("SELECT ${a;\nSELECT 2}", spec) == ["SELECT ${a", "SELECT 2}"]


def script_with(rules_text: str = "SELECT 1") -> DelimiterScript:
    return DelimiterScript(MYSQL_RULES, "mysql", rules_text, [], 0, MYSQL_SPEC.text_blanks)


# `word()` and the qualifier it reports have no reader until the stored-program tracker is wired in
# (a later change); these tests drive the event API directly.
def test_a_name_qualifier_lives_until_the_line_ends_unless_a_comment_ended_it():
    script = script_with()
    script.symbol(".")
    assert script.word("end") is True
    assert script.word("end") is False
    script.symbol("@")
    script.symbol(",")
    assert script.word("x") is False
    script.symbol(".")
    script.line_end(5)
    assert script.word("end") is False
    script.symbol(".")
    script.comment(2, 7, True)
    script.line_end(7)
    assert script.word("end") is True


def test_a_literal_or_a_lexeme_spanning_lines_breaks_the_qualifier():
    script = script_with()
    script.symbol(".")
    script.lexeme(1, 1)
    assert script.word("end") is True
    script.symbol(".")
    script.lexeme(1, 2)
    assert script.word("end") is False
    script.symbol(".")
    script.literal(0, 1, 1, 1)
    assert script.word("end") is False
    script.symbol(".")
    script.reset_qualifier()
    assert script.word("end") is False


def test_a_closer_breaks_the_qualifier_and_ends_the_analysis_flag():
    script = script_with()
    script.executable(1)
    assert script.analysis_exec_comment is True
    script.symbol(".")
    assert script.close(0, 0, 1) is True
    assert script.analysis_exec_comment is False
    assert script.word("end") is False
    script.symbol(".")
    assert script.close(0, 0, 1) is False
    assert script.word("end") is True


def test_a_delimiter_free_script_is_cut_at_its_semicolons():
    script = "SELECT 'a;b' /* ; */ ; SELECT 2 # c\n;"
    assert [r.text for r in LexicalEngine(MYSQL_SPEC).split(script)] == [
        "SELECT 'a;b' /* ; */",
        "SELECT 2 # c",
    ]


NBSP = chr(0xA0)


def _statements_of(spec, script):
    return [r for r in LexicalEngine(spec).split(script) if r.kind != "directive"]


@BOTH
def test_a_delimiter_block_keeps_the_no_break_spaces_at_the_edges_of_its_statements(spec):
    script = f"DELIMITER //\n{NBSP}SELECT 1{NBSP};{NBSP};{NBSP}SELECT 2{NBSP};{NBSP}//\nDELIMITER ;"
    (record,) = _statements_of(spec, script)
    assert record.text == f"{NBSP}SELECT 1{NBSP};{NBSP};{NBSP}SELECT 2{NBSP};{NBSP}"
    assert record.analysis_statements == (
        f"{NBSP}SELECT 1{NBSP}",
        NBSP,
        f"{NBSP}SELECT 2{NBSP}",
        NBSP,
    )
    blanks = f"DELIMITER //\n \tSELECT 1 \t;\t ;\x0b\x0cSELECT 2\x0b;\n//\nDELIMITER ;"
    (record,) = _statements_of(spec, blanks)
    assert record.text == "SELECT 1 \t;\t ;\x0b\x0cSELECT 2\x0b;"
    assert record.analysis_statements == ("SELECT 1", "SELECT 2")
