"""The unit-head table decides exactly as the previous classifier did."""

import random
from itertools import product

import pytest

from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.core.sql_parser.unit_heads import decide
from dblift.db.plugins.oracle.parser._unit_heads import MAX_HEAD_TOKENS, head_decided
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

RULES = ORACLE_SPEC.client_script
assert RULES is not None
VOCABULARY = (
    "CREATE OR REPLACE EDITIONABLE FUNCTION PROCEDURE PACKAGE AND COMPILE RESOLVE NOFORCE "
    "JAVA SOURCE CLASS IF NOT EXISTS MLE MODULE BEGIN DECLARE < > x"
).split()
LONGER = VOCABULARY + ["NONEDITIONABLE", "TYPE", "TRIGGER", "LIBRARY", "RESOURCE", "TABLE"]


def previous(words, comments=()):
    """The previous classifier plus the parser's head-length rule, with comment tokens mixed in."""
    tokens = []
    for index, word in enumerate(words):
        if index in comments:
            tokens.append(Token(TokenType.COMMENT, "", index, 1, 1))
        tokens.append(Token(TokenType.KEYWORD, word, index, 1, 1))
    result = head_decided(tokens)
    if result is None and len(words) >= MAX_HEAD_TOKENS:
        return False
    return result


def current(words):
    return decide(RULES.unit_heads, [w.upper() for w in words], RULES.max_head_tokens)


def test_every_head_up_to_four_words_decides_as_before():
    count = 0
    for length in range(1, 5):
        for words in product(VOCABULARY, repeat=length):
            assert current(words) == previous(words), words
            count += 1
    assert count > 300_000


def test_seeded_longer_heads_with_comments_between_words_decide_as_before():
    rng = random.Random(42)
    seeds = [
        "CREATE OR REPLACE EDITIONABLE PACKAGE",
        "CREATE OR REPLACE AND COMPILE NOFORCE IF NOT EXISTS MLE MODULE",
        "CREATE OR REPLACE AND RESOLVE NOFORCE JAVA SOURCE",
        "CREATE NOFORCE IF NOT EXISTS MLE MODULE",
        "< < x > > BEGIN",
        "CREATE JAVA CLASS",
        "CREATE OR REPLACE NONEDITIONABLE TRIGGER",
    ]
    for _ in range(200_000):
        words = rng.choice(seeds).split() if rng.random() < 0.7 else []
        if not words:
            words = [rng.choice(LONGER) for _ in range(rng.randrange(1, 11))]
        for _ in range(rng.randrange(0, 3)):
            edit = rng.randrange(3)
            at = rng.randrange(len(words) + 1)
            if edit == 0 and words:
                del words[min(at, len(words) - 1)]
            elif edit == 1:
                words.insert(at, rng.choice(LONGER))
            elif words:
                words[min(at, len(words) - 1)] = rng.choice(LONGER)
        if not words:
            continue
        comments = {i for i in range(len(words)) if rng.random() < 0.2}
        assert current(words) == previous(words, comments), words


@pytest.mark.parametrize(
    "script, unit",
    [
        ("DECLARE x NUMBER; BEGIN NULL; END;", True),
        ("begin null; end;", True),
        ("<<lbl>> BEGIN NULL; END;", True),
        ("<<lbl>>\nDECLARE x NUMBER; BEGIN NULL; END;", True),
        ("CREATE FUNCTION f RETURN NUMBER AS BEGIN RETURN 1; END;", True),
        ("CREATE OR REPLACE PROCEDURE p AS BEGIN NULL; END;", True),
        ("CREATE OR REPLACE EDITIONABLE PACKAGE pk AS END pk;", True),
        ("CREATE OR REPLACE NONEDITIONABLE PACKAGE BODY pk AS END pk;", True),
        ("CREATE TYPE t AS OBJECT (id NUMBER);", True),
        ("CREATE OR REPLACE LIBRARY lib AS 'x.so';", True),
        ("CREATE OR REPLACE AND COMPILE JAVA SOURCE NAMED h AS class H {}", True),
        ("CREATE OR REPLACE AND RESOLVE NOFORCE JAVA SOURCE NAMED h AS class H {}", True),
        ("CREATE JAVA CLASS USING BFILE (d, 'f.class')", True),
        ("CREATE OR REPLACE IF NOT EXISTS MLE MODULE m LANGUAGE JAVASCRIPT AS x", True),
        ("CREATE MLE MODULE m LANGUAGE JAVASCRIPT AS x", True),
        ("CREATE TABLE t (type NUMBER)", False),
        ("CREATE VIEW v AS SELECT begin FROM t", False),
        ("SELECT begin FROM t", False),
        ("ALTER PACKAGE p COMPILE", False),
        ("<<lbl>> SELECT 1 FROM dual", False),
        ("CREATE OR REPLACE AND COMPILE NOFORCE IF NOT EXISTS MLE MODULE m AS x", False),
    ],
)
def test_head_table_on_scripts(script, unit):
    words = [
        t.text.upper()
        for t in LexicalTokenizer(script, spec=ORACLE_SPEC).tokenize()
        if t.type not in (TokenType.COMMENT, TokenType.EOF)
    ][: RULES.max_head_tokens]
    assert decide(RULES.unit_heads, words, RULES.max_head_tokens) is unit


def test_undecided_prefixes_and_the_head_length_limit():
    heads = RULES.unit_heads
    assert decide(heads, ["CREATE", "OR", "REPLACE"], 8) is None
    assert decide(heads, ["CREATE", "OR", "REPLACE", "PACKAGE"], 8) is True
    assert decide(heads, ["CREATE", "TABLE"], 8) is False
    assert decide(heads, ["<", "x"], 8) is False
    undecided = "CREATE OR REPLACE AND COMPILE NOFORCE IF NOT EXISTS MLE MODULE".split()
    assert decide(heads, undecided[:7], 8) is None
    assert decide(heads, undecided[:8], 8) is False
