"""PostgreSQL escape literals retain their text and source coordinates."""

import pytest

from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.postgresql.parser.postgresql_tokenizer import PostgreSQLTokenizer

pytestmark = pytest.mark.unit


@pytest.mark.parametrize("prefix", ["E", "e"])
def test_escape_string_is_one_token_with_source_coordinates(prefix):
    literal = prefix + "'it\\'s;\n x'"
    sql = "SELECT (" + literal + "); SELECT 2;"
    tokens = PostgreSQLTokenizer(sql).tokenize()
    strings = [token for token in tokens if token.type == TokenType.STRING]

    assert len(strings) == 1
    token = strings[0]
    assert token.text == literal
    assert (token.pos, token.line, token.col, token.parens_depth) == (8, 1, 9, 1)
    following_select = [token for token in tokens if token.text == "SELECT"][1]
    assert (following_select.pos, following_select.line, following_select.col) == (
        sql.index("SELECT", 1),
        2,
        7,
    )


@pytest.mark.parametrize("prefix", ["SOME", "some", "_E", "a$E", "éE", "'x'E", '"x"E'])
def test_non_standalone_e_is_not_an_escape_prefix(prefix):
    tokens = PostgreSQLTokenizer(prefix + r"'x\'; SELECT 2;").tokenize()

    assert [token.text for token in tokens if token.type == TokenType.STRING][-1] == r"'x\'"
    assert [token.text for token in tokens if token.type == TokenType.DELIMITER] == [";", ";"]
