"""Where an engine's blank-replacing pass leaves the blanks of a script alone."""

from typing import Dict, List

from dblift.core.sql_parser.lexical_spec import BlankPassRules


def kept_stretches(
    sql: str, begin: int, last: int, line_ends: str, rules: BlankPassRules
) -> List[int]:
    """The stretches ``[start, end)`` in which the pass keeps blanks, flat: start, end, start, end...

    Only stretches that start at or before ``last``, the offset of the final blank, are looked for.
    Each search for the next character that matters goes on from where the last one stopped, so the
    cost is linear in the script.
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
    """Read the dollar at ``pos``: where to go on, or -1 when a tag that is never closed ends the pass."""
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
