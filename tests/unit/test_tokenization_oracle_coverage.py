"""Additional Oracle tokenizer tests to reach 80%+ coverage."""

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.tokens import TokenType
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC
from dblift.db.plugins.oracle.parser.oracle_tokenizer import OracleTokenizer


class TestOracleTokenizerCoverage:
    """Tests to cover remaining Oracle tokenizer lines."""

    def test_double_quoted_string_fallback(self):
        """Test that double quotes fall through to parent string handler."""
        # This tests the path where peek() == '"' leads to _handle_quoted_identifier
        sql = '"identifier_name"'
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        assert any(t.type == TokenType.IDENTIFIER for t in tokens)

    def test_single_quoted_string(self):
        """Test standard single-quoted string (super()._handle_string())."""
        sql = "'standard string'"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) == 1

    def test_q_quote_with_single_char_delimiter(self):
        """Test Q-quote with single character delimiter (not in close_map)."""
        # This covers line 90: else branch for single char delimiter
        sql = "q'|text with | pipe|'"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        string_tokens = [t for t in tokens if t.type == TokenType.STRING]
        assert len(string_tokens) == 1

    def test_double_quoted_identifier_without_escapes(self):
        """Test double-quoted identifier without escaped quotes."""
        sql = 'SELECT "simple_identifier" FROM dual;'
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()

        # Should parse entire identifier
        identifier_tokens = [t for t in tokens if t.type == TokenType.IDENTIFIER]
        assert len(identifier_tokens) >= 1
        # Verify we have identifiers (may or may not include quotes depending on implementation)
        assert len(identifier_tokens) > 0

    def test_doubled_quote_in_identifier_is_not_an_escape(self):
        """``""`` is not an escape: an identifier cannot contain ``"`` (spec section 2)."""
        tokens = OracleTokenizer('SELECT "id""with""quotes" FROM dual;').tokenize()

        identifiers = [t.text for t in tokens if t.type == TokenType.IDENTIFIER]
        assert identifiers[:3] == ['"id"', '"with"', '"quotes"']

    def test_doubled_quote_identifier_splits_into_two_statements(self):
        """Spec section 2: the first ``"`` closes, so ``"a""b"`` is two identifiers.

        The server rejects the first statement; the client splits the same way.
        """
        script = 'SELECT "a""b" FROM t;\nSELECT 1 FROM dual;'
        tokens = OracleTokenizer(script).tokenize()

        identifiers = [t.text for t in tokens if t.type == TokenType.IDENTIFIER]
        assert identifiers[:2] == ['"a"', '"b"']
        assert len(LexicalEngine(ORACLE_SPEC).split_statements(script)) == 2

    def test_semicolon_after_doubled_quote_stays_inside_the_second_identifier(self):
        """In ``"a"";b"`` the second ``"`` opens a new identifier ``";b"``.

        So the ``;`` is inside a quoted identifier, not a terminator (spec section 2).
        """
        script = 'SELECT "a"";b" FROM t;\nSELECT 1 FROM dual;'
        tokens = OracleTokenizer(script).tokenize()

        identifiers = [t.text for t in tokens if t.type == TokenType.IDENTIFIER]
        assert identifiers[:2] == ['"a"', '";b"']
        assert len(LexicalEngine(ORACLE_SPEC).split_statements(script)) == 2

    def test_q_quote_at_end_of_input_is_unterminated(self):
        with pytest.raises(UnsafeStatementSplitError, match="unterminated q-quoted string"):
            OracleTokenizer("SELECT q'").tokenize()

    def test_percent_rowtype_not_dropped(self):
        sql = "DECLARE v employees%ROWTYPE; BEGIN NULL; END;\n/"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()
        full_text = "".join(t.text for t in tokens if t.type != TokenType.EOF)
        assert "%" in full_text

    def test_percent_found_not_dropped(self):
        sql = "BEGIN IF SQL%FOUND THEN NULL; END IF; END;\n/"
        tokenizer = OracleTokenizer(sql)
        tokens = tokenizer.tokenize()
        full_text = "".join(t.text for t in tokens if t.type != TokenType.EOF)
        assert "%" in full_text


class TestOracleUnitTermination:
    """A unit ends only at its terminator line."""

    def test_package_body_without_slash_is_refused(self):
        """A PACKAGE BODY ends only at ``/`` (docs/sql-parsing/oracle.md section 11, row 20)."""
        sql = """CREATE OR REPLACE PACKAGE BODY test_pkg AS
    PROCEDURE proc1 AS BEGIN NULL; END;
END test_pkg;"""
        with pytest.raises(UnsafeStatementSplitError, match="not terminated by a '/' line"):
            LexicalEngine(ORACLE_SPEC).split_statements(sql)

    def test_package_spec_without_slash_is_refused(self):
        """A PACKAGE spec ends only at ``/`` (docs/sql-parsing/oracle.md section 11, row 20)."""
        sql = """CREATE PACKAGE test_pkg AS
    PROCEDURE proc1;
END test_pkg;"""
        with pytest.raises(UnsafeStatementSplitError, match="not terminated by a '/' line"):
            LexicalEngine(ORACLE_SPEC).split_statements(sql)


class TestOracleNationalQQuote:
    @pytest.mark.parametrize("prefix", ["nq", "NQ", "Nq", "nQ", "q"])
    def test_alternative_quote_literal_with_embedded_quote_splits_cleanly(self, prefix):
        from dblift.core.migration.sql.statement_reader import StatementReader

        script = f"SELECT {prefix}'[it's]' FROM dual;\nSELECT 1 FROM dual;"
        assert StatementReader("oracle").split_statements(script) == [
            f"SELECT {prefix}'[it's]' FROM dual;",
            "SELECT 1 FROM dual;",
        ]
