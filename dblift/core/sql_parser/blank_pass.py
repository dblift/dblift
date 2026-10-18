"""Where an engine's blank-replacing pass leaves the blanks of a script alone."""

from bisect import bisect_right
from typing import Dict, List, Sequence

from dblift.core.sql_parser.lexical_spec import BlankPassRules, SegmentScriptRules


def kept_stretches(
    sql: str, begin: int, last: int, line_ends: str, rules: BlankPassRules
) -> List[int]:
    """The stretches ``[start, end)`` where the pass keeps blanks, flat: start, end, start, end...

    Only stretches that start at or before ``last``, the offset of the final blank, are looked for.
    Each search for the next character that matters goes on from where the last one stopped, so
    the cost is linear in the script.
    """
    size = len(sql)
    stretches: List[int] = []
    special = (*rules.quotes, rules.dollar, rules.comment)
    ahead: Dict[str, int] = {}

    def next_at(what: str, pos: int) -> int:
        found = ahead.get(what, -1)
        if found < pos:
            found = sql.find(what, pos)
            ahead[what] = found = size if found < 0 else found
        return found

    pos = begin
    while True:
        pos = min(next_at(what, pos) for what in special)
        if pos > last:
            return stretches
        char = sql[pos]
        if char in rules.quotes:
            end = pos + 1
            while True:
                end = sql.find(char, end)
                if end < 0 or not sql.startswith(char, end + 1):
                    break
                end += 2
            if end < 0:
                stretches += (pos, size)
                return stretches
            stretches += (pos, end + 1)
            pos = end + 1
        elif char == rules.dollar:
            pos = _dollar(sql, pos, rules, stretches)
            if pos < 0:
                return stretches
        elif sql.startswith(rules.comment, pos):
            end = min(next_at(line, pos + len(rules.comment)) for line in line_ends)
            stretches += (pos, end)
            pos = end


def _dollar(sql: str, pos: int, rules: BlankPassRules, stretches: List[int]) -> int:
    """Read the dollar at ``pos``: where to go on, or -1 when an unclosed tag ends the pass."""
    size = len(sql)
    if pos + 1 >= size:
        return size
    after = sql[pos + 1]
    if after != rules.dollar and after < "\x80" and after not in rules.tag_first:
        return pos + 1
    end = pos + 1
    while end < size:
        char = sql[end]
        if char == rules.dollar or not (char >= "\x80" or char in rules.tag_rest):
            break
        end += 1
    if end >= size or sql[end] != rules.dollar:
        stretches += (pos, end)
        return end
    tag = sql[pos : end + 1]
    close = sql.find(tag, end)
    if close < 0:
        stretches += (pos, size)
        return -1
    stretches += (pos, close + len(tag))
    return close + len(tag) - 1


def differs_alone(
    source: str, lo: int, hi: int, kept: Sequence[int], rules: SegmentScriptRules
) -> int:
    """The offset of the first blank of ``source[lo:hi]`` kept in the script, replaced run alone.

    A statement is run on its own, so the pass reads its text afresh: a blank that the pass of the
    whole script kept can be replaced there. The pass never reads the last two bytes of a text, so a
    final two-byte blank is kept alone as well. Returns -1 when there is none.
    """
    first = bisect_right(kept, lo) // 2 * 2
    if first >= len(kept) or kept[first] >= hi:
        return -1
    assert rules.blank_pass is not None
    wide = [blank for blank in rules.blanks if blank >= "\x80"]
    text = source[lo:hi]
    last = max(text.rfind(blank) for blank in wide)
    alone = kept_stretches(text, 0, last, rules.line_comment_ends, rules.blank_pass)
    tail = last if last == len(text) - 1 and len(text[last].encode()) == 2 else -1
    seen = 0
    for index in range(first, len(kept), 2):
        if kept[index] >= hi:
            break
        pos, stop = max(kept[index], lo) - lo, min(kept[index + 1], hi) - lo
        while pos < stop:
            while seen < len(alone) and alone[seen + 1] <= pos:
                seen += 2
            if seen < len(alone) and alone[seen] <= pos:
                pos = alone[seen + 1]
                continue
            end = min(stop, alone[seen]) if seen < len(alone) else stop
            found = [at for at in (text.find(blank, pos, end) for blank in wide) if at >= 0]
            if found and min(found) != tail:
                return lo + min(found)
            pos = end
    return -1


def kept_alone_only(
    source: str, lo: int, hi: int, kept: Sequence[int], rules: SegmentScriptRules
) -> int:
    """The offset of the final two-byte blank of ``source[lo:hi]`` that the script replaces, or -1.

    Run alone, the pass never reads the last two bytes of the text, so that blank is kept; in the
    script it is kept only inside a kept stretch or at the very end of the script.
    """
    if rules.blank_pass is None or hi <= lo or hi >= len(source):
        return -1
    pos = hi - 1
    if source[pos] not in rules.blanks or len(source[pos].encode()) != 2:
        return -1
    return -1 if bisect_right(kept, pos) % 2 else pos
