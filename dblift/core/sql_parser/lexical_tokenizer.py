"""Shared lexical tokenization driven by immutable plugin facts."""

from typing import Iterable, List, Optional

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.lexical_spec import LexicalSpec
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


class LexicalTokenizer(BaseTokenizer):
    """Use the base character scanner with the selected plugin's lexical rules."""

    def __init__(self, sql: str, *, spec: LexicalSpec):
        """Read source positions with the plugin's lexical policies."""
        super().__init__(sql)
        self.spec = spec
        self.dialect_name = spec.name
        self.NESTED_BLOCK_COMMENTS = spec.nested_comments
        self.comments: List[tuple[int, int]] = []
        self.in_copy_data = False
        # Set once the ';' ending a "COPY ... FROM STDIN" header has been read;
        # the very next token is then the data block, not ordinary SQL.
        self._copy_data_pending = False
        # Tokens read since a COPY keyword, until the ';' ending its header.
        self._copy_header: Optional[List[Token]] = None
        self._statement_start = True

    def _next_sql_token(self) -> Optional[Token]:
        """Get the next token from the input.

        Overrides base to handle double-quoted identifiers.

        Returns:
            Next token or None if no more tokens
        """
        if self._copy_data_pending:
            self._copy_data_pending = False
            return self.handle_copy_data()

        if self.spec.sqlite_shell:
            return self._next_sqlite_token()

        self._skip_whitespace()

        if self.pos >= len(self.sql):
            return Token(TokenType.EOF, "", self.pos, self.line, self.col, self.parens_depth)

        char = self.peek()

        # psql's ``\;`` adds a ';' to the query buffer without ending the
        # statement (spec §4): one token, so the parser can combine around it.
        if (
            self.spec.combine_terminator
            and self._copy_header is None
            and self.peek(len(self.spec.combine_terminator)) == self.spec.combine_terminator
        ):
            start_pos, start_line, start_col = self.pos, self.line, self.col
            text = self.read(len(self.spec.combine_terminator))
            return Token(
                TokenType.SYMBOL, text, start_pos, start_line, start_col, self.parens_depth
            )

        # psql client meta-command (e.g. \restrict, \set): any unquoted '\'
        # in SQL state, mid-line included (spec §6). Quoted text, comments and
        # dollar-quotes are consumed whole by their handlers, so a backslash
        # reaching here is unquoted. Not inside a COPY header (up to its ';'),
        # which stays one unit with its data block; the data block itself
        # (rows may start with \N) is read whole above.
        if self.spec.meta_prefix and char == self.spec.meta_prefix and self._copy_header is None:
            return self._handle_meta_command()

        # Flyway / DBLift placeholders ${name} or ${name:default} — not PostgreSQL
        # dollar-quoting ($$…$$ / $tag$…$tag$). Treat as a single token so statement
        # splitting and reconstruction preserve the exact spelling (including before '.').
        if self.peek(2) == "${":
            return self._handle_migration_placeholder()

        # Check for double-quoted identifier BEFORE other checks
        if char == self.spec.quoted_identifier:
            return self._handle_quoted_identifier()

        # '$' that does not open a dollar-quote: a positional parameter ($1)
        # or a stray '$'.
        if char == "$" and not self._is_alternative_string_start():
            start_pos, start_line, start_col = self.pos, self.line, self.col
            text = self.read()
            while self.pos < len(self.sql) and self.peek().isdigit():
                text += self.read()
            return Token(
                TokenType.SYMBOL, text, start_pos, start_line, start_col, self.parens_depth
            )

        # Delegate to base class for other token types
        return super()._next_token()

    def _next_sqlite_token(self) -> Optional[Token]:
        """Read SQLite lexemes using the same token stream as other dialects."""
        if self.pos == 0 and self.peek() == "\ufeff":
            self.read()
        while self.pos < len(self.sql) and self.peek() in " \t\n\f\r":
            self.read()
        if self.pos >= len(self.sql):
            return None
        char = self.peek()
        if self.peek(2) in ("--", "/*"):
            return self._handle_comment()
        if char in "'\"`[":
            return self._handle_sqlite_quote(char)
        if char == ";":
            return self._handle_delimiter()
        start, line, col = self.pos, self.line, self.col
        if (char.isascii() and (char.isalnum() or char in "_$")) or ord(char) >= 128:
            while self.pos < len(self.sql):
                word_char = self.peek()
                if not (
                    (word_char.isascii() and (word_char.isalnum() or word_char in "_$"))
                    or ord(word_char) >= 128
                ):
                    break
                self.read()
            word = self.sql[start : self.pos]
            kind = TokenType.KEYWORD if word.upper() in self.SQL_KEYWORDS else TokenType.IDENTIFIER
            return Token(kind, word, start, line, col, self.parens_depth)
        self.read()
        return Token(TokenType.SYMBOL, char, start, line, col, self.parens_depth)

    def _handle_sqlite_quote(self, opener: str) -> Token:
        """A SQLite quote runs to its first closer, or to end of script."""
        start, line, col = self.pos, self.line, self.col
        closer = "]" if opener == "[" else opener
        self.read()
        end = self.sql.find(closer, self.pos)
        self.read(len(self.sql) - self.pos if end < 0 else end + 1 - self.pos)
        kind = TokenType.STRING if opener == "'" else TokenType.IDENTIFIER
        return Token(kind, self.sql[start : self.pos], start, line, col, self.parens_depth)

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
        """Check for PostgreSQL escape strings and dollar-quote strings.

        Returns:
            True if an escape prefix or dollar-quote is detected
        """
        if self.peek(2) in self.spec.escape_prefixes:
            # An identifier suffix or a prefix touching a quote is not E'...'.
            previous = self.sql[self.pos - 1] if self.pos else ""
            return not previous or not (previous.isalnum() or previous in "_$'\"")
        if not self.spec.dollar_quotes or self.peek() != "$":
            return False
        previous = self.sql[self.pos - 1] if self.pos else ""
        if previous and (previous.isalnum() or previous in "_$"):
            return False  # part of an identifier such as a$b
        after = self.peek(2)[1:]
        if after == "$":
            return True  # empty tag
        # A tag starts like an unquoted identifier; $1 is a parameter, ${ a placeholder.
        return bool(after) and (after.isalpha() or after == "_")

    def _handle_string(self) -> Token:
        """Handle standard strings, escape strings and dollar-quotes.

        Returns:
            String token
        """
        # Check for dollar-quote
        if self.peek() == "$":
            return self._handle_dollar_quote()

        # Check for double-quoted identifier (not string in PostgreSQL)
        if self.peek() == self.spec.quoted_identifier:
            return self._handle_quoted_identifier()

        if self.peek(2) in self.spec.escape_prefixes:
            return self._handle_escape_string()

        if self.spec.plain_string_escapes:
            return self._handle_escape_string()

        # Standard single-quoted string
        return super()._handle_string()

    def _handle_escape_string(self) -> Token:
        """Read a backslash-escaped literal, including an optional E prefix."""
        start_pos, start_line, start_col = self.pos, self.line, self.col
        self.read(2 if self.peek(2) in self.spec.escape_prefixes else 1)
        closed = False
        while self.pos < len(self.sql):
            if self.peek() == "\\" or self.peek(2) == "''":
                self.read(2)
            elif self.read() == "'":
                closed = True
                break
        if not closed:
            raise UnsafeStatementSplitError(
                f"unterminated string opened at line {start_line}, column {start_col}"
            )
        return Token(
            TokenType.STRING,
            self.sql[start_pos : self.pos],
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

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
        else:
            raise UnsafeStatementSplitError(
                f"malformed dollar-quote tag at line {start_line}, column {start_col}"
            )

        # Now read until matching closing tag
        closed = False
        while self.pos < len(self.sql):
            if self.peek(len(tag)) == tag:
                string_text += self.read(len(tag))
                closed = True
                break
            string_text += self.read()
        if not closed:
            raise UnsafeStatementSplitError(
                f"unterminated dollar-quoted string opened at line {start_line}, "
                f"column {start_col}"
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
        closed = False
        while self.pos < len(self.sql):
            char = self.peek()
            if char == self.spec.quoted_identifier:
                # Check for doubled quote (escape)
                if self.peek(2) == self.spec.quoted_identifier * 2:
                    identifier_text += self.read(2)
                else:
                    identifier_text += self.read()  # Closing quote
                    closed = True
                    break
            else:
                identifier_text += self.read()
        if not closed:
            raise UnsafeStatementSplitError(
                f"unterminated quoted identifier opened at line {start_line}, "
                f"column {start_col}"
            )

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
        if token.type == TokenType.DELIMITER and token.parens_depth == 0:
            if self._copy_header is not None and copy_header_reads(
                self._copy_header, "FROM", "STDIN"
            ):
                self.in_copy_data = True
                self._copy_data_pending = True
            self._copy_header = None
        elif self._copy_header is not None:
            self._copy_header.append(token)
        elif (
            self.spec.copy_from_stdin
            and self._statement_start
            and token.type == TokenType.KEYWORD
            and token.text.upper() == "COPY"
        ):
            self._copy_header = []
        if token.type not in (TokenType.COMMENT, TokenType.EOF):
            self._statement_start = token.type in (
                TokenType.META_COMMAND,
                TokenType.COPY_DATA,
            ) or (
                token.parens_depth == 0
                and (
                    token.type == TokenType.DELIMITER
                    or (
                        token.type == TokenType.SYMBOL
                        and bool(self.spec.combine_terminator)
                        and token.text == self.spec.combine_terminator
                    )
                )
            )
        return token

    def handle_copy_data(self) -> Token:
        r"""Read COPY FROM STDIN rows up to the line that is exactly ``\.``.

        The rest of the header line after ``;`` is framing and is dropped. The
        token text is the exact rows, including the newline before the ``\.`` line;
        the statement parser treats that line as the terminator. A line with
        blanks before ``\.`` is data (psql compares the whole line). Rows
        running to end of input remain unchanged.
        """
        header_line = self.line
        while self.pos < len(self.sql) and self.peek() not in ("\r", "\n"):
            if self.peek() in (" ", "\t"):
                self.read()
            elif self.peek(2) in ("--", "/*"):
                comment_col = self.col
                self._handle_comment()
                if self.line != header_line:
                    raise UnsafeStatementSplitError(
                        f"multiline COPY FROM STDIN header comment at line {header_line}, "
                        f"column {comment_col}"
                    )
            else:
                raise UnsafeStatementSplitError(
                    f"text after COPY FROM STDIN header terminator at line {self.line}, "
                    f"column {self.col}"
                )
        if self.peek() == "\r":
            self.read()
        if self.peek() == "\n":
            self.read()
        start_pos, start_line, start_col = self.pos, self.line, self.col
        data_end = len(self.sql)
        while self.pos < len(self.sql):
            line_start = self.pos
            newline = self.sql.find("\n", line_start)
            line_end = len(self.sql) if newline == -1 else newline
            if self.sql[line_start:line_end].rstrip("\r") == "\\.":
                data_end = line_start
                self.read(line_end - line_start + (0 if newline == -1 else 1))
                break
            self.read(line_end - line_start + (0 if newline == -1 else 1))
        self.in_copy_data = False
        return Token(
            TokenType.COPY_DATA,
            self.sql[start_pos:data_end],
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

    def _handle_comment(self) -> Token:
        start = self.pos
        token = super()._handle_comment()
        self.comments.append((start, self.pos))
        if self.spec.sqlite_shell:
            token.text = self.sql[start : self.pos]
        return token
