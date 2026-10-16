"""Line-head commands of a delimiter script."""

import re
from typing import Optional, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_spec import DelimiterScriptRules


def classify_line(
    rules: DelimiterScriptRules, source: str, start: int, end: int, delimiter: str
) -> Optional[Tuple[str, str]]:
    """The command a line begins: (word as written, argument tail), or None when it is text.

    ``source[start:end]`` is one line without its line feed; the tail is the rest of the line.
    """
    blanks = rules.blanks
    while start < end and source[start] in blanks:
        start += 1
    found = re.compile(rules.line_word).match(source, start, end)
    if found is None or found.group().upper() != rules.command.upper():
        return None
    stop = found.end()
    gap = (
        stop == end
        or source[stop] in " \t"
        or re.compile("[" + re.escape(blanks) + "]*").fullmatch(source, stop, end) is not None
    )
    tail = source[stop:end].rstrip("\r")
    if gap or tail.startswith(rules.initial):
        return found.group(), tail if gap else ""
    return None


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
            "one): "
            "the mysql client prints an error and keeps the old delimiter, the mariadb "
            "client sends the line to the server as text"
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
