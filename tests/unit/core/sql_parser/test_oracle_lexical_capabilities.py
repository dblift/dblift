"""Oracle lexical facts, read through the shared tokenizer and engine."""

import warnings
from dataclasses import replace

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.base_tokenizer import TokenizerWarning
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC


def texts(script):
    return [record.text for record in LexicalEngine(ORACLE_SPEC).split(script)]


def tokens(script):
    return [(t.type, t.text) for t in LexicalTokenizer(script, spec=ORACLE_SPEC).tokenize()]


def tokens_and_warnings(script):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = tokens(script)
    return result, [w.category for w in caught]


@pytest.mark.parametrize(
    "literal",
    [
        "q'[it's; fine]'",
        "nq'{x;y}'",
        "Q'(a;b)'",
        "NQ'<a;b>'",
        "q'!a;b!'",
        "q'|a;b|'",
        "q'[a]b;c]'",
        "nq'{it's;y}'",
        "Q'(a'b;c)'",
        "q'!a'b;c!'",
        "q'|it's;|'",
    ],
)
def test_alternative_quote_hides_the_terminator(literal):
    assert texts(f"INSERT INTO t VALUES ({literal});\nSELECT 1 FROM dual;") == [
        f"INSERT INTO t VALUES ({literal})",
        "SELECT 1 FROM dual",
    ]


def test_closer_depends_on_the_opener():
    assert texts("SELECT q'[a) ; b]' FROM dual;") == ["SELECT q'[a) ; b]' FROM dual"]


@pytest.mark.parametrize(
    "script, message",
    [
        (
            "INSERT INTO t VALUES (q' x ');",
            "q-quote delimiter cannot be whitespace at line 1, column 23",
        ),
        (
            "INSERT INTO t VALUES (q'[abc",
            "unterminated q-quoted string opened at line 1, column 23",
        ),
        ("SELECT q'", "unterminated q-quoted string opened at line 1, column 8"),
    ],
)
def test_alternative_quote_refusals(script, message):
    with pytest.raises(UnsafeStatementSplitError) as raised:
        LexicalEngine(ORACLE_SPEC).split(script)
    assert str(raised.value) == message


def test_a_word_ending_in_q_is_not_a_quote_opener():
    assert texts("SELECT faq'[a' FROM dual;\nSELECT 2 FROM dual;") == [
        "SELECT faq'[a' FROM dual",
        "SELECT 2 FROM dual",
    ]


def test_quoted_identifier_has_no_escape():
    assert tokens('select "a""b"') == [
        (TokenType.KEYWORD, "select"),
        (TokenType.IDENTIFIER, '"a"'),
        (TokenType.IDENTIFIER, '"b"'),
    ]
    with pytest.raises(
        UnsafeStatementSplitError,
        match="unterminated quoted identifier opened at line 1, column 11",
    ):
        LexicalTokenizer('select "a""', spec=ORACLE_SPEC).tokenize()


def test_dollar_digit_is_two_tokens():
    result, categories = tokens_and_warnings("$1")
    assert result == [(TokenType.SYMBOL, "$"), (TokenType.IDENTIFIER, "1")]
    assert categories == [TokenizerWarning]


def test_placeholder_is_not_tokenised_for_oracle():
    assert texts("SELECT ${x;\nSELECT 2 FROM dual;") == ["SELECT ${x", "SELECT 2 FROM dual"]
    result, _ = tokens_and_warnings("SELECT ${a;b} FROM dual;")
    assert [text for _, text in result] == [
        "SELECT",
        "$",
        "{",
        "a",
        ";",
        "b",
        "}",
        "FROM",
        "dual",
        ";",
    ]
    assert result[4] == (TokenType.DELIMITER, ";")


def test_other_specs_keep_placeholder_tokens():
    assert POSTGRESQL_SPEC.placeholder_open == "${"
    assert SQLITE_SPEC.placeholder_open == "${"
    postgres = LexicalTokenizer("SELECT ${x;", spec=POSTGRESQL_SPEC).tokenize()
    assert [t.text for t in postgres] == ["SELECT", "${x;"]


@pytest.mark.parametrize("spec", [POSTGRESQL_SPEC, SQLITE_SPEC])
def test_other_specs_keep_the_new_fact_defaults(spec):
    assert spec.alternative_quotes == ()
    assert spec.alternative_quote_pairs == ()
    assert spec.quoted_identifier_escape is True
    assert spec.parameter_prefix == "$"


# --- line terminators, unit heads, statement ends and refusals -------------------------


def execution(script):
    return LexicalEngine(ORACLE_SPEC).split_statements(script)


