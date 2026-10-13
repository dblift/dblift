"""Decide from the first tokens of a statement whether it is a client-buffered unit."""

from typing import Optional, Sequence, Tuple

from dblift.core.sql_parser.lexical_spec import HeadPattern, HeadStep

_FAIL, _PREFIX, _FULL = 0, 1, 2


def _match_alternative(alternative: Tuple[str, ...], words: Sequence[str], at: int) -> int:
    """Match one word sequence at ``at``: _FULL, _PREFIX (words ran out) or _FAIL."""
    for offset, expected in enumerate(alternative):
        if at + offset >= len(words):
            return _PREFIX
        if expected != "*" and words[at + offset] != expected:
            return _FAIL
    return _FULL


def _match_step(step: HeadStep, words: Sequence[str], at: int) -> Tuple[int, int]:
    """Match ``step`` at ``at``; returns the outcome and the position after a full match."""
    if at >= len(words):
        return _PREFIX, at
    first = [
        alternative
        for alternative in step.alternatives
        if alternative[0] == "*" or alternative[0] == words[at]
    ]
    if not first:
        return (_FULL, at) if step.optional else (_FAIL, at)
    outcome = _FAIL
    for alternative in first:
        found = _match_alternative(alternative, words, at)
        if found == _FULL:
            return _FULL, at + len(alternative)
        outcome = max(outcome, found)
    return outcome, at


def _match(pattern: HeadPattern, words: Sequence[str]) -> int:
    at = 0
    for step in pattern:
        outcome, at = _match_step(step, words, at)
        if outcome != _FULL:
            return outcome
    return _FULL


def decide(
    patterns: Tuple[HeadPattern, ...], words: Sequence[str], max_tokens: int
) -> Optional[bool]:
    """Whether ``words`` (upper-cased non-comment token texts) head a unit.

    True when a pattern matched in full; None while at least one pattern is a
    proper prefix of the words; False otherwise, and after ``max_tokens``
    undecided words.
    """
    outcomes = [_match(pattern, words) for pattern in patterns]
    if _FULL in outcomes:
        return True
    if _PREFIX in outcomes and len(words) < max_tokens:
        return None
    return False
