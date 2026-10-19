"""The client state of one delimiter script, driven by the tokenizer in source order."""

import re
from bisect import bisect_left
from typing import List, NoReturn, Optional, Sequence, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.delimiter_commands import (
    check_escape,
    classify_line,
    read_delimiter,
    refuse_command,
)
from dblift.core.sql_parser.lexical_spec import DelimiterScriptRules
from dblift.core.sql_parser.program_body import ProgramBody
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
        text_blanks: str,
        trailing_blanks: str,
    ) -> None:
        """Take the script as read (CRLF as LF); ``removed`` maps offsets back.

        A statement loses only ``text_blanks`` at its start and ``trailing_blanks`` at its end;
        one made only of ``trailing_blanks`` is empty.
        """
        self.rules = rules
        self.text_blanks = text_blanks
        self.trailing_blanks = trailing_blanks
        self.client_name = client_name
        self.text = text
        self.removed = removed  # `removed` and `origin` map record offsets back to the source
        self.origin = origin
        self.delimiter = rules.initial
        self.program = ProgramBody(rules.program)
        self.records: List[Statement] = []
        self.exec_comment = False
        self.analysis_exec_comment = False
        self.exec_clean = False  # set at an opener; a delimiter in the comment keeps it
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
        self.exec_only = False
        self.program.reset()
        self._literals: List[Tuple[int, int]] = []
        self._spans: List[Tuple[int, int]] = []
        self._fragments: List[int] = []

    def _source(self, offset: int) -> int:
        return offset + bisect_left(self.removed, offset)

    def line_head(self, pos: int, end: int, line: int) -> bool:
        """Read the line at ``pos`` as a command: True for a delimiter command, else it is text.

        With only executable comments pending, just the exit commands still count.
        """
        found = classify_line(self.rules, self.text, pos, end, self.delimiter)
        if found is None:
            return False
        word = found[0].upper()
        if self.code_started and word not in self.rules.exit_commands:
            return False
        if word != self.rules.command.upper():
            refuse_command(self.client_name, found[0], line, after_comment=False)
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

    def after_comment(self, pos: int, end: int, line: int) -> None:
        """A command word after a comment on its line: some clients run it, so it is refused."""
        found = classify_line(self.rules, self.text, pos, end, self.delimiter)
        if found is not None and found[0].upper() != self.rules.command.upper():
            refuse_command(self.client_name, found[0], line, after_comment=True)

    def escape(self, pos: int, end: int, line: int) -> None:
        """The escape character met outside lexemes and comments."""
        check_escape(self.rules, self.client_name, self.text, pos, end, line)

    def code(self, pos: int, line: int) -> None:
        """Code was read: it starts the statement when none is open."""
        if not self.code_started:
            self.code_started, self.start, self.start_line = True, pos, line

    def word(self, text: str) -> bool:
        """A word was read; True when what precedes it qualifies it (``t.end``, ``@begin``)."""
        qualified = self.qualifier
        self.qualifier = False
        self._outside_executable()
        if qualified:
            self.program.quoted()
        else:
            self.program.word(text.upper())
        return qualified

    def _outside_executable(self) -> None:
        """Code read outside an executable comment ends the executable-comment-only text."""
        if not self.exec_comment:
            self.exec_only = False

    def symbol(self, char: str) -> None:
        """A one-character code symbol was read."""
        self.qualifier = char in self.rules.qualifiers
        self._outside_executable()
        self.program.punct(char)

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
        """A line feed ends the executable-comment flag, and the qualifier unless a comment did."""
        self.exec_comment = False
        if pos != self._line_comment_end:
            self.qualifier = False

    def lexeme(self, start_line: int, end_line: int) -> None:
        """A lexeme or comment that spans lines ends the flag and the qualifier too."""
        if end_line != start_line:
            self.exec_comment = False
            self.qualifier = False

    def literal(self, start: int, stop: int, start_line: int, end_line: int) -> None:
        """A string or quoted name was read."""
        self._literals.append((start, stop))
        self.program.quoted()
        self.lexeme(start_line, end_line)
        self.qualifier = False
        self._outside_executable()

    def reset_qualifier(self) -> None:
        """A client command pair or a closer breaks a qualified name."""
        self.qualifier = False

    def end(self, pos: int) -> None:
        """The active delimiter at ``pos`` ends the statement being read."""
        if self.code_started:
            self._emit(pos, self.delimiter, pos + len(self.delimiter))
        self._begin()

    def _emit(self, cut: int, terminator: Optional[str], source_end: int) -> None:
        blanks, trailing = self.text_blanks, self.trailing_blanks
        text = self.text[self.start : cut].rstrip(trailing)
        if not text:
            return
        self._refuse_session_mode(text)
        analysis: Optional[Tuple[str, ...]] = None
        if self._fragments and not self.program.is_program:
            code = self._blank(text, self._spans)
            parts = []
            begin = self.start
            for end in self._fragments:
                if code[begin - self.start : end - 1 - self.start].strip(trailing):
                    parts.append(self.text[begin : end - 1].lstrip(blanks).rstrip(trailing))
                begin = end
            if code[begin - self.start :].strip(trailing):
                parts.append(self.text[begin : self.start + len(text)].lstrip(blanks))
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

    def _refuse_session_mode(self, text: str) -> None:
        """Refuse a statement that sets the mode that changes how the client reads a backslash."""
        rules = self.rules
        mode = rules.session_mode.upper()
        if mode not in text.upper():
            return
        code = self._blank(text, self._spans)
        verbs = "|".join(re.escape(verb) for verb in rules.session_mode_verbs)
        openers = "|".join(re.escape(opener) for opener in rules.executable_openers)
        sets = re.match(rf"\s*(?:(?:{openers})\d*\s*)?(?:{verbs})\b", code, re.IGNORECASE)
        if not (sets or self.program.is_program):
            code = self._blank(code, self._literals)
        setter = re.escape(rules.session_mode_verbs[0])
        if mode in code.upper() and re.search(rf"\b{setter}\b", code, re.IGNORECASE):
            raise UnsafeStatementSplitError(
                f"the statement on line {self.start_line} sets {rules.session_mode}: the "
                f"{self.client_name} client then reads backslashes as ordinary characters, "
                "this splitter cannot follow"
            )

    def _blank(self, text: str, spans: List[Tuple[int, int]]) -> str:
        """The statement text with the given spans blanked."""
        chars = list(text)
        for begin, stop in spans:
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
        self.exec_clean = not self.code_started
        if not self.code_started:
            self.exec_only = True
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

    def close(self, pos: int, end: int, line: int) -> bool:
        """A closer in code ends an executable comment, else an open hint; else it is no closer."""
        self.analysis_exec_comment = False
        if self.exec_comment:
            self.exec_comment = False
            if self.exec_clean:
                self.after_comment(pos + 2, end, line)
        elif self.open_hint is not None:
            self.open_hint = None
            self.exec_only = False
            self.program.punct("*")
            self.program.punct("/")
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
        first = max(self.text.rfind("\n", 0, pos) + 1, self.origin)
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
        if self.code_started and self.delimiter == self.rules.initial and self.program.open:
            raise UnsafeStatementSplitError(
                f"stored-program body opened at line {self.start_line} is not closed before "
                "the end of the script"
            )
        if self.code_started:
            self._emit(len(self.text), None, len(self.text))
            self._begin()
