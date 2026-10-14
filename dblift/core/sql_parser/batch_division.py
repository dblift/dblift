"""Where the code of a batch is: the runs of a script outside its lexemes and comments."""

import re
from bisect import bisect_left
from typing import List, Sequence, Tuple

from dblift.core.sql_parser.lexical_spec import BatchScriptRules


def code_spans(
    source: str, start: int, end: int, extents: Sequence[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Maximal runs of ``source[start:end]`` outside the sorted ``extents``, in order."""
    spans: List[Tuple[int, int]] = []
    cursor = start
    for lo, hi in extents:
        if hi <= cursor:
            continue
        if lo >= end:
            break
        if lo > cursor:
            spans.append((cursor, lo))
        cursor = max(cursor, hi)
    if cursor < end:
        spans.append((cursor, end))
    return spans


def code_positions(
    rules: BatchScriptRules,
    source: str,
    spans: Sequence[Tuple[int, int]],
    lexeme_starts: Sequence[int],
) -> List[int]:
    """Sorted starts of the runs of code characters in ``spans``, and every lexeme start.

    A code character is none of the blanks, the ignored characters and the line break.
    """
    code_run = re.compile(f"[^{re.escape(rules.blanks + rules.ignored_in_code)}\\n]+")
    positions: List[int] = list(lexeme_starts)
    for lo, hi in spans:
        positions.extend(match.start() for match in code_run.finditer(source, lo, hi))
    positions.sort()
    return positions


def has_code(positions: Sequence[int], first: int, last: int) -> bool:
    """Whether a code position lies in ``[first, last]``."""
    index = bisect_left(positions, first)
    return index < len(positions) and positions[index] <= last
