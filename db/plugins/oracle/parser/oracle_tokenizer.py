"""Oracle-specific tokenizer.

This module provides Oracle-specific tokenization including Q-quotes,
wrapped PL/SQL detection, and slash delimiters.
"""

from typing import List

from core.sql_parser.base_tokenizer import BaseTokenizer
from core.sql_parser.tokens import Token, TokenType


class OracleTokenizer(BaseTokenizer):
    """Oracle-specific tokenizer with Q-quote and wrapped PL/SQL support.

    Handles Oracle-specific features:
    - Q-quotes: q'{...}', q'[...]', q'(...)', q'<...>', q'!...!'
    - Wrapped PL/SQL (encrypted code)
    - Slash (/) delimiter for PL/SQL blocks
    - Double-quoted identifiers
    """

    dialect_name = "oracle"  # lint: allow-dialect-string: dialect dispatch

    # ``%`` and ``@`` were added here when only Oracle needed them; both are in
    # ``BaseTokenizer.SYMBOL_CHARS`` now, so the override would be a no-op.

    def _is_string_start(self) -> bool:
        """Treat double quotes like string starts so _handle_string runs.

        BaseTokenizer only recognizes single-quoted literals here; without this,
        ``"`` is skipped as an unknown character and quoted identifiers break.
        """
        char = self.peek()
        return char == "'" or char == '"' or self._is_alternative_string_start()

    def _is_alternative_string_start(self) -> bool:
        """Check for Oracle Q-quote string literals.

        Returns:
            True if Q-quote is detected
        """
        peek2 = self.peek(2)
        return peek2.upper() == "Q'"

    def _handle_string(self) -> Token:
        """Handle string literals including Q-quotes.

        Returns:
            String token
        """
        # Check for Q-quote
        if self.peek(2).upper() == "Q'":
            return self._handle_q_quote()

        # Check for double-quoted identifier (not string in Oracle)
        if self.peek() == '"':
            return self._handle_quoted_identifier()

        # Standard single-quoted string
        return super()._handle_string()

    def _handle_q_quote(self) -> Token:
        """Handle Oracle Q-quote string literals.

        Q-quotes allow arbitrary delimiters:
        - q'{text}' - braces
        - q'[text]' - brackets
        - q'(text)' - parentheses
        - q'<text>' - angle brackets
        - q'!text!' - any single character

        Returns:
            String token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Capture entire Q-quote string
        string_text = ""

        # Read Q'
        string_text += self.read(2)

        # Get delimiter character
        delimiter_char = self.read()
        string_text += delimiter_char

        # Map opening delimiter to closing delimiter
        close_map = {
            "[": "]'",
            "{": "}'",
            "(": ")'",
            "<": ">'",
            "!": "!'",
        }

        # Get closing delimiter
        if delimiter_char in close_map:
            close_quote = close_map[delimiter_char]
        else:
            # Single character delimiter (e.g., q'|text|')
            close_quote = delimiter_char + "'"

        # Read until closing delimiter
        while self.pos < len(self.sql):
            if self.peek(len(close_quote)) == close_quote:
                string_text += self.read(len(close_quote))
                break
            string_text += self.read()

        return Token(
            TokenType.STRING,
            string_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _handle_quoted_identifier(self) -> Token:
        """Handle double-quoted identifiers (case-sensitive in Oracle).

        Returns:
            Identifier token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Preserve full identifier including quotes
        identifier_text = ""
        identifier_text += self.read()  # Opening quote

        # Read until closing quote
        while self.pos < len(self.sql):
            char = self.peek()
            if char == '"':
                # Check for doubled quote (escape)
                if self.peek(2) == '""':
                    identifier_text += self.read(2)
                else:
                    identifier_text += self.read()  # Closing quote
                    break
            else:
                identifier_text += self.read()

        return Token(
            TokenType.IDENTIFIER,
            identifier_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _is_delimiter_start(self) -> bool:
        """Check for Oracle delimiters (semicolon or slash).

        Returns:
            True if delimiter is detected
        """
        char = self.peek()
        if char == ";":
            return True

        # Check for slash delimiter (must be alone on line for PL/SQL)
        if char == "/":
            # Look back to see if we're at start of line
            return self._is_slash_delimiter()

        return False

    def _is_slash_delimiter(self) -> bool:
        """Check if slash is a PL/SQL delimiter (must be alone on line).

        Returns:
            True if slash is a valid delimiter
        """
        # Slash must be at start of line or preceded only by whitespace
        # Look back from current position
        check_pos = self.pos - 1
        while check_pos >= 0:
            char = self.sql[check_pos]
            if char == "\n":
                # Found newline - slash is at start of line
                return True
            elif not char.isspace():
                # Found non-whitespace before slash - not a delimiter
                return False
            check_pos -= 1

        # Reached start of file - slash is at start
        return True

    def _handle_delimiter(self) -> Token:
        """Handle Oracle delimiters (semicolon or slash).

        Returns:
            Delimiter token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        delimiter_text = self.read()  # Read semicolon or slash

        return Token(
            TokenType.DELIMITER,
            delimiter_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def is_wrapped_plsql(self, tokens: List[Token]) -> bool:
        """Detect wrapped PL/SQL (encrypted code).

        Wrapped PL/SQL has pattern: CREATE [OR REPLACE] ... WRAPPED

        Args:
            tokens: Tokens processed so far

        Returns:
            True if wrapped PL/SQL is detected
        """
        # Look for CREATE followed by WRAPPED keyword
        if len(tokens) < 3:
            return False

        # Look back through last 10 tokens for CREATE
        create_idx = -1
        check_tokens = tokens[-10:] if len(tokens) >= 10 else tokens

        for i, token in enumerate(check_tokens):
            if token.type == TokenType.KEYWORD and token.text.upper() == "CREATE":
                create_idx = i
                break

        if create_idx < 0:
            return False

        # Check if WRAPPED appears after CREATE
        for token in check_tokens[create_idx:]:
            if token.type == TokenType.KEYWORD and token.text.upper() == "WRAPPED":
                return True

        return False
