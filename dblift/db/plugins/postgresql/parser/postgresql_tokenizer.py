"""PostgreSQL-specific tokenizer.

This module provides PostgreSQL-specific tokenization including dollar quotes
and COPY FROM STDIN data block handling.
"""

from typing import Optional

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType


class PostgreSQLTokenizer(BaseTokenizer):
    """PostgreSQL-specific tokenizer with dollar-quote and COPY support.

    Handles PostgreSQL-specific features:
    - Dollar-quoted strings: $$text$$ or $tag$text$tag$
    - COPY FROM STDIN data blocks
    - Double-quoted identifiers (case-sensitive)
    """

    dialect_name = "postgresql"  # lint: allow-dialect-string: dialect dispatch

    def __init__(self, sql: str, strict_unknown_chars: bool = False):
        """Initialize PostgreSQL tokenizer.

        Args:
            sql: SQL content to tokenize
            strict_unknown_chars: If True, unknown characters fail tokenization.
        """
        super().__init__(sql, strict_unknown_chars=strict_unknown_chars)
        self.in_copy_data = False

    def _next_token(self) -> Optional[Token]:
        """Get the next token from the input.

        Overrides base to handle double-quoted identifiers.

        Returns:
            Next token or None if no more tokens
        """
        self._skip_whitespace()

        if self.pos >= len(self.sql):
            return Token(TokenType.EOF, "", self.pos, self.line, self.col, self.parens_depth)

        char = self.peek()

        # Flyway / DBLift placeholders ${name} or ${name:default} — not PostgreSQL
        # dollar-quoting ($$…$$ / $tag$…$tag$). Treat as a single token so statement
        # splitting and reconstruction preserve the exact spelling (including before '.').
        if self.peek(2) == "${":
            return self._handle_migration_placeholder()

        # Check for double-quoted identifier BEFORE other checks
        if char == '"':
            return self._handle_quoted_identifier()

        # Delegate to base class for other token types
        return super()._next_token()

    def _handle_migration_placeholder(self) -> Token:
        """Read a ${…} placeholder as one identifier-like token.

        Stops at the first closing `}` (same rule as placeholder replacement).
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col
        text = ""
        text += self.read(2)  # ${
        while self.pos < len(self.sql) and self.peek() != "}":
            text += self.read()
        if self.pos < len(self.sql) and self.peek() == "}":
            text += self.read()
        return Token(
            TokenType.IDENTIFIER,
            text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _is_alternative_string_start(self) -> bool:
        """Check for PostgreSQL dollar-quote strings.

        Returns:
            True if dollar-quote is detected
        """
        if self.peek() != "$":
            return False
        # ${…} is handled in _next_token; do not treat as dollar-quoted string.
        return len(self.sql) <= self.pos + 1 or self.sql[self.pos + 1] != "{"

    def _handle_string(self) -> Token:
        """Handle string literals including dollar-quotes.

        Returns:
            String token
        """
        # Check for dollar-quote
        if self.peek() == "$":
            return self._handle_dollar_quote()

        # Check for double-quoted identifier (not string in PostgreSQL)
        if self.peek() == '"':
            return self._handle_quoted_identifier()

        # Standard single-quoted string
        return super()._handle_string()

    def _handle_dollar_quote(self) -> Token:
        """Handle PostgreSQL dollar-quoted strings.

        Dollar quotes can be:
        - $$ ... $$
        - $tag$ ... $tag$

        Returns:
            String token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Capture entire dollar-quoted string
        string_text = ""

        # Read opening tag
        tag = self.read()  # $
        string_text += tag
        while self.pos < len(self.sql) and self.peek() != "$":
            # Tag can contain letters, numbers, underscore
            char = self.peek()
            if char.isalnum() or char == "_":
                tag += self.read()
                string_text += char
            else:
                break

        # Read closing $
        if self.pos < len(self.sql) and self.peek() == "$":
            closing_dollar = self.read()
            tag += closing_dollar
            string_text += closing_dollar

        # Now read until matching closing tag
        while self.pos < len(self.sql):
            if self.peek(len(tag)) == tag:
                string_text += self.read(len(tag))
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
        """Handle double-quoted identifiers (case-sensitive in PostgreSQL).

        Returns:
            Identifier token
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Capture entire identifier including quotes
        identifier_text = ""

        # Read opening quote
        identifier_text += self.read()

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

    def _handle_keyword(self) -> Token:
        """Handle keywords, including COPY detection.

        Returns:
            Keyword token
        """
        # Read the keyword
        token = super()._handle_keyword()

        # Check if this is COPY FROM STDIN
        if token.text.upper() == "COPY":
            # Check if followed by FROM STDIN pattern
            if self._is_copy_from_stdin():
                self.in_copy_data = True

        return token

    def _is_copy_from_stdin(self) -> bool:
        """Check if we're in a COPY FROM STDIN statement.

        Returns:
            True if COPY FROM STDIN is detected
        """
        # Look ahead to find FROM STDIN pattern
        saved_pos = self.pos
        saved_line = self.line
        saved_col = self.col

        try:
            # Skip whitespace and tokens until we find FROM and STDIN
            found_from = False
            found_stdin = False

            for _ in range(20):  # Look ahead up to 20 tokens
                self._skip_whitespace()
                if self.pos >= len(self.sql):
                    break

                # Read next word
                if self._is_keyword_start():
                    word = ""
                    while self.pos < len(self.sql) and (
                        self.sql[self.pos].isalnum() or self.sql[self.pos] == "_"
                    ):
                        word += self.read()

                    if word.upper() == "FROM":
                        found_from = True
                    elif word.upper() == "STDIN" and found_from:
                        found_stdin = True
                        break
                else:
                    # Skip non-keyword character
                    self.read()

            return found_from and found_stdin

        finally:
            # Restore position
            self.pos = saved_pos
            self.line = saved_line
            self.col = saved_col

    def handle_copy_data(self) -> Token:
        r"""Handle COPY FROM STDIN data block.

        Data ends with \. on its own line.

        Returns:
            String token containing COPY data
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        # Capture entire COPY data block
        data_text = ""

        # Read until \. on its own line
        while self.pos < len(self.sql):
            # Check for \. at start of line
            if self._is_at_line_start() and self.peek(2) == "\\.":
                # Read the \. marker
                data_text += self.read(2)
                # Skip to end of line
                while self.pos < len(self.sql) and self.peek() not in ("\n", "\r"):
                    data_text += self.read()
                if self.pos < len(self.sql):
                    data_text += self.read()  # Read the newline
                break

            # Read character
            data_text += self.read()

        self.in_copy_data = False
        return Token(
            TokenType.STRING,
            data_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _is_at_line_start(self) -> bool:
        """Check if we're at the start of a line.

        Returns:
            True if at line start
        """
        # Look back to find if we're after a newline or at file start
        if self.pos == 0:
            return True

        check_pos = self.pos - 1
        while check_pos >= 0:
            char = self.sql[check_pos]
            if char in ("\n", "\r"):
                return True
            elif not char.isspace():
                return False
            check_pos -= 1

        return True
