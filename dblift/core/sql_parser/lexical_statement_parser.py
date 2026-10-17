"""Shared token-stream statement splitting driven by lexical specifications."""

from typing import List, Optional, Sequence, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.batch_script import BatchScript
from dblift.core.sql_parser.client_script import ClientScript
from dblift.core.sql_parser.delimiter_script import DelimiterScript
from dblift.core.sql_parser.driver_strip import refuse_edges_the_driver_strips
from dblift.core.sql_parser.lexical_spec import BOM, LexicalSpec
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.segment_script import SegmentScript
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import Token, TokenType


class LexicalStatementParser(BaseStatementParser):
    """Apply a plugin's boundary, block, directive and raw-data policies."""

    def __init__(
        self,
        tokens: List[Token],
        context: Optional[ParserContext] = None,
        source: Optional[str] = None,
        *,
        spec: LexicalSpec,
        comments: Optional[Sequence[Tuple[int, int]]] = None,
        delimiter_script: Optional[DelimiterScript] = None,
        terminator_records: Optional[List[Statement]] = None,
        segment_script: Optional[SegmentScript] = None,
    ):
        """Bind token boundaries to their original source and plugin rules."""
        super().__init__(tokens, context, source)
        self.spec = spec
        self.TERMINATOR_RESPECTS_PARENS = spec.terminator_respects_parens
        self.text_blanks = spec.text_blanks
        self._comments: Sequence[Tuple[int, int]] = comments or ()
        self._head: List[str] = []
        self._head_limit = max(map(len, spec.routine_heads), default=0)
        self._previous: Optional[Token] = None
        self._sqlite_state = 1
        self._sqlite_code = False
        self._sqlite_last_line_comment = 0
        self._sqlite_checked_line = 0
        self._sqlite_token_end = 0
        self.warnings: List[str] = []
        self.notices: List[str] = []
        self._batches: Optional[BatchScript] = None
        if spec.batch_script is not None:
            assert source is not None and comments is not None  # batches are cut from their text
            self._batches = BatchScript(
                spec.batch_script,
                source,
                spec.client_name,
                comments,
                origin=int(spec.leading_bom_is_blank and source.startswith(BOM)),
            )
        # A delimiter script is cut by the tokenizer as it reads: its records are final.
        assert (spec.delimiter_script is None) == (delimiter_script is None)
        self._delimiter_script = delimiter_script
        # A terminator script is cut by its own assembly: its records are final too.
        assert (spec.terminator_script is None) == (terminator_records is None)
        self._terminator_records = terminator_records
        # A segment script is cut between its ';' tokens: its records come from the tokens.
        assert (spec.segment_script is None) == (segment_script is None)
        self._segments = segment_script
        self._script: Optional[ClientScript] = None
        if spec.client_script is not None:
            assert source is not None  # a client script is read line by line from its text
            self._script = ClientScript(
                spec.client_script, source, spec.client_name, text_blanks=spec.text_blanks
            )

    def _adjust_context(self, token: Token) -> None:
        if self.spec.sqlite_shell:
            if token.type == TokenType.COMMENT:
                if self.source is not None and self.source.startswith("--", token.pos):
                    self._sqlite_last_line_comment = token.line
                return
            if token.type == TokenType.DELIMITER:
                token_class = 0
            else:
                token_class = (
                    {
                        "EXPLAIN": 2,
                        "CREATE": 3,
                        "TEMP": 4,
                        "TEMPORARY": 4,
                        "TRIGGER": 5,
                        "END": 6,
                    }.get(token.text.upper(), 1)
                    if token.type in (TokenType.KEYWORD, TokenType.IDENTIFIER)
                    and token.text[:1] not in ('"', "`", "[")
                    else 1
                )
                self._sqlite_code = True
            self._sqlite_state = self.spec.completion_table[self._sqlite_state][token_class]
            return
        if (
            self.spec.combine_terminator
            and token.type == TokenType.SYMBOL
            and token.text == self.spec.combine_terminator
            and token.parens_depth == 0
            and self.context.block_depth == 0
        ):
            # One execution buffer may contain multiple independent SQL heads.
            self._head.clear()
            self._previous = None
            return
        if token.type != TokenType.COMMENT and len(self._head) < self._head_limit:
            self._head.append(token.text.upper())
        super()._adjust_context(token)
        if token.type != TokenType.COMMENT:
            self._previous = token

    def _adjust_block_depth(self, token: Token) -> None:
        keyword = token.text.upper()
        opener, marker = self.spec.block_opener
        if (
            keyword == marker
            and token.parens_depth == 0
            and self._previous is not None
            and self._previous.type == TokenType.KEYWORD
            and self._previous.text.upper() == opener
            and any(tuple(self._head[: len(head)]) == head for head in self.spec.routine_heads)
        ):
            self.context.increase_block_depth(marker)
        elif keyword in self.spec.nested_block_keywords and self.context.block_depth:
            self.context.increase_block_depth(keyword)
        elif keyword == self.spec.block_closer and self.context.block_depth:
            self.context.decrease_block_depth()

    def _is_statement_end(self, token: Token) -> bool:
        """A COPY data block ends its own statement — no ``;`` follows its ``\\.`` line.

        The ``;`` closing a ``COPY ... FROM stdin`` header does not end the
        statement: the header and its data block are one COPY, which the
        provider streams through the driver's copy API in a single call.
        """
        if self.spec.sqlite_shell:
            return token.type == TokenType.DELIMITER and self._sqlite_state == 1
        if self._script is not None:
            following_idx = self.current_idx + 1
            following = self.tokens[following_idx] if following_idx < len(self.tokens) else None
            return self._script.is_statement_end(token, following, self.context.tokens)
        if token.type == TokenType.COPY_DATA:
            return True
        if not super()._is_statement_end(token):
            return False
        next_token = self._peek_next_token(skip_comments=False)
        return next_token is None or next_token.type != TokenType.COPY_DATA

    def split(self, *, include_comment_only: bool = False) -> List[Statement]:
        """Cut the token stream into Statement records (see ``_split_with_rendered``)."""
        return [record for record, _ in self._split_with_rendered(include_comment_only)]

    def _split_with_rendered(
        self, include_comment_only: bool = False
    ) -> List[Tuple[Statement, str]]:
        """Cut the token stream into ``(Statement, rendered)`` pairs.

        ``rendered`` is the verbatim source slice of the statement, terminator included.

        A psql meta-command is not SQL and never joins the statement around
        it, so it is pulled out here rather than in ``_is_statement_end``
        (which only marks a boundary, it can't drop the token from output).
        A safe one is recorded as a ``directive``; any other is refused.
        """
        if self._delimiter_script is not None:
            return [(record, record.text) for record in self._delimiter_script.records]
        if self._terminator_records is not None:
            return [(record, record.text) for record in self._terminator_records]
        if self._segments is not None:
            return [
                (record, record.text)
                for record in self._segments.records(self.tokens, include_comment_only)
            ]
        if self._batches is not None:
            return self._batches.split(self.tokens)
        records: List[Tuple[Statement, str]] = []
        current: List[Token] = []

        def flush(terminator: Optional[Token], end_pos: Optional[int]) -> None:
            has_code = (
                self._sqlite_code
                if self.spec.sqlite_shell
                else any(t.type not in (TokenType.COMMENT, TokenType.DELIMITER) for t in current)
            )
            has_comments = any(t.type == TokenType.COMMENT for t in current)
            if current and (has_code or (include_comment_only and has_comments)):
                text = self._render_statement(current, terminator, end_pos)
                if text.strip(self.text_blanks):
                    first = next((t for t in current if t.type != TokenType.COMMENT), None)
                    if self._script is not None and first is not None:
                        text = self._script.substitute(text, first.line)
                        if self._script.rules.driver_strips_edges and self.source is not None:
                            refuse_edges_the_driver_strips(
                                self.source,
                                current,
                                self._comments,
                                self.text_blanks,
                                floor=(records[-1][0].source_end or 0) if records else 0,
                                end=end_pos,
                                terminator=terminator,
                            )
                    records.append(self._record(current, text, terminator, end_pos))
            current.clear()
            self.context.reset_for_new_statement()
            self._head.clear()
            self._previous = None
            self._sqlite_state = 1
            self._sqlite_code = False
            if self._script is not None:
                self._script.reset_statement()

        for idx, token in enumerate(self.tokens):
            self.current_idx = idx

            if token.type == TokenType.EOF:
                continue

            if self.spec.sqlite_shell:
                self._check_sqlite_line(token)
                self._sqlite_token_end = token.pos + len(token.text)

            if token.type == TokenType.DIRECTIVE and self._script is not None:
                flush(None, None)
                records.append(self._script.directive_record(token))
                if self._script.is_exit(token):
                    message = self._script.ignored_tail_message(token)
                    if message is not None:
                        self.warnings.append(message)
                    return records
                continue

            if token.type == TokenType.META_COMMAND:
                flush(None, token.pos)
                command = token.text.split(None, 1)[0]
                if command not in self.spec.safe_meta_commands:
                    raise UnsupportedMetaCommandError(
                        f"Unsupported {self.spec.client_name} meta-command {command!r} at line {token.line}; "
                        f"dblift does not run it (column {token.col})"
                    )
                records.append(
                    (
                        Statement(
                            text=token.text,
                            line=token.line,
                            terminator=None,
                            kind="directive",
                            source_start=token.pos if self.source is not None else None,
                            source_end=self._line_end(token.pos),
                        ),
                        token.text,
                    )
                )
                continue

            self._adjust_context(token)
            current.append(token)

            if self._is_statement_end(token):
                flush(token, None)

        if self._script is not None:
            self._script.check_tail(current)
        flush(None, None)
        return records

    def _render_statement(
        self,
        kept_tokens: List[Token],
        terminator: Optional[Token],
        dropped_terminator_pos: Optional[int],
    ) -> str:
        if not self.spec.sqlite_shell or self.source is None:
            return super()._render_statement(kept_tokens, terminator, dropped_terminator_pos)
        start = kept_tokens[0].pos
        end = (
            dropped_terminator_pos
            if dropped_terminator_pos is not None
            else (
                terminator.pos + len(terminator.text)
                if terminator is not None
                else len(self.source)
            )
        )
        return self.source[start:end].rstrip(self.text_blanks)

    def _check_sqlite_line(self, token: Token) -> None:
        """Refuse shell-only lines that would change SQLite statement boundaries."""
        if self.source is None or token.line == self._sqlite_checked_line:
            return
        self._sqlite_checked_line = token.line
        line_start = self.source.rfind("\n", 0, token.pos) + 1
        if line_start < self._sqlite_token_end:
            return
        line_end = self.source.find("\n", line_start)
        line = self.source[line_start : line_end if line_end >= 0 else len(self.source)]
        if line_start == 0 and line.startswith("\ufeff"):
            line = line[1:]
        if line.startswith(".") and not self._sqlite_code:
            command = line.split(None, 1)[0]
            raise UnsupportedMetaCommandError(
                f"sqlite3 shell command {command!r} on line {token.line}: the shell runs "
                "it and the engine cannot; dblift does not run client commands"
            )
        if (
            self._sqlite_code
            and self._sqlite_state not in (5, 6)
            and self._sqlite_last_line_comment != token.line - 1
            and _sqlite_terminator_line(line)
        ):
            raise UnsafeStatementSplitError(
                f"line {token.line} holds only {line.strip()!r}: the sqlite3 shell ends "
                "the statement there, the engine reads it as part of the statement; "
                "put the terminator on the statement"
            )

    def _line_end(self, pos: int) -> Optional[int]:
        if self.source is None:
            return None
        newline = self.source.find("\n", pos)
        return newline + 1 if newline >= 0 else len(self.source)

    def _record(
        self,
        tokens: List[Token],
        rendered: str,
        terminator: Optional[Token],
        end_pos: Optional[int],
    ) -> Tuple[Statement, str]:
        """Build the record for one rendered statement and its verbatim string.

        The record's text has the terminator stripped; the string keeps it.
        """
        first = (
            tokens[0]
            if self.spec.sqlite_shell
            else next(t for t in tokens if t.type != TokenType.COMMENT)
        )
        source_start = first.pos if self.source is not None else None
        source_end = (
            terminator.pos + len(terminator.text)
            if terminator is not None
            else (
                end_pos
                if end_pos is not None
                else len(self.source) if self.source is not None else None
            )
        )
        if self._script is not None:
            source_end = self._script.record_end(tokens, terminator, source_end)
        combinators = [
            t
            for t in tokens
            if t.type == TokenType.SYMBOL
            and self.spec.combine_terminator
            and t.text == self.spec.combine_terminator
        ]
        multi = bool(combinators)
        analysis_statements = None
        if combinators and self.source is not None:
            end = terminator.pos if terminator is not None else len(self.source)
            starts = [first.pos, *(t.pos + len(t.text) for t in combinators)]
            ends = [*(t.pos for t in combinators), end]
            analysis_statements = tuple(
                part
                for start, stop in zip(starts, ends)
                if (part := self.source[start:stop].strip(self.text_blanks))
            )
            parts: List[str] = []
            cursor = 0
            for t in combinators:
                rel = t.pos - first.pos
                parts.extend((rendered[cursor:rel], ";"))
                cursor = rel + len(t.text)
            parts.append(rendered[cursor:])
            rendered = "".join(parts)
        if terminator is None:
            return (
                Statement(
                    text=rendered,
                    line=first.line,
                    terminator=None,
                    multi=multi,
                    analysis_statements=analysis_statements,
                    source_start=source_start,
                    source_end=source_end,
                ),
                rendered,
            )
        if terminator.type == TokenType.COPY_DATA:
            if combinators:
                raise UnsafeStatementSplitError(
                    "COPY FROM STDIN cannot be combined with another statement using psql \\;"
                )
            if self.source is None:
                record = Statement(
                    text=rendered, line=first.line, terminator="\\.", kind="copy_stdin"
                )
                return record, rendered
            end = terminator.pos + len(terminator.text)
            text = self.source[first.pos : end]
            ended = self.source.startswith("\\.", end)
            header_end = next(t.pos for t in tokens if t.type == TokenType.DELIMITER)
            header = self.source[first.pos : header_end].strip(self.text_blanks)
            record = Statement(
                text=text,
                line=first.line,
                terminator="\\." if ended else None,
                kind="copy_stdin",
                analysis_statements=(header,),
                source_start=source_start,
                source_end=self._line_end(end) if ended else end,
            )
            return record, rendered
        text = rendered
        if text.endswith(terminator.text):
            text = text[: -len(terminator.text)].rstrip(self.text_blanks)
        return (
            Statement(
                text=text,
                line=first.line,
                terminator=terminator.text,
                multi=multi,
                analysis_statements=analysis_statements,
                source_start=source_start,
                source_end=source_end,
            ),
            rendered,
        )

    def split_statements(self) -> List[str]:
        """Statement strings as execution receives them (``;`` kept, directives dropped)."""
        out: List[str] = []
        if self._batches is not None:
            for record, rendered in self._split_with_rendered():
                if record.repeat == 0:
                    self.notices.append(
                        f"GO 0 follows the batch starting on line {record.line}: it is not run"
                    )
                out.extend([rendered] * record.repeat)
            return out
        for record, rendered in self._split_with_rendered():
            if record.kind == "sql":
                ends_at_line = (
                    self._script is not None
                    and record.terminator == self._script.rules.line_terminator
                )
                out.append(record.text if self.spec.sqlite_shell or ends_at_line else rendered)
            elif record.kind != "directive":
                out.append(record.text)
            elif self._script is not None and rendered:
                out.append(rendered)
        return out


def _sqlite_terminator_line(line: str) -> bool:
    """The sqlite3 shell's GO or / line with optional trailing comments."""
    blanks = " \t\f\r\v"
    size, pos = len(line), 0
    while pos < size and line[pos] in blanks:
        pos += 1
    if line.startswith("/", pos):
        pos += 1
    elif line[pos : pos + 2].lower() == "go":
        pos += 2
    else:
        return False
    while True:
        while pos < size and line[pos] in blanks:
            pos += 1
        if not line.startswith("/*", pos):
            return pos == size or line.startswith("--", pos)
        end = line.find("*/", pos + 2)
        if end < 0:
            return False
        pos = end + 2
