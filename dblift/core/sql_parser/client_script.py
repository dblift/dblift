"""Statement ends and refusals for a client that reads a script line by line."""

import re
from typing import List, Optional, Sequence, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.client_directives import classify_directive
from dblift.core.sql_parser.lexical_spec import ClientScriptRules, DirectiveAction
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.core.sql_parser.unit_heads import decide

_EXEC_BODY = re.compile(r"^\s*\w+\s*(.*?)\s*$", re.DOTALL)


class ClientScript:
    """The line-oriented rules of one script; state is fresh for every call.

    A statement is a unit or not from its first tokens (``unit_heads``). A unit
    ends only at a line terminator alone on its line; any other statement ends
    at a ``;`` that is last on its line or at such a line terminator.
    """

    def __init__(
        self, rules: ClientScriptRules, source: Optional[str], client_name: str = "SQL client"
    ) -> None:
        """Start a script with no previous terminator."""
        self.rules = rules
        self.source = source
        self.client_name = client_name
        self._words: List[str] = []
        self._head_line = 0
        self._unit: Optional[bool] = None
        self._last_terminator: Optional[str] = None
        self._policy = re.compile(
            "^\\s*("
            + "|".join(
                r"\s+".join(map(re.escape, name.split())) for name in rules.policy_projection
            )
            + r")\s+(?:"
            + "|".join(map(re.escape, rules.policy_actions))
            + r")\b",
            re.IGNORECASE,
        )

    def reset_statement(self) -> None:
        """Forget the head of the statement that just ended."""
        self._words = []
        self._unit = None

    def _observe(self, token: Token) -> None:
        if token.type == TokenType.COMMENT or self._unit is not None:
            return
        if not self._words:
            self._head_line = token.line
        self._words.append(token.text.upper())
        self._unit = decide(self.rules.unit_heads, self._words, self.rules.max_head_tokens)

    def is_statement_end(
        self, token: Token, following: Optional[Token], buffered: Sequence[Token]
    ) -> bool:
        """Whether ``token`` ends the statement; refuses what the client would reject."""
        self._observe(token)
        if token.type != TokenType.DELIMITER:
            return False
        rules = self.rules
        if token.text == rules.discard_line:
            raise UnsafeStatementSplitError(
                f"'{rules.discard_line}' alone on line {token.line} would discard the "
                "buffered statement without running it"
            )
        if token.text == rules.line_terminator:
            if all(t is token or t.type == TokenType.COMMENT for t in buffered):
                if self._last_terminator in (";", rules.line_terminator):
                    raise UnsafeStatementSplitError(
                        f"'{rules.line_terminator}' on line {token.line}, column {token.col} "
                        "would re-execute the previous statement"
                    )
            else:
                self._last_terminator = rules.line_terminator
            return True
        if self._unit or token.text != ";" or token.parens_depth > 0:
            return False
        if following and following.type != TokenType.EOF and following.line == token.line:
            self._refuse_directive_after_terminator(following)
            raise UnsafeStatementSplitError(
                f"';' is not the last text on line {token.line}: {self.client_name} rejects the line "
                "(ORA-03405); move the comment or the next statement to its own line"
            )
        self._last_terminator = ";"
        return True

    def check_tail(self, tokens: Sequence[Token]) -> None:
        """Refuse a unit that reached the end of the script without its line terminator."""
        if tokens and self._unit:
            raise UnsafeStatementSplitError(self.unterminated_unit_message(tokens, self._head_line))

    def unterminated_unit_message(self, tokens: Sequence[Token], head_line: int) -> str:
        """Refusal for a unit that reached the end of the script without its terminator."""
        last_line = max(t.line for t in tokens if t.type != TokenType.EOF)
        on_last_line = [t for t in tokens if t.line == last_line]
        terminator = self.rules.line_terminator
        if len(on_last_line) > 1 and on_last_line[0].text == terminator:
            return (
                f"PL/SQL unit starting at line {head_line}: a '{terminator}' followed by other "
                f"text does not end the unit (line {last_line})"
            )
        return (
            f"PL/SQL unit starting at line {head_line} is not terminated by "
            f"a '{terminator}' line before the end of the script"
        )

    def record_end(
        self, tokens: Sequence[Token], terminator: Optional[Token], default: Optional[int]
    ) -> Optional[int]:
        """End offset of a record under the client's rules."""
        if self.source is None:
            return default
        rules = self.rules
        if terminator is not None:
            if rules.slash_record_ends_at_line_end and terminator.text == rules.line_terminator:
                newline = self.source.find("\n", terminator.pos)
                return newline + 1 if newline >= 0 else len(self.source)
            return default
        if rules.tail_record_ends_at_last_token and tokens:
            last = tokens[-1]
            return last.pos + len(last.text)
        return default

    def _refuse_directive_after_terminator(self, following: Token) -> None:
        """A directive after a ``;`` on the same line: the client sends the line to the server."""
        if self.source is None:
            return
        eol = self.source.find("\n", following.pos)
        found = classify_directive(
            self.rules, self.source[following.pos : eol if eol != -1 else len(self.source)]
        )
        if found is not None:
            raise UnsupportedMetaCommandError(
                f"{self.client_name} directive {found[0]!r} follows a ';' on line {following.line}: "
                f"{self.client_name} rejects the line (ORA-03405); put it on its own line"
            )

    def flush_before_directive(self, pending: Sequence[Token]) -> bool:
        """Whether a statement is pending where a directive begins; refuses an open unit."""
        if not any(t.type != TokenType.COMMENT for t in pending):
            return False
        if self._unit:
            raise UnsafeStatementSplitError(
                self.unterminated_unit_message(pending, self._head_line)
            )
        return True

    def is_exit(self, token: Token) -> bool:
        """Whether a directive token stops the script."""
        found = classify_directive(self.rules, token.text)
        return found is not None and found[1] is DirectiveAction.EXIT

    def directive_record(self, token: Token) -> Tuple[Statement, str]:
        """Record a directive line, or refuse it.

        The string is empty, except for a policy directive: execution reads
        that policy from the statement list, so it gets ``<line>;``.
        """
        found = classify_directive(self.rules, token.text)
        assert found is not None  # the tokenizer only emits recognised directives
        name, action, _ = found
        if action is DirectiveAction.EXEC:
            return self.exec_record(token)
        if action is DirectiveAction.REJECT:
            raise UnsupportedMetaCommandError(
                f"Unsupported {self.client_name} directive {name!r} at line {token.line}; "
                "dblift does not run it"
            )
        record = Statement(
            text=token.text,
            line=token.line,
            terminator=None,
            kind="directive",
            source_start=token.pos if self.source is not None else None,
            source_end=self._line_end(token.pos),
        )
        if name not in self.rules.policy_projection:
            return record, ""
        if self._policy.match(token.text) is None:
            raise UnsupportedMetaCommandError(
                f"Unsupported {name} action at line {token.line}: "
                f"expected {' or '.join(self.rules.policy_actions)}"
            )
        return record, token.text if token.text.endswith(";") else token.text + ";"

    def exec_record(self, token: Token) -> Tuple[Statement, str]:
        """``EXEC[UTE] stmt[;]`` is the unit ``BEGIN stmt; END;``."""
        body = _EXEC_BODY.match(token.text)
        stmt = body.group(1) if body else ""
        if stmt.endswith(";"):
            stmt = stmt[:-1].rstrip()
        if not stmt:
            raise UnsupportedMetaCommandError(
                f"EXECUTE on line {token.line} has no statement to run"
            )
        opener, closer = self.rules.exec_wrapper
        text = f"{opener}{stmt}{closer}"
        return (
            Statement(
                text=text,
                line=token.line,
                terminator=None,
                kind="sql",
                source_start=token.pos if self.source is not None else None,
                source_end=self._line_end(token.pos),
            ),
            text,
        )

    def ignored_tail_message(self, exit_token: Token) -> Optional[str]:
        """What follows an EXIT directive: the client never runs it. None when nothing would run."""
        if self.source is None:
            return None
        line_end = self.source.find("\n", exit_token.pos)
        if line_end < 0:
            return None
        tail = self.source[line_end + 1 :]
        first_line = next(
            (
                line
                for line, text in enumerate(tail.splitlines(), start=exit_token.line + 1)
                if text.strip()
                and not text.lstrip().startswith("--")
                and classify_directive(self.rules, text.strip()) is None
            ),
            None,
        )
        if first_line is None:
            return None
        return (
            f"Content after {exit_token.text.split(None, 1)[0].upper()} on line {exit_token.line} "
            f"ignored, as {self.client_name} does not run it (first ignored line: {first_line})"
        )

    def _line_end(self, pos: int) -> Optional[int]:
        if self.source is None:
            return None
        newline = self.source.find("\n", pos)
        return newline + 1 if newline >= 0 else len(self.source)
