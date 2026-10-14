"""Classification of a client script line: a batch separator, or SQL text."""

import re
from functools import lru_cache
from typing import Optional, Pattern, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_spec import BatchScriptRules


@lru_cache(maxsize=None)
def _patterns(rules: BatchScriptRules) -> Tuple[Pattern[str], Pattern[str]]:
    blanks = re.escape(rules.blanks)
    word = re.compile(f"[{rules.word_start}][{rules.word_part}]*")
    tail = re.compile(
        f"[{blanks}]*(?:([0-9]+)[{blanks}]*)?(?:{re.escape(rules.tail_comment)}.*)?\\Z"
    )
    return word, tail


def read_command(
    rules: BatchScriptRules,
    client_name: str,
    source: str,
    pos: int,
    line: int,
    commented: bool,
) -> Optional[int]:
    """The repeat count when the line whose head token starts at ``pos`` is a separator.

    ``line`` is the tokenizer's own line counter; ``commented`` says a comment ended before
    the head on its line. ``None`` means the line is SQL text. A malformed separator raises
    ``UnsafeStatementSplitError``. Only the line is matched, never the rest of the script.
    """
    word_re, tail_re = _patterns(rules)
    newline = source.find("\n", pos)
    eol = len(source) if newline < 0 else newline
    word = word_re.match(source, pos, eol)
    if word is None or word.group().upper() != rules.separator.upper():
        return None
    follower = source[word.end() : word.end() + 1] if word.end() < eol else ""
    if (
        follower
        and follower not in rules.command_followers
        and follower not in rules.separator_followers
    ):
        return None
    sep, tail_comment = rules.separator, rules.tail_comment
    tail = tail_re.match(source, word.end(), eol)
    if tail is None:
        raise UnsafeStatementSplitError(
            f"text after {sep} on line {line}: only a count and a '{tail_comment}' comment "
            "may follow it"
        )
    if commented:
        raise UnsafeStatementSplitError(
            f"{sep} after a comment on line {line}: {client_name} takes it as a command after "
            "one comment and as text after two; put it first on its line"
        )
    count_text = tail.group(1)
    if source.startswith(tail_comment, word.end()) or (
        count_text is not None and source.startswith(tail_comment, tail.end(1))
    ):
        raise UnsafeStatementSplitError(
            f"{sep} on line {line}: {sep} must be followed by a blank, a count or end of line; "
            f"'{tail_comment}' directly after {sep} is read differently by {client_name} clients"
        )
    digits = (count_text or "").lstrip("0")
    limit = rules.max_repeat
    if len(digits) > len(str(limit)):
        raise UnsafeStatementSplitError(f"{sep} count on line {line} exceeds the limit of {limit}")
    count = int(digits) if digits else (0 if count_text else 1)
    if count > limit:
        raise UnsafeStatementSplitError(
            f"{sep} {count} on line {line} exceeds the limit of {limit}"
        )
    return count
