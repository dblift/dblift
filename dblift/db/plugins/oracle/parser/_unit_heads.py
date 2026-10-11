"""Which statements are PL/SQL units, decided from their first tokens.

A unit ends only at a ``/`` alone on its line and nothing inside it is counted
(docs/sql-parsing/oracle.md §5). The classifier is tri-state so the parser can
feed it the statement's head one token at a time: ``None`` means "not enough
tokens yet", ``True``/``False`` is final.
"""

from typing import List, Optional, Sequence

from dblift.core.sql_parser.tokens import Token, TokenType

# The longest head: CREATE OR REPLACE IF NOT EXISTS MLE MODULE.
MAX_HEAD_TOKENS = 8

_BLOCK_STARTS = ("DECLARE", "BEGIN")
_EDITIONED_UNITS = ("FUNCTION", "PROCEDURE", "PACKAGE", "TYPE", "TRIGGER", "LIBRARY")


def head_decided(tokens: Sequence[Token]) -> Optional[bool]:
    """Whether the statement starting with ``tokens`` is a PL/SQL unit.

    Comments are skipped; keywords and identifiers compare by upper-cased text.
    Returns ``None`` while ``tokens`` is a proper prefix of a unit head.
    """
    words = [t.text.upper() for t in tokens if t.type != TokenType.COMMENT]
    try:
        return _classify(words)
    except IndexError:
        return None


def _classify(w: List[str]) -> bool:
    if w[0] in _BLOCK_STARTS:
        return True
    if w[0] == "<":
        return w[1] == "<" and w[3] == ">" and w[4] == ">" and w[5] in _BLOCK_STARTS
    if w[0] != "CREATE":
        return False
    i = 1
    if w[i] == "OR":
        if w[i + 1] != "REPLACE":
            return False
        i += 2
    if w[i] in ("EDITIONABLE", "NONEDITIONABLE"):
        return w[i + 1] in _EDITIONED_UNITS
    if w[i] in _EDITIONED_UNITS:
        return True
    if w[i] == "AND":
        if w[i + 1] not in ("COMPILE", "RESOLVE"):
            return False
        i += 2
    if w[i] == "NOFORCE":
        i += 1
    if w[i] == "JAVA":
        return w[i + 1] in ("SOURCE", "CLASS", "RESOURCE")
    if w[i] == "IF":
        if w[i + 1] != "NOT" or w[i + 2] != "EXISTS":
            return False
        i += 3
    return w[i] == "MLE" and w[i + 1] == "MODULE"
