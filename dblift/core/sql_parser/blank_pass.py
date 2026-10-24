"""Where an engine's blank-replacing pass leaves the blanks of a script alone."""

from bisect import bisect_right
from typing import Dict, List, Sequence, Tuple

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


def reads_differently_alone(
    source: str, lo: int, hi: int, kept: Sequence[int], rules: SegmentScriptRules
) -> Tuple[int, bool]:
    """The first wide blank of ``source[lo:hi]`` the pass keeps in one reading only.

    The statement is run on its own, so the pass reads its text afresh: an opener in a comment can
    close a stretch of an earlier statement in the script, but not alone. A blank is kept when it
    lies in a kept stretch, and also when it is two bytes wide and ends its text, since the pass
    never reads the last two bytes. Returns ``(offset, kept in the script)``, or ``(-1, False)``.
    """
    assert rules.blank_pass is not None
    text = source[lo:hi]
    wide = [at for at, char in enumerate(text) if char in rules.blanks and char >= "\x80"]
    if not wide:
        return -1, False
    alone = kept_stretches(text, 0, wide[-1], rules.line_comment_ends, rules.blank_pass)
    for at in wide:
        in_script = kept_in_script(source, kept, lo + at)
        in_alone = bisect_right(alone, at) % 2 == 1 or _unread(text, at)
        if in_script != in_alone:
            return lo + at, in_script
    return -1, False


def kept_in_script(source: str, kept: Sequence[int], at: int) -> bool:
    """Whether the pass over the whole script keeps the blank at ``at``."""
    return bisect_right(kept, at) % 2 == 1 or _unread(source, at)


def _unread(text: str, at: int) -> bool:
    """Whether the blank at ``at`` begins one of the last two bytes of ``text``."""
    return at == len(text) - 1 and len(text[at].encode()) == 2


def shell_keeps_blank(source: str, kept: Sequence[int], rules: SegmentScriptRules) -> int:
    """The offset of a blank the shell keeps and the pass over the whole script replaces, or -1.

    The shell drops one final line ending before it parses, so a two-byte blank just before it ends
    the text and is never read; the engine, given the script with its line ending, replaces it.
    """
    end = len(source) - (2 if source.endswith("\r\n") else 1 if source.endswith("\n") else 0)
    at = end - 1
    if rules.blank_pass is None or end == len(source) or at < 0:
        return -1
    if not _two_byte_blank(source[at], rules):
        return -1
    return -1 if kept_in_script(source, kept, at) else at


def stray_final_blank(source: str, rules: SegmentScriptRules) -> int:
    """The offset of a two-byte blank that ends the script, which the pass never reads, or -1."""
    last = len(source) - 1
    if rules.blank_pass is None or last < 0 or not _two_byte_blank(source[last], rules):
        return -1
    return last


def _two_byte_blank(char: str, rules: SegmentScriptRules) -> bool:
    """Whether ``char`` is a blank of the engine of two bytes, which the pass can leave unread."""
    return char in rules.blanks and char >= "\x80" and len(char.encode()) == 2
