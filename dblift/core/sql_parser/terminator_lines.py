"""Classify the lines of a script read by a client that ends a statement at a terminator line."""

import re
from dataclasses import dataclass
from typing import List, Optional, Tuple

from dblift.core.sql_parser.lexical_spec import TerminatorScriptRules


@dataclass(frozen=True)
class Line:
    """One physical line: where it lies, what it is, and where its code ends."""

    number: int
    start: int
    end: int
    text: str
    kind: str
    terminator: str
    body_end: int
    tail_end: int


def read_lines(rules: TerminatorScriptRules, text: str) -> Tuple[List[Line], str, Optional[int]]:
    """The lines, the text with every consumed terminator blanked, and the first malformed directive line.

    A directive line, a comment line, a ``comment_block`` line and a blank line are never cut; any
    other line whose last non-blank characters are the active terminator is. The pass stops at a
    malformed directive: the assembly raises it, in order, when it reaches that line.
    """
    directive = re.compile(rules.directive)
    value = re.compile(rules.directive_value)
    terminator = rules.initial
    lines: List[Line] = []
    kept: List[str] = []  # the masked text: slices of ``text`` between the blanked runs
    copied = 0
    malformed: Optional[int] = None
    pos, size = 0, len(text)
    while pos < size:
        feed = text.find("\n", pos)
        end = size if feed < 0 else feed + 1
        stop = size if feed < 0 else feed
        if feed >= 0 and stop > pos and text[stop - 1] == "\r":
            stop -= 1  # the CR of a CRLF pair is not part of the line
        line = text[pos:stop]
        number = len(lines) + 1
        tail_end = pos + len(line.rstrip(rules.blanks))
        body_end, active = -1, terminator
        stripped = line.strip(rules.blanks)
        found = directive.match(line)
        if found is not None:
            kind = "directive"
            changed = value.match(line, found.end())
            if changed is None:
                malformed = number
            else:
                terminator = changed.group(1)
        elif stripped.startswith(rules.line_comment):
            kind = "comment"
        elif stripped.startswith(rules.comment_block):
            kind = "block"
        elif not stripped:
            kind = "blank"
        else:
            kind = "code"
            cut = tail_end - len(terminator)
            if cut >= pos and text.startswith(terminator, cut):
                body_end = cut
                kept.append(text[copied:body_end])
                kept.append(" " * len(terminator))
                copied = tail_end
        lines.append(Line(number, pos, end, line, kind, active, body_end, tail_end))
        if malformed is not None:
            break
        pos = end
    kept.append(text[copied:])
    return lines, "".join(kept), malformed