def refusal(script):
    with pytest.raises(UnsafeStatementSplitError) as raised:
        LexicalEngine(ORACLE_SPEC).split(script)
    return str(raised.value)


def fields(script):
    return [
        (r.text, r.line, r.terminator, r.source_start, r.source_end)
        for r in LexicalEngine(ORACLE_SPEC).split(script)
    ]


@pytest.mark.parametrize(
    "script, expected",
    [
        (
            "CREATE TABLE a (x NUMBER);\nCREATE TABLE b (y NUMBER);",
            ["CREATE TABLE a (x NUMBER);", "CREATE TABLE b (y NUMBER);"],
        ),
        (
            "CREATE TABLE a (x NUMBER)\n/\nCREATE TABLE b (y NUMBER);",
            ["CREATE TABLE a (x NUMBER)", "CREATE TABLE b (y NUMBER);"],
        ),
        (
            "CREATE OR REPLACE PROCEDURE p AS BEGIN IF 1=1 THEN NULL; END IF; END;\n/\n"
            "CREATE TABLE t (id NUMBER);",
            [
                "CREATE OR REPLACE PROCEDURE p AS BEGIN IF 1=1 THEN NULL; END IF; END;",
                "CREATE TABLE t (id NUMBER);",
            ],
        ),
        (
            "BEGIN\n  OPEN c FOR SELECT 1 FROM dual;\n  NULL;\nEND;\n/\nSELECT 1 FROM dual;",
            ["BEGIN\n  OPEN c FOR SELECT 1 FROM dual;\n  NULL;\nEND;", "SELECT 1 FROM dual;"],
        ),
        (
            "CREATE OR REPLACE PACKAGE BODY pk AS\n  PROCEDURE a IS BEGIN NULL; END;\n"
            "  FUNCTION f RETURN NUMBER IS BEGIN RETURN 4\n/ 2; END;\nBEGIN NULL;\nEND pk;\n/",
            [
                "CREATE OR REPLACE PACKAGE BODY pk AS\n  PROCEDURE a IS BEGIN NULL; END;\n"
                "  FUNCTION f RETURN NUMBER IS BEGIN RETURN 4\n/ 2; END;\nBEGIN NULL;\nEND pk;"
            ],
        ),
        (
            "CREATE TYPE t AS OBJECT (id NUMBER);\n/\nCREATE TABLE u (id NUMBER);",
            ["CREATE TYPE t AS OBJECT (id NUMBER);", "CREATE TABLE u (id NUMBER);"],
        ),
        (
            "CREATE VIEW v AS SELECT type, package FROM t;\nSELECT begin FROM t;",
            ["CREATE VIEW v AS SELECT type, package FROM t;", "SELECT begin FROM t;"],
        ),
        (
            "CREATE TABLE t25 (id NUMBER)\n/ -- done\nINSERT INTO t25 VALUES (1);",
            ["CREATE TABLE t25 (id NUMBER)\n/ -- done\nINSERT INTO t25 VALUES (1);"],
        ),
        ("/\n", []),
    ],
)
def test_execution_strings_follow_the_spec_rows(script, expected):
    assert execution(script) == expected


@pytest.mark.parametrize("line", ["/", "  /  ", "\t/\t"])
@pytest.mark.parametrize("newline", ["\n", "\r\n"])
def test_slash_alone_between_blanks_terminates(line, newline):
    script = f"BEGIN NULL; END;{newline}{line}{newline}SELECT 1 FROM dual;"
    assert len(execution(script)) == 2


def test_the_unit_record_ends_at_the_slash_and_keeps_its_semicolons():
    assert fields("CREATE PROCEDURE p AS BEGIN NULL; END;\n/\nCREATE TABLE t (id NUMBER);\n") == [
        ("CREATE PROCEDURE p AS BEGIN NULL; END;", 1, "/", 0, 41),
        ("CREATE TABLE t (id NUMBER)", 3, ";", 41, 68),
    ]


