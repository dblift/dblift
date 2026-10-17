"""Classify the lines of a script read by a client that ends a statement at a terminator line."""

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
    """The lines, the text with every consumed terminator blanked, and the first malformed directive line."""
    return [], text, None
