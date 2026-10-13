"""Statement ends and refusals for a client that reads a script line by line."""

from typing import List, Optional, Sequence

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_spec import ClientScriptRules
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.core.sql_parser.unit_heads import decide


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