@pytest.mark.parametrize(
    "script, message",
    [
        (
            "SELECT 1 FROM dual; -- note\nSELECT 2 FROM dual;",
            "';' is not the last text on line 1: SQL*Plus rejects the line (ORA-03405); "
            "move the comment or the next statement to its own line",
        ),
        (
            "INSERT INTO t VALUES (1); INSERT INTO t VALUES (2);",
            "';' is not the last text on line 1: SQL*Plus rejects the line (ORA-03405); "
            "move the comment or the next statement to its own line",
        ),
        (
            "SELECT ${a;b} FROM dual;",
            "';' is not the last text on line 1: SQL*Plus rejects the line (ORA-03405); "
            "move the comment or the next statement to its own line",
        ),
        (
            "CREATE TABLE t (id NUMBER);\n/\n",
            "'/' on line 2, column 1 would re-execute the previous statement",
        ),
        (
            "INSERT INTO t VALUES (1)\n/\n/\n",
            "'/' on line 3, column 1 would re-execute the previous statement",
        ),
        (
            "INSERT INTO t VALUES (1)\n/\n   /\n",
            "'/' on line 3, column 4 would re-execute the previous statement",
        ),
        (
            "BEGIN\n  NULL;\nEND;\n.\nCREATE TABLE t26 (id NUMBER);",
            "'.' alone on line 4 would discard the buffered statement without running it",
        ),
        (
            "BEGIN\n  NULL;\nEND;\nCREATE TABLE t (id NUMBER);\n",
            "PL/SQL unit starting at line 1 is not terminated by a '/' line before the end "
            "of the script",
        ),
        (
            "BEGIN NULL; END;\n/ -- c\n",
            "PL/SQL unit starting at line 1: a '/' followed by other text does not end the "
            "unit (line 2)",
        ),
    ],
)
def test_refusals_keep_their_wording(script, message):
    assert refusal(script) == message


def test_each_call_starts_without_a_previous_terminator():
    engine = LexicalEngine(ORACLE_SPEC)
    assert len(engine.split("SELECT 1;\n")) == 1
    assert engine.split("/\n") == []


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT 4 /", [("SELECT 4 /", 1, None, 0, 10)]),  # row 29
        (  # row 25: an open buffer keeps the slash line as statement text
            "CREATE TABLE t25 (id NUMBER)\n/ -- done\nINSERT INTO t25 VALUES (1);",
            [
                (
                    "CREATE TABLE t25 (id NUMBER)\n/ -- done\nINSERT INTO t25 VALUES (1)",
                    1,
                    ";",
                    0,
                    66,
                )
            ],
        ),
        ("SELECT 4 / -- c", [("SELECT 4 / -- c", 1, None, 0, 11)]),  # row 32
        (  # row 34
            "SELECT 1 FROM dual /* c */",
            [("SELECT 1 FROM dual /* c */", 1, None, 0, 19)],
        ),
        (
            "SELECT 1 FROM dual\n/* c */",
            [("SELECT 1 FROM dual\n/* c */", 1, None, 0, 19)],
        ),
        (  # row 35
            "SELECT 1 FROM dual -- a/",
            [("SELECT 1 FROM dual -- a/", 1, None, 0, 19)],
        ),
        (
            "SELECT 1 FROM dual -- see http://host/",
            [("SELECT 1 FROM dual -- see http://host/", 1, None, 0, 19)],
        ),
    ],
)
def test_a_slash_that_is_not_alone_on_its_line_stays_statement_text(script, expected):
    assert fields(script) == expected


_AFTER = "'/' followed by text on line {}, column 1 would re-execute the previous statement"
_EMPTY = "'/' followed by text on line 1, column 1 would run an empty buffer"


@pytest.mark.parametrize(
    "script, message",
    [
        ("SELECT 1 FROM dual;\n/ SELECT 2 FROM dual;", _AFTER.format(2)),  # row 28
        ("SELECT 1;\n/ ;\nSELECT 2;", _AFTER.format(2)),  # row 30
        ("SELECT 1;\n/ /\n", _AFTER.format(2)),  # row 31
        ("SELECT 1;\n/ SELECT 4 /", _AFTER.format(2)),  # row 33
        ("/ -- done", _EMPTY),  # row 36
        ("SELECT 1 FROM dual;\n/ -- c\nSELECT 2 FROM dual;", _AFTER.format(2)),
        ("SELECT 1;\n/ garbage", _AFTER.format(2)),
        ("BEGIN NULL; END;\n/\n/ x\n", _AFTER.format(3)),
        ("-- c\n/ x", _EMPTY.replace("line 1", "line 2")),
    ],
)
def test_a_slash_with_text_where_the_buffer_is_complete_is_refused(script, message):
    assert refusal(script) == message


_RERUN = "'/' on line {}, column {} would re-execute the previous statement"
_RERUN_TEXT = "'/' followed by text on line {}, column {} would re-execute the previous statement"


