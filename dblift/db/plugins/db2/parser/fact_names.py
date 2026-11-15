"""Db2 name tokens, folding and provenance used by the native statement facts reader."""

from __future__ import annotations

from typing import FrozenSet, List, Optional, Tuple

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import NamedObject
from dblift.core.sql_parser.tokens import Token, TokenType

_QUERY_RESERVED = frozenset(
    """SELECT WITH VALUES FROM WHERE AS INTO FOR UPDATE DELETE INSERT MERGE FINAL NEW OLD
    TABLE JOIN INNER LEFT RIGHT FULL CROSS ON UNION EXCEPT INTERSECT GROUP ORDER HAVING
    FETCH OFFSET LIMIT DISTINCT ALL RECURSIVE CONNECT START BY CASE WHEN THEN ELSE END
    SET RETURNING USING CALL CREATE ALTER DROP""".split()
)

#: Words that are never a name part.
STOP_WORDS: FrozenSet[str] = frozenset(
    """TO ON IS IN FOR AS LIKE WITH SET USING VALUES FROM WHERE INTO IF RESTRICT IMMEDIATE ONLY
    FOREIGN DATABASE DB CFG SELECT TABLE AUTHORIZATION NOT EXISTS ADD CLONE CASCADE""".split()
)


def fold_name(token_text: str) -> str:
    """Fold one name part as Db2 does: quoted exact, unquoted to the engine's case."""
    if token_text.startswith('"'):
        return _unquote(token_text)
    from dblift.db.plugins.db2.quirks import Db2Quirks

    return token_text.upper() if Db2Quirks.unquoted_identifier_case == "uppercase" else token_text


def _unquote(text: str) -> str:
    return text[1:-1].replace('""', '"') if text.startswith('"') else text


def _is_part(token: Token) -> bool:
    return token.type in (TokenType.KEYWORD, TokenType.IDENTIFIER)


def _name_run(words: List[Token], at: int) -> Tuple[List[Token], int]:
    """Word and quoted-identifier tokens joined by dots from ``at``, and the index after them."""
    i = at
    run: List[Token] = []
    while i < len(words) and _is_part(words[i]):
        run.append(words[i])
        i += 1
        if i + 1 < len(words) and _is_symbol(words[i], ".") and _is_part(words[i + 1]):
            i += 1
        else:
            break
    return run, i


def _read_name(
    words: List[Token], at: int, max_parts: int, stop: FrozenSet[str] = STOP_WORDS
) -> Optional[Tuple[Tuple[str, ...], int, int, Tuple[bool, ...]]]:
    """The folded name parts, source offset, end index and quoted-part flags."""
    run, i = _name_run(words, at)
    if not run or len(run) > max_parts or (i < len(words) and _is_symbol(words[i], ".")):
        return None
    if any(t.text == '""' for t in run):
        return None
    if any(t.type is TokenType.KEYWORD and t.text.upper() in stop for t in run):
        return None
    return (
        tuple(fold_name(t.text) for t in run),
        run[0].pos,
        i,
        tuple(t.type is TokenType.IDENTIFIER and t.text.startswith('"') for t in run),
    )


def _object(
    parts: Tuple[str, ...], otype: SqlObjectType, role: str, quoted: Tuple[bool, ...] = ()
) -> NamedObject:
    return NamedObject(
        parts[-1],
        otype,
        role,
        parts[-2] if len(parts) > 1 else None,
        name_quoted=quoted[-1] if quoted else None,
        schema_quoted=quoted[-2] if len(quoted) > 1 else None,
    )


_KEY_RESERVED = (
    STOP_WORDS
    | _QUERY_RESERVED
    | frozenset({"CONSTRAINT", "PRIMARY", "KEY", "UNIQUE", "REFERENCES", "CHECK"})
)


def _key_columns(words: List[Token], at: int) -> Tuple[Tuple[str, ...], int]:
    """Read a nonempty parenthesized list of simple column names."""
    if at >= len(words) or not _is_symbol(words[at], "("):
        return (), at
    columns = []
    while True:
        entry = _read_name(words, at + 1, 1, _KEY_RESERVED)
        if entry is None:
            return (), at
        columns.append(entry[0][0])
        at = entry[2]
        if at >= len(words) or not _is_symbol(words[at], ","):
            break
    return (tuple(columns), at + 1) if at < len(words) and _is_symbol(words[at], ")") else ((), at)


def _is_unterminated(token: Token) -> bool:
    """Whether a quoted identifier lacks its closing quote (a doubled quote does not close it)."""
    text = token.text
    return (
        token.type is TokenType.IDENTIFIER
        and text.startswith('"')
        and (len(text) < 2 or not text.endswith('"') or '"' in text[1:-1].replace('""', ""))
    )


def _is_symbol(token: Token, text: str) -> bool:
    return token.type is TokenType.SYMBOL and token.text == text


def _unread_character(sql: str, words: List[Token], head_end: int) -> Optional[int]:
    """Offset of the first non-ASCII character the engine may read as part of a name."""
    for token in words[:head_end]:
        if token.type is TokenType.SYMBOL:
            for k, char in enumerate(token.text):
                if ord(char) > 127:
                    return token.pos + k
        elif token.type is TokenType.KEYWORD:
            for at in (token.pos - 1, token.pos + len(token.text)):
                if 0 <= at < len(sql) and ord(sql[at]) > 127:
                    return at
    return None


def _key_names_are_complete(sql: str, tokens: List[Token]) -> bool:
    """All non-ASCII characters belong to complete lexemes such as comments or quoted names."""
    if sql.isascii():
        return True
    if _unread_character(sql, tokens, len(tokens)) is not None:
        return False
    start = 0
    for token in tokens:
        if not sql[start : token.pos].isascii():
            return False
        start = token.pos + len(token.text)
    return sql[start:].isascii()
