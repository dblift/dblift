"""Oracle SQL comment stripping (Phase-Oracle-02 — ADR-0012).

Pure functions extracted from the pre-split monolithic OracleParser.
No class state: these are side-effect-free rewrites.

Two variants exist because the pre-split parser used them from two
different contexts with subtly different needs:

- :func:`strip_comments` — remove line and block comments only. Used
  when a downstream regex still needs to see the original whitespace
  (e.g. statement-type classification).
- :func:`strip_sql_comments` — like :func:`strip_comments` **and**
  collapse runs of spaces/tabs into a single space (newlines
  preserved). Used as the first stage of the statement splitter
  where column alignment would otherwise trip up boundary regexes.

Comments are found with the shared lexical engine, so ``--`` and ``/*`` inside plain and
q-quoted literals (``'a -- b'``, ``q'[--]'``) are kept as data, and
SQL*Plus directive lines (``REM don't run twice``) are left untouched.
"""

from __future__ import annotations

import re

from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.db.plugins.oracle.parser.lexical_spec import ORACLE_SPEC

__all__ = ["strip_comments", "strip_sql_comments"]

_HORIZONTAL_WS = re.compile(r"[ \t]+")


def _remove_comments(sql: str) -> str:
    """Cut out every comment the shared masking view finds, literals untouched.

    A line comment runs to (not including) the newline; a block comment to
    the first ``*/`` (Oracle comments do not nest). An unterminated ``/*``
    and the text after it are left in place. SQL*Plus directive lines are
    free text, not SQL, and are kept as they are: the apostrophe in
    ``PROMPT Creating customer's table`` opens no literal.
    """
    if "--" not in sql and "/*" not in sql:
        return sql
    _, comments = LexicalEngine(ORACLE_SPEC).masking_spans(sql)
    parts = []
    last = 0
    for start, end in comments:
        if sql.startswith("/*", start) and not sql.endswith("*/", start, end):
            break
        parts.append(sql[last:start])
        last = end
    parts.append(sql[last:])
    return "".join(parts)


def strip_comments(sql: str) -> str:
    """Remove ``--`` line comments and ``/* ... */`` block comments.

    Whitespace is preserved. Returns the result ``.strip()``-ed to match
    the pre-split contract.
    """
    return _remove_comments(sql).strip()


def strip_sql_comments(sql: str) -> str:
    """Remove comments and normalise horizontal whitespace (newlines kept).

    Runs of spaces and tabs inside any line are collapsed to a single
    space so column-alignment tricks in hand-authored SQL don't break
    statement-boundary regexes. Line structure is preserved.
    """
    lines = _remove_comments(sql).split("\n")
    normalized = [_HORIZONTAL_WS.sub(" ", line) for line in lines]
    return "\n".join(normalized)
