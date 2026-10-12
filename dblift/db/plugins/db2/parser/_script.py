"""Cut a Db2 script into the statements the command line processor (CLP) sends to the server.

docs/sql-parsing/db2.md sections 3 to 5. The CLP reads a script line by line and looks at
nothing else: a statement ends at a line whose last non-blank characters are the active
terminator, whatever the line holds (a string, a comment, a quoted identifier), and a line
that starts with ``--`` is a comment. The scanner reproduces that, with two additions that
protect what runs: the ``BEGIN ... END`` body of a routine is kept whole (the CLP cuts it at
every line that ends in the terminator and the server then runs the pieces as statements),
and a statement with a ``;`` in the middle is refused (the CLP sends it and the server
rejects it, the ``ibm_db`` driver runs the text before the ``;`` and drops the rest).
"""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.statement import StatementKind

DEFAULT_TERMINATOR = ";"

#: A ``--#SET TERMINATOR`` line: upper case, blanks (not tabs) between the words (measured).
_DIRECTIVE = re.compile(r"[ \t]*--#SET +TERMINATOR(?!\w)")
_DIRECTIVE_VALUE = re.compile(r" +(\S{1,2})[ \t]*\Z")
_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_$#@]*")
_LEADING_WORD = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")
#: The whole text of an epilogue command, a comment on its line allowed.
_EPILOGUE = re.compile(
    r"(?:QUIT|TERMINATE|CONNECT[ \t]+RESET)[ \t]*(?:--.*|/\*.*?\*/[ \t]*)?\Z", re.I
)
#: First words of CLP commands that no SQL statement starts with (the CLP's own ``?`` listing).
_COMMAND_WORDS = frozenset(
    "ACTIVATE ADD ARCHIVE ATTACH AUTOCONFIGURE BACKUP BIND CATALOG CHANGE COMPLETE CONNECT "
    "DEACTIVATE DECOMPOSE DEREGISTER DESCRIBE DETACH ECHO EDIT EXPORT FORCE GET HELP HISTORY "
    "IMPORT INITIALIZE INSPECT LIST LOAD PING PRECOMPILE PREP PRUNE PUT QUERY QUIESCE QUIT "
    "REBIND RECOVER REDISTRIBUTE REGISTER REORG REORGCHK RESET RESTART RESTORE REWIND "
    "ROLLFORWARD RUNCMD RUNSTATS START STOP TAKEOVER TERMINATE UNCATALOG UNQUIESCE UPGRADE".split()
)
#: CLP commands whose first word also starts an SQL statement: the next word(s) decide.
#: ``CREATE DATABASE`` and ``DROP DATABASE`` are not here on purpose: the server rejects them
#: with an error, and ``CREATE DATABASE LINK`` is SQL other dialects write.
_COMMAND_PHRASES = frozenset(
    {
        ("DROP", "DBPARTITIONNUM"),
        ("REFRESH", "LDAP"),
        ("SET", "CLIENT"),
        ("SET", "RUNTIME"),
        ("SET", "TABLESPACE"),
        ("SET", "TAPE"),
        ("SET", "UTIL_IMPACT_PRIORITY"),
        ("SET", "WRITE"),
        ("UPDATE", "COMMAND", "OPTIONS"),
        ("UPDATE", "DATABASE", "CONFIGURATION"),
        ("UPDATE", "DATABASE", "MANAGER"),
        ("UPDATE", "DB", "CFG"),
        ("UPDATE", "DB", "CONFIGURATION"),
        ("UPDATE", "DB", "MANAGER"),
        ("UPDATE", "DBM", "CFG"),
        ("UPDATE", "DBM", "CONFIGURATION"),
        ("UPDATE", "ALERT", "CFG"),
        ("UPDATE", "ALERT", "CONFIGURATION"),
        ("UPDATE", "CLI", "CFG"),
        ("UPDATE", "CLI", "CONFIGURATION"),
        ("UPDATE", "HISTORY", "FOR"),
        ("UPDATE", "HISTORY", "EID"),
        ("UPDATE", "LDAP", "NODE"),
        ("UPDATE", "MONITOR", "SWITCHES"),
    }
)

