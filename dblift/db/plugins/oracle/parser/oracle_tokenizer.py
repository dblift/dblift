"""Oracle-specific tokenizer.

This module provides Oracle-specific tokenization including Q-quotes,
wrapped PL/SQL detection, and slash delimiters.
"""

from typing import List, Optional

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.oracle.parser._directives import classify_directive
from dblift.db.plugins.oracle.parser._unit_heads import MAX_HEAD_TOKENS, head_decided


def has_stray_comment_close(tokens: List[Token]) -> bool:
    """Whether ``tokens`` contain a ``*/`` outside any comment or literal.

    The tokenizer has already consumed comments and string, q-quote and
    quoted-identifier literals, so a ``*`` symbol directly followed by a
    ``/`` symbol is a block-comment close with no matching open.
    """
    return any(
        a.text == "*" and b.text == "/" and b.pos == a.pos + 1 for a, b in zip(tokens, tokens[1:])
    )


def is_alone_on_line(sql: str, pos: int) -> bool:
    """Whether ``sql[pos]`` is the only non-blank text on its line.

    Looks only at the blanks adjacent to ``pos``, so the cost does not grow
    with the length of the line.
    """
    i = pos - 1
    while i >= 0 and sql[i] != "\n":
        if not sql[i].isspace():
            return False
        i -= 1
    i = pos + 1
    while i < len(sql) and sql[i] != "\n":
        if not sql[i].isspace():
            return False
        i += 1
    return True


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

    def __init__(self, sql: str, strict_unknown_chars: bool = False, directives: bool = True):
        """Initialize the tokenizer.

        Args:
            sql: SQL content to tokenize
            strict_unknown_chars: see ``BaseTokenizer``
            directives: read SQL*Plus directive lines as ``DIRECTIVE`` tokens
                (docs/sql-parsing/oracle.md section 6). Off for the callers
                that still handle directives themselves.
        """
        super().__init__(sql, strict_unknown_chars)
        self._directives = directives
        # Whether a statement can begin at the cursor, and the statement being
        # read: its head, and whether that head makes it a PL/SQL unit.
        self._at_start = True
        self._head: List[Token] = []
        self._unit: Optional[bool] = None

    def _next_token(self) -> Optional[Token]:
        if not self._directives:
            return super()._next_token()
        self._skip_whitespace()
        if self._at_start and self.pos < len(self.sql):
            directive = self._directive_token()
            if directive is not None:
                return directive
        token = super()._next_token()
        if token is not None:
            self._track(token)
        return token

    def _track(self, token: Token) -> None:
        """Follow where statements end, as the statement parser does (section 4)."""
        if token.type in (TokenType.COMMENT, TokenType.EOF):
            return
        if self._at_start:
            self._at_start = False
            self._head = []
            self._unit = None
        if self._unit is None:
            self._head.append(token)
            self._unit = head_decided(self._head)
            if self._unit is None and len(self._head) >= MAX_HEAD_TOKENS:
                self._unit = False
        if token.type != TokenType.DELIMITER:
            return
        if token.text == "/" or (token.text == ";" and not self._unit and token.parens_depth == 0):
            self._at_start = True

    def _directive_token(self) -> Optional[Token]:
        """Consume a directive line (and its ``-`` continuations) at the cursor.

        Only blanks may precede it on its line. A ``--`` ends the directive;
        the rest of the line is a comment and tokenized as one. The text is
        not lexed: ``REM don't`` opens no literal.
        """
        line_start = self.sql.rfind("\n", 0, self.pos) + 1
        if self.sql[line_start : self.pos].strip():
            return None
        parts: List[str] = []
        cursor = self.pos
        while True:
            eol = self.sql.find("\n", cursor)
            eol = eol if eol != -1 else len(self.sql)
            comment = self.sql.find("--", cursor, eol)
            end = comment if comment != -1 else eol
            part = self.sql[cursor:end].strip()
            if comment == -1 and part.endswith("-") and eol < len(self.sql):
                parts.append(part[:-1].rstrip())
                cursor = eol + 1
                continue
            parts.append(part)
            break
        text = " ".join(p for p in parts if p)
        if classify_directive(text) is None:
            return None
        token = Token(TokenType.DIRECTIVE, text, self.pos, self.line, self.col, self.parens_depth)
        self.read(end - self.pos)
        return token

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
        return self._q_quote_prefix_length() > 0

    def _q_quote_prefix_length(self) -> int:
        """Length of an ``q'`` / ``nq'`` opener at the cursor, else 0."""
        if self.peek(2).upper() == "Q'":
            return 2
        if self.peek(3).upper() == "NQ'":
            return 3
        return 0

    def _handle_string(self) -> Token:
        """Handle string literals including Q-quotes.

        Returns:
            String token
        """
        # Check for Q-quote
        if self._q_quote_prefix_length():
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

        # Read Q' (or NQ')
        string_text += self.read(self._q_quote_prefix_length())

        # Get delimiter character; end of input is checked first because
        # ``"" in " \t\r\n"`` is True.
        if self.pos >= len(self.sql):
            raise UnsafeStatementSplitError(
                f"unterminated q-quoted string opened at line {start_line}, column {start_col}"
            )
        delimiter_char = self.read()
        if delimiter_char in " \t\r\n":
            raise UnsafeStatementSplitError(
                f"q-quote delimiter cannot be whitespace at line {start_line}, column {start_col}"
            )
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
        closed = False
        while self.pos < len(self.sql):
            if self.peek(len(close_quote)) == close_quote:
                string_text += self.read(len(close_quote))
                closed = True
                break
            string_text += self.read()
        if not closed:
            raise UnsafeStatementSplitError(
                f"unterminated q-quoted string opened at line {start_line}, column {start_col}"
            )

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
        closed = False
        while self.pos < len(self.sql):
            # A quoted identifier cannot contain ``"`` (spec section 2), so
            # ``""`` is not an escape: it closes at the first quote.
            char = self.read()
            identifier_text += char
            if char == '"':
                closed = True
                break
        if not closed:
            raise UnsafeStatementSplitError(
                f"unterminated quoted identifier opened at line {start_line}, column {start_col}"
            )

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

        # ``/`` and ``.`` are SQL*Plus terminators only alone on their line.
        if char in ("/", "."):
            return self._is_alone_on_line()

        return False

    def _is_alone_on_line(self) -> bool:
        """Whether the character at the cursor is the only non-blank text on its line."""
        return is_alone_on_line(self.sql, self.pos)

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
