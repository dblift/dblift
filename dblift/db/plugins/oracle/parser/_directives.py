"""SQL*Plus client directives and what the splitter does with each.

docs/sql-parsing/oracle.md section 6. ``classify_directive`` answers one
question about a line that begins where a statement can begin: is it a client
directive, and which action does the splitter take.

SQL*Plus accepts a command abbreviated to its documented minimum
(``SET SERVEROUT``, ``SET FEED``), so each word below carries that minimum and
a typed word matches when it is a prefix of the full word of at least that
length.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from enum import Enum
from typing import Optional, Tuple

__all__ = ["Directive", "DirectiveAction", "classify_directive"]


class DirectiveAction(Enum):
    """What the splitter does with a directive."""

    DROP_RECORD = "drop_record"
    RECORD_POLICY = "record_policy"
    DEFINE = "define"
    EXEC = "exec"
    EXIT = "exit"
    REJECT = "reject"


@dataclass(frozen=True)
class Directive:
    """A recognised directive: its canonical name, action and minimum abbreviation."""

    name: str
    action: DirectiveAction
    min_abbrev: int


_DROP = DirectiveAction.DROP_RECORD
_POLICY = DirectiveAction.RECORD_POLICY
_DEFINE = DirectiveAction.DEFINE
_EXEC = DirectiveAction.EXEC
_EXIT = DirectiveAction.EXIT
_REJECT = DirectiveAction.REJECT

# (full word, minimum abbreviation, action) for directives named by one word.
_COMMANDS: Tuple[Tuple[str, int, DirectiveAction], ...] = (
    ("SHOW", 3, _DROP),
    ("SPOOL", 3, _DROP),
    ("PROMPT", 3, _DROP),
    ("REMARK", 3, _DROP),
    ("COLUMN", 3, _DROP),
    ("TTITLE", 3, _DROP),
    ("BTITLE", 3, _DROP),
    ("REPHEADER", 4, _DROP),
    ("REPFOOTER", 4, _DROP),
    ("BREAK", 3, _DROP),
    ("COMPUTE", 4, _DROP),
    ("CLEAR", 2, _DROP),
    ("TIMING", 4, _DROP),
    ("VARIABLE", 3, _DROP),
    ("PRINT", 3, _DROP),
    ("DESCRIBE", 4, _DROP),
    ("DEFINE", 3, _DEFINE),
    ("UNDEFINE", 5, _DEFINE),
    ("EXECUTE", 4, _EXEC),
    ("EXIT", 4, _EXIT),
    ("QUIT", 4, _EXIT),
    ("START", 3, _REJECT),
    ("HOST", 2, _REJECT),
    ("ACCEPT", 3, _REJECT),
    ("PAUSE", 3, _REJECT),
    ("CONNECT", 4, _REJECT),
    ("DISCONNECT", 4, _REJECT),
    ("PASSWORD", 5, _REJECT),
)

# SET options the splitter does not drop.
_SET_OPTIONS: Tuple[Tuple[str, int, DirectiveAction], ...] = (
    ("SERVEROUTPUT", 9, _POLICY),
    ("DEFINE", 3, _DEFINE),
    ("SQLTERMINATOR", 4, _REJECT),
    ("BLOCKTERMINATOR", 3, _REJECT),
    ("SQLBLANKLINES", 4, _REJECT),
    ("SQLPREFIX", 6, _REJECT),
    ("CMDSEP", 4, _REJECT),
)

# ``SET <word>`` that is SQL, not a client command.
_SET_SQL = frozenset({"ROLE", "TRANSACTION", "CONSTRAINT", "CONSTRAINTS"})

_WORD = re.compile(r"[A-Za-z]+(?![A-Za-z0-9_$#])")


def _matches(typed: str, full: str, minimum: int) -> bool:
    return len(typed) >= minimum and full.startswith(typed)


def _words(line: str) -> list[str]:
    """Upper-cased leading words of ``line`` (``;`` ends the scan)."""
    out: list[str] = []
    pos = 0
    while True:
        while pos < len(line) and line[pos].isspace():
            pos += 1
        m = _WORD.match(line, pos)
        if not m:
            return out
        out.append(m.group().upper())
        pos = m.end()


def classify_directive(line: str) -> Optional[Directive]:
    """The directive ``line`` holds, or ``None`` when it is SQL.

    ``line`` starts where a statement can begin. ``CONNECT TO`` and
    ``SET ROLE|TRANSACTION|CONSTRAINT[S]`` are SQL.
    """
    text = line.strip()
    if text.startswith("@@"):
        return Directive("@@", _REJECT, 2)
    if text.startswith("@"):
        return Directive("@", _REJECT, 1)
    if text.startswith("!"):
        return Directive("!", _REJECT, 1)

    words = _words(text)
    if not words:
        return None
    first = words[0]

    if _matches(first, "SET", 3):
        return _classify_set(words[1:])
    if _matches(first, "WHENEVER", 8):
        if len(words) > 1 and words[1] == "SQLERROR":
            return Directive("WHENEVER SQLERROR", _POLICY, 8)
        if len(words) > 1 and words[1] == "OSERROR":
            return Directive("WHENEVER OSERROR", _DROP, 8)
        return None
    for full, minimum, action in _COMMANDS:
        if _matches(first, full, minimum):
            if full == "CONNECT" and len(words) > 1 and words[1] == "TO":
                return None
            return Directive(full, action, minimum)
    return None


def _classify_set(rest: list[str]) -> Optional[Directive]:
    if not rest or rest[0] in _SET_SQL:
        return None
    for full, minimum, action in _SET_OPTIONS:
        if _matches(rest[0], full, minimum):
            return Directive(f"SET {full}", action, minimum)
    return Directive("SET", _DROP, 3)
