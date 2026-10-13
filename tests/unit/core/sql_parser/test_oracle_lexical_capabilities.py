"""Oracle lexical facts, read through the shared tokenizer and engine."""

import warnings

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
