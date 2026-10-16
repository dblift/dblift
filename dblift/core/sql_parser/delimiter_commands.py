"""Line-head commands of a delimiter script."""

import re
from functools import lru_cache
from typing import FrozenSet, NoReturn, Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_spec import DelimiterScriptRules


@lru_cache(maxsize=None)
def _known_words(rules: DelimiterScriptRules) -> FrozenSet[str]:
    """Every word that can begin a command line."""
    return (
        rules.bare_commands
        | rules.terminated_commands
        | rules.argument_commands
        | rules.unterminated_commands
        | {rules.command.upper()}
    )


def _terminator_run(source: str, start: int, end: int, delimiter: str, filler: str) -> bool:
    """Whether a suffix holds only blanks, the initial delimiter and the active delimiter."""
    while start < end:
        if source.startswith(delimiter, start, end):
            start += len(delimiter)
        elif source[start] in filler:
            start += 1
        else:
            return False
    return True


def _terminated(
    rules: DelimiterScriptRules, source: str, start: int, end: int, delimiter: str
) -> bool:
    """True when the active delimiter ends the line's code (before any comment)."""
    stop = source.find(delimiter, start, end)
    if stop < 0:
        return False
    opener = "|".join(
        [
            re.escape(rules.hash_comment),
            re.escape(rules.dash_comment) + "(?=[" + re.escape(rules.blanks) + "]|$)",
            "/\\*",
        ]
    )
    return re.compile(opener).search(source, start, stop) is None


def classify_line(
    rules: DelimiterScriptRules, source: str, start: int, end: int, delimiter: str
) -> Optional[Tuple[str, str]]:
    """The command a line begins: (word as written, argument tail), or None when it is text.

    ``source[start:end]`` is one line without its line feed; the tail is the rest of the line
    for the delimiter command and empty for a refused command.
    """
    blanks = rules.blanks
    while start < end and source[start] in blanks:
        start += 1
    found = re.compile(rules.line_word).match(source, start, end)
    if found is None:
        return None
    word = found.group().upper()
    command = rules.command.upper()
    if word not in _known_words(rules):
        return None
    stop = found.end()
    blank_run = re.compile("[" + re.escape(blanks) + "]*")
    gap = stop == end or source[stop] in " \t" or blank_run.fullmatch(source, stop, end) is not None
    if word == command:
        tail = source[stop:end].rstrip("\r")
        if gap or tail.startswith(rules.initial):
            return found.group(), tail if gap else ""
        return None
    run = _terminator_run(source, stop, end, delimiter, blanks + rules.initial)
    if word in rules.bare_commands:
        refused = blank_run.fullmatch(source, stop, end) is not None
    elif word in rules.exit_commands:
        after = stop
        while after < end and source[after] in blanks:
            after += 1
        refused = (
            after == end
            or source.startswith(rules.initial, after)
            or source.startswith(delimiter, after)
        )
    elif word in rules.unterminated_commands:
        refused = (run and word not in rules.statement_words) or (
            gap and not _terminated(rules, source, stop, end, delimiter)
        )
    elif word in rules.argument_commands:
        refused = gap or run
    else:
        refused = run
    return (found.group(), "") if refused else None


def refuse_command(client_name: str, word: str, line: int, *, after_comment: bool) -> NoReturn:
    """Refuse a client command: dblift does not run it."""
    if after_comment:
        raise UnsupportedMetaCommandError(
            f"{client_name} client command {word!r} after a comment on line {line}: "
            "clients and versions differ on whether it is a command"
        )
    raise UnsupportedMetaCommandError(
        f"{client_name} client command {word!r} on line {line}: dblift does not run client commands"
    )


def check_escape(
    rules: DelimiterScriptRules, client_name: str, source: str, pos: int, end: int, line: int
) -> None:
    """``source[pos]`` is the escape character: its text followers pass, any other is a command."""
    following = source[pos + 1 : pos + 2] if pos + 1 < end else ""
    if following in rules.escape_text and following:
        return
    what = "a backslash at the end of a line" if not following else f"{rules.escape}{following}"
    raise UnsupportedMetaCommandError(
        f"{client_name} client command {what} on line {line}: dblift does not run client commands"
    )


def read_delimiter(
    rules: DelimiterScriptRules, client_name: str, raw: str, tail: str, line: int
) -> str:
    """The delimiter a delimiter command sets; refuses what the client misreads, in its order."""
    command = rules.command
    if "\r" in raw.rstrip("\r"):
        raise UnsafeStatementSplitError(
            f"{command} on line {line} has a carriage return that is not part of a "
            f"line end: the {client_name} client reads the rest of the script as part of "
            "that line and sends nothing"
        )
    argument = tail.lstrip(" \t")
    if argument and argument[0] in rules.argument_quotes:
        close = argument.find(argument[0], 1)
        value = argument[1:close] if close > 1 else ""
    else:
        value = argument.split(" ", 1)[0]
    if not value:
        raise UnsafeStatementSplitError(
            f"{command} on line {line} has no argument (or an empty or unclosed quoted "
            f"one): the {client_name} client does not set a delimiter from it"
        )
    if rules.escape in value:
        raise UnsafeStatementSplitError(
            f"{command} on line {line} contains a backslash: "
            f"the {client_name} client refuses it, backslash is the escape character"
        )
    if len(value) > rules.max_length:
        raise UnsafeStatementSplitError(
            f"{command} on line {line} is longer than {rules.max_length} characters: "
            f"the {client_name} client silently keeps only the first ones"
        )
    return value
