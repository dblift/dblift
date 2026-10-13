"""Classify a client directive line from the spec's tables.

A client accepts a command abbreviated to its documented minimum, so a typed
word matches a rule when it is a prefix of the rule's word of at least that
length. The commands that carry options (``SET``, ``WHENEVER``) are named
here; every word, minimum and action is table data.
"""

import re
from typing import List, Optional, Tuple

from dblift.core.sql_parser.lexical_spec import ClientScriptRules, DirectiveAction

_SET = ("SET", 3)
_WHENEVER = "WHENEVER"
_WORD = re.compile(r"[A-Za-z]+(?![A-Za-z0-9_$#])")


def _matches(typed: str, full: str, minimum: int) -> bool:
    return len(typed) >= minimum and full.startswith(typed)


def _words(line: str) -> List[str]:
    """Upper-cased leading words of ``line``."""
    out: List[str] = []
    pos = 0
    while True:
        while pos < len(line) and line[pos].isspace():
            pos += 1
        match = _WORD.match(line, pos)
        if not match:
            return out
        out.append(match.group().upper())
        pos = match.end()


def classify_directive(
    rules: ClientScriptRules, line: str
) -> Optional[Tuple[str, DirectiveAction, int]]:
    """The directive ``line`` holds as (name, action, minimum abbreviation), or None for SQL.

    ``line`` starts where a statement can begin. A command followed by one of
    the rules' follow words, and ``SET`` followed by a SQL word, are SQL.
    """
    text = line.strip()
    for prefix, name in rules.prefix_directives:
        if text.startswith(prefix):
            return name, DirectiveAction.REJECT, len(prefix)
    words = _words(text)
    if not words:
        return None
    first = words[0]
    if _matches(first, *_SET):
        return _classify_set(rules, words[1:])
    if _matches(first, _WHENEVER, rules.whenever_min_abbrev):
        for word, action in rules.whenever:
            if len(words) > 1 and words[1] == word:
                return f"{_WHENEVER} {word}", action, rules.whenever_min_abbrev
        return None
    for rule in rules.directives:
        if _matches(first, rule.word, rule.min_abbrev):
            if any(
                rule.word == a and len(words) > 1 and words[1] == b
                for a, b in rules.sql_follow_words
            ):
                return None
            return rule.word, rule.action, rule.min_abbrev
    return None


def _classify_set(
    rules: ClientScriptRules, rest: List[str]
) -> Optional[Tuple[str, DirectiveAction, int]]:
    if not rest or rest[0] in rules.set_sql_words:
        return None
    for rule in rules.set_options:
        if _matches(rest[0], rule.word, rule.min_abbrev):
            return f"{_SET[0]} {rule.word}", rule.action, rule.min_abbrev
    return _SET[0], DirectiveAction.DROP_RECORD, _SET[1]


def is_free_text(rules: ClientScriptRules, name: str) -> bool:
    """Whether the execution view reads the whole line of this directive as text."""
    return any(rule.free_text and rule.word == name for rule in rules.directives)
