"""Whether a statement's object names can be trusted to match what the engine reads.

sqlglot disagrees with several engines on characters inside a name: a no-break space is a blank to
sqlglot and a name character to PostgreSQL. Naming ``t`` for ``t<NBSP>`` makes an undo drop the
user's own ``t``, so such a statement is read as naming nothing.
"""

from __future__ import annotations

from typing import Optional


def names_unreadable(sql: str, sqlglot_dialect: Optional[str]) -> bool:
    """Whether the object names read from ``sql`` cannot be trusted.

    True when one of the 22 characters sqlglot and the engines read differently stands outside
    strings, quoted identifiers and comments.
    """
    if sql.isascii():
        return False
    # Imported here: sqlglot is not loaded for the ASCII statements that are nearly all of them.
    from dblift.core.sql_parser.sqlglot_statement_facts import unread_name_character

    try:
        at = unread_name_character(sql, dialect=sqlglot_dialect or "")
    except ValueError:  # sqlglot does not know the dialect: the rule does not depend on it
        at = unread_name_character(sql, dialect="")
    return at is not None
