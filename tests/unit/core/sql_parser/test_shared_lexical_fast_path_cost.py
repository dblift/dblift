"""Cost contract for ordinary words read by the shared lexical tokenizer."""

import pytest

from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlserver.parser.lexical_spec import SQLSERVER_SPEC


@pytest.mark.parametrize("spec", [POSTGRESQL_SPEC, SQLITE_SPEC, SQLSERVER_SPEC])
def test_plain_word_is_read_as_one_span(spec):
    class CountingTokenizer(LexicalTokenizer):
        reads = 0

        def read(self, n=1):
            self.reads += 1
            return super().read(n)

    word = "a" * 4096
    tokenizer = CountingTokenizer(f"SELECT {word};", spec=spec)
    tokens = tokenizer.tokenize()

    assert [(token.type, token.text) for token in tokens] == [
        (TokenType.KEYWORD, "SELECT"),
        (TokenType.IDENTIFIER, word),
        (TokenType.DELIMITER, ";"),
    ]
    assert tokenizer.reads < 32


@pytest.mark.parametrize("spec", [POSTGRESQL_SPEC, SQLITE_SPEC, SQLSERVER_SPEC])
def test_repeated_insert_words_do_not_require_a_read_per_character(spec):
    class CountingTokenizer(LexicalTokenizer):
        reads = 0

        def read(self, n=1):
            self.reads += 1
            return super().read(n)

    script = "INSERT INTO t (id, payload) VALUES (1, 'text');\n" * 100
    tokenizer = CountingTokenizer(script, spec=spec)
    tokens = tokenizer.tokenize()

    assert sum(token.type == TokenType.KEYWORD and token.text == "INSERT" for token in tokens) == 100
    assert tokenizer.reads < len(script) // 2
