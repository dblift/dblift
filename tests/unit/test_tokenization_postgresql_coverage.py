"""Additional PostgreSQL tokenizer tests to reach 80%+ coverage."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.postgresql.parser.lexical_spec import POSTGRESQL_SPEC


class TestLexicalTokenizerCoverage:
    """Tests to cover remaining PostgreSQL tokenizer lines."""

    def test_double_quoted_identifier_simple(self):
        """Test double-quoted identifier (lines 99-119)."""
        sql = 'SELECT "column_name" FROM "table_name";'
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_double_quoted_identifier_with_escaped_quotes(self):
        """Test double-quoted identifier with escaped quotes (lines 111-112)."""
        sql = 'SELECT "col""name" FROM "tab""le";'
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_copy_from_stdin_data_block(self):
        """The tokenizer consumes COPY rows after the header terminator."""
        sql = """COPY users FROM STDIN;
1\tJohn
2\tJane
\\.
"""
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        data_tokens = [token for token in tokens if token.type == TokenType.COPY_DATA]
        assert len(data_tokens) == 1
        assert data_tokens[0].text == "1\tJohn\n2\tJane\n"
        assert tokenizer.in_copy_data is False

    def test_copy_from_stdin_with_backslash_dot(self):
        """Test COPY data with \\. terminator."""
        sql = """COPY test FROM STDIN;
data line 1
data line 2
\\.
SELECT 1;"""
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        # Should tokenize without error
        assert len(tokens) > 0

    def test_is_copy_from_stdin_detection(self):
        """Test _is_copy_from_stdin method (lines 169)."""
        sql = "COPY users (id, name) FROM STDIN;"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        # Should detect COPY FROM STDIN
        assert any(t.text.upper() == "COPY" for t in tokens)
        assert any(t.text.upper() == "STDIN" for t in tokens)

    def test_dollar_quote_at_end_of_string(self):
        """Test dollar quote that reaches end of string."""
        sql = "$$incomplete"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)

        # an unterminated dollar-quoted string is refused, not swallowed
        with pytest.raises(UnsafeStatementSplitError):
            tokenizer.tokenize()

    def test_dollar_quote_with_alphanumeric_tag(self):
        """Test dollar quote with alphanumeric characters in tag."""
        sql = "$tag123$content$tag123$"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1

    def test_dollar_quote_tag_with_underscore(self):
        """Test dollar quote tag with underscore."""
        sql = "$my_tag$content$my_tag$"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1

    def test_handle_keyword_with_copy(self):
        """Test _handle_keyword when it encounters COPY."""
        sql = "COPY users FROM STDIN;"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        # Should set in_copy_data flag
        # (This is tested indirectly through tokenization)
        assert len(tokens) > 0

    def test_restrict_meta_command_is_its_own_token(self):
        """A ``\\restrict`` line at the top level tokenizes as one
        META_COMMAND token ending at end of line, not as unclaimed
        characters glued onto the next statement."""
        sql = "\\restrict tok\nSELECT 1;"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        meta_tokens = [t for t in tokens if t.type == TokenType.META_COMMAND]
        assert len(meta_tokens) == 1
        assert meta_tokens[0].text == "\\restrict tok"

    def test_meta_command_not_recognized_inside_copy_data(self):
        """A data row starting with '\\N' must not become a META_COMMAND
        token: the data block is consumed before top-level dispatch resumes."""
        sql = "COPY t FROM STDIN;\n1\t\\N\n\\.\n"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)
        tokens = tokenizer.tokenize()

        assert [token.text for token in tokens if token.type == TokenType.COPY_DATA] == ["1\t\\N\n"]
        assert not any(token.type == TokenType.META_COMMAND for token in tokens)

    def test_meta_command_gate_protects_the_copy_header_window(self):
        """Unlike the data block above, the COPY-header gate *is* load-
        bearing here: a header is open for the tokens between ``COPY`` and
        its terminating ``;`` (a multi-line column list, say), and a stray ``\\`` there must
        still fall to the unclaimed-character path, not become a
        META_COMMAND — removing the gate reddens this test."""
        sql = "COPY t (\n    id\n)\n\\restrict tok\nFROM stdin;\n1\n\\.\n"
        tokenizer = LexicalTokenizer(sql, spec=POSTGRESQL_SPEC)

        with pytest.warns(UserWarning, match="unclaimed character"):
            tokens = tokenizer.tokenize()

        assert not any(t.type == TokenType.META_COMMAND for t in tokens)
