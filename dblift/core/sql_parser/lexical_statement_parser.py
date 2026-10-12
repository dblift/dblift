"""Shared token-stream statement splitting driven by lexical specifications."""

from typing import List, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.parser_context import ParserContext
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
    ):
        """Bind token boundaries to their original source and plugin rules."""
        super().__init__(tokens, context, source)
        self.spec = spec
        self.TERMINATOR_RESPECTS_PARENS = spec.terminator_respects_parens
        self._head: List[str] = []
        self._head_limit = max(map(len, spec.routine_heads), default=0)
        self._previous: Optional[Token] = None

    def _adjust_context(self, token: Token) -> None:
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
        if token.type == TokenType.COPY_DATA:
            return True
        if not super()._is_statement_end(token):
            return False
        next_token = self._peek_next_token(skip_comments=False)
        return next_token is None or next_token.type != TokenType.COPY_DATA

    def split(self) -> List[Statement]:
        """Cut the token stream into Statement records (see ``_split_with_rendered``)."""
        return [record for record, _ in self._split_with_rendered()]

    def _split_with_rendered(self) -> List[Tuple[Statement, str]]:
        """Cut the token stream into ``(Statement, rendered)`` pairs.

        ``rendered`` is the verbatim source slice of the statement, terminator included.

        A psql meta-command is not SQL and never joins the statement around
        it, so it is pulled out here rather than in ``_is_statement_end``
        (which only marks a boundary, it can't drop the token from output).
        A safe one is recorded as a ``directive``; any other is refused.
        """
        records: List[Tuple[Statement, str]] = []
        current: List[Token] = []

        def flush(terminator: Optional[Token], end_pos: Optional[int]) -> None:
            if current and not all(
                t.type in (TokenType.COMMENT, TokenType.DELIMITER) for t in current
            ):
                text = self._render_statement(current, terminator, end_pos)
                if text.strip():
                    records.append(self._record(current, text, terminator, end_pos))
            current.clear()
            self.context.reset_for_new_statement()
            self._head.clear()
            self._previous = None

        for idx, token in enumerate(self.tokens):
            self.current_idx = idx

            if token.type == TokenType.EOF:
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

        flush(None, None)
        return records

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
        first = next(t for t in tokens if t.type != TokenType.COMMENT)
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
                if (part := self.source[start:stop].strip())
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
            header = self.source[first.pos : header_end].strip()
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
            text = text[: -len(terminator.text)].rstrip()
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
        for record, rendered in self._split_with_rendered():
            if record.kind == "sql":
                out.append(rendered)
            elif record.kind != "directive":
                out.append(record.text)
        return out
