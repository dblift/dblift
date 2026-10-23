"""SQL Server lexical facts, read through the shared tokenizer and engine."""

import warnings
from dataclasses import replace

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser import lexical_spec
from dblift.core.sql_parser.base_tokenizer import TokenizerWarning
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC
from tests.support.facts_parser import facts_parser


def tokens(script, spec=SQLSERVER_SPEC):
    return [
        (t.type, t.text)
        for t in LexicalTokenizer(script, spec=spec).tokenize()
        if t.type != TokenType.EOF
    ]


def tokens_and_warnings(script, spec=SQLSERVER_SPEC):
    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        result = tokens(script, spec)
    return result, [w.category for w in caught]


def test_bracketed_identifier_has_a_doubled_closer_escape():
    assert tokens("SELECT [a]]b] FROM t") == [
        (TokenType.KEYWORD, "SELECT"),
        (TokenType.IDENTIFIER, "[a]]b]"),
        (TokenType.KEYWORD, "FROM"),
        (TokenType.IDENTIFIER, "t"),
    ]


def test_brackets_inside_a_string_or_a_comment_are_text():
    assert tokens("SELECT '[a' -- ]\n") == [
        (TokenType.KEYWORD, "SELECT"),
        (TokenType.STRING, "'[a'"),
        (TokenType.COMMENT, ""),
    ]
    assert [t for t, _ in tokens("/* [a */ SELECT 1")][:2] == [TokenType.COMMENT, TokenType.KEYWORD]


def test_bracketed_identifier_spans_lines():
    assert tokens("[a\nGO\nb]") == [(TokenType.IDENTIFIER, "[a\nGO\nb]")]


def test_bracket_identifier_is_a_spec_field():
    assert tokens("[a]", replace(SQLSERVER_SPEC, bracket_identifier=())) == [
        (TokenType.SYMBOL, "["),
        (TokenType.IDENTIFIER, "a"),
        (TokenType.SYMBOL, "]"),
    ]


def test_unterminated_bracketed_identifier_is_refused():
    with pytest.raises(
        UnsafeStatementSplitError,
        match=r"unterminated bracketed identifier opened at line 1, column 8",
    ):
        LexicalEngine(SQLSERVER_SPEC).split("SELECT [abc")


def test_block_comment_ends_at_the_first_close():
    assert tokens("/* a /* b */ c */") == [
        (TokenType.COMMENT, ""),
        (TokenType.IDENTIFIER, "c"),
        (TokenType.SYMBOL, "*"),
        (TokenType.SYMBOL, "/"),
    ]


def test_leading_bom_is_skipped_and_columns_ignore_it():
    first = LexicalTokenizer("\ufeffSELECT 1", spec=SQLSERVER_SPEC).tokenize()[0]
    assert (first.text, first.pos, first.line, first.col) == ("SELECT", 1, 1, 1)
    with pytest.raises(UnsafeStatementSplitError, match=r"opened at line 1, column 1$"):
        LexicalEngine(SQLSERVER_SPEC).split("\ufeff'abc")
    mid, warned = tokens_and_warnings("a\ufeffb")
    assert (TokenType.SYMBOL, "\ufeff") in mid and warned == []


def test_leading_bom_is_a_spec_field():
    kept = LexicalTokenizer(
        "\ufeffSELECT 1", spec=replace(SQLSERVER_SPEC, leading_bom_is_blank=False)
    )
    with warnings.catch_warnings(record=True):
        warnings.simplefilter("always")
        first = kept.tokenize()[0]
    assert (first.text, first.pos) == ("\ufeff", 0)


@pytest.mark.parametrize(
    "script, text",
    [("\xa35", "\xa3"), ("$action", "$"), ("a\x00b", "\x00"), ("a\U0001f600b", "\U0001f600")],
)
def test_unclaimed_characters_are_symbols_without_a_warning(script, text):
    result, warned = tokens_and_warnings(script)
    assert (TokenType.SYMBOL, text) in result
    assert warned == []


@pytest.mark.parametrize(
    "blank", ["\x0b", "\x0c", "\x1c", "\x1d", "\x1e", "\x1f", "\x85", "\xa0", "\u2028", "\u2029"]
)
def test_token_level_whitespace_is_str_isspace_as_before(blank):
    # The tokenizer skips these exactly as the previous T-SQL tokenizer did (values recorded from it);
    # only the line-head rules use the narrower blank set.
    result, warned = tokens_and_warnings("a" + blank + "b")
    assert result == [(TokenType.IDENTIFIER, "a"), (TokenType.IDENTIFIER, "b")]
    assert warned == []


def test_unclaimed_character_warns_when_not_silent():
    _, warned = tokens_and_warnings("\xa35", replace(SQLSERVER_SPEC, silent_unclaimed=False))
    assert TokenizerWarning in warned


def test_placeholder_is_not_tokenised_for_sqlserver():
    script = "SELECT ${a\nGO\nSELECT 2}"
    assert not [text for _, text in tokens(script) if "${" in text]
    swallowing = [
        text
        for _, text in tokens(script, replace(SQLSERVER_SPEC, placeholder_open="${"))
        if "${" in text
    ]
    assert swallowing == ["${a\nGO\nSELECT 2}"]
    with pytest.raises(
        UnsafeStatementSplitError, match=r"unterminated string opened at line 1, column 4"
    ):
        tokens("${a'b}")
    assert (TokenType.COMMENT, "") in tokens("${a -- x}")


def test_batch_and_client_script_are_exclusive():
    BatchScriptRules, DivisionRules = lexical_spec.BatchScriptRules, lexical_spec.DivisionRules
    division = DivisionRules(
        routine_heads=(),
        block_open="BEGIN",
        block_open_exempt=frozenset(),
        case_word="CASE",
        block_close="END",
        split_heads=frozenset(),
        clause_exemptions=(),
    )
    rules = BatchScriptRules(
        separator="GO",
        word_start="A-Za-z_@#$",
        word_part="A-Za-z0-9_@#$",
        bare_commands=(),
        colon_commands=(),
        shell_prefix="!!",
        command_followers=frozenset(),
        separator_followers=frozenset(),
        unmeasured_blanks=frozenset(),
        tail_comment="--",
        max_repeat=1_000_000,
        lone_cr_words=("GO",),
        variable_reference=("$(", ")"),
        blanks=" \t\r",
        ignored_in_code=";",
        division=division,
    )
    with pytest.raises(
        ValueError, match=r"client_script.*batch_script|batch_script.*client_script"
    ):
        replace(ORACLE_SPEC, batch_script=rules)
    assert replace(SQLSERVER_SPEC, batch_script=rules).batch_script is rules
