"""PostgreSQL-specific tokenizer.

This module provides PostgreSQL-specific tokenization including dollar quotes
and COPY FROM STDIN data block handling.
"""

from typing import Iterable, List, Optional

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType


def copy_header_reads(tokens: Iterable[Token], direction: str, stream: str) -> bool:
    """Whether a ``COPY`` header's tokens contain *direction* *stream* at the top level.

    For example ``("FROM", "STDIN")`` or ``("TO", "STDOUT")``. Words inside
    parentheses (a column list, ``WITH (...)`` options, a ``COPY (query)``)
    and quoted identifiers or strings never match, and comments are skipped.
    """
    words = [
        token.text.upper()
        for token in tokens
        if token.type != TokenType.COMMENT and token.parens_depth == 0
    ]
    return any(a == direction and b == stream for a, b in zip(words, words[1:]))


class PostgreSQLTokenizer(BaseTokenizer):
    """PostgreSQL-specific tokenizer with dollar-quote and COPY support.

    Handles PostgreSQL-specific features:
    - Dollar-quoted strings: $$text$$ or $tag$text$tag$
    - COPY FROM STDIN data blocks
    - Double-quoted identifiers (case-sensitive)
    """

    dialect_name = "postgresql"  # lint: allow-dialect-string: dialect dispatch

    # PostgreSQL documents nested block comments explicitly.
    NESTED_BLOCK_COMMENTS = True

    def __init__(self, sql: str, strict_unknown_chars: bool = False):
        """Initialize PostgreSQL tokenizer.

        Args:
            sql: SQL content to tokenize
            strict_unknown_chars: If True, unknown characters fail tokenization.
        """
        super().__init__(sql, strict_unknown_chars=strict_unknown_chars)
        self.in_copy_data = False
        # Set once the ';' ending a "COPY ... FROM STDIN" header has been read;
        # the very next token is then the data block, not ordinary SQL.
        self._copy_data_pending = False
        # Tokens read since a COPY keyword, until the ';' ending its header.
        self._copy_header: Optional[List[Token]] = None

    def _next_sql_token(self) -> Optional[Token]:
        """Get the next token from the input.

        Overrides base to handle double-quoted identifiers.

        Returns:
            Next token or None if no more tokens
        """
        if self._copy_data_pending:
            self._copy_data_pending = False
            return self.handle_copy_data()

        self._skip_whitespace()

        if self.pos >= len(self.sql):
            return Token(TokenType.EOF, "", self.pos, self.line, self.col, self.parens_depth)

        char = self.peek()

        # psql client meta-command (e.g. \restrict, \i): a line whose first
        # non-whitespace character is '\' at the top level. Not inside a COPY
        # header (up to its ';'), which stays one unit with its data block;
        # the data block itself (rows may start with \N) is read whole above.
        if char == "\\" and self._copy_header is None and self._is_at_line_start():
            return self._handle_meta_command()

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

    def _next_token(self) -> Optional[Token]:
        """Get the next token, tracking whether a ``COPY`` header reads FROM STDIN.

        The tokens after ``COPY`` are collected up to the ``;`` that ends the
        header, whatever its length; only then is the header classified. A
        header never looks past its own ``;``.

        Returns:
            Next token or None if no more tokens
        """
        token = self._next_sql_token()
        if token is None:
            return None
        if token.type == TokenType.DELIMITER:
            if self._copy_header is not None and copy_header_reads(
                self._copy_header, "FROM", "STDIN"
            ):
                self.in_copy_data = True
                self._copy_data_pending = True
            self._copy_header = None
        elif self._copy_header is not None:
            self._copy_header.append(token)
        elif token.type == TokenType.KEYWORD and token.text.upper() == "COPY":
            self._copy_header = []
        return token

    def handle_copy_data(self) -> Token:
        r"""Handle a COPY FROM STDIN data block, ending at \. on its own line.

        The newline that ends the header's ``;`` is formatting, not data, and
        is dropped before the token starts — otherwise a row whose first
        column is empty (a leading tab) would lose that tab to whitespace
        skipping.

        Returns:
            COPY_DATA token containing the data block, terminator included
        """
        if self.peek() == "\r":
            self.read()
        if self.peek() == "\n":
            self.read()

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
            TokenType.COPY_DATA,
            data_text,
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _handle_meta_command(self) -> Token:
        r"""Read a psql meta-command line, ending at end of line.

        PostgreSQL's own parser never sees this line — it is a client
        directive, not SQL — so it is its own unit rather than glued onto
        whatever statement follows. What dblift does with it is decided by
        the statement parser, not the tokenizer.

        Returns:
            META_COMMAND token containing the line, backslash included
        """
        start_pos = self.pos
        start_line = self.line
        start_col = self.col

        text = ""
        while self.pos < len(self.sql) and self.peek() not in ("\n", "\r"):
            text += self.read()

        return Token(
            TokenType.META_COMMAND,
            text,
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


class NonNestingPostgreSQLTokenizer(PostgreSQLTokenizer):
    """PostgreSQL-syntax tokenizer for a wire-compatible engine kept
    non-nesting by default because nesting isn't established for it
    (Redshift — see ``RedshiftQuirks.parser_class`` and CHANGELOG.md).
    Reuses everything else PostgreSQL does; only the nesting claim is
    withheld.
    """

    NESTED_BLOCK_COMMENTS = False
