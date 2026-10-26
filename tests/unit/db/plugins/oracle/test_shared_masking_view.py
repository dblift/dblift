"""The masking view has different SQL*Plus boundaries from statement splitting."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC


@pytest.mark.parametrize(
    "script, expected",
    [
        ("PROMPT it's -- c", ([(0, 12)], [(12, 16)])),
        ("SELECT (1;\nPROMPT it's -- c\n);", ([(11, 23)], [(23, 27)])),
        ("PROMPT hi -- c", ([(0, 10)], [(10, 14)])),
        ("EXIT -- c\nSELECT 1;", ([(0, 5)], [(5, 9)])),
        ("PROMPT; -- c", ([(0, 8)], [(8, 12)])),
    ],
)
def test_shared_masking_view_preserves_directive_and_comment_spans(script, expected):
    assert LexicalEngine(ORACLE_SPEC).masking_spans(script) == expected


def test_shared_masking_view_does_not_accept_directive_after_block_comment():
    with pytest.raises(UnsafeStatementSplitError, match="unterminated string"):
        LexicalEngine(ORACLE_SPEC).masking_spans("/* c */ PROMPT it's -- x")


@pytest.mark.parametrize(
    "script",
    [
        "REMA it's -- x",
        "CREATE PROCEDURE p AS\nBEGIN NULL;\nPROMPT it's -- x\nEND;\n/",
    ],
)
def test_shared_masking_view_keeps_invalid_directive_text_as_sql(script):
    with pytest.raises(UnsafeStatementSplitError, match="unterminated string"):
        LexicalEngine(ORACLE_SPEC).masking_spans(script)
