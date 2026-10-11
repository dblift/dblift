"""Oracle-specific statement parser.

This module provides Oracle-specific statement parsing including
slash delimiter handling and PL/SQL unit detection from the statement head.
"""

import logging
from typing import Callable, List, Optional, Tuple

from dblift.core.exceptions import (
    ParserError,
    UnsafeStatementSplitError,
    UnsupportedMetaCommandError,
)
from dblift.core.sql_parser.base_statement_parser import BaseStatementParser
from dblift.core.sql_parser.parser_context import ParserContext
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.oracle.parser._directives import DirectiveAction, classify_directive
from dblift.db.plugins.oracle.parser._sqlplus import parse_whenever_sqlerror
from dblift.db.plugins.oracle.parser._unit_heads import MAX_HEAD_TOKENS, head_decided

logger = logging.getLogger(__name__)


class OracleStatementParser(BaseStatementParser):
    """Oracle-specific statement parser.

    A statement is a PL/SQL unit or not from its first tokens
    (``_unit_heads.head_decided``). A unit ends only at a ``/`` alone on its
    line; any other statement ends at a ``;`` that is last on its line or at
    such a ``/``. Nothing inside a unit is counted.

    A ``DIRECTIVE`` token (a SQL*Plus client line, section 6 of the spec) ends
    whatever statement was being read and is recorded, never sent to the
    server: ``WHENEVER SQLERROR`` is also projected to its string, because the
    executor applies that policy positionally.
    """

    TERMINATOR_RESPECTS_PARENS = True

    def __init__(
        self,
        tokens: List[Token],
        context: Optional[ParserContext] = None,
        source: Optional[str] = None,
    ):
        """Initialize Oracle statement parser.

        Args:
            tokens: List of tokens to parse
            context: Parser context
            source: Original SQL text the tokens came from (see
                ``BaseStatementParser.__init__``)
        """
        super().__init__(tokens, context, source)
        # Head of the statement being read; ``_unit`` stays None until it decides.
        self._head: List[Token] = []
        self._unit: Optional[bool] = None
        # Text of the delimiter that ended the previous statement (a "/" right
        # after a ";"-ended statement re-executes it).
        self._last_terminator: Optional[str] = None

    def split(self) -> List[Statement]:
        """Cut the token stream into Statement records (see ``_split_with_rendered``)."""
        return [record for record, _ in self._split_with_rendered()]

    def split_statements(self) -> List[str]:
        """Statement strings as execution receives them (``;`` of a SQL statement kept)."""
        return [rendered for _, rendered in self._split_with_rendered() if rendered]

    def _split_with_rendered(self) -> List[Tuple[Statement, str]]:
        """Cut the token stream into ``(Statement, rendered)`` pairs.

        Resets parser state after each statement and filters standalone ``/``
        and ``;``. ``rendered`` is the string execution receives: SQL keeps its
        ``;``, a trailing ``/`` is never included; a directive has none (empty)
        except ``WHENEVER SQLERROR``.
        """
        records: List[Tuple[Statement, str]] = []
        current_statement_tokens: List[Token] = []

        def emit(terminator: Optional[Token], is_tail: bool) -> None:
            rendered = self._statement_text(current_statement_tokens, is_tail=is_tail)
            if rendered and rendered not in ("/", ";"):
                records.append(self._record(current_statement_tokens, rendered, terminator))

        for idx, token in enumerate(self.tokens):
            self.current_idx = idx

            # Skip EOF tokens
            if token.type == TokenType.EOF:
                continue

            if token.type == TokenType.DIRECTIVE:
                self._flush_before_directive(current_statement_tokens, emit)
                current_statement_tokens = []
                self.context.reset_for_new_statement()
                self._head = []
                self._unit = None
                records.append(self._directive_record(token))
                if self._is_exit(token):
                    self._warn_ignored(self.tokens[idx + 1 :], token)
                    break
                continue

            # Adjust context based on token
            self._adjust_context(token)

            # Add token to current statement
            current_statement_tokens.append(token)

            # Check if this marks end of statement
            if self._is_statement_end(token):
                emit(token, is_tail=False)

                # Reset for next statement
                current_statement_tokens = []
                # Reset parser context
                self.context.reset_for_new_statement()
                self._head = []
                self._unit = None

        # Handle any remaining tokens
        if current_statement_tokens:
            if self._unit:
                raise UnsafeStatementSplitError(
                    self._unterminated_unit_message(current_statement_tokens)
                )
            emit(None, is_tail=True)

        return records

    def _flush_before_directive(
        self, pending: List[Token], emit: Callable[[Optional[Token], bool], None]
    ) -> None:
        """End the statement being read where a directive begins (a statement can begin there)."""
        if not any(t.type != TokenType.COMMENT for t in pending):
            return
        if self._unit:
            raise UnsafeStatementSplitError(self._unterminated_unit_message(pending))
        emit(None, False)

    @staticmethod
    def _is_exit(token: Token) -> bool:
        directive = classify_directive(token.text)
        return directive is not None and directive.action is DirectiveAction.EXIT

    def _directive_record(self, token: Token) -> Tuple[Statement, str]:
        """Record a directive line, or refuse it (spec section 6).

        The string is empty, except for ``WHENEVER SQLERROR``: execution reads
        that policy from the statement list, so it gets ``<line>;``.
        """
        directive = classify_directive(token.text)
        assert directive is not None  # the tokenizer only emits recognised directives
        if directive.action is DirectiveAction.REJECT:
            raise UnsupportedMetaCommandError(
                f"Unsupported SQL*Plus directive {directive.name!r} at line {token.line}; "
                "dblift does not run it"
            )
        record = Statement(text=token.text, line=token.line, terminator=None, kind="directive")
        if directive.name != "WHENEVER SQLERROR":
            return record, ""
        if parse_whenever_sqlerror(token.text) is None:
            raise UnsupportedMetaCommandError(
                f"Unsupported WHENEVER SQLERROR action at line {token.line}: "
                "expected EXIT or CONTINUE"
            )
        return record, token.text if token.text.endswith(";") else token.text + ";"

    def _warn_ignored(self, rest: List[Token], exit_token: Token) -> None:
        """Log what follows an ``EXIT``/``QUIT``: SQL*Plus never runs it."""
        first = next((t for t in rest if t.type not in (TokenType.COMMENT, TokenType.EOF)), None)
        if first is None:
            return
        try:
            count = str(
                sum(
                    1
                    for record in OracleStatementParser(rest, source=self.source).split()
                    if record.kind == "sql"
                )
            )
        except ParserError:
            count = "some"
        logger.warning(
            "%s statement(s) after %s on line %d ignored, as SQL*Plus does not run them "
            "(first ignored line: %d)",
            count,
            exit_token.text.split(None, 1)[0].upper(),
            exit_token.line,
            first.line,
        )

    def _unterminated_unit_message(self, tokens: List[Token]) -> str:
        """Refusal for a PL/SQL unit that reached the end of the script without its ``/``."""
        last_line = max(t.line for t in tokens if t.type != TokenType.EOF)
        on_last_line = [t for t in tokens if t.line == last_line]
        if len(on_last_line) > 1 and on_last_line[0].text == "/":
            return (
                f"PL/SQL unit starting at line {self._head[0].line}: a '/' followed by other "
                f"text does not end the unit (line {last_line})"
            )
        return (
            f"PL/SQL unit starting at line {self._head[0].line} is not terminated by "
            "a '/' line before the end of the script"
        )

    def _record(
        self, tokens: List[Token], rendered: str, terminator: Optional[Token]
    ) -> Tuple[Statement, str]:
        """Build the record for one rendered statement and its execution string.

        The record's text has the terminator removed, except that a PL/SQL
        unit keeps its closing ``END;``: its ``;`` belongs to the unit and the
        ``/`` that ended it is the terminator.
        """
        first = next(t for t in tokens if t.type != TokenType.COMMENT and t.text != "/")
        end = terminator.text if terminator is not None else None
        if end is None:
            # A "/" after a SQL statement is not a statement end for the
            # tokenizer (the delimiter is ";"), so it arrives in the tail.
            last = next((t for t in reversed(tokens) if t.type != TokenType.COMMENT), None)
            if last is not None and last.text == "/":
                end = "/"
        text = rendered
        if end == ";" and text.endswith(";"):
            text = text[:-1].rstrip()
        return Statement(text=text, line=first.line, terminator=end), rendered

    def _statement_text(self, tokens: List[Token], is_tail: bool = False) -> str:
        """Render one statement, verbatim from source when source is known.

        Mirrors ``BaseStatementParser._render_statement``: a leading plain
        comment is skipped when locating the start (a lone comment renders
        empty, matching the historical token-join behaviour of dropping
        comment text), and everything else between that point and the end
        of the accumulated tokens is copied unchanged. Oracle keeps its
        terminator (``;``) in the returned text and, separately, still
        strips a stray leading/trailing ``/`` afterwards — untouched by
        this method, since ``/`` is sometimes tokenized as SYMBOL rather
        than DELIMITER and needs the same string-level handling either way.
        """
        first_content = next((t for t in tokens if t.type != TokenType.COMMENT), None)
        if first_content is None:
            return ""
        if self.source is None:
            stmt_text = self._tokens_to_string(tokens)
        else:
            end = len(self.source) if is_tail else tokens[-1].pos + len(tokens[-1].text)
            stmt_text = self.source[first_content.pos : end].rstrip()

        stmt_stripped = stmt_text.strip()
        # Strip leading/trailing slash (SQL*Plus delimiter, not valid Oracle SQL)
        # This handles cases where / is tokenized as SYMBOL instead of DELIMITER
        if stmt_stripped.startswith("/"):
            stmt_stripped = stmt_stripped[1:].strip()
        if stmt_stripped.endswith("/"):
            stmt_stripped = stmt_stripped[:-1].strip()
        return stmt_stripped

    def _adjust_context(self, token: Token) -> None:
        """Track tokens and parentheses, and classify the statement from its head."""
        self.context.tokens.append(token)
        if token.type == TokenType.SYMBOL:
            self._adjust_parens_depth(token)
        if self._unit is None and token.type != TokenType.COMMENT:
            self._head.append(token)
            self._unit = head_decided(self._head)
            if self._unit is None and len(self._head) >= MAX_HEAD_TOKENS:
                self._unit = False

    def _is_statement_end(self, token: Token) -> bool:
        """Check if token marks statement end in Oracle (docs/sql-parsing/oracle.md §4).

        ``/`` alone on its line ends any statement; ``;`` ends a statement
        that is not a PL/SQL unit (decided by its head, §5), outside
        parentheses, and only as the last text on its line. A ``/`` with nothing buffered after a ``;``-ended
        statement, or a ``.`` alone on a line, is refused.
        """
        if token.type != TokenType.DELIMITER:
            return False

        if token.text == ".":
            raise UnsafeStatementSplitError(
                f"'.' alone on line {token.line} would discard the buffered statement "
                "without running it"
            )

        if token.text == "/":
            return self._slash_ends_statement(token)

        if self._unit or token.text != ";" or token.parens_depth > 0:
            return False

        following = self.tokens[self.current_idx + 1 :]
        if following and following[0].type != TokenType.EOF and following[0].line == token.line:
            self._refuse_directive_after_terminator(following[0])
            raise UnsafeStatementSplitError(
                f"';' is not the last text on line {token.line}: SQL*Plus rejects the line "
                "(ORA-03405); move the comment or the next statement to its own line"
            )
        self._last_terminator = ";"
        return True

    def _slash_ends_statement(self, token: Token) -> bool:
        """Whether a ``/`` alone on its line ends the statement being read."""
        if all(t is token or t.type == TokenType.COMMENT for t in self.context.tokens):
            if self._last_terminator == ";":
                raise UnsafeStatementSplitError(
                    f"'/' on line {token.line} would re-execute the previous statement"
                )
        else:
            self._last_terminator = "/"
        return True

    def _refuse_directive_after_terminator(self, next_token: Token) -> None:
        """A directive after a ``;`` on the same line: SQL*Plus sends the line to the server."""
        if self.source is None:
            return
        eol = self.source.find("\n", next_token.pos)
        directive = classify_directive(
            self.source[next_token.pos : eol if eol != -1 else len(self.source)]
        )
        if directive is not None:
            raise UnsupportedMetaCommandError(
                f"SQL*Plus directive {directive.name!r} follows a ';' on line {next_token.line}: "
                "SQL*Plus rejects the line (ORA-03405); put it on its own line"
            )
