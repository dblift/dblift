"""The client state of one delimiter script, driven by the tokenizer in source order."""

from typing import NoReturn, Optional, Sequence, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_spec import DelimiterScriptRules


class DelimiterScript:
    """What the client remembers between lexemes, and the refusals it raises where it meets them."""

    def __init__(
        self,
        rules: DelimiterScriptRules,
        client_name: str,
        text: str,
        removed: Sequence[int],
        origin: int,
    ) -> None:
        """Take the script as read (CRLF as LF); ``removed`` maps offsets back."""
        self.rules = rules
        self.client_name = client_name
        self.text = text
        self.removed = removed
        self.origin = origin
        self.exec_comment = False
        self.open_hint: Optional[Tuple[int, int]] = None
        nul = text.find("\x00")
        if nul >= 0:
            raise UnsafeStatementSplitError(
                f"NUL byte on line {text.count(chr(10), 0, nul) + 1}: the {client_name} client "
                "refuses it unless --binary-mode is set"
            )

    def line_end(self) -> None:
        """The client keeps the executable-comment flag per line."""
        self.exec_comment = False

    def lexeme(self, start_line: int, end_line: int) -> None:
        """A lexeme or comment that spans lines ends the flag too."""
        if end_line != start_line:
            self.exec_comment = False

    def block_opens(self, line: int) -> None:
        """Refuse a comment opened inside an executable comment."""
        if self.exec_comment:
            raise UnsafeStatementSplitError(
                f"comment opens inside an executable comment on line {line}: "
                f"the {self.client_name} client misreads it"
            )

    def executable(self, line: int) -> None:
        """An executable comment opens: its text is code until the closer."""
        self.block_opens(line)
        self.exec_comment = True

    def hint_opens(self, line: int, col: int) -> None:
        """A hint opens on this line and may stay open on later ones."""
        self.block_opens(line)
        self.open_hint = (line, col)

    def close(self) -> bool:
        """A closer in code ends an executable comment, else an open hint; else it is no closer."""
        if self.exec_comment:
            self.exec_comment = False
            return True
        if self.open_hint is not None:
            self.open_hint = None
            return True
        return False

    def check_line_comment(self, start: int, end: int, line: int) -> None:
        """Refuse a carriage return in a line comment: the client reads on to the next line feed."""
        if "\r" in self.text[start:end]:
            raise UnsafeStatementSplitError(
                f"comment on line {line} holds a carriage return that is not part of a line end: "
                f"the {self.client_name} client reads the rest of the script as part of the "
                "comment and drops the statements in it"
            )

    def check_hint(self, start: int, stop: int, line: int) -> None:
        """Refuse a backslash in the opening-line text of a hint: the client runs it."""
        if self.text.find(self.rules.escape, start, stop) >= 0:
            raise UnsupportedMetaCommandError(
                f"backslash inside an optimizer hint on line {line}: the {self.client_name} "
                "client runs it as a command"
            )

    def unterminated_block(self, error: UnsafeStatementSplitError) -> NoReturn:
        """An unterminated block comment while a hint is open is reported as the hint."""
        if self.open_hint is not None:
            self.finish()
        raise error

    def finish(self) -> None:
        """The end of the script: refuse what is still open."""
        if self.open_hint is not None:
            line, col = self.open_hint
            raise UnsafeStatementSplitError(
                f"unterminated optimizer hint starting at line {line}, column {col}"
            )
