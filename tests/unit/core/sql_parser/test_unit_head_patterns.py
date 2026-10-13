"""The unit-head table decides which statements a client buffers up to its terminator line."""

import pytest

from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.core.sql_parser.unit_heads import decide
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

RULES = ORACLE_SPEC.client_script
assert RULES is not None


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
