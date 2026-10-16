"""The client state of one delimiter script, driven by the tokenizer in source order."""

from bisect import bisect_left
from typing import List, NoReturn, Optional, Sequence, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.delimiter_commands import classify_line, read_delimiter
from dblift.core.sql_parser.lexical_spec import DelimiterScriptRules
from dblift.core.sql_parser.statement import Statement


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
        self.removed = removed  # `removed` and `origin` map record offsets back to the source
        self.origin = origin
        self.delimiter = rules.initial
        self.records: List[Statement] = []
        self.exec_comment = False
        self.analysis_exec_comment = False
        self.open_hint: Optional[Tuple[int, int]] = None
        self._line_comment_end = -1
        self._begin()
        nul = text.find("\x00")
        if nul >= 0:
            raise UnsafeStatementSplitError(
                f"NUL byte on line {text.count(chr(10), 0, nul) + 1}: the {client_name} client "
                "refuses it unless --binary-mode is set"
            )

    def _begin(self) -> None:
        """A new statement: nothing read yet."""
        self.code_started = False
        self.start = -1
        self.start_line = 0
        self.qualifier = False
        self._spans: List[Tuple[int, int]] = []
        self._fragments: List[int] = []

    def _source(self, offset: int) -> int:
        return offset + bisect_left(self.removed, offset)

    def line_head(self, pos: int, end: int, line: int) -> bool:
        """Read the line at ``pos`` as a command (no code pending): True for a delimiter command."""
        found = classify_line(self.rules, self.text, pos, end)
        if found is None:
            return False
        raw = self.text[pos:end]
        self.delimiter = read_delimiter(self.rules, self.client_name, raw, found[1], line)
        first = pos + len(raw) - len(raw.lstrip(self.rules.blanks))
        self.records.append(
            Statement(
                text=raw.strip(self.rules.blanks),
                line=line,
                terminator=None,
                kind="directive",
                source_start=self._source(first),
                source_end=self._source(end + (end < len(self.text))),
            )
        )
        return True

    def code(self, pos: int, line: int) -> None:
        """Code was read: it starts the statement when none is open."""
        if not self.code_started:
            self.code_started, self.start, self.start_line = True, pos, line

    def word(self, text: str) -> bool:
        """A word was read; True when what precedes it qualifies it (``t.end``, ``@begin``)."""
        qualified = self.qualifier
        self.qualifier = False
        return qualified

    def symbol(self, char: str) -> None:
        """A one-character code symbol was read."""
        self.qualifier = char in self.rules.qualifiers

    def comment(self, start: int, end: int, line_comment: bool) -> None:
        """A comment of the statement being read."""
        self._spans.append((start, end))
        if line_comment:
            self._line_comment_end = end

    def fragment(self, pos: int) -> None:
        """A ``;`` under another delimiter, outside an executable comment, ends a fragment."""
        if not self.analysis_exec_comment:
            self._fragments.append(pos + 1)

    def line_end(self, pos: int) -> None:
        """A line feed ends the executable-comment flag; the qualifier too, unless a line comment ended it."""
        self.exec_comment = False
        if pos != self._line_comment_end:
            self.qualifier = False

    def lexeme(self, start_line: int, end_line: int) -> None:
        """A lexeme or comment that spans lines ends the flag and the qualifier too."""
        if end_line != start_line:
            self.exec_comment = False
            self.qualifier = False

    def literal(self, start_line: int, end_line: int) -> None:
        """A string or quoted name was read."""
        self.lexeme(start_line, end_line)
        self.qualifier = False

    def reset_qualifier(self) -> None:
        """A client command pair or a closer breaks a qualified name."""
        self.qualifier = False

    def end(self, pos: int) -> None:
        """The active delimiter at ``pos`` ends the statement being read."""
        if self.code_started:
            self._emit(pos, self.delimiter, pos + len(self.delimiter))
        self._begin()

    def _emit(self, cut: int, terminator: Optional[str], source_end: int) -> None:
        text = self.text[self.start : cut].rstrip()
        analysis: Optional[Tuple[str, ...]] = None
        if self._fragments:
            code = self._blank(text)
            parts = []
            begin = self.start
            for end in self._fragments:
                if code[begin - self.start : end - 1 - self.start].strip():
                    parts.append(self.text[begin : end - 1].strip())
                begin = end
            if code[begin - self.start :].strip():
                parts.append(self.text[begin : self.start + len(text)].strip())
            analysis = tuple(parts)
        self.records.append(
            Statement(
                text=text,
                line=self.start_line,
                terminator=terminator,
                analysis_statements=analysis,
                source_start=self._source(self.start),
                source_end=self._source(source_end),
            )
        )

    def _blank(self, text: str) -> str:
        """The statement text with its comments blanked."""
        chars = list(text)
        for begin, stop in self._spans:
            for k in range(max(begin - self.start, 0), min(stop - self.start, len(chars))):
                chars[k] = " "
        return "".join(chars)

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
        self.analysis_exec_comment = True

    def hint_opens(self, line: int, col: int) -> None:
        """A hint opens on this line and may stay open on later ones."""
        self.block_opens(line)
        self.open_hint = (line, col)

    def hint_closes(self, line: int) -> None:
        """A hint that closes on its own line takes the place of one left open earlier."""
        self.block_opens(line)
        self.open_hint = None

    def close(self) -> bool:
        """A closer in code ends an executable comment, else an open hint; else it is no closer."""
        self.analysis_exec_comment = False
        if self.exec_comment:
            self.exec_comment = False
        elif self.open_hint is not None:
            self.open_hint = None
        else:
            return False
        self.qualifier = False
        return True

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

    def first_word_check(self, pos: int, line: int) -> None:
        """Refuse the command word met away from the head of its line."""
        first = self.text.rfind("\n", 0, pos) + 1
        while self.text[first] in self.rules.blanks:
            first += 1
        if first != pos:
            raise UnsafeStatementSplitError(
                f"{self.rules.command} is not the first word of line {line}: the "
                f"{self.client_name} client silently drops the statements that follow"
            )

    def finish(self) -> None:
        """The end of the script: refuse what is still open, then close the statement being read."""
        if self.open_hint is not None:
            line, col = self.open_hint
            raise UnsafeStatementSplitError(
                f"unterminated optimizer hint starting at line {line}, column {col}"
            )
        if self.code_started:
            self._emit(len(self.text), None, len(self.text))
            self._begin()