@pytest.mark.parametrize(
    "script, message",
    [
        ("SELECT 7 AS a FROM dual;\n/* c */ /", _RERUN.format(2, 9)),
        ("SELECT 7 AS a FROM dual;\n/* c */ / x", _RERUN_TEXT.format(2, 9)),
        ("SELECT 1;\n/* a */ /* b */ / x", _RERUN_TEXT.format(2, 17)),
        ("SELECT 1;\n/* a\n b */ /\nSELECT 2;", _RERUN.format(3, 7)),
        ("SELECT 1;\n-- c\n/* a */ /", _RERUN.format(3, 9)),
        ("/* c */ /", "'/' on line 1, column 9 would run an empty buffer"),
        # nothing has run yet: a bare ';' or a directive line is no previous statement
        (";\n/ x", "'/' followed by text on line 2, column 1 would run an empty buffer"),
        ("PROMPT hi\n/ x", "'/' followed by text on line 2, column 1 would run an empty buffer"),
        (
            "SELECT 1;\n/x",
            "'/' followed by text on line 2, column 1: SQL*Plus reads the line as an unknown "
            "command (SP2-0042)",
        ),
    ],
)
def test_a_slash_after_blanks_and_block_comments_is_the_slash_command(script, message):
    assert refusal(script) == message


@pytest.mark.parametrize(
    "script, texts",
    [
        # an open buffer keeps the line (unverified against SQL*Plus, not changed here)
        ("SELECT 1\n/* c */ /", ["SELECT 1\n/* c */ /"]),
        ("SELECT 1\n/* c */ / x;", ["SELECT 1\n/* c */ / x"]),
        # a slash inside a block comment is no slash at all
        ("SELECT 1;\n/* c / x */ SELECT 2;", ["SELECT 1", "SELECT 2"]),
        # something other than a comment comes first on the line
        ("SELECT 1;\nSELECT 2 / x;", ["SELECT 1", "SELECT 2 / x"]),
    ],
)
def test_other_slashes_stay_statement_text(script, texts):
    assert [r.text for r in LexicalEngine(ORACLE_SPEC).split(script)] == texts


@pytest.mark.parametrize(
    "script, source_end",
    [
        ("SELECT 1 FROM dual\n\n\n", 18),
        ("SELECT 1 FROM dual -- c\n\n", 19),
        ("SELECT 1 FROM dual /* c */", 19),
        ("SELECT 4 / -- c", 11),
    ],
)
def test_a_record_ended_by_the_end_of_the_script_ends_at_its_last_token(script, source_end):
    assert fields(script)[-1][4] == source_end


def test_a_record_ended_by_the_slash_line_ends_at_the_end_of_that_line():
    script = "CREATE TABLE a (x NUMBER)\n/  \nSELECT 1 FROM dual;"
    assert fields(script)[0] == ("CREATE TABLE a (x NUMBER)", 1, "/", 0, 30)


def test_the_record_bound_flags_decide_where_a_record_ends():
    rules = ORACLE_SPEC.client_script
    assert rules is not None
    script = "CREATE TABLE a (x NUMBER)\n/  \nSELECT 1 FROM dual\n\n"
    default = LexicalEngine(ORACLE_SPEC).split(script)
    other = LexicalEngine(
        replace(
            ORACLE_SPEC,
            client_script=replace(
                rules, slash_record_ends_at_line_end=False, tail_record_ends_at_last_token=False
            ),
        )
    ).split(script)
    assert [r.source_end for r in default] == [30, 48]
    assert [r.source_end for r in other] == [27, len(script)]


@pytest.mark.parametrize(
    "script, expected",
    [
        ("SELECT (1;\n2) FROM dual;", ["SELECT (1;\n2) FROM dual"]),
        ("CREATE TABLE t (a NUMBER;\nb NUMBER);", ["CREATE TABLE t (a NUMBER;\nb NUMBER)"]),
        ("SELECT f(g(1;\n2), 3) FROM dual;", ["SELECT f(g(1;\n2), 3) FROM dual"]),
        (
            "CREATE TABLE t (v VARCHAR2(10) DEFAULT (';')\n);\nSELECT 1 FROM dual;",
            ["CREATE TABLE t (v VARCHAR2(10) DEFAULT (';')\n)", "SELECT 1 FROM dual"],
        ),
    ],
)
def test_a_semicolon_inside_parentheses_does_not_end_the_statement(script, expected):
    assert texts(script) == expected


def test_the_empty_buffer_rule_is_a_spec_flag():
    rules = ORACLE_SPEC.client_script
    assert rules is not None
    off = replace(
        ORACLE_SPEC, client_script=replace(rules, refuse_terminator_text_on_empty_buffer=False)
    )
    assert [r.text for r in LexicalEngine(off).split("SELECT 1;\n/ SELECT 2;")] == [
        "SELECT 1",
        "/ SELECT 2",
    ]
