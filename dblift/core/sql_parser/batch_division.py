"""Where the code of a batch is: the runs of a script outside its lexemes and comments."""

import re
from bisect import bisect_left
from typing import List, Sequence, Tuple

from dblift.core.sql_parser.batch_cache import RulesCache
from dblift.core.sql_parser.lexical_spec import BatchScriptRules
from dblift.core.sql_parser.unit_heads import decide


def code_spans(
    source: str, start: int, end: int, extents: Sequence[Tuple[int, int]]
) -> List[Tuple[int, int]]:
    """Maximal runs of ``source[start:end]`` outside the sorted ``extents``, in order."""
    spans: List[Tuple[int, int]] = []
    cursor = start
    for lo, hi in extents:
        if lo > cursor:
            spans.append((cursor, lo))
        cursor = hi
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


_WORDS: RulesCache["re.Pattern[str]"] = RulesCache(
    lambda rules: re.compile(f"[{rules.word_start}][{rules.word_part}]*|;")
)
#: Division reads ``str.strip()`` whitespace before a head word, as the previous heuristic did, not ``blanks``.
_NOT_BLANK = re.compile(r"\S")


def _events(
    rules: BatchScriptRules,
    source: str,
    start: int,
    end: int,
    spans: Sequence[Tuple[int, int]],
) -> List[Tuple[int, str, int]]:
    """``(offset, upper-cased word or ';', start of its physical line)`` for the code of a batch."""
    pattern = _WORDS.get(rules)
    events: List[Tuple[int, str, int]] = []
    line_start = cursor = start
    for lo, hi in spans[max(bisect_left(spans, (start,)) - 1, 0) :]:
        if lo >= end:
            break
        lo, hi = max(lo, start), min(hi, end)
        if lo >= hi:
            continue
        for match in pattern.finditer(source, lo, hi):
            offset = match.start()
            while cursor < offset:
                newline = source.find("\n", cursor, offset)
                if newline < 0:
                    cursor = offset
                    break
                line_start = cursor = newline + 1
            events.append((offset, match.group().upper(), line_start))
    return events


def divide(
    rules: BatchScriptRules,
    source: str,
    batch_start: int,
    batch_end: int,
    spans: Sequence[Tuple[int, int]],
    positions: Sequence[int],
) -> Tuple[str, ...]:
    """The analysis constituents of one batch; ``rules.division`` holds the data.

    ``batch_end`` is the cut: the start of the separator line, or the end of the script.
    """
    division = rules.division
    events = _events(rules, source, batch_start, batch_end, spans)
    words = [word for _, word, _ in events if word != ";"]
    if decide(division.routine_heads, words[:4], 4):
        return (source[batch_start:batch_end].strip(),)
    exemptions = dict(division.clause_exemptions)
    parts: List[str] = []
    start = batch_start
    depth = case_depth = 0
    part_head: List[str] = []
    first_blank = (-1, -1)  # (line start, offset of its first non-blank character)
    for index, (offset, word, line_start) in enumerate(events):
        following = events[index + 1][1] if index + 1 < len(events) else ""
        if word == division.block_open:
            if following not in division.block_open_exempt:
                depth += 1
        elif word == division.case_word:
            case_depth += 1
        elif word == division.block_close:
            if case_depth:
                case_depth -= 1
            elif depth:
                depth -= 1
        elif word == ";" and depth == 0:
            if has_code(positions, start, offset):
                parts.append(source[start : offset + 1].strip())
            start = offset + 1
            part_head = []
        elif word in division.split_heads and depth == 0:
            clause = exemptions.get((part_head[0], part_head[1]), ()) if len(part_head) == 2 else ()
            if (
                (word, following) not in clause
                and line_start > batch_start
                and has_code(positions, start, offset - 1)
            ):
                if first_blank[0] != line_start:
                    found = _NOT_BLANK.search(source, line_start)
                    first_blank = (line_start, len(source) if found is None else found.start())
                if first_blank[1] >= offset:
                    parts.append(source[start:offset].strip())
                    start = offset
                    part_head = []
        if word != ";" and len(part_head) < 2:
            part_head.append(word)
    if has_code(positions, start, batch_end - 1):
        parts.append(source[start:batch_end].strip())
    return tuple(parts)
