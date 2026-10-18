"""Refuse a statement whose edge a driver would strip and the engine does not read as a blank.

Some drivers remove every white space character from both ends of a statement before they send it.
When the engine reads such a character as part of a name, or rejects it, the statement that runs is
not the one in the file. The edge of the code is judged without comments: a blank inside a trailing
comment only shortens the comment.
"""

from typing import Optional, Sequence, Tuple

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.tokens import Token, TokenType


def edge_characters_outside(text: str, text_blanks: str) -> bool:
    """Whether ``text`` holds a white space character that is not one of ``text_blanks``."""
    return any(c.isspace() and c not in text_blanks for c in set(text))


def refuse_edges_the_driver_strips(
    source: str,
    tokens: Sequence[Token],
    comments: Sequence[Tuple[int, int]],
    text_blanks: str,
    *,
    floor: int = 0,
    end: Optional[int] = None,
    terminator: Optional[Token] = None,
) -> None:
    """Raise ``UnsafeStatementSplitError`` for such a character before or after the code.

    ``tokens`` are those of one statement, comments included; ``comments`` are the source spans of
    every comment of the script; ``terminator`` is the token that ends it and is not part of its text. The leading edge is read from ``floor`` (where the previous
    record ended) to the first code token, the trailing edge from the last code token to the next
    comment, the terminator or ``end``.
    """
    code = [
        t
        for t in tokens
        if t.type not in (TokenType.COMMENT, TokenType.EOF) and t is not terminator
    ]
    if not code:
        return
    spans = sorted(comments)
    last = code[-1]
    trailing_start = last.pos + len(last.text)
    stop = len(source) if end is None else end
    if terminator is not None:
        stop = min(stop, terminator.pos)
    stop = min([stop, *(a for a, _ in spans if a >= trailing_start)])
    _refuse_in(source, floor, code[0].pos, spans, text_blanks)
    _refuse_in(source, trailing_start, stop, spans, text_blanks)


def _refuse_in(
    source: str, start: int, stop: int, comments: Sequence[Tuple[int, int]], text_blanks: str
) -> None:
    for pos in range(start, stop):
        char = source[pos]
        if not char.isspace() or char in text_blanks:
            continue
        if any(a <= pos < b for a, b in comments):
            continue
        line = source.count("\n", 0, pos) + 1
        column = pos - (source.rfind("\n", 0, pos) + 1) + 1
        raise UnsafeStatementSplitError(
            f"U+{ord(char):04X} at line {line}, column {column} is at the edge of a statement: "
            "the driver removes it before it sends the statement and the database does not read "
            "it as a blank, so the statement that would run is not the one in the file; remove "
            "the character"
        )
