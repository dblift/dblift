"""Shared lexical tokenization driven by immutable plugin facts."""

import re
from typing import Callable, Dict, FrozenSet, Iterable, List, NoReturn, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.batch_commands import (
    find_lone_cr,
    read_command,
    refuse_lone_cr,
    refuse_variable_in_code,
    refuse_variable_in_lexeme,
)
from dblift.core.sql_parser.blank_pass import kept_stretches
from dblift.core.sql_parser.client_directives import classify_directive, is_free_text
from dblift.core.sql_parser.delimiter_script import DelimiterScript
from dblift.core.sql_parser.lexical_spec import (
    BOM,
    DirectiveAction,
    LexicalSpec,
    SegmentScriptRules,
)
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.terminator_script import TerminatorScript
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
        delimiter_rules = spec.delimiter_script
        terminator_rules = spec.terminator_script
        terminator_script: Optional[TerminatorScript] = None
        if terminator_rules is not None:
            # Terminator runs are blanked before lexing; offsets are into the text after the mark.
            origin = 1 if spec.leading_bom_is_blank and sql.startswith(BOM) else 0
            terminator_script = TerminatorScript(
                terminator_rules, spec.client_name, sql[origin:], origin, spec.text_blanks
            )
            sql = terminator_script.masked
        removed: List[int] = []
        if delimiter_rules is not None:
            # The client reads lines and drops the CR of a CRLF pair; `removed` maps offsets back.
            removed = [
                match.start() - count for count, match in enumerate(re.finditer("\r\n", sql))
            ]
            sql = sql.replace("\r\n", "\n")
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
        # The code segment being read (a line's text up to the next lexeme or comment opener):
        # where it ends, whether its refusals ran, the start of the blanks before it, a carriage
        # return found in it, the cached end of the current line, where the current token began.
        self._seg_end = 0
        self._seg_checked = True
        self._region_start = 0
        self._seg_lone_cr = False
        self._line_end = -1
        self._token_start = 0
        self._token_line = 1
        openers = ["'", "/*", "--", spec.quoted_identifier, *spec.bracket_identifier[:1]]
        self._opener_re = re.compile("|".join(re.escape(o) for o in openers if o))
        # Delimiter scripts: client state, word alphabet, active delimiter, cached line end.
        self.delimiter_script: Optional[DelimiterScript] = None
        # Terminator scripts: the client's reading, where a lexeme left open at the end begins,
        # and the nesting depth at each consumed terminator that falls inside a comment.
        self.terminator_script = terminator_script
        self.open_lexeme = -1
        # Segment scripts: the line and column of a block comment left open, for the split to refuse.
        self.open_comment: Optional[Tuple[int, int]] = None
        self.marks: Dict[int, Tuple[int, bool]] = {}
        self._word_re = re.compile("" if terminator_rules is None else terminator_rules.word)
        self._delimiter = ""
        self._eol_cache = -1
        self._line_start = True
        self._seen_from, self._seen_at = len(sql) + 1, -1
        if delimiter_rules is not None:
            origin = 1 if spec.leading_bom_is_blank and sql.startswith(BOM) else 0
            self.delimiter_script = DelimiterScript(
                delimiter_rules,
                spec.client_name,
                sql,
                removed,
                origin,
                spec.text_blanks,
                spec.trailing_edge_blanks,
                spec.comment_adjacent_blanks,
            )
            self._word_re = re.compile("[" + delimiter_rules.word_part + "]+")
            self._delimiter = delimiter_rules.initial
        # Segment scripts: the patterns compiled once, and the two facts the next lexeme depends on.
        self._segment = spec.segment_script
        self._seg_blanks: FrozenSet[str] = frozenset()
        self._seg_wide: FrozenSet[str] = frozenset()
        self._seg_word = self._seg_number = self._seg_tag = re.compile("")
        self._seg_word_part = self._seg_kept_part = re.compile("")
        self._seg_kept: List[int] = []
        self._seg_kept_at = 0
        self._seg_parameter = self._seg_comment = re.compile("")
        self.origin = 0
        self._seg_pending = False
        self._seg_escape = False
        if self._segment is not None:
            self._init_segment_script(self._segment)

    def tokenize(self) -> List[Token]:
        """Read every token; a delimiter script then refuses what it left open."""
        if self.spec.terminator_script is not None:
            return self._tokenize_terminator_script()
        if self._segment is not None:
            return self._tokenize_segment_script(self._segment)
        tokens = super().tokenize()
        if self.delimiter_script is not None:
            self.delimiter_script.finish()
        return tokens

    def _tokenize_terminator_script(self) -> List[Token]:
        """Lexemes of a terminator script, read from the text with its terminators blanked.

        An unterminated string, identifier or comment runs to the end of the script: the assembly
        decides what that means. The depth at each consumed terminator that falls inside a comment is marked.
        """
        sql = self.sql
        tokens: List[Token] = []
        assert self.terminator_script is not None
        stops = [line.body_end for line in self.terminator_script.lines if line.body_end >= 0]
        index, size = 0, len(sql)
        while self.pos < size:
            pos, line, col = self.pos, self.line, self.col
            char = sql[pos]
            if char.isspace():
                end = pos + 1
                while end < size and sql[end].isspace():
                    end += 1
                self.read(end - pos)
                continue
            kind = TokenType.SYMBOL
            if sql.startswith("--", pos):
                kind = TokenType.COMMENT
                end = sql.find("\n", pos)
                end = size if end < 0 else end
                self.read(end - pos)
                self.comments.append((pos, end))
            elif sql.startswith("/*", pos):
                kind = TokenType.COMMENT
                self.read(2)
                while index < len(stops) and stops[index] < self.pos:
                    index += 1
                depth, index = self._read_block_comment(stops, index, self.marks)
                if depth:
                    self.open_lexeme = pos
                self.comments.append((pos, self.pos))
            elif char == "'" or char == self.spec.quoted_identifier:
                kind = TokenType.STRING if char == "'" else TokenType.IDENTIFIER
                try:
                    if char == "'":
                        self._handle_standard_string()
                    else:
                        self._handle_quoted_identifier()
                except UnsafeStatementSplitError:
                    self.open_lexeme = pos  # the lexeme ran to the end of the script
            else:
                word = self._word_re.match(sql, pos)
                if word is not None:
                    kind = TokenType.KEYWORD
                    self.read(word.end() - pos)
                else:
                    self.read()
            tokens.append(Token(kind, sql[pos : self.pos], pos, line, col, self.parens_depth))
        return tokens

    def _init_segment_script(self, rules: SegmentScriptRules) -> None:
        """Compile the patterns a segment script reads at the cursor."""
        self._seg_blanks = frozenset(rules.blanks)
        self._seg_wide = frozenset(blank for blank in rules.blanks if blank >= "\x80")
        self._seg_word = re.compile(rules.word)
        pass_rules = rules.blank_pass
        self._seg_word_part = re.compile(pass_rules.word_part if pass_rules else "")
        self._seg_kept_part = re.compile(pass_rules.kept_word_part if pass_rules else "")
        self._seg_number = re.compile(rules.number)
        self._seg_tag = re.compile(rules.dollar_tag)
        self._seg_parameter = re.compile(rules.parameter)
        self._seg_comment = re.compile("--[^" + re.escape(rules.line_comment_ends) + "]*")

    def _tokenize_segment_script(self, rules: SegmentScriptRules) -> List[Token]:
        """Lexemes of a segment script in one pass, after the refused character check.

        An unterminated string, identifier, dollar-quoted string or comment runs to the end of the
        script, and nothing at the end of a script is refused. Closed comments are recorded.
        """
        sql = self.sql
        self.origin = origin = 1 if self.spec.leading_bom_is_blank and sql.startswith(BOM) else 0
        bad = sql.find(rules.refused_character, origin)
        if bad >= 0:
            raise UnsafeStatementSplitError(
                f"a {rules.refused_character_name} character on line "
                f"{sql.count(chr(10), origin, bad) + 1}: {rules.refused_reason}"
            )
        self.pos = origin
        tokens: List[Token] = []
        size = len(sql)
        if rules.blank_pass is not None:
            last = max(sql.rfind(blank) for blank in rules.blanks)
            if last >= origin:
                self._seg_kept = kept_stretches(
                    sql, origin, last, rules.line_comment_ends, rules.blank_pass
                )
        while self.pos < size:
            token = self._next_segment_token(rules)
            if token is not None:
                tokens.append(token)
        return tokens

    def _next_segment_token(self, rules: SegmentScriptRules) -> Optional[Token]:
        """The lexeme at the cursor, or None for a blank."""
        sql, pos = self.sql, self.pos
        char = sql[pos]
        if char in self._seg_blanks and not (char in self._seg_wide and self._kept_until(pos)):
            self.read()
            return None
        if self._at_command_line(rules, pos):
            self._refuse_command_line(pos)
        if sql.startswith("--", pos):
            return self._segment_line_comment()
        if sql.startswith("/*", pos):
            return self._segment_block_comment()
        if char == "'":
            return self._segment_string()
        if char == '"':
            return self._segment_identifier()
        if char == "$":
            return self._segment_dollar()
        if char == ";":
            return self._segment_delimiter()
        return self._segment_word()

    def _at_command_line(self, rules: SegmentScriptRules, pos: int) -> bool:
        """Whether the command prefix starts a line while no statement text is pending."""
        prefix = rules.command_prefix
        if not prefix or self._seg_pending or not self.sql.startswith(prefix, pos):
            return False
        return pos == self.origin or self.sql[pos - 1] == "\n"

    def _refuse_command_line(self, pos: int) -> NoReturn:
        """Refuse a client command: the client runs it and the engine cannot."""
        eol = self.sql.find("\n", pos)
        word = self.sql[pos : len(self.sql) if eol < 0 else eol].split(None, 1)[0]
        raise UnsupportedMetaCommandError(
            f"{self.spec.client_name} command {word!r} on line {self.line}: the shell runs it "
            "and the engine cannot; dblift does not run client commands"
        )

    def _segment_token(self, kind: TokenType, start: int, line: int, col: int) -> Token:
        """The token for ``sql[start:pos]`` read from ``line`` and ``col``."""
        return Token(kind, self.sql[start : self.pos], start, line, col, self.parens_depth)

    def _segment_lexeme(self, kind: TokenType, read: Callable[[], Token]) -> Token:
        """Read one lexeme with a shared handler; an unterminated one runs to the end."""
        start, line, col = self.pos, self.line, self.col
        try:
            read()
        except UnsafeStatementSplitError:
            pass
        return self._segment_token(kind, start, line, col)

    def _segment_line_comment(self) -> Token:
        """A line comment up to the first line end; it keeps the escape mode."""
        start, line, col = self.pos, self.line, self.col
        match = self._seg_comment.match(self.sql, start)
        assert match is not None  # the pattern starts with the two dashes the caller found
        self.read(match.end() - start)
        self.comments.append((start, self.pos))
        return self._segment_token(TokenType.COMMENT, start, line, col)

    def _segment_block_comment(self) -> Token:
        """A block comment; one left open is code, and the rest of the script is inside it."""
        start, line, col = self.pos, self.line, self.col
        self._seg_escape = False
        self.read(2)
        depth, _ = self._read_block_comment()
        if depth:
            self._seg_pending = True
            self.open_comment = self.open_comment or (line, col)
            return self._segment_token(TokenType.SYMBOL, start, line, col)
        self.comments.append((start, self.pos))
        return self._segment_token(TokenType.COMMENT, start, line, col)

    def _segment_string(self) -> Token:
        """A string; an escape string while the escape mode continues. A string keeps the mode."""
        self._seg_pending = True
        read = self._handle_escape_string if self._seg_escape else self._handle_standard_string
        return self._segment_lexeme(TokenType.STRING, read)

    def _segment_identifier(self) -> Token:
        """A quoted identifier."""
        self._seg_pending = True
        self._seg_escape = False
        return self._segment_lexeme(TokenType.IDENTIFIER, self._handle_quoted_identifier)

    def _segment_dollar(self) -> Token:
        """A dollar-quoted string closed by its own tag, else a parameter."""
        start, line, col = self.pos, self.line, self.col
        self._seg_pending = True
        self._seg_escape = False
        kind, end = TokenType.SYMBOL, start + 1
        tag = self._seg_tag.match(self.sql, start)
        if tag is not None:
            close = self.sql.find(tag.group(), tag.end())
            kind, end = TokenType.STRING, len(self.sql) if close < 0 else close + len(tag.group())
        else:
            parameter = self._seg_parameter.match(self.sql, start)
            end = start + 1 if parameter is None else parameter.end()
        self.read(end - start)
        return self._segment_token(kind, start, line, col)

    def _segment_delimiter(self) -> Token:
        """A ``;``: the statement is complete and the escape mode ends."""
        start, line, col = self.pos, self.line, self.col
        self._seg_pending = self._seg_escape = False
        self.read()
        return self._segment_token(TokenType.DELIMITER, start, line, col)

    def _segment_word(self) -> Token:
        """A word, a number or one other character; an escape prefix opens the escape mode."""
        start, line, col = self.pos, self.line, self.col
        self._seg_pending = True
        kind = TokenType.KEYWORD
        match = self._seg_word.match(self.sql, start)
        end = self._kept_word(start if match is None else match.end())
        if end == start:
            kind = TokenType.IDENTIFIER
            match = self._seg_number.match(self.sql, start)
            end = start if match is None else match.end()
        if end == start:
            self._seg_escape = False
            self.read()
            return self._segment_token(TokenType.SYMBOL, start, line, col)
        self._seg_escape = self._opens_escape_string(self.sql[start:end], end)
        self.read(end - start)
        return self._segment_token(kind, start, line, col)

    @property
    def kept(self) -> List[int]:
        """The stretches, flat, where the engine's pass over the script keeps blanks."""
        return self._seg_kept

    def _kept_until(self, pos: int) -> int:
        """The end of the stretch of kept blanks that holds ``pos``, else 0."""
        kept, at = self._seg_kept, self._seg_kept_at
        while at < len(kept) and kept[at + 1] <= pos:
            at += 2
        self._seg_kept_at = at
        return kept[at + 1] if at < len(kept) and kept[at] <= pos else 0

    def _kept_word(self, end: int) -> int:
        """Carry a word on from ``end`` through the blanks the pass kept, letters to the parser."""
        stretch = self._kept_until(end)
        while stretch and self.sql[end] in self._seg_wide:
            kept = self._seg_kept_part.match(self.sql, end, stretch)
            assert kept is not None  # both patterns can match nothing
            plain = self._seg_word_part.match(self.sql, kept.end())
            assert plain is not None
            end = plain.end()
            stretch = self._kept_until(end)
        return end

    def _opens_escape_string(self, word: str, end: int) -> bool:
        """Whether ``word``, with a quote at ``end``, is an escape prefix (alone or after digits)."""
        assert self._segment is not None
        return (
            self.sql.startswith("'", end)
            and word[-1] in self._segment.escape_letters
            and (len(word) == 1 or word[:-1].isdigit())
        )

    def assemble(self, tokens: List[Token]) -> List[Statement]:
        """The records of a terminator script read as ``tokens``, or its refusal."""
        assert self.terminator_script is not None  # only a terminator script is assembled
        return self.terminator_script.assemble(tokens, self.marks, self.open_lexeme)

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

        if self.delimiter_script is not None:
            return self._next_delimiter_token()

        self._skip_whitespace()

        if self.pos >= len(self.sql):
            return Token(TokenType.EOF, "", self.pos, self.line, self.col, self.parens_depth)

        if self._reads_directives and self._at_start:
            directive = self._directive_token()
            if directive is not None:
                return directive

        if self._batches is not None:
            self._token_start, self._token_line = self.pos, self.line
            if self.pos >= self._seg_end:
                self._enter_segment()

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

        if self._batches is not None and not self._seg_checked:
            self._check_segment()

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

    def _handle_escape_string(self, quote: str = "'") -> Token:
        """Read a backslash-escaped literal closed by ``quote``, including an optional E prefix.

        A doubled quote belongs to the literal unless the spec reads it as a close and a reopen.
        """
        start_pos, start_line, start_col = self.pos, self.line, self.col
        self.read(2 if quote == "'" and self.peek(2) in self.spec.escape_prefixes else 1)
        doubled = quote * 2 if self.spec.string_quote_doubling else None
        closed = False
        while self.pos < len(self.sql):
            if self.peek() == "\\" or self.peek(2) == doubled:
                self.read(2)
            elif self.read() == quote:
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
        """Read a quoted identifier; a doubled quote is an escape when the spec says so."""
        start_pos, start_line, start_col = self.pos, self.line, self.col
        quote = self.spec.quoted_identifier
        self.read()
        while True:
            end = self.sql.find(quote, self.pos)
            if end < 0:
                self.read(len(self.sql) - self.pos)
                raise UnsafeStatementSplitError(
                    f"unterminated quoted identifier opened at line {start_line}, "
                    f"column {start_col}"
                )
            self.read(end + 1 - self.pos)
            if not (self.spec.quoted_identifier_escape and self.peek() == quote):
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

    def _enter_segment(self) -> None:
        """Start a code segment at the cursor: refuse a lone carriage return in the blanks before it."""
        assert self._batches is not None
        if self.pos > self._line_end:
            newline = self.sql.find("\n", self.pos)
            self._line_end = len(self.sql) if newline < 0 else newline
        opener = self._opener_re.search(self.sql, self.pos, self._line_end)
        self._seg_end = opener.start() if opener else self._line_end
        self._seg_checked = False
        found = find_lone_cr(self._batches, self.sql, self._region_start, self._seg_end)
        if found is not None and found < self.pos:
            refuse_lone_cr(self._batches, self.spec.client_name, self.line)
        self._seg_lone_cr = found is not None

    def _check_segment(self) -> None:
        """Refuse a lone carriage return, then a variable reference, in the segment at the cursor."""
        assert self._batches is not None
        self._seg_checked = True
        if self._seg_lone_cr:
            refuse_lone_cr(self._batches, self.spec.client_name, self.line)
        refuse_variable_in_code(
            self._batches, self.spec.client_name, self.sql, self.pos, self._seg_end, self.line
        )

    def _skip_whitespace(self) -> None:
        """Skip what ``str.isspace`` accepts; a character that is not a blank ends the line head."""
        if self._batches is None:
            if self.spec.unread_blanks_are_code:
                while self.pos < len(self.sql) and self.sql[self.pos] in self.spec.text_blanks:
                    self.read()
            else:
                super()._skip_whitespace()
            return
        blanks = self._batches.blanks
        self._region_start = self.pos
        while self.pos < len(self.sql) and self.sql[self.pos].isspace():
            char = self.sql[self.pos]
            if char == "\n":
                self._line_head = True
                self._region_start = self.pos + 1
            elif char not in blanks:
                self._line_head = False
            self.read()

    def _is_lexeme(self, token: Token) -> bool:
        """Whether a token is a string or a quoted or bracketed name."""
        return token.type == TokenType.STRING or (
            token.type == TokenType.IDENTIFIER
            and token.text[:1] in (self.spec.quoted_identifier, *self.spec.bracket_identifier[:1])
        )

    def _refuse_variable_in_unterminated(self) -> None:
        """A variable reference in the text an unterminated lexeme swallowed is reported first."""
        assert self._batches is not None
        start = self._token_start
        opener = self.sql[start : start + 1]
        if opener and opener in (
            "'",
            self.spec.quoted_identifier,
            *self.spec.bracket_identifier[:1],
        ):
            refuse_variable_in_lexeme(
                self._batches,
                self.spec.client_name,
                self.sql,
                start + 1,
                len(self.sql),
                self._token_line,
            )

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
        try:
            token = self._next_sql_token()
        except UnsafeStatementSplitError as error:
            if self._batches is not None and str(error).startswith("unterminated"):
                self._refuse_variable_in_unterminated()
            raise
        if token is None:
            return None
        if self._batches is not None and self._is_lexeme(token):
            refuse_variable_in_lexeme(
                self._batches,
                self.spec.client_name,
                self.sql,
                token.pos + 1,
                token.pos + len(token.text) - 1,
                token.line,
            )
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

    def _delimiter_eol(self) -> int:
        """The end of the current line, searched once per line."""
        if self._eol_cache < self.pos:
            eol = self.sql.find("\n", self.pos)
            self._eol_cache = len(self.sql) if eol < 0 else eol
        return self._eol_cache

    def _delimiter_token(self, kind: TokenType, length: int) -> Token:
        start_pos, start_line, start_col = self.pos, self.line, self.col
        return Token(kind, self.read(length), start_pos, start_line, start_col, 0)

    def _is_dash_comment(self, script: DelimiterScript) -> bool:
        """The dash opener counts only before a blank or the line end; else it is subtraction."""
        dash = script.rules.dash_comment
        if not self.sql.startswith(dash, self.pos):
            return False
        after = self.pos + len(dash)
        return after >= len(self.sql) or self.sql[after] in script.rules.blanks + "\n"

    def _next_delimiter_token(self) -> Optional[Token]:
        """The next token of a delimiter script; code tokens start or continue a statement."""
        token = self._read_delimiter_token()
        script = self.delimiter_script
        assert script is not None
        if token is not None and token.type not in (TokenType.COMMENT, TokenType.DELIMITER):
            script.code(token.pos, token.line)
        return token

    def _next_occurrence(self, start: int) -> int:
        """Where the active delimiter next begins from ``start`` (-1: nowhere), searched once."""
        # No reset on a DELIMITER line: it takes effect with no code pending, so the cached
        # occurrence of the old delimiter is always behind the cursor and gets recomputed.
        if not (self._seen_from <= start and (self._seen_at < 0 or start <= self._seen_at)):
            self._seen_from, self._seen_at = start, self.sql.find(self._delimiter, start)
        return self._seen_at

    def _read_delimiter_token(self) -> Optional[Token]:
        """The next token of a delimiter script, in the order the client meets what it reads."""
        script = self.delimiter_script
        assert script is not None
        rules, sql = script.rules, self.sql
        while self.pos < len(sql):
            pos, char = self.pos, sql[self.pos]
            if char == "\n":
                script.line_end(pos)
                self.read()
                self._line_start = True
                continue
            if self._line_start:
                self._line_start = False
                if (not script.code_started or script.exec_only) and script.line_head(
                    pos, self._delimiter_eol(), self.line
                ):
                    self._delimiter = script.delimiter
                    self.read(self._delimiter_eol() - pos)
                    continue
            if char == rules.escape:
                # a client command to the end of the line; the next character is not read as code
                script.escape(pos, self._delimiter_eol(), self.line)
                follows = pos + 1 < len(sql) and sql[pos + 1] != "\n"
                script.reset_qualifier()
                return self._delimiter_token(TokenType.SYMBOL, 2 if follows else 1)
            if sql.startswith(self._delimiter, pos):
                if self._delimiter == rules.initial and script.program.open:
                    # inside a stored-program body the initial delimiter is code
                    script.symbol(rules.initial)
                    return self._delimiter_token(TokenType.SYMBOL, len(self._delimiter))
                script.end(pos)
                return self._delimiter_token(TokenType.DELIMITER, len(self._delimiter))
            if char in rules.blanks:
                self.read()
                continue
            if char == rules.initial and self._delimiter != rules.initial:
                script.fragment(pos)
            if sql.startswith(rules.hash_comment, pos) or self._is_dash_comment(script):
                return self._delimiter_line_comment(script)
            if sql.startswith("/*", pos):
                return self._delimiter_block(script)
            if sql.startswith("*/", pos) and script.close(pos, self._delimiter_eol(), self.line):
                return self._delimiter_token(TokenType.SYMBOL, 2)
            if char in rules.string_quotes:
                return self._delimiter_literal(script, lambda: self._handle_escape_string(char))
            if char == self.spec.quoted_identifier:
                return self._delimiter_literal(script, self._handle_quoted_identifier)
            if not script.code_started and self._is_command_word(script):
                script.first_word_check(pos, self.line)
            return self._delimiter_word(script)
        return None

    def _is_command_word(self, script: DelimiterScript) -> bool:
        """The command word, followed by a blank or the line end, at the cursor."""
        command = script.rules.command
        after = self.pos + len(command)
        if self.sql[self.pos : after].upper() != command.upper():
            return False
        return after >= self._delimiter_eol() or self.sql[after] in " \t\r"

    def _delimiter_word(self, script: DelimiterScript) -> Token:
        """A word ends where the next delimiter begins; any other character is a symbol."""
        pos = self.pos
        word = self._word_re.match(self.sql, pos)
        if word is None:
            script.symbol(self.sql[pos])
            return self._delimiter_token(TokenType.SYMBOL, 1)
        end = word.end()
        nxt = self._next_occurrence(pos + 1)
        if 0 <= nxt < end:
            end = nxt
        script.word(self.sql[pos:end])
        return self._delimiter_token(TokenType.KEYWORD, end - pos)

    def _delimiter_literal(self, script: DelimiterScript, read: Callable[[], Token]) -> Token:
        start_line = self.line
        start_pos = self.pos
        token = read()
        script.literal(start_pos, self.pos, start_line, self.line)
        return token

    def _delimiter_line_comment(self, script: DelimiterScript) -> Token:
        start_pos, start_line, start_col = self.pos, self.line, self.col
        end = self._delimiter_eol()
        script.check_line_comment(start_pos, end, start_line)
        self.read(end - start_pos)
        self.comments.append((start_pos, end))
        script.comment(start_pos, end, True)
        return Token(TokenType.COMMENT, "", start_pos, start_line, start_col, 0)

    def _delimiter_block(self, script: DelimiterScript) -> Token:
        """A block comment, an executable comment (code), or a hint, as the client rules say."""
        rules, sql = script.rules, self.sql
        start_pos, start_line = self.pos, self.line
        for opener in rules.executable_openers:
            if sql.startswith(opener, start_pos):
                script.executable(start_line)
                return self._delimiter_token(TokenType.SYMBOL, len(opener))
        if rules.hint_opening_line_only and sql.startswith(rules.hint_opener, start_pos):
            return self._delimiter_hint(script)
        script.block_opens(start_line)
        try:
            token = self._handle_comment()
        except UnsafeStatementSplitError as error:
            # the only refusal of a block comment is the unterminated one
            script.unterminated_block(error)
        script.lexeme(start_line, self.line)
        script.comment(start_pos, self.pos, False)
        if not script.code_started:
            script.after_comment(self.pos, self._delimiter_eol(), self.line)
        return token

    def _delimiter_hint(self, script: DelimiterScript) -> Token:
        """A hint hides the delimiter on its opening line only; the lines after it are code."""
        start_pos, start_line, start_col = self.pos, self.line, self.col
        text_from = start_pos + len(script.rules.hint_opener)
        end = self._delimiter_eol()
        close = self.sql.find("*/", text_from, end)
        if close < 0:
            script.hint_opens(start_line, start_col)
        else:
            script.hint_closes(start_line)
        script.check_hint(text_from, end if close < 0 else close, start_line)
        stop = end if close < 0 else close + 2
        self.read(stop - start_pos)
        self.comments.append((start_pos, stop))
        script.comment(start_pos, stop, False)
        if close >= 0 and not script.code_started:
            script.after_comment(self.pos, self._delimiter_eol(), self.line)
        return Token(TokenType.COMMENT, "", start_pos, start_line, start_col, 0)
