"""Shared lexical tokenization driven by immutable plugin facts."""

from typing import Iterable, List, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.batch_commands import read_command
from dblift.core.sql_parser.client_directives import classify_directive, is_free_text
from dblift.core.sql_parser.lexical_spec import BOM, DirectiveAction, LexicalSpec
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.core.sql_parser.unit_heads import decide


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


def _scan_line(sql: str, start: int, eol: int) -> Tuple[int, bool]:
    """Find the ``--`` that starts a comment on ``sql[start:eol]``, outside quotes.

    Returns ``(index or -1, closed)``; ``closed`` is False when a quote is
    still open at the end of the line, which means neither a comment nor a
    ``-`` continuation (a doubled quote is read as close-then-open).
    """
    quote = ""
    i = start
    while i < eol:
        char = sql[i]
        if quote:
            if char == quote:
                quote = ""
        elif char in "'\"":
            quote = char
        elif char == "-" and sql.startswith("--", i):
            return i, True
        i += 1
    return -1, not quote


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
        # (position, opener length) of the last alternative-quote lookup.
        self._opener_at = (-1, 0)
        rules = spec.client_script
        self._reads_directives = rules is not None and bool(
            rules.directives or rules.prefix_directives
        )
        # Whether a statement can begin at the cursor, and the statement being read:
        # its head words, and whether that head makes it a unit.
        self._at_start = True
        self._head: List[str] = []
        self._unit: Optional[bool] = None
        # End of a block comment read where a directive could begin: a directive
        # may follow it on the same line.
        self._clear_from: Optional[int] = None
        # Batch scripts: whether only blanks and comments precede the cursor on its line (a
        # command may follow them, nothing else), and the line the last comment ended on.
        self._batches = spec.batch_script
        self._line_head = True
        self._comment_end_line = 0

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

        if self.spec.leading_bom_is_blank and self.pos == 0 and self.peek() == BOM:
            self.pos = 1  # offsets stay source offsets; columns do not count the BOM

        self._skip_whitespace()

        if self.pos >= len(self.sql):
            return Token(TokenType.EOF, "", self.pos, self.line, self.col, self.parens_depth)

        if self._reads_directives and self._at_start:
            directive = self._directive_token()
            if directive is not None:
                return directive

        if self._batches is not None and self._line_head and self.peek(2) not in ("--", "/*"):
            count = read_command(
                self._batches,
                self.spec.client_name,
                self.sql,
                self.pos,
                self.line,
                self._comment_end_line == self.line,
            )
            if count is not None:
                return self._separator_token()

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
        placeholder = self.spec.placeholder_open
        if placeholder and self.peek(len(placeholder)) == placeholder:
            return self._handle_migration_placeholder()

        bracket = self.spec.bracket_identifier
        if bracket and char == bracket[0]:
            return self._handle_bracket_identifier()

        # Check for double-quoted identifier BEFORE other checks
        if char == self.spec.quoted_identifier:
            return self._handle_quoted_identifier()

        # '$' that does not open a dollar-quote: a positional parameter ($1)
        # or a stray '$'.
        prefix = self.spec.parameter_prefix
        if prefix and self.peek(len(prefix)) == prefix and not self._is_alternative_string_start():
            start_pos, start_line, start_col = self.pos, self.line, self.col
            text = self.read(len(prefix))
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
        text += self.read(len(self.spec.placeholder_open or ""))
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
        """Check for alternative quoting, escape strings and dollar-quote strings.

        Returns:
            True if an alternative-quote opener, escape prefix or dollar-quote is detected
        """
        if self._alternative_quote_opener():
            return True
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

    def _track(self, token: Token) -> None:
        """Follow where statements end, as the statement parser does."""
        rules = self.spec.client_script
        assert rules is not None
        if token.type in (TokenType.COMMENT, TokenType.EOF):
            return
        if self._at_start:
            self._at_start = False
            self._head = []
            self._unit = None
        if self._unit is None:
            self._head.append(token.text.upper())
            self._unit = decide(rules.unit_heads, self._head, rules.max_head_tokens)
        if token.type != TokenType.DELIMITER:
            return
        if token.text == rules.line_terminator or (
            token.text == ";" and not self._unit and token.parens_depth == 0
        ):
            self._at_start = True

    def _directive_token(self) -> Optional[Token]:
        """Consume a directive line (and its ``-`` continuations) at the cursor.

        Only blanks and block comments may precede it on its line. A ``--``
        outside quotes ends the directive; the rest of the line is a comment
        and tokenized as one. The text is not lexed: ``REM don't`` opens no
        literal, and for free-text commands the whole line is the text.
        """
        rules = self.spec.client_script
        assert rules is not None
        if not self._line_is_clear(self.pos):
            return None
        first = self.sql[self.pos : self._eol(self.pos)].strip()
        found = classify_directive(rules, first)
        free_text = found is not None and is_free_text(rules, found[0])
        parts: List[str] = []
        cursor = self.pos
        while True:
            eol = self._eol(cursor)
            comment, closed = (-1, True) if free_text else _scan_line(self.sql, cursor, eol)
            end = comment if comment != -1 else eol
            part = self.sql[cursor:end].strip()
            if comment == -1 and closed and part.endswith("-") and eol < len(self.sql):
                parts.append(part[:-1].rstrip())
                cursor = eol + 1
                continue
            parts.append(part)
            break
        text = " ".join(p for p in parts if p)
        directive = classify_directive(rules, text)
        if directive is None:
            return None
        token = Token(TokenType.DIRECTIVE, text, self.pos, self.line, self.col, self.parens_depth)
        self.read(end - self.pos)
        if directive[1] is DirectiveAction.EXIT:
            # The client ignores everything after EXIT, including malformed SQL.
            self.pos = len(self.sql)
        return token

    def _eol(self, start: int) -> int:
        eol = self.sql.find("\n", start)
        return eol if eol != -1 else len(self.sql)

    def _line_is_clear(self, pos: int) -> bool:
        """Whether only blanks and block comments precede ``pos`` on its line."""
        line_start = self.sql.rfind("\n", 0, pos) + 1
        if not self.sql[line_start:pos].strip():
            return True
        return self._clear_from is not None and not self.sql[self._clear_from : pos].strip()

    def _is_delimiter_start(self) -> bool:
        """A ``;``, or a line terminator and discard line when alone on their line."""
        char = self.peek()
        if char == ";":
            return True
        rules = self.spec.client_script
        if rules is not None and char in (rules.line_terminator, rules.discard_line):
            return is_alone_on_line(self.sql, self.pos)
        return False

    def _alternative_quote_opener(self) -> int:
        """Length of the alternative-quote opener (``q'``, ``nq'``) at the cursor, else 0."""
        if self._opener_at[0] == self.pos:
            return self._opener_at[1]
        length = 0
        for opener in self.spec.alternative_quotes:
            if self.peek(len(opener)).lower() == opener.lower():
                length = len(opener)
                break
        self._opener_at = (self.pos, length)
        return length

    def _handle_alternative_quote(self, opener_length: int) -> Token:
        """Read ``q'<d>...<c>'``: the closer ``<c>`` depends on the delimiter ``<d>``."""
        start_pos, start_line, start_col = self.pos, self.line, self.col
        self.read(opener_length)
        # End of input is checked first: ``"" in " \t\r\n"`` is True.
        if self.pos >= len(self.sql):
            raise UnsafeStatementSplitError(
                f"unterminated q-quoted string opened at line {start_line}, column {start_col}"
            )
        delimiter = self.read()
        if delimiter in " \t\r\n":
            raise UnsafeStatementSplitError(
                f"q-quote delimiter cannot be whitespace at line {start_line}, column {start_col}"
            )
        closer = dict(self.spec.alternative_quote_pairs).get(delimiter, delimiter) + "'"
        end = self.sql.find(closer, self.pos)
        if end < 0:
            raise UnsafeStatementSplitError(
                f"unterminated q-quoted string opened at line {start_line}, column {start_col}"
            )
        self.read(end + len(closer) - self.pos)
        return Token(
            TokenType.STRING,
            self.sql[start_pos : self.pos],
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _handle_string(self) -> Token:
        """Handle standard strings, alternative quotes, escape strings and dollar-quotes.

        Returns:
            String token
        """
        opener_length = self._alternative_quote_opener()
        if opener_length:
            return self._handle_alternative_quote(opener_length)

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

        return self._handle_standard_string()

    def _handle_standard_string(self) -> Token:
        """Read ``'...'``: a doubled quote is part of the string. Linear in the string length."""
        start_pos, start_line, start_col = self.pos, self.line, self.col
        quote = self.read()
        while True:
            end = self.sql.find(quote, self.pos)
            if end < 0:
                self.read(len(self.sql) - self.pos)
                raise UnsafeStatementSplitError(
                    f"unterminated string opened at line {start_line}, column {start_col}"
                )
            self.read(end + 1 - self.pos)
            if self.peek() != quote:
                break
            self.read()
        return Token(
            TokenType.STRING,
            self.sql[start_pos : self.pos],
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

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
                if (
                    self.spec.quoted_identifier_escape
                    and self.peek(2) == self.spec.quoted_identifier * 2
                ):
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

    def _skip_whitespace(self) -> None:
        """Skip what ``str.isspace`` accepts; a character that is not a blank ends the line head."""
        if self._batches is None:
            super()._skip_whitespace()
            return
        blanks = self._batches.blanks
        while self.pos < len(self.sql) and self.sql[self.pos].isspace():
            char = self.sql[self.pos]
            if char == "\n":
                self._line_head = True
            elif char not in blanks:
                self._line_head = False
            self.read()

    def _separator_token(self) -> Token:
        """The rest of the line, a trailing CR included, as one DIRECTIVE token."""
        start_pos, start_line, start_col = self.pos, self.line, self.col
        newline = self.sql.find("\n", start_pos)
        end = len(self.sql) if newline < 0 else newline
        text = self.read(end - start_pos)
        return Token(TokenType.DIRECTIVE, text, start_pos, start_line, start_col, self.parens_depth)

    def _handle_bracket_identifier(self) -> Token:
        """Read ``[...]``: a doubled closer is an escape, newlines are part of the name."""
        closer = self.spec.bracket_identifier[1]
        start_pos, start_line, start_col = self.pos, self.line, self.col
        self.read()
        while True:
            end = self.sql.find(closer, self.pos)
            if end < 0:
                self.read(len(self.sql) - self.pos)
                raise UnsafeStatementSplitError(
                    f"unterminated bracketed identifier opened at line {start_line}, "
                    f"column {start_col}"
                )
            self.read(end + 1 - self.pos)
            if self.peek() != closer:
                break
            self.read()
        return Token(
            TokenType.IDENTIFIER,
            self.sql[start_pos : self.pos],
            start_pos,
            start_line,
            start_col,
            self.parens_depth,
        )

    def _handle_unknown_char(self, char: str) -> Optional[Token]:
        """An unclaimed character is a symbol; it only warns when the spec has not declared it silent."""
        if not self.spec.silent_unclaimed:
            return super()._handle_unknown_char(char)
        start_pos, start_line, start_col = self.pos, self.line, self.col
        return Token(
            TokenType.SYMBOL, self.read(), start_pos, start_line, start_col, self.parens_depth
        )

    def _next_token(self) -> Optional[Token]:
        """Get the next token, tracking whether a ``COPY`` header reads FROM STDIN.

        The tokens after ``COPY`` are collected up to the ``;`` that ends the
        header, whatever its length; only then is the header classified. A
        header never looks past its own ``;``.

        Returns:
            Next token or None if no more tokens
        """
        clear = False
        if self._reads_directives:
            self._skip_whitespace()
            clear = self._at_start and self._line_is_clear(self.pos)
        token = self._next_sql_token()
        if token is None:
            return None
        if self._batches is not None:
            if token.type == TokenType.COMMENT:
                if self.sql.find("\n", token.pos, self.pos) >= 0:
                    self._line_head = True  # the line the comment ends on starts inside it
            elif token.type != TokenType.EOF:
                self._line_head = False
        if self._reads_directives and token.type != TokenType.DIRECTIVE:
            if clear and token.type == TokenType.COMMENT and self.sql.startswith("/*", token.pos):
                self._clear_from = self.pos
            self._track(token)
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
        self._comment_end_line = self.line
        if self.spec.sqlite_shell:
            token.text = self.sql[start : self.pos]
        return token
