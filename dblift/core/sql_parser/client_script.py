"""Statement ends and refusals for a client that reads a script line by line."""

import re
from typing import Dict, List, Optional, Sequence

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.client_directives import classify_directive
from dblift.core.sql_parser.lexical_spec import ClientScriptRules, DirectiveAction
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.core.sql_parser.unit_heads import decide

_COMMENT = re.compile(r"/\*.*?\*/|--[^\n]*", re.DOTALL)
_EXEC_BODY = re.compile(r"^\s*\w+\s*(.*?)\s*$", re.DOTALL)
_SET_DEFINE_ARG = re.compile(r"^\s*\w+\s+\w+\s+(\S+)")
_DEFINE_ASSIGN = re.compile(r"^\s*\w+\s+(\w+)\s*=\s*(.*?)\s*;?\s*$", re.DOTALL)
_UNDEFINE_NAMES = re.compile(r"^\s*\w+\s+(.*?)\s*;?\s*$", re.DOTALL)


class ClientScript:
    """The line-oriented rules of one script; state is fresh for every call.

    A statement is a unit or not from its first tokens (``unit_heads``). A unit
    ends only at a line terminator alone on its line; any other statement ends
    at a ``;`` that is last on its line or at such a line terminator.
    """

    def __init__(
        self,
        rules: ClientScriptRules,
        source: str,
        client_name: str = "SQL client",
        *,
        text_blanks: str,
    ) -> None:
        """Start a script with no previous terminator."""
        self.rules = rules
        self.source = source
        self.client_name = client_name
        self.text_blanks = text_blanks
        self._words: List[str] = []
        self._head_line = 0
        self._unit: Optional[bool] = None
        self._last_terminator: Optional[str] = None
        self._ran = False
        # Substitution state: on, with the rules' character, until a directive says otherwise.
        self._define_on = True
        self._define_char = rules.substitution_char
        self._defines: Dict[str, str] = {}
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
        rules = self.rules
        if token.type != TokenType.DELIMITER:
            self._refuse_terminator_text(token, following, buffered)
            return False
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
                self._ran = True
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
        self._ran = self._ran or any(
            t is not token and t.type != TokenType.COMMENT for t in buffered
        )
        return True

    def _starts_the_line(self, token: Token, buffered: Sequence[Token]) -> bool:
        """Whether only blanks and block comments come before ``token`` on its line."""
        others = [t for t in buffered if t is not token]
        line_start = self.source.rfind("\n", 0, token.pos) + 1
        start = others[0].pos if others else line_start
        text = _COMMENT.sub(" ", self.source[start : token.pos])
        return not text.rsplit("\n", 1)[-1].strip(self.text_blanks)

    def _refuse_terminator_text(
        self, token: Token, following: Optional[Token], buffered: Sequence[Token]
    ) -> None:
        """The client runs a line that starts with the terminator, whatever follows it."""
        rules = self.rules
        if not (
            rules.refuse_terminator_text_on_empty_buffer
            and token.text == rules.line_terminator
            and all(t is token or t.type == TokenType.COMMENT for t in buffered)
            and self._starts_the_line(token, buffered)
        ):
            return
        has_text = (
            following is not None
            and following.type != TokenType.EOF
            and following.line == token.line
        )
        mark = rules.line_terminator
        where = f"on line {token.line}, column {token.col}"
        if has_text and following is not None:
            if following.type != TokenType.COMMENT and following.col == token.col + 1:
                raise UnsafeStatementSplitError(
                    f"'{mark}' followed by text {where}: {self.client_name} reads the line as an "
                    "unknown command (SP2-0042)"
                )
            where = f"followed by text {where}"
        effect = "re-execute the previous statement" if self._ran else "run an empty buffer"
        raise UnsafeStatementSplitError(f"'{mark}' {where} would {effect}")

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
        eol = self.source.find("\n", following.pos)
        found = classify_directive(
            self.rules,
            self.source[following.pos : eol if eol != -1 else len(self.source)],
            text_blanks=self.text_blanks,
        )
        if found is not None:
            raise UnsupportedMetaCommandError(
                f"{self.client_name} directive {found[0]!r} follows a ';' on line {following.line}: "
                f"{self.client_name} rejects the line (ORA-03405); put it on its own line"
            )

    def is_exit(self, token: Token) -> bool:
        """Whether a directive token stops the script."""
        found = classify_directive(self.rules, token.text, text_blanks=self.text_blanks)
        return found is not None and found[1] is DirectiveAction.EXIT

    def directive_record(self, token: Token) -> Statement:
        """Record a directive line, or refuse it.

        Nothing is sent for it, except for a policy directive: execution reads
        that policy from the statement list, so it gets ``<line>;``.
        """
        found = classify_directive(self.rules, token.text, text_blanks=self.text_blanks)
        assert found is not None  # the tokenizer only emits recognised directives
        name, action = found
        if action is DirectiveAction.EXEC:
            return self.exec_record(token)
        if action is DirectiveAction.DEFINE:
            self._apply_define(name, token.text, token.line)
        if action is DirectiveAction.REJECT:
            raise UnsupportedMetaCommandError(
                f"Unsupported {self.client_name} directive {name!r} at line {token.line}; "
                "dblift does not run it"
            )
        sent = None
        if name in self.rules.policy_projection:
            if self._policy.match(token.text) is None:
                raise UnsupportedMetaCommandError(
                    f"Unsupported {name} action at line {token.line}: "
                    f"expected {' or '.join(self.rules.policy_actions)}"
                )
            sent = token.text if token.text.endswith(";") else token.text + ";"
        return Statement(
            text=token.text,
            line=token.line,
            terminator=None,
            kind="directive",
            execution_text=sent,
            source_start=token.pos,
            source_end=self._line_end(token.pos),
        )

    def exec_record(self, token: Token) -> Statement:
        """``EXEC[UTE] stmt[;]`` is the unit ``BEGIN stmt; END;``."""
        body = _EXEC_BODY.match(token.text)
        stmt = body.group(1) if body else ""
        if stmt.endswith(";"):
            stmt = stmt[:-1].rstrip(self.text_blanks)
        if not stmt:
            raise UnsupportedMetaCommandError(
                f"EXECUTE on line {token.line} has no statement to run"
            )
        opener, closer = self.rules.exec_wrapper
        text = self.substitute(f"{opener}{stmt}{closer}", token.line)
        return Statement(
            text=text,
            line=token.line,
            terminator=None,
            kind="sql",
            source_start=token.pos,
            source_end=self._line_end(token.pos),
        )

    def ignored_tail_message(self, exit_token: Token) -> Optional[str]:
        """What follows an EXIT directive: the client never runs it. None when nothing would run."""
        line_end = self.source.find("\n", exit_token.pos)
        if line_end < 0:
            return None
        tail = self.source[line_end + 1 :]
        first_line = next(
            (
                line
                for line, text in enumerate(tail.splitlines(), start=exit_token.line + 1)
                if text.strip(self.text_blanks)
                and not text.lstrip(self.text_blanks).startswith("--")
                and classify_directive(
                    self.rules, text.strip(self.text_blanks), text_blanks=self.text_blanks
                )
                is None
            ),
            None,
        )
        if first_line is None:
            return None
        return (
            f"Content after {exit_token.text.split(None, 1)[0].upper()} on line {exit_token.line} "
            f"ignored, as {self.client_name} does not run it (first ignored line: {first_line})"
        )

    def _line_end(self, pos: int) -> int:
        newline = self.source.find("\n", pos)
        return newline + 1 if newline >= 0 else len(self.source)

    def _apply_define(self, name: str, line: str, line_no: int) -> None:
        """Update the substitution state from a DEFINE-action directive line."""
        set_word = self.rules.set_command[0]
        if name in (f"{set_word} DEFINE", f"{set_word} SCAN"):
            arg = _SET_DEFINE_ARG.match(line)
            value = arg.group(1).rstrip(";") if arg else ""
            if value.upper() == "OFF":
                self._define_on = False
            elif value.upper() == "ON":
                self._define_on = True
            elif len(value) == 1 and name == f"{set_word} DEFINE":
                self._define_on = True
                self._define_char = value
        elif name == "UNDEFINE":
            names = _UNDEFINE_NAMES.match(line)
            for var in (names.group(1) if names else "").replace(";", " ").split():
                self._defines.pop(var.upper(), None)
        else:
            assign = _DEFINE_ASSIGN.match(line)
            if assign:
                value = self.substitute(assign.group(2), line_no)
                if len(value) >= 2 and value[0] == value[-1] and value[0] in ("'", '"'):
                    value = value[1:-1]
                self._defines[assign.group(1).upper()] = value

    def substitute(self, text: str, first_line: int) -> str:
        """Replace ``&x`` / ``&&x`` / ``&x.`` with the defined values.

        The client substitutes variables before sending the command to the
        server, so a reference inside a literal is replaced too. The ``.``
        after a name ends it and is consumed. A reference to an undefined
        variable would make the client prompt, which a migration cannot
        answer: refused (so ``&&x`` never has an undefined value to define).
        """
        if not self._define_on or self._define_char not in text:
            return text
        char = re.escape(self._define_char)

        def replace(m: "re.Match[str]") -> str:
            var = m.group(2).upper()
            if var not in self._defines:
                where = first_line + text.count("\n", 0, m.start())
                raise UnsafeStatementSplitError(
                    f"{self._define_char}{m.group(2)} on line {where} is undefined; "
                    f"{self.client_name} would prompt for it"
                )
            return self._defines[var]

        return re.sub(f"({char}{char}?)(\\w+)\\.?", replace, text)
