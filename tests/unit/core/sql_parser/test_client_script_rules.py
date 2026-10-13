"""The client script rules, driven directly (a DEFINE without a value, EXIT as the last line)."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.client_script import ClientScript
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

RULES = ORACLE_SPEC.client_script
assert RULES is not None


def tokens(script):
    return [
        t for t in LexicalTokenizer(script, spec=ORACLE_SPEC).tokenize() if t.type != TokenType.EOF
    ]


def test_a_define_without_a_value_defines_nothing():
    assert LexicalEngine(ORACLE_SPEC).split_statements("DEFINE v\nSELECT 1 FROM dual;") == [
        "SELECT 1 FROM dual;"
    ]
    with pytest.raises(UnsafeStatementSplitError, match="&v on line 2 is undefined"):
        LexicalEngine(ORACLE_SPEC).split_statements("DEFINE v\nSELECT &v FROM dual;")


def test_exit_as_the_last_line_has_no_ignored_tail():
    script = ClientScript(RULES, "SELECT 1 FROM dual;\nEXIT")
    exit_token = next(
        t for t in tokens("SELECT 1 FROM dual;\nEXIT") if t.type == TokenType.DIRECTIVE
    )
    assert script.ignored_tail_message(exit_token) is None
