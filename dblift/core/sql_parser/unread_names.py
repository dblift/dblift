"""Whether a statement's object names can be trusted to match what the engine reads.

The regex extractors and sqlglot disagree with several engines on characters inside a name: a
no-break space is a blank to sqlglot and a name character to PostgreSQL, a combining accent ends
the name the extractors read. Naming ``t`` for ``t<NBSP>`` makes an undo drop the user's own
``t``, so such a statement is read as naming nothing.
"""

from __future__ import annotations

import re
from typing import Iterable, Optional

_NAME_CHARACTER = re.compile(r"[\w$]")
# What is not a name: the first match from the left wins, so a quote inside a comment is the
# comment's. An opener that never closes matches nothing and its text stays, which only
# over-reports.
_NOT_NAMES = re.compile(
    r"""'(?:''|[^'])*'|"(?:""|[^"])*"|`[^`]*`|\[[^\]]*\]|--[^\n]*|/\*.*?\*/""", re.S
)


def _cut_short(sql: str, name: str) -> bool:
    """Whether ``name`` stands in ``sql`` right next to a non-ASCII character: the extractors
    stop at one they do not know, so the name the engine reads is a longer one."""
    sql = _NOT_NAMES.sub(" ", sql)
    for match in re.finditer(re.escape(name), sql, re.IGNORECASE):
        before = sql[match.start() - 1] if match.start() else ""
        after = sql[match.end()] if match.end() < len(sql) else ""
        if before and before.isascii() and _NAME_CHARACTER.match(before):
            continue
        if (before and not before.isascii()) or (after and not after.isascii()):
            return True
    return False


def names_unreadable(sql: str, sqlglot_dialect: Optional[str], names: Iterable[str] = ()) -> bool:
    """Whether the object names read from ``sql`` cannot be trusted.

    True when one of the 22 characters sqlglot and the engines read differently stands outside
    strings, quoted identifiers and comments, or when one of ``names`` (as the extractors read
    them) stands next to a non-ASCII character that cut it short.
    """
    if sql.isascii():
        return False
    # Imported here: sqlglot is not loaded for the ASCII statements that are nearly all of them.
    from dblift.core.sql_parser.sqlglot_statement_facts import unread_name_character

    try:
        at = unread_name_character(sql, dialect=sqlglot_dialect or "")
    except Exception:  # an unknown dialect: the rule does not depend on it
        at = unread_name_character(sql, dialect="")
    if at is not None:
        return True
    return any(
        _cut_short(sql, part) for name in names for part in str(name).split(".") if part.strip()
    )
