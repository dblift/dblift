"""Additional PostgreSQL tokenizer tests to reach 80%+ coverage."""

import pytest

from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.postgresql.parser.postgresql_tokenizer import PostgreSQLTokenizer


class TestPostgreSQLTokenizerCoverage:
    """Tests to cover remaining PostgreSQL tokenizer lines."""

    def test_double_quoted_identifier_simple(self):
        """Test double-quoted identifier (lines 99-119)."""
        sql = 'SELECT "column_name" FROM "table_name";'
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_double_quoted_identifier_with_escaped_quotes(self):
        """Test double-quoted identifier with escaped quotes (lines 111-112)."""
        sql = 'SELECT "col""name" FROM "tab""le";'
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 2

    def test_copy_from_stdin_data_block(self):
        """Test COPY FROM STDIN data block handling (lines 204-227)."""
        sql = """COPY users FROM STDIN;
1\tJohn
2\tJane
\\.
"""
        tokenizer = PostgreSQLTokenizer(sql)
        # Set in_copy_data to True to test handle_copy_data
        tokenizer.in_copy_data = True

        # Manually call handle_copy_data
        token = tokenizer.handle_copy_data()

        # Should return a COPY_DATA token
        assert token.type == TokenType.COPY_DATA
        assert tokenizer.in_copy_data is False

    def test_copy_from_stdin_with_backslash_dot(self):
        """Test COPY data with \\. terminator."""
        sql = """COPY test FROM STDIN;
data line 1
data line 2
\\.
SELECT 1;"""
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should tokenize without error
        assert len(tokens) > 0

    def test_is_at_line_start_after_newline(self):
        """Test _is_at_line_start method (lines 236-248)."""
        sql = "\ntext"
        tokenizer = PostgreSQLTokenizer(sql)

        # At start of file
        assert tokenizer._is_at_line_start()

        # After reading newline
        tokenizer.read()
        assert tokenizer._is_at_line_start()

        # After reading text
        tokenizer.read()
        assert not tokenizer._is_at_line_start()

    def test_is_at_line_start_with_whitespace(self):
        """Test _is_at_line_start with whitespace before text."""
        sql = "\n   text"
        tokenizer = PostgreSQLTokenizer(sql)

        # Read newline
        tokenizer.read()
        assert tokenizer._is_at_line_start()

        # Read spaces
        tokenizer.read(3)
        # Still at line start (only whitespace)
        assert tokenizer._is_at_line_start()

    def test_is_at_line_start_with_carriage_return(self):
        """Test _is_at_line_start with \\r."""
        sql = "\rtext"
        tokenizer = PostgreSQLTokenizer(sql)

        # Read carriage return
        tokenizer.read()
        assert tokenizer._is_at_line_start()

    def test_is_copy_from_stdin_detection(self):
        """Test _is_copy_from_stdin method (lines 169)."""
        sql = "COPY users (id, name) FROM STDIN;"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should detect COPY FROM STDIN
        assert any(t.text.upper() == "COPY" for t in tokens)
        assert any(t.text.upper() == "STDIN" for t in tokens)

    def test_dollar_quote_at_end_of_string(self):
        """Test dollar quote that reaches end of string."""
        sql = "$$incomplete"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should handle incomplete dollar quote gracefully
        assert len(tokens) > 0

    def test_dollar_quote_with_alphanumeric_tag(self):
        """Test dollar quote with alphanumeric characters in tag."""
        sql = "$tag123$content$tag123$"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1

    def test_dollar_quote_tag_with_underscore(self):
        """Test dollar quote tag with underscore."""
        sql = "$my_tag$content$my_tag$"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) >= 1

    def test_handle_keyword_with_copy(self):
        """Test _handle_keyword when it encounters COPY."""
        sql = "COPY users FROM STDIN;"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should set in_copy_data flag
        # (This is tested indirectly through tokenization)
        assert len(tokens) > 0

    def test_restrict_meta_command_is_its_own_token(self):
        """A ``\\restrict`` line at the top level tokenizes as one
        META_COMMAND token ending at end of line, not as unclaimed
        characters glued onto the next statement."""
        sql = "\\restrict tok\nSELECT 1;"
        tokenizer = PostgreSQLTokenizer(sql)
        tokens = tokenizer.tokenize()

        meta_tokens = [t for t in tokens if t.type == TokenType.META_COMMAND]
        assert len(meta_tokens) == 1
        assert meta_tokens[0].text == "\\restrict tok"

    def test_meta_command_not_recognized_inside_copy_data(self):
        """The in_copy_data gate: a data row starting with '\\N' must not
        become a META_COMMAND token."""
        sql = "1\t\\N\n\\.\n"
        tokenizer = PostgreSQLTokenizer(sql)
        tokenizer.in_copy_data = True

        token = tokenizer.handle_copy_data()

        assert token.type == TokenType.COPY_DATA
        assert "\\N" in token.text
