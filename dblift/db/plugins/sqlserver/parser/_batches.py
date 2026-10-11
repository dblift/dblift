"""Cut a T-SQL script into the batches ``sqlcmd`` sends to the server.

docs/sql-parsing/sqlserver.md sections 3 and 4. A batch ends at a ``GO`` line and
nothing else: ``;`` never ends one and no ``BEGIN``/``END`` is counted. The scanner
reproduces the *client's* lexer, which is simpler than the server's: a block comment
ends at the first ``*/`` (the server nests them; its text is passed through verbatim).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError

_WORD = re.compile(r"[A-Za-z_@#$][A-Za-z0-9_@#$]*")
_GO_LINE_END = re.compile(r"[ \t\r]*(?:--.*)?\Z", re.DOTALL)
_OPENER = re.compile(r"'|\[|\"|/\*|--")
_CLOSER = {"'": "'", "[": "]", '"': '"'}
_LEXEME = {
    "'": "string literal",
    "[": "bracketed identifier",
    '"': "quoted identifier",
    "/*": "block comment",
}


@dataclass(frozen=True)
class Batch:
    """One batch: its verbatim text, first line, how often to send it, and whether a GO ended it."""

    text: str
    line: int
    repeat: int = 1
    terminated: bool = False


def scan_batches(script: str) -> List[Batch]:
    """The batches of ``script``; refuses what ``sqlcmd`` would reject or silently act on."""
    return _Scanner(script[1:] if script.startswith("﻿") else script).run()


class _Scanner:
    def __init__(self, text: str) -> None:
        self.text = text
        self.batches: List[Batch] = []
        self.state: Optional[str] = None  # an open lexeme: ', [, ", /*
        self.opened: Tuple[int, int] = (0, 0)
        self.batch_start = 0
        self.batch_line = 1
        self.has_code = False

    def run(self) -> List[Batch]:
        text, pos, line_no = self.text, 0, 0
        while pos < len(text):
            newline = text.find("\n", pos)
            end = len(text) if newline == -1 else newline
            following = len(text) if newline == -1 else newline + 1
            line_no += 1
            count = self._scan_line(text[pos:end], line_no)
            if count is not None:
                self._cut(pos, following, count, line_no)
            pos = following
        if self.state is not None:
            line, col = self.opened
            raise UnsafeStatementSplitError(
                f"unterminated {_LEXEME[self.state]} starting at line {line}, column {col}"
            )
        self._flush(len(text), repeat=1, terminated=False)
        return self.batches

    def _scan_line(self, line: str, line_no: int) -> Optional[int]:
        """Advance the lexical state over one line; the ``GO`` count when the line is a ``GO``."""
        i, size = 0, len(line)
        at_head = self.state in (None, "/*")
        while i < size:
            if self.state == "/*":
                close = line.find("*/", i)
                if close < 0:
                    return None
                self.state, i = None, close + 2
                continue
            if self.state is not None:
                i = self._close_lexeme(line, i)
                continue
            if line[i] in " \t\r":
                i += 1
                continue
            if at_head:
                if line.startswith("/*", i):
                    self._open("/*", line_no, i)
                    i += 2
                    continue
                if line.startswith("--", i):
                    return None
                at_head = False
                count = self._command(line, i)
                if count is not None:
                    return count
            opener = _OPENER.search(line, i)
            stop = opener.start() if opener else size
            self._code(line[i:stop])
            if opener is None or opener.group() == "--":
                return None
            self._open(opener.group(), line_no, stop)
            i = stop + len(opener.group())
        return None

    @staticmethod
    def _command(line: str, i: int) -> Optional[int]:
        """``GO`` alone on its line, a ``--`` comment allowed after it: a batch separator."""
        rest = line[i:]
        word = _WORD.match(rest)
        if word and word.group().upper() == "GO" and _GO_LINE_END.match(rest, word.end()):
            return 1
        return None

    def _open(self, lexeme: str, line_no: int, index: int) -> None:
        self.state, self.opened = lexeme, (line_no, index + 1)
        if lexeme != "/*":
            self.has_code = True

    def _close_lexeme(self, line: str, i: int) -> int:
        """Consume a string or identifier up to its closer (a doubled closer is an escape)."""
        closer = _CLOSER[self.state or ""]
        j = i
        while True:
            j = line.find(closer, j)
            if j < 0:
                return len(line)
            if line.startswith(closer * 2, j):
                j += 2
                continue
            self.state = None
            return j + 1

    def _code(self, segment: str) -> None:
        if segment.strip(" \t\r;"):
            self.has_code = True

    def _cut(self, line_start: int, following: int, count: int, line_no: int) -> None:
        self._flush(line_start, repeat=count, terminated=True)
        self.batch_start, self.batch_line = following, line_no + 1

    def _flush(self, end: int, repeat: int, terminated: bool) -> None:
        raw = self.text[self.batch_start : end]
        if self.has_code:
            lead = raw[: len(raw) - len(raw.lstrip())]
            self.batches.append(
                Batch(raw.strip(), self.batch_line + lead.count("\n"), repeat, terminated)
            )
        self.has_code = False
