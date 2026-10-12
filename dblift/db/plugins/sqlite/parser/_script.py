"""Cut a SQLite script into the statements the ``sqlite3`` shell sends to the engine.

docs/sql-parsing/sqlite.md sections 1 to 6. The shell reads a script line by line, hands a line
that starts with a dot to its own command interpreter when no statement is pending, treats a line
that holds only ``go`` or ``/`` as a terminator, and otherwise asks ``sqlite3_complete`` whether
the text so far is a whole statement. The scanner reproduces that: tokens are read as the engine
reads them (strings, quoted identifiers, comments), a ``;`` ends a statement except inside a
``CREATE TRIGGER`` body, which ends at the ``END`` that follows a ``;``, and the lines the shell
would interpret are refused instead of being glued to the next statement.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError

# Token classes of sqlite3_complete and its states (docs/sql-parsing/sqlite.md section 5).
_SEMI, _OTHER, _EXPLAIN, _CREATE, _TEMP, _TRIGGER, _END = range(7)
_START, _NORMAL, _EXPLAINED, _CREATING, _IN_TRIGGER, _AFTER_SEMI, _AFTER_END = range(1, 8)

#: ``_NEXT[state][token]``: the state after the token. Row 0 is unused.
_NEXT = (
    (),
    (1, 2, 3, 4, 2, 2, 2),
    (1, 2, 2, 2, 2, 2, 2),
    (1, 3, 2, 4, 2, 2, 2),
    (1, 2, 2, 2, 4, 5, 2),
    (6, 5, 5, 5, 5, 5, 5),
    (6, 5, 5, 5, 5, 5, 7),
    (1, 5, 5, 5, 5, 5, 5),
)
_KEYWORDS = {
    "explain": _EXPLAIN,
    "create": _CREATE,
    "temp": _TEMP,
    "temporary": _TEMP,
    "trigger": _TRIGGER,
    "end": _END,
}
#: A word is a run of these (sqlite3_complete's IdChar), so ``end_at`` and ``end$`` are not END.
_WORD = re.compile(r"[A-Za-z0-9_$\x80-\U0010ffff]+")
#: The blanks around a ``go`` or ``/`` line; the shell's include the vertical tab.
_LINE_BLANKS = " \t\f\r\v"
_BLANKS = " \t\n\f\r"
_CLOSERS = {"'": "'", '"': '"', "`": "`", "[": "]"}


@dataclass(frozen=True)
class Unit:
    """One statement: its text without the terminator, its first line, what ended it."""

    text: str
    line: int
    terminator: Optional[str]


def scan_script(script: str, *, comment_only: bool = False) -> List[Unit]:
    """The statements of ``script``; ``comment_only`` keeps the comment-only segments as units."""
    text = script[1:] if script.startswith("﻿") else script
    return _Scanner(text, comment_only).run()


def blank_comments(script: str) -> str:
    """``script`` with every comment replaced by a space; strings and identifiers are untouched."""
    text = script[1:] if script.startswith("\ufeff") else script
    scanner = _Scanner(text, False)
    scanner.run()
    pieces, last = [], 0
    for start, end in scanner.comments:
        pieces.append(text[last:start])
        pieces.append(" ")
        last = end
    pieces.append(text[last:])
    return "".join(pieces)


def _is_terminator_line(line: str) -> bool:
    """``go`` or ``/``, then closed block comments and a line comment, blanks between."""
    size, i = len(line), 0
    while i < size and line[i] in _LINE_BLANKS:
        i += 1
    if line.startswith("/", i):
        i += 1
    elif line[i : i + 2].lower() == "go":
        i += 2
    else:
        return False
    while True:
        while i < size and line[i] in _LINE_BLANKS:
            i += 1
        if not line.startswith("/*", i):
            return i == size or line.startswith("--", i)
        end = line.find("*/", i + 2)
        if end < 0:
            return False
        i = end + 2


class _Scanner:
    def __init__(self, text: str, comment_only: bool) -> None:
        self.text = text
        self.comment_only = comment_only
        self.units: List[Unit] = []
        self.comments: List[Tuple[int, int]] = []
        self.state = _START
        self.code = False
        self.segment = 0
        self.segment_line = 1
        self.line = 1
        self.at_line_start = True
        self.comment_ends_line = False
        self.comment_ended_previous_line = False

    def run(self) -> List[Unit]:
        text, size, i = self.text, len(self.text), 0
        while i < size:
            char = text[i]
            if self.at_line_start:
                self._line_start(i)
            if char == "\n":
                self.line += 1
                self.at_line_start = True
                self.comment_ended_previous_line = self.comment_ends_line
                self.comment_ends_line = False
                i += 1
                continue
            self.at_line_start = False
            if char in " \t\f\r":
                i += 1
            elif text.startswith("--", i):
                self.comment_ends_line = True
                end = text.find("\n", i)
                stop = size if end < 0 else end
                self.comments.append((i, stop))
                i = stop
            elif text.startswith("/*", i):
                i = self._block_comment(i)
            elif char in _CLOSERS:
                i = self._quoted(i, _CLOSERS[char])
            elif char == ";":
                i = self._semicolon(i)
            else:
                word = _WORD.match(text, i)
                if word:
                    self._token(_KEYWORDS.get(word.group().lower(), _OTHER))
                    i = word.end()
                else:
                    self._token(_OTHER)
                    i += 1
        self._finish(size, None)
        return self.units

    def _line_start(self, i: int) -> None:
        """The shell's two line-level rules, read where no literal or comment is open."""
        end = self.text.find("\n", i)
        line = self.text[i:] if end < 0 else self.text[i:end]
        if line.startswith(".") and not self.code:
            raise UnsupportedMetaCommandError(
                f"sqlite3 shell command {line.split(None, 1)[0]!r} on line {self.line}: the "
                "shell runs it and the engine cannot; dblift does not run client commands"
            )
        if (
            self.code
            and self.state not in (_IN_TRIGGER, _AFTER_SEMI)
            and not self.comment_ended_previous_line
            and _is_terminator_line(line)
        ):
            raise UnsafeStatementSplitError(
                f"line {self.line} holds only {line.strip()!r}: the sqlite3 shell ends the "
                "statement there, the engine reads it as part of the statement; put the "
                "terminator on the statement"
            )

    def _token(self, token: int) -> None:
        self.code = True
        self.state = _NEXT[self.state][token]

    def _block_comment(self, i: int) -> int:
        end = self.text.find("*/", i + 2)
        if end < 0:
            raise UnsafeStatementSplitError(
                f"the block comment opened on line {self.line} is not closed before the end of "
                "the script: the statements inside it would be dropped"
            )
        self.line += self.text.count("\n", i, end)
        self.comments.append((i, end + 2))
        return end + 2

    def _quoted(self, i: int, closer: str) -> int:
        """A string or quoted identifier; a doubled quote is two lexemes in a row, so no escape."""
        self._token(_OTHER)
        end = self.text.find(closer, i + 1)
        if end < 0:
            self.line += self.text.count("\n", i)
            return len(self.text)
        self.line += self.text.count("\n", i, end)
        return end + 1

    def _semicolon(self, i: int) -> int:
        self.state = _NEXT[self.state][_SEMI]
        if self.state == _START:
            self._finish(i, ";")
            self.segment, self.segment_line = i + 1, self.line
        return i + 1

    def _finish(self, end: int, terminator: Optional[str]) -> None:
        raw = self.text[self.segment : end]
        if self.code or (self.comment_only and raw.strip(_BLANKS)):
            text = raw.lstrip(_BLANKS)
            line = self.segment_line + raw.count("\n", 0, len(raw) - len(text))
            self.units.append(Unit(text.rstrip(_BLANKS), line, terminator))
        self.state, self.code = _START, False
