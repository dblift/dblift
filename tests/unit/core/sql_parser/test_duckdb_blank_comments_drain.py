"""Public DuckDB comment masking keeps scanner outcomes without retaining its tokens."""

from unittest.mock import patch

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser import lexical_engine as engine_module
from dblift.core.sql_parser import lexical_tokenizer as tokenizer_module
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC
from tests.support.splitting_cost import CountingPattern, CountingText, Meter

ENGINE = LexicalEngine(DUCKDB_SPEC)
PATTERNS = (
    "_seg_word",
    "_seg_number",
    "_seg_tag",
    "_seg_parameter",
    "_seg_comment",
    "_seg_word_part",
    "_seg_kept_part",
)


@pytest.mark.parametrize(
    ("script", "expected"),
    [
        (
            "\ufeffSELECT '/*literal*/', \"--name\"; /* real */ SELECT 1;\r\n",
            "SELECT '/*literal*/', \"--name\";   SELECT 1;\r\n",
        ),
        (
            "\ufeffSELECT 'α;β'; /* outer /* inner */ tail */ SELECT 2;",
            "SELECT 'α;β';   SELECT 2;",
        ),
        (
            "SELECT $tag$--literal;/*x*/$tag$; -- real\n",
            "SELECT $tag$--literal;/*x*/$tag$;  \n",
        ),
        (
            "SELECT x\u00a0y; /* c */ -- c\n",
            "SELECT x\u00a0y;    \n",
        ),
        ("SELECT 'unterminated", "SELECT 'unterminated"),
        ("SELECT 1; /* unterminated", "SELECT 1; /* unterminated"),
    ],
)
def test_blank_comments_preserves_segment_masking(script, expected):
    assert ENGINE.blank_comments(script) == expected


@pytest.mark.parametrize(
    ("script", "error_type", "message"),
    [
        (
            "\ufeffSELECT 1;\n  \x00 SELECT 2;",
            UnsafeStatementSplitError,
            "a NUL character on line 2, column 3: "
            "the engine reads the script up to it and silently drops the rest",
        ),
        (
            ".open database\nSELECT 1;",
            UnsupportedMetaCommandError,
            "duckdb shell command '.open' on line 1: the shell runs it "
            "and the engine cannot; dblift does not run client commands",
        ),
    ],
)
def test_blank_comments_preserves_exact_refusals(script, error_type, message):
    with pytest.raises(error_type) as raised:
        ENGINE.blank_comments(script)
    assert str(raised.value) == message


def test_public_tokenize_still_returns_all_tokens_and_split_still_works():
    script = "SELECT 1; -- c\nSELECT 2"
    tokens = LexicalTokenizer(script, spec=DUCKDB_SPEC).tokenize()
    assert isinstance(tokens, list)
    assert [(token.type, token.text, token.pos, token.line, token.col) for token in tokens] == [
        (TokenType.KEYWORD, "SELECT", 0, 1, 1),
        (TokenType.IDENTIFIER, "1", 7, 1, 8),
        (TokenType.DELIMITER, ";", 8, 1, 9),
        (TokenType.COMMENT, "-- c", 10, 1, 11),
        (TokenType.KEYWORD, "SELECT", 15, 2, 1),
        (TokenType.IDENTIFIER, "2", 22, 2, 8),
    ]
    assert ENGINE.split_statements("SELECT 1; SELECT 2;") == ["SELECT 1", "SELECT 2"]


@pytest.mark.parametrize("repetitions", [80, 640])
def test_blank_comments_keeps_live_token_count_bounded(monkeypatch, repetitions):
    class LiveToken(Token):
        __slots__ = ()
        live = 0
        peak = 0

        def __init__(self, *args, **kwargs):
            super().__init__(*args, **kwargs)
            type(self).live += 1
            type(self).peak = max(type(self).peak, type(self).live)

        def __del__(self):
            type(self).live -= 1

    unit = (
        "SELECT \"col\", 'x;--', $tag$/*x*/$tag$ FROM t WHERE id=$1; "
        "/* outer /* inner */ tail */ -- end\n"
    )
    script = unit * repetitions
    expected = unit.replace("/* outer /* inner */ tail */", " ").replace("-- end", " ")
    monkeypatch.setattr(tokenizer_module, "Token", LiveToken)
    assert ENGINE.blank_comments(script) == expected * repetitions
    assert LiveToken.peak <= 32
    assert LiveToken.live == 0


def _count_blank_comments(script):
    meter = Meter()
    source = CountingText(script, meter)
    original = LexicalTokenizer

    def counted_tokenizer(text, *, spec):
        assert text is source
        tokenizer = original(text._value, spec=spec)
        tokenizer.sql = CountingText(tokenizer.sql, meter)
        for name in PATTERNS:
            setattr(
                tokenizer,
                name,
                CountingPattern(
                    getattr(tokenizer, name),
                    meter,
                    allow_empty=name in {"_seg_word_part", "_seg_kept_part"},
                ),
            )
        return tokenizer

    with patch.object(engine_module, "LexicalTokenizer", counted_tokenizer):
        output = ENGINE.blank_comments(source)
    return meter.count, output


@pytest.mark.parametrize(
    "unit",
    [
        "SELECT 1; /* block */ -- line\n",
        "SELECT x\u00a0y, $tag$--literal$tag$; /* block */ -- line\n",
    ],
)
def test_blank_comments_scanner_work_scales_with_input(unit):
    small, small_output = _count_blank_comments(unit * 80)
    large, large_output = _count_blank_comments(unit * 320)
    expected = unit.replace("/* block */", " ").replace("-- line", " ")
    assert small_output == expected * 80
    assert large_output == expected * 320
    assert small > 0
    assert large <= 5 * small
