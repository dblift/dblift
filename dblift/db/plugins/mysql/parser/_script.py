"""Cut a MySQL or MariaDB script into the statements the ``mysql`` client sends.

docs/sql-parsing/mysql.md. A statement ends at the active delimiter (``;`` at first), which the
client matches as a plain string outside quotes and comments; ``DELIMITER`` changes it. A few words
at the start of a line are client commands; ``DELIMITER`` is the one read so far, the others pass
through as text. One documented extension goes beyond the client:
while the delimiter is ``;``, the ``BEGIN ... END`` body of a stored program stays whole.
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.statement import Statement

#: The client keeps a delimiter in a 16-byte buffer: longer ones are silently cut (measured).
MAX_DELIMITER_LENGTH = 15

#: Blanks of the client's ``my_isspace`` (the newline is gone: the script is read line by line).
_BLANKS = " \t\r\x0b\x0c"
_QUOTES = {"'": "string literal", '"': "string literal", "`": "quoted identifier"}
_LINE_WORD = re.compile(r"[A-Za-z_]+|\?")
_DELIMITER_WORD = re.compile(r"delimiter(?=[ \t\r]|$)", re.IGNORECASE)

_PROGRAM_KINDS = frozenset({"PROCEDURE", "FUNCTION", "TRIGGER", "EVENT"})
_BLOCK_WORDS = frozenset({"IF", "LOOP", "WHILE", "REPEAT", "CASE", "FOR"})
_STATEMENT_START = frozenset({";", ":", "BEGIN", "THEN", "ELSE", "DO", "LOOP", "REPEAT"})


class _Program:
    """Whether the statement being read is a stored program whose BEGIN ... END body stays whole.

    Fed the words and punctuation of the statement outside strings and comments. The head is
    ``CREATE [OR REPLACE] [DEFINER = user@host] [AGGREGATE] PROCEDURE|FUNCTION|TRIGGER|EVENT`` or
    ``ALTER [DEFINER = ...] EVENT``; the body opens at the first ``BEGIN`` at parenthesis depth 0.
    """

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.head = "start"
        self.verb = ""
        self.is_program = False
        self.stack: List[str] = []
        self.depth = 0
        self.prev = ""
        self.after_end = False

    @property
    def open(self) -> bool:
        """True inside a body: a ``;`` here does not end the statement."""
        return self.is_program and bool(self.stack)

    def word(self, word: str) -> None:
        if not self.is_program:
            self._head("word", word)
        else:
            self._body(word)
        self.prev = word

    def quoted(self) -> None:
        if not self.is_program:
            self._head("quoted", "")
        self.prev = "'"

    def punct(self, char: str) -> None:
        if not self.is_program:
            self._head("punct", char)
        else:
            if char == "(":
                self.depth += 1
            elif char == ")" and self.depth:
                self.depth -= 1
            self.after_end = False
        self.prev = char

    def _head(self, kind: str, value: str) -> None:
        head = self.head
        if head == "done":
            return
        if head == "start":
            if kind == "word" and value in ("CREATE", "ALTER"):
                self.verb, self.head = value, "verb"
            else:
                self.head = "done"
        elif head == "definer_eq":
            self.head = "definer_user" if (kind, value) == ("punct", "=") else "done"
        elif head == "definer_user":
            if kind == "word" and value == "CURRENT_USER":
                self.head = "definer_current"
            elif kind in ("word", "quoted"):
                self.head = "definer_at"
            else:
                self.head = "done"
        elif head == "definer_current":
            if (kind, value) == ("punct", "("):
                self.head = "definer_close"
            else:
                self.head = "verb"
                self._head(kind, value)
        elif head == "definer_close":
            self.head = "verb" if (kind, value) == ("punct", ")") else "done"
        elif head == "definer_at":
            if (kind, value) == ("punct", "@"):
                self.head = "definer_host"
            else:
                self.head = "verb"
                self._head(kind, value)
        elif head == "definer_host":
            self.head = "verb" if kind in ("word", "quoted") else "done"
        else:  # "verb": the words between CREATE/ALTER and the kind of object
            if kind != "word":
                self.head = "done"
            elif value in ("OR", "REPLACE") or (value == "AGGREGATE" and self.verb == "CREATE"):
                return
            elif value == "DEFINER":
                self.head = "definer_eq"
            elif value in _PROGRAM_KINDS and (self.verb == "CREATE" or value == "EVENT"):
                self.is_program, self.head = True, "done"
            else:
                self.head = "done"

    def _body(self, word: str) -> None:
        stack = self.stack
        after_end, self.after_end = self.after_end, False
        if word == "END":
            if stack:
                stack.pop()
            self.after_end = True
            return
        if after_end and word in _BLOCK_WORDS:
            return  # END IF, END LOOP, END WHILE, END REPEAT, END CASE, END FOR
        if not stack:
            if word == "BEGIN" and self.depth == 0:
                stack.append("BEGIN")
            return
        if word == "BEGIN" and self.depth == 0:
            stack.append("BEGIN")
        elif word == "CASE":
            statement = (
                self.depth == 0 and self.prev in _STATEMENT_START and stack[-1] != "CASE_EXPR"
            )
            stack.append("CASE" if statement else "CASE_EXPR")
        elif (
            word in _BLOCK_WORDS
            and self.depth == 0
            and self.prev in _STATEMENT_START
            and stack[-1] != "CASE_EXPR"
        ):
            stack.append(word)


class _Scanner:
    def __init__(self, text: str, mariadb: bool) -> None:
        self.text = text
        self.mariadb = mariadb
        self.statements: List[Statement] = []
        self.delimiter = ";"
        self.program = _Program()
        self.quote = ""
        self.quote_at = (0, 0)
        self.block = ""  # "/*" or "/*+" while inside one
        self.block_at = (0, 0)
        self.exec_comment = False
        self.client = "mariadb" if mariadb else "mysql"
        self.open_hint: Optional[Tuple[int, int]] = None  # mysql: a hint opened and not yet closed
        self._begin_statement()

    def _begin_statement(self) -> None:
        self.code = False
        self.start = -1
        self.start_line = 0
        self.word_chars: List[str] = []
        self.word_qualified = False
        self.prev_char = ""
        self.program.reset()

    def run(self) -> List[Statement]:
        text = self.text
        nul = text.find("\x00")
        if nul >= 0:
            raise UnsafeStatementSplitError(
                f"NUL byte on line {text.count(chr(10), 0, nul) + 1}: the {self.client} client "
                "refuses it unless --binary-mode is set"
            )
        pos, line_no = 0, 0
        while pos < len(text):
            newline = text.find("\n", pos)
            end = len(text) if newline < 0 else newline
            line_no += 1
            if not (self.quote or self.block or self.code) and self._command(pos, end, line_no):
                pos = end + 1
                continue
            self._scan(pos, end, line_no)
            pos = end + 1
        return self._finish()

    # -- lines that are client commands ---------------------------------------------------

    def _command(self, pos: int, end: int, line_no: int) -> bool:
        """A client command at the start of a line (statement text empty): handled or refused."""
        raw = self.text[pos:end]
        stripped = raw.lstrip(_BLANKS)
        found = _LINE_WORD.match(stripped)
        if found is None:
            return False
        word = found.group().upper()
        rest = stripped[found.end() :]
        tail = rest.rstrip("\r")
        has_argument_gap = tail == "" or tail[0] in " \t"
        if word == "DELIMITER" and (has_argument_gap or tail.startswith(";")):
            self._delimiter(raw, tail if has_argument_gap else "", line_no)
            return True
        return False

    def _delimiter(self, raw: str, tail: str, line_no: int) -> None:
        if "\r" in raw.rstrip("\r"):
            raise UnsafeStatementSplitError(
                f"DELIMITER on line {line_no} has a carriage return that is not part of a "
                f"line end: the {self.client} client reads the rest of the script as part of "
                "that line and sends nothing"
            )
        argument = tail.lstrip(" \t")
        if argument and argument[0] in "'\"`":
            close = argument.find(argument[0], 1)
            value = argument[1:close] if close > 1 else ""
        else:
            value = argument.split(" ", 1)[0]
        if not value:
            raise UnsafeStatementSplitError(
                f"DELIMITER on line {line_no} has no argument (or an empty or unclosed quoted "
                "one): "
                "the mysql client prints an error and keeps the old delimiter, the mariadb "
                "client sends the line to the server as text"
            )
        if "\\" in value:
            raise UnsafeStatementSplitError(
                f"DELIMITER on line {line_no} contains a backslash: "
                f"the {self.client} client refuses it, backslash is the escape character"
            )
        if len(value) > MAX_DELIMITER_LENGTH:
            raise UnsafeStatementSplitError(
                f"DELIMITER on line {line_no} is longer than {MAX_DELIMITER_LENGTH} characters: "
                f"the {self.client} client silently keeps only the first ones"
            )
        self.delimiter = value
        self.statements.append(
            Statement(text=raw.strip(_BLANKS), line=line_no, terminator=None, kind="directive")
        )

    # -- the character scan ------------------------------------------------------------------

    def _scan(self, pos: int, end: int, line_no: int) -> None:
        text = self.text
        i = pos
        self.exec_comment = False  # the client keeps this flag per line, not per statement
        while i < end:
            if self.block:
                i = self._in_block(i, end, line_no)
                continue
            if self.quote:
                i = self._in_quote(i, end)
                continue
            ch = text[i]
            delimiter = self.delimiter
            if text.startswith(delimiter, i):
                self._flush_word()
                if delimiter == ";" and self.program.open:
                    self._code(i, line_no)
                    self.program.punct(";")
                    self.prev_char = ";"
                    i += 1
                    continue
                self._end_statement(i, delimiter)
                i += len(delimiter)
                continue
            if ch == "#" or (text.startswith("--", i) and (i + 2 >= end or text[i + 2] in _BLANKS)):
                if "\r" in text[i:end]:
                    raise UnsafeStatementSplitError(
                        f"comment on line {line_no} holds a carriage return that is not part of "
                        f"a line end: the {self.client} client reads the rest of the script as "
                        "part of the comment and drops the statements in it"
                    )
                self._flush_word()
                return
            if ch == "/" and text.startswith("/*", i):
                i = self._open_comment(i, pos, line_no)
                continue
            if self.exec_comment and text.startswith("*/", i):
                self.exec_comment = False
                self._code(i, line_no)
                self._flush_word()
                self.prev_char = ""
                i += 2
                continue
            if self.open_hint is not None and text.startswith("*/", i):
                self.open_hint = None  # the end of a hint whose first line is behind us
                self._code_char("*", i, line_no)
                self._code_char("/", i + 1, line_no)
                i += 2
                continue
            if ch in _QUOTES:
                self._code(i, line_no)
                self._flush_word()
                self.program.quoted()
                self.quote, self.quote_at = ch, (line_no, i - pos + 1)
                self.prev_char = ""
                i += 1
                continue
            if not self.code and ch in "dD" and _DELIMITER_WORD.match(text, i, end):
                if i != pos + len(text[pos:end]) - len(text[pos:end].lstrip(_BLANKS)):
                    raise UnsafeStatementSplitError(
                        f"DELIMITER is not the first word of line {line_no}: the {self.client} "
                        "client silently drops the statements that follow"
                    )
            self._code_char(ch, i, line_no)
            i += 1
        if self.block == "/*+" and not self.mariadb:
            # the mysql client hides the delimiter in a hint on its opening line only
            self.block = ""
        self._flush_word()
        self.prev_char = ""

    def _code(self, index: int, line_no: int) -> None:
        if not self.code:
            self.code, self.start, self.start_line = True, index, line_no

    def _code_char(self, ch: str, index: int, line_no: int) -> None:
        if ch in _BLANKS:
            self._flush_word()
            return
        self._code(index, line_no)
        if ch.isalnum() or ch in "_$" or ord(ch) > 127:
            if not self.word_chars:
                self.word_qualified = self.prev_char in ("@", ".")
            self.word_chars.append(ch)
        else:
            self._flush_word()
            self.program.punct(ch)
        self.prev_char = ch

    def _flush_word(self) -> None:
        if self.word_chars:
            word = "".join(self.word_chars)
            self.word_chars = []
            if self.word_qualified:
                self.program.quoted()
            else:
                self.program.word(word.upper())

    def _open_comment(self, i: int, pos: int, line_no: int) -> int:
        text = self.text
        third = text[i + 2 : i + 3]
        executable = third == "!" or (self.mariadb and text.startswith("M!", i + 2))
        if self.exec_comment:
            raise UnsafeStatementSplitError(
                f"comment opens inside an executable comment on line {line_no}: "
                f"the {self.client} client misreads it"
            )
        if executable:
            self._code(i, line_no)
            self._flush_word()
            self.exec_comment = True
            return i + (3 if third == "!" else 4)
        self._flush_word()
        self.block = "/*+" if third == "+" else "/*"
        self.block_at = (line_no, i - pos)
        if third == "+" and not self.mariadb:
            self.open_hint = (line_no, i - pos)
        return i + (3 if third == "+" else 2)

    def _in_block(self, i: int, end: int, line_no: int) -> int:
        text = self.text
        close = text.find("*/", i, end)
        if close < 0:
            return end
        if self.block == "/*+":
            self.open_hint = None
        self.block = ""
        return close + 2

    def _in_quote(self, i: int, end: int) -> int:
        text, quote = self.text, self.quote
        while i < end:
            ch = text[i]
            if ch == "\\" and quote != "`":
                i += 2
                continue
            i += 1
            if ch == quote:
                self.quote = ""
                break
        return min(i, end)

    # -- statements ----------------------------------------------------------------------------

    def _end_statement(self, index: int, delimiter: str) -> None:
        self._flush_word()
        if self.code:
            self._emit(self.text[self.start : index], delimiter)
        self._begin_statement()

    def _emit(self, text: str, terminator: Optional[str]) -> None:
        self.statements.append(
            Statement(text=text.rstrip(), line=self.start_line, terminator=terminator)
        )

    def _finish(self) -> List[Statement]:
        if self.quote:
            line, col = self.quote_at
            raise UnsafeStatementSplitError(
                f"unterminated {_QUOTES[self.quote]} starting at line {line}, column {col}"
            )
        if self.open_hint is not None:
            line, col = self.open_hint
            raise UnsafeStatementSplitError(
                f"unterminated optimizer hint starting at line {line}, column {col + 1}"
            )
        if self.block:
            line, col = self.block_at
            raise UnsafeStatementSplitError(
                f"unterminated block comment starting at line {line}, column {col + 1}"
            )
        self._flush_word()
        if self.code and self.delimiter == ";" and self.program.open:
            raise UnsafeStatementSplitError(
                f"stored-program body opened at line {self.start_line} is not closed before the "
                "end of the script"
            )
        if self.code:
            self._emit(self.text[self.start :], None)
        return self.statements


def scan_script(script: str, *, mariadb: bool = False) -> List[Statement]:
    """The statements and ``DELIMITER`` directives of ``script``, as the client reads them."""
    text = script[1:] if script.startswith("\ufeff") else script
    # The client reads lines and drops the carriage return of a CRLF pair: what it sends, in
    # strings and bodies too, has LF only. A carriage return alone stays (it is no line end).
    return _Scanner(text.replace("\r\n", "\n"), mariadb).run()
