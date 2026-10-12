"""Cut a T-SQL script into the batches ``sqlcmd`` sends to the server.

docs/sql-parsing/sqlserver.md sections 3, 4 and 6. A batch ends at a ``GO`` line and
nothing else: ``;`` never ends one and no ``BEGIN``/``END`` is counted. The scanner
reproduces the *client's* lexer, which is simpler than the server's: a block comment
ends at the first ``*/`` (the server nests them; its text is passed through verbatim),
and a command word that is the first token of a line is a client command or a client
error, never SQL.
"""

from __future__ import annotations

import re
from bisect import bisect_left
from dataclasses import dataclass, field
from typing import List, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError

#: ``GO n`` hands the batch to the server n times; a count above this is refused
#: (``split_statements`` returns one string per repetition).
MAX_GO_COUNT = 1_000_000

#: What may follow a command word for sqlcmd to take the line as a command (measured): a blank, the
#: end of the line, ``-``, ``=``, ``(``, ``[``, ``'`` or ``/``. After ``.``, ``,``, ``;``, ``+``,
#: ``)``, ``*``, ``:``, ``|``, ``<`` or a letter it sends the line to the server as text
#: (``go.id``, ``quit;``).
_COMMAND_FOLLOWERS = frozenset(" \t\r-=(['/")

#: Blanks sqlcmd was not measured on: it may or may not take ``GO`` followed by one as a command.
_UNMEASURED_BLANKS = frozenset("\x0b\x0c")
_LONE_CR_GO = re.compile(r"\r(?!\Z)[ \t]*GO(?![A-Za-z0-9_@#$])", re.IGNORECASE)

_COLON_COMMAND = re.compile(
    r":(?:!!|(?:setvar|r|connect|on|exit|quit|list|listvar|error|out|perftrace|help|serverlist"
    r"|xml|reset|ed)(?![A-Za-z0-9_@#$]))",
    re.IGNORECASE,
)
_WORD = re.compile(r"[A-Za-z_@#$][A-Za-z0-9_@#$]*")
_GO_TAIL = re.compile(r"[ \t\r]*(?:([0-9]+)[ \t\r]*)?(?:--.*)?\Z", re.DOTALL)
#: Every ``$(`` outside a comment: sqlcmd reads it as a variable reference or fails on it.
_VARIABLE_REFERENCE = re.compile(r"\$\([^)\r\n]{0,40}\)?")
_OPENER = re.compile(r"'|\[|\"|/\*|--")
_CLOSER = {"'": "'", "[": "]", '"': '"'}
_LEXEME = {
    "'": "string literal",
    "[": "bracketed identifier",
    '"': "quoted identifier",
    "/*": "block comment",
}
#: osql-compatible commands that need no colon.
_BARE_COMMANDS = frozenset({"EXIT", "QUIT", "RESET", "ED"})


@dataclass(frozen=True)
class Batch:
    """One batch: its verbatim text, first line, how often to send it, and whether a GO ended it."""

    text: str
    line: int
    repeat: int = 1
    terminated: bool = False
    analysis_statements: Tuple[str, ...] = field(default=(), compare=False)
    source_start: int = field(default=0, compare=False)
    source_end: int = field(default=0, compare=False)


def scan_batches(script: str) -> List[Batch]:
    """The batches of ``script``; refuses what ``sqlcmd`` would reject or silently act on."""
    offset = int(script.startswith("\ufeff"))
    return _Scanner(script[offset:], offset=offset).run()


