"""Classification of a client script line, and the refusals of a client that substitutes text."""

import re
from typing import NamedTuple, Optional, Pattern

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.batch_cache import RulesCache
from dblift.core.sql_parser.lexical_spec import BatchScriptRules


class _Patterns(NamedTuple):
    word: Pattern[str]
    tail: Pattern[str]
    colon: Pattern[str]
    variable: Pattern[str]
    lone_cr: Pattern[str]


_NAME = re.compile(r"\S+")


def _patterns(rules: BatchScriptRules) -> _Patterns:
    """The compiled patterns of ``rules``."""
    return _CACHE.get(rules)


def _compile(rules: BatchScriptRules) -> _Patterns:
    blanks = re.escape(rules.blanks)
    part = rules.word_part
    opener, closer = rules.variable_reference
    colon_words = "|".join(re.escape(word) for word in rules.colon_commands)
    # CR stays out of the class: with it, a run of carriage returns makes the pattern quadratic
    lone_blanks = re.escape(rules.blanks.replace("\r", ""))
    lone_words = "|".join(re.escape(word) for word in rules.lone_cr_words)
    return _Patterns(
        word=re.compile(f"[{rules.word_start}][{part}]*"),
        tail=re.compile(
            f"[{blanks}]*(?:([0-9]+)[{blanks}]*)?(?:{re.escape(rules.tail_comment)}.*)?\\Z"
        ),
        colon=re.compile(
            f":(?:{re.escape(rules.shell_prefix)}|(?:{colon_words})(?![{part}]))", re.IGNORECASE
        ),
        variable=re.compile(
            f"{re.escape(opener)}[^{re.escape(closer)}\\r\\n]{{0,40}}{re.escape(closer)}?"
        ),
        lone_cr=re.compile(f"\\r[{lone_blanks}]*(?:{lone_words})(?![{part}])", re.IGNORECASE),
    )


_CACHE: RulesCache[_Patterns] = RulesCache(lambda rules: _compile(rules))


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
    the head on its line. ``None`` means the line is SQL text. A client command, or a
    malformed separator, raises. Only the line is matched, never the rest of the script.
    """
    patterns = _patterns(rules)
    newline = source.find("\n", pos)
    eol = len(source) if newline < 0 else newline
    if source.startswith(rules.shell_prefix, pos) or patterns.colon.match(source, pos, eol):
        name = _NAME.match(source, pos, eol)
        assert name is not None  # the line starts with a non-blank command character
        raise UnsupportedMetaCommandError(_command_message(client_name, name.group(), line))
    word = patterns.word.match(source, pos, eol)
    if word is None:
        return None
    sep = rules.separator
    name_upper = word.group().upper()
    is_separator = name_upper == sep.upper()
    if not is_separator and name_upper not in {c.upper() for c in rules.bare_commands}:
        return None
    follower = source[word.end() : word.end() + 1] if word.end() < eol else ""
    tail_comment = rules.tail_comment
    if is_separator and follower and follower in rules.unmeasured_blanks:
        raise UnsafeStatementSplitError(_tail_message(sep, tail_comment, line, ""))
    allowed = rules.command_followers | (rules.separator_followers if is_separator else frozenset())
    if follower and follower not in allowed:
        return None
    if not is_separator:
        raise UnsupportedMetaCommandError(_command_message(client_name, name_upper, line))
    tail = patterns.tail.match(source, word.end(), eol)
    if tail is None:
        variable = patterns.variable.search(source, word.end(), eol)
        hint = f"; {variable.group()} is not substituted" if variable else ""
        raise UnsafeStatementSplitError(_tail_message(sep, tail_comment, line, hint))
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


def _command_message(client_name: str, name: str, line: int) -> str:
    return f"{client_name} command {name!r} on line {line}: dblift does not run client commands"


def _tail_message(sep: str, tail_comment: str, line: int, hint: str) -> str:
    return (
        f"text after {sep} on line {line}: only a count and a '{tail_comment}' comment "
        f"may follow it{hint}"
    )


def find_lone_cr(rules: BatchScriptRules, source: str, start: int, end: int) -> Optional[int]:
    """Offset of a carriage return, then blanks, then a lone-CR word, in ``source[start:end]``."""
    match = _patterns(rules).lone_cr.search(source, start, end)
    return None if match is None else match.start()


def refuse_lone_cr(rules: BatchScriptRules, client_name: str, line: int) -> None:
    """A carriage return in code that the client may not take as a line break before a separator."""
    raise UnsafeStatementSplitError(
        f"text after {rules.separator} on line {line}: a lone carriage return is not a line "
        f"break {client_name} was measured on; end the line with a newline"
    )


def refuse_variable_in_code(
    rules: BatchScriptRules, client_name: str, source: str, start: int, end: int, line: int
) -> None:
    """Refuse a variable reference in the code segment ``source[start:end]`` of one line."""
    match = _patterns(rules).variable.search(source, start, end)
    if match is not None:
        raise UnsupportedMetaCommandError(_variable_message(client_name, match.group(), line))


def refuse_variable_in_lexeme(
    rules: BatchScriptRules, client_name: str, source: str, start: int, end: int, first_line: int
) -> None:
    """Refuse a variable reference in a string or name body ``source[start:end]``.

    ``first_line`` is the line of ``start``; the line of a match counts the body's newlines.
    """
    match = _patterns(rules).variable.search(source, start, end)
    if match is not None:
        line = first_line + source.count("\n", start, match.start())
        raise UnsupportedMetaCommandError(_variable_message(client_name, match.group(), line))


def _variable_message(client_name: str, text: str, line: int) -> str:
    return (
        f"scripting variable {text} on line {line}: {client_name} substitutes it before the "
        "batch is sent, dblift sends the text as it is"
    )