#: Routine kinds whose ``BEGIN ... END`` body the scanner keeps whole.
_BODY_HEADS = frozenset({"PROCEDURE", "FUNCTION", "TRIGGER", "METHOD"})
#: ``END <word>`` pairs with an ``IF`` / ``WHILE`` / ... the scanner does not count.
_END_QUALIFIERS = frozenset({"IF", "WHILE", "FOR", "LOOP", "REPEAT"})


@dataclass(frozen=True)
class Unit:
    """A statement (``kind="sql"``) or a line the scanner consumed (``"directive"``)."""

    text: str
    line: int
    terminator: Optional[str]
    kind: StatementKind = "sql"
    epilogue: bool = False  # CONNECT RESET or TERMINATE: a directive when nothing follows


class _Reader:
    """Reads one statement's text the way the server does and answers three questions.

    ``inside``: is a routine body open? (``BEGIN`` and ``CASE`` against ``END``; ``END IF``,
    ``END WHILE``, ``END FOR``, ``END LOOP`` and ``END REPEAT`` close nothing it counted.)
    ``stray``: does code follow a ``;`` that is outside strings, quoted identifiers, comments
    (which nest, as on the server) and a routine body? ``code``: is there any code at all?
    """

    def __init__(self) -> None:
        self.words: List[str] = []
        self.routine: Optional[bool] = None
        self.package = False
        self.opened = False
        self.depth = 0
        self.parens = 0
        self.pending_end = False
        self.quote: Optional[str] = None
        self.block = 0
        self.code = False
        self.tokens = 0
        self.semicolon = False
        self.semi_at = -1
        self.stray = False

    @property
    def inside(self) -> bool:
        return self.opened and self.depth > 0

    def feed(self, line: str) -> None:
        self.semi_at = -1
        i, size = 0, len(line)
        while i < size:
            if self.block:
                if line.startswith("/*", i):
                    self.block, i = self.block + 1, i + 2
                elif line.startswith("*/", i):
                    self.block, i = self.block - 1, i + 2
                else:
                    i += 1
                continue
            if self.quote:
                j = line.find(self.quote, i)
                if j < 0:
                    return
                if line.startswith(self.quote * 2, j):
                    i = j + 2
                    continue
                self.quote, i = None, j + 1
                continue
            if line.startswith("--", i):
                return
            if line.startswith("/*", i):
                self.block, i = 1, i + 2
                continue
            char = line[i]
            if char in "'\"":
                self._token()
                self.quote, i = char, i + 1
                continue
            word = _WORD.match(line, i)
            if word:
                self._word(word.group().upper())
                i = word.end()
                continue
            if char == ";":
                self.settle()
                if not self.inside:
                    self.semicolon, self.semi_at = True, i
            elif not char.isspace():
                self.settle()
                self._token()
                self.parens += (char == "(") - (char == ")")
            i += 1

    def settle(self) -> None:
        """A token that is not a word settles a pending ``END`` (the terminator is one)."""
        if self.pending_end:
            self.pending_end = False
            self.depth -= 1

    def _token(self) -> None:
        self.code = True
        self.tokens += 1
        if self.semicolon:
            self.stray = True

    def _word(self, word: str) -> None:
        self._token()
        if self.pending_end:
            self.pending_end = False
            if word in _END_QUALIFIERS:
                return
            self.depth -= 1
            if word == "CASE":
                return
        if self.routine is None:
            self._head(word)
        elif self.routine and not self.opened:
            opener = ("AS", "IS") if self.package else ("BEGIN",)
            if word in opener and self.parens == 0:
                self.opened, self.depth = True, 1
        elif self.routine and self.depth > 0:
            if word in ("BEGIN", "CASE"):
                self.depth += 1
            elif word == "END":
                self.pending_end = True

    def _head(self, word: str) -> None:
        self.words.append(word)
        first = self.words[0]
        if first == "BEGIN":
            self.routine, self.opened, self.depth = True, True, 1
        elif first == "CREATE":
            target = 3 if self.words[1:2] == ["OR"] else 1
            if len(self.words) > target:
                self.package = self.words[target] == "PACKAGE"
                self.routine = self.package or self.words[target] in _BODY_HEADS
        elif first == "ALTER":
            if len(self.words) > 1:
                self.routine = self.words[1] == "MODULE"
        else:
            self.routine = False