class _Scanner:
    def __init__(self, text: str, *, offset: int = 0) -> None:
        self.text = text
        self.offset = offset
        self.batches: List[Batch] = []
        self.state: Optional[str] = None  # an open lexeme: ', [, ", /*
        self.opened: Tuple[int, int] = (0, 0)
        self.batch_start = 0
        self.batch_line = 1
        self.has_code = False
        # SQL words and semicolons are collected while the batch lexer is already
        # in code. Analysis boundaries never need to lex the batch a second time.
        self.events: List[Tuple[int, str]] = []
        self.code_positions: List[int] = []

    def run(self) -> List[Batch]:
        text, pos, line_no = self.text, 0, 0
        while pos < len(text):
            newline = text.find("\n", pos)
            end = len(text) if newline == -1 else newline
            following = len(text) if newline == -1 else newline + 1
            line_no += 1
            count = self._scan_line(text[pos:end], line_no, pos)
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

    def _scan_line(self, line: str, line_no: int, line_start: int) -> Optional[int]:
        """Advance the lexical state over one line; the ``GO`` count when the line is a ``GO``."""
        i, size = 0, len(line)
        at_head = self.state in (None, "/*")
        commented = False
        while i < size:
            if self.state == "/*":
                close = line.find("*/", i)
                if close < 0:
                    return None
                self.state, i, commented = None, close + 2, True
                continue
            if self.state is not None:
                i = self._close_lexeme(line, i, line_no)
                continue
            if line[i] in " \t\r":
                if line[i] == "\r" and _LONE_CR_GO.match(line, i):
                    raise UnsafeStatementSplitError(
                        f"text after GO on line {line_no}: a lone carriage return is not a line "
                        "break sqlcmd was measured on; end the line with a newline"
                    )
                i += 1
                continue
            if at_head:
                if line.startswith("/*", i):
                    self._open("/*", line_no, i, line_start)
                    i += 2
                    continue
                if line.startswith("--", i):
                    return None
                at_head = False
                count = self._command(line, i, line_no, commented)
                if count is not None:
                    return count
            opener = _OPENER.search(line, i)
            stop = opener.start() if opener else size
            self._code(line[i:stop], line_no, line_start + i)
            if opener is None or opener.group() == "--":
                return None
            self._open(opener.group(), line_no, stop, line_start)
            i = stop + len(opener.group())
        return None

    @staticmethod
    def _command(line: str, i: int, line_no: int, commented: bool) -> Optional[int]:
        """A client command at the first token of a line: the ``GO`` count, or a refusal."""
        rest = line[i:]
        if rest.startswith("!!") or _COLON_COMMAND.match(rest):
            name = rest.split(None, 1)[0]
            raise UnsupportedMetaCommandError(
                f"sqlcmd command {name!r} on line {line_no}: dblift does not run client commands"
            )
        word = _WORD.match(rest)
        if word is None or word.group().upper() not in _BARE_COMMANDS | {"GO"}:
            return None
        name = word.group().upper()
        follower = rest[word.end() : word.end() + 1]
        if name == "GO" and follower in _UNMEASURED_BLANKS:
            raise UnsafeStatementSplitError(
                f"text after GO on line {line_no}: only a count and a '--' comment may follow it"
            )
        if follower and follower not in _COMMAND_FOLLOWERS and (name, follower) != ("GO", ";"):
            return None
        if name != "GO":
            raise UnsupportedMetaCommandError(
                f"sqlcmd command {name!r} on line {line_no}: dblift does not run client commands"
            )
        tail = _GO_TAIL.match(rest, word.end())
        if tail is None:
            variable = _VARIABLE_REFERENCE.search(rest, word.end())
            hint = f"; {variable.group()} is not substituted" if variable else ""
            raise UnsafeStatementSplitError(
                f"text after GO on line {line_no}: only a count and a '--' comment may follow it"
                f"{hint}"
            )
        if commented:
            raise UnsafeStatementSplitError(
                f"GO after a comment on line {line_no}: sqlcmd takes it as a command after one "
                "comment and as text after two; put it first on its line"
            )
        glued = rest.startswith("--", word.end()) or (
            tail.group(1) is not None and rest.startswith("--", tail.end(1))
        )
        if glued:
            raise UnsafeStatementSplitError(
                f"GO on line {line_no}: GO must be followed by a blank, a count or end of line; "
                "'--' directly after GO is read differently by sqlcmd clients"
            )
        digits = (tail.group(1) or "").lstrip("0")
        if len(digits) > len(str(MAX_GO_COUNT)):
            raise UnsafeStatementSplitError(
                f"GO count on line {line_no} exceeds the limit of {MAX_GO_COUNT}"
            )
        count = int(digits) if digits else (0 if tail.group(1) else 1)
        if count > MAX_GO_COUNT:
            raise UnsafeStatementSplitError(
                f"GO {count} on line {line_no} exceeds the limit of {MAX_GO_COUNT}"
            )
        return count

    def _open(self, lexeme: str, line_no: int, index: int, line_start: int) -> None:
        self.state, self.opened = lexeme, (line_no, index + 1)
        if lexeme != "/*":
            self.has_code = True
            self.code_positions.append(line_start + index)

    def _close_lexeme(self, line: str, i: int, line_no: int) -> int:
        """Consume a string or identifier up to its closer (a doubled closer is an escape)."""
        closer = _CLOSER[self.state or ""]
        j = i
        while True:
            j = line.find(closer, j)
            if j < 0:
                self._variables(line[i:], line_no)
                return len(line)
            if line.startswith(closer * 2, j):
                j += 2
                continue
            self._variables(line[i:j], line_no)
            self.state = None
            return j + 1

    def _code(self, segment: str, line_no: int, start: int) -> None:
        if _LONE_CR_GO.search(segment):
            raise UnsafeStatementSplitError(
                f"text after GO on line {line_no}: a lone carriage return is not a line "
                "break sqlcmd was measured on; end the line with a newline"
            )
        if segment.strip(" \t\r;"):
            self.has_code = True
            self.code_positions.extend(
                start + match.start() for match in re.finditer(r"[^ \t\r;]+", segment)
            )
        for match in re.finditer(r"[A-Za-z_@#$][A-Za-z0-9_@#$]*|;", segment):
            self.events.append((start + match.start(), match.group().upper()))
        self._variables(segment, line_no)

    @staticmethod
    def _variables(segment: str, line_no: int) -> None:
        reference = _VARIABLE_REFERENCE.search(segment)
        if reference:
            raise UnsupportedMetaCommandError(
                f"scripting variable {reference.group()} on line {line_no}: sqlcmd substitutes it "
                "before the batch is sent, dblift sends the text as it is"
            )

    def _cut(self, line_start: int, following: int, count: int, line_no: int) -> None:
        self._flush(line_start, repeat=count, terminated=True, source_end=following)
        self.batch_start, self.batch_line = following, line_no + 1

    def _flush(
        self, end: int, repeat: int, terminated: bool, source_end: Optional[int] = None
    ) -> None:
        raw = self.text[self.batch_start : end]
        if self.has_code:
            lead = raw[: len(raw) - len(raw.lstrip())]
            self.batches.append(
                Batch(
                    raw.strip(),
                    self.batch_line + lead.count("\n"),
                    repeat,
                    terminated,
                    self._analysis_parts(end),
                    self.offset + self.batch_start,
                    self.offset + (source_end if source_end is not None else end),
                )
            )
        self.has_code = False
        self.events.clear()
        self.code_positions.clear()

    def _analysis_parts(self, end: int) -> Tuple[str, ...]:
        """Project top-level SQL statements from code tokens seen by this batch scan."""
        words = [word for _, word in self.events if word != ";"]
        head = words[:4]
        if head[:2] in (
            ["CREATE", "PROCEDURE"],
            ["CREATE", "PROC"],
            ["ALTER", "PROCEDURE"],
            ["ALTER", "PROC"],
            ["CREATE", "TRIGGER"],
            ["ALTER", "TRIGGER"],
            ["CREATE", "FUNCTION"],
            ["ALTER", "FUNCTION"],
        ) or (
            head[:3] in (["CREATE", "OR", "ALTER"], ["CREATE", "OR", "REPLACE"])
            and len(head) > 3
            and head[3] in {"PROCEDURE", "PROC", "TRIGGER", "FUNCTION"}
        ):
            return (self.text[self.batch_start : end].strip(),)

        parts: List[str] = []
        start = self.batch_start
        depth = 0
        case_depth = 0
        part_head: List[str] = []

        def has_code(first: int, last: int) -> bool:
            index = bisect_left(self.code_positions, first)
            return index < len(self.code_positions) and self.code_positions[index] <= last

        for index, (position, word) in enumerate(self.events):
            if word == "BEGIN":
                next_word = self.events[index + 1][1] if index + 1 < len(self.events) else ""
                if next_word not in {
                    "TRAN",
                    "TRANSACTION",
                    "DISTRIBUTED",
                    "CONVERSATION",
                    "DIALOG",
                }:
                    depth += 1
            elif word == "CASE":
                case_depth += 1
            elif word == "END":
                if case_depth:
                    case_depth -= 1
                elif depth:
                    depth -= 1
            elif word == ";" and depth == 0:
                if has_code(start, position):
                    parts.append(self.text[start : position + 1].strip())
                start = position + 1
                part_head = []
            elif word in {"CREATE", "ALTER", "DROP", "TRUNCATE"} and depth == 0:
                line_start = self.text.rfind("\n", self.batch_start, position) + 1
                alter_clause = part_head[:2] == ["ALTER", "TABLE"] and word in {"ALTER", "DROP"}
                if (
                    not alter_clause
                    and line_start > self.batch_start
                    and not self.text[line_start:position].strip()
                    and has_code(start, position - 1)
                ):
                    parts.append(self.text[start:position].strip())
                    start = position
                    part_head = []
            if word != ";" and len(part_head) < 2:
                part_head.append(word)
        if has_code(start, end - 1):
            parts.append(self.text[start:end].strip())
        return tuple(parts)