def scan_script(script: str) -> List[Unit]:
    """The units of ``script``; refuses what the CLP would run differently, skip or reject."""
    return _Scanner(script[1:] if script.startswith("\ufeff") else script).run()


class _Scanner:
    def __init__(self, text: str) -> None:
        self.pieces = text.split("\n")
        self.final_newline = self.pieces[-1] == ""
        if self.final_newline:
            self.pieces.pop()
        self.terminator = DEFAULT_TERMINATOR
        self.units: List[Unit] = []
        self.buf: List[str] = []
        self.start = 0
        self.reader = _Reader()
        self.block_line = 0
        self.block_code = False
        self.last_code = 0
        self.stray_line = 0

    def run(self) -> List[Unit]:
        last = len(self.pieces)
        for number, piece in enumerate(self.pieces, start=1):
            # A CR is a line end only before a LF; a lone CR is text (measured).
            line = (
                piece[:-1]
                if piece.endswith("\r") and (number < last or self.final_newline)
                else piece
            )
            self._line(piece, line, number)
        if self.buf:
            self.reader.settle()
            if self.reader.block:
                raise UnsafeStatementSplitError(
                    f"the block comment opened on line {self.block_line} is not closed before "
                    "the end of the script: the statements inside it would be dropped"
                )
            if self.reader.inside:
                raise UnsafeStatementSplitError(
                    f"the routine body starting on line {self.start} is not closed "
                    "before the end of the script"
                )
            self._end(None, self.buf[: self.last_code])
        return self._epilogue()

    def _feed(self, text: str, number: int) -> None:
        """Feed a line to the reader, remembering where a block comment opened and a ';' strayed."""
        reader = self.reader
        was_block, was_stray, tokens, quote = (
            reader.block,
            reader.stray,
            reader.tokens,
            reader.quote,
        )
        reader.feed(text)
        if reader.tokens > tokens or quote or reader.quote or (was_block and self.block_code):
            self.last_code = len(self.buf)  # the line is code, not a comment after the code
        if not was_block and reader.block:
            self.block_code = reader.tokens > tokens
        elif not reader.block:
            self.block_code = False
        if reader.block and not was_block:
            self.block_line = number
        if reader.stray and not was_stray:
            self.stray_line = number

    def _line(self, raw: str, line: str, number: int) -> None:
        keyword = _DIRECTIVE.match(line)
        if keyword:
            if self.buf and (self.reader.quote or self.reader.block):
                raise UnsafeStatementSplitError(
                    f"--#SET TERMINATOR on line {number} stands inside a string, "
                    "a quoted identifier or a comment: the CLP honours it there and cuts "
                    "the statement; close it first"
                )
            self._directive(line, keyword, number)
            return
        stripped = line.strip(" \t")
        if stripped.startswith("--"):
            if self.buf:
                self.buf.append(raw)
                self._feed(line, number)
            return
        if stripped.startswith("(="):
            raise UnsupportedMetaCommandError(
                f"CLP comment block '(=' on line {number}: the CLP skips it, "
                "dblift does not run CLP input syntax"
            )
        if not self.buf:
            if not stripped:
                return
            self.start, self.reader = number, _Reader()
            self.stray_line = 0
            self.last_code = 0
        self.buf.append(raw)
        tail = line.rstrip(" \t")
        reader = self.reader
        if not tail.endswith(self.terminator):
            self._feed(line, number)
            if self._ends_before_a_comment(line):
                self._end(self.terminator, self.buf[:-1] + [line[: reader.semi_at]])
            return
        whole = copy.copy(reader)
        whole.words = list(reader.words)
        whole.feed(tail)
        body = tail[: -len(self.terminator)]
        self._feed(body, number)
        if bool(whole.block) != bool(reader.block):
            raise UnsafeStatementSplitError(
                f"line {number} ends with {self.terminator!r}, which is also part of a "
                "comment delimiter: the CLP cuts the statement there, the splitter cannot tell "
                "the two readings apart; put the comment on a line of its own"
            )
        reader.settle()
        if reader.quote:
            raise UnsafeStatementSplitError(
                f"line {number} ends with {self.terminator!r} inside a string "
                "or a quoted identifier: "
                "the CLP cuts the statement there and the server rejects both halves; "
                "close the literal before the end of the line"
            )
        if reader.inside or reader.block:
            # A body is kept whole; a comment runs to its close, whatever its lines end with.
            return
        self._end(self.terminator, self.buf[:-1] + [body])

    def _ends_before_a_comment(self, line: str) -> bool:
        """A ';' followed only by comments on its line ends the statement there (``stmt; -- c``)."""
        reader = self.reader
        return (
            self.terminator == DEFAULT_TERMINATOR
            and reader.semi_at >= 0
            and not (reader.stray or reader.inside or reader.quote or reader.block)
            and line[reader.semi_at + 1 :].lstrip(" \t").startswith(("--", "/*"))
        )

    def _directive(self, line: str, keyword: "re.Match[str]", number: int) -> None:
        value = _DIRECTIVE_VALUE.match(line, keyword.end())
        if value is None:
            raise UnsafeStatementSplitError(
                f"malformed --#SET TERMINATOR directive on line {number}: expected one or two "
                "characters after the keyword, separated from it by blanks"
            )
        self.terminator = value.group(1)
        self.units.append(Unit(line.strip(), number, None, "directive"))

    def _command(self, stripped: str, number: int) -> bool:
        """True for the commands a CLP script may end with; refuses every other CLP command.

        The CLP joins the lines of a statement, so the head is read from the whole text.
        """
        if stripped[0] in "!?":
            raise UnsupportedMetaCommandError(
                f"CLP command {stripped[0]!r} on line {number}: dblift does not run client commands"
            )
        words = self._leading_words(stripped)
        if not words:
            return False
        if words[0] in ("TERMINATE", "QUIT") or words[:2] == ("CONNECT", "RESET"):
            if not _EPILOGUE.match(stripped):
                raise UnsafeStatementSplitError(
                    f"{words[0]} on line {number} is not alone on its line: the CLP joins it "
                    "with what follows and the server rejects the text; end it with the "
                    "terminator"
                )
            return True
        if words[:2] == ("GET", "DIAGNOSTICS"):
            return False
        if words[0] in _COMMAND_WORDS or words[:2] in _COMMAND_PHRASES or words in _COMMAND_PHRASES:
            raise UnsupportedMetaCommandError(
                f"CLP command {words[0]} on line {number}: dblift does not run client commands"
            )
        return False

    @staticmethod
    def _leading_words(stripped: str) -> Tuple[str, ...]:
        words = []
        for token in stripped.split()[:3]:
            match = _LEADING_WORD.match(token)
            if match is None:
                break
            words.append(match.group().upper())
            if match.end() < len(token):
                break
        return tuple(words)

    def _end(self, terminator: Optional[str], lines: List[str]) -> None:
        text = "\n".join(lines).strip()
        start, reader, stray_line = self.start, self.reader, self.stray_line
        for piece in lines:  # the statement starts on the first line with anything on it
            if piece.strip():
                break
            start += 1
        self.buf, self.reader = [], _Reader()
        if not text or not reader.code:
            return
        epilogue = self._command(text, start)
        if reader.stray:
            raise UnsafeStatementSplitError(
                f"line {stray_line} has code after a ';' in the middle of a line: "
                "the CLP sends it whole and the server rejects it, and the ibm_db driver "
                "runs only the text before the ';'; put each statement on its own line, ended by "
                "the terminator, or declare another terminator with --#SET TERMINATOR"
            )
        self.units.append(Unit(text, start, terminator, "sql", epilogue))

    def _epilogue(self) -> List[Unit]:
        """``CONNECT RESET``, ``TERMINATE``, ``QUIT``: recorded and dropped when last."""
        last_sql = max(
            (i for i, u in enumerate(self.units) if u.kind == "sql" and not u.epilogue), default=-1
        )
        out: List[Unit] = []
        for index, unit in enumerate(self.units):
            if unit.epilogue:
                if index < last_sql:
                    raise UnsupportedMetaCommandError(
                        f"CLP command {unit.text.split(None, 1)[0].upper()} on line {unit.line}: "
                        "dblift does not run client commands"
                    )
                unit = Unit(unit.text, unit.line, unit.terminator, "directive", True)
            out.append(unit)
        return out
