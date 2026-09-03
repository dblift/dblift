"""Oracle SQL comment stripping (Phase-Oracle-02 — ADR-0012).

Pure functions extracted from the pre-split monolithic OracleParser.
No class state: these are side-effect-free regex rewrites.

Two variants exist because the pre-split parser used them from two
different contexts with subtly different needs:

- :func:`strip_comments` — remove line and block comments only. Used
  when a downstream regex still needs to see the original whitespace
  (e.g. statement-type classification).
- :func:`strip_sql_comments` — like :func:`strip_comments` **and**
  collapse runs of spaces/tabs into a single space (newlines
  preserved). Used as the first stage of the statement splitter
  where column alignment would otherwise trip up boundary regexes.

String-literal awareness: neither variant currently strips comment
markers that happen to appear inside string literals (e.g.
``'a -- b'``). This matches the pre-split behaviour and is pinned by
the conformance harness. Tightening it is post-split work with its
own regression tests.
"""

from __future__ import annotations

import re

__all__ = ["strip_comments", "strip_sql_comments"]

_LINE_COMMENT = re.compile(r"--.*?(?=\n|$)", re.MULTILINE)
_BLOCK_COMMENT = re.compile(r"/\*.*?\*/", re.DOTALL)
_HORIZONTAL_WS = re.compile(r"[ \t]+")


def strip_comments(sql: str) -> str:
    """Remove ``--`` line comments and ``/* ... */`` block comments.

    Whitespace is preserved. Returns the result ``.strip()``-ed to match
    the pre-split contract.
    """
    sql = _LINE_COMMENT.sub("", sql)
    sql = _BLOCK_COMMENT.sub("", sql)
    return sql.strip()


def strip_sql_comments(sql: str) -> str:
    """Remove comments and normalise horizontal whitespace (newlines kept).

    Runs of spaces and tabs inside any line are collapsed to a single
    space so column-alignment tricks in hand-authored SQL don't break
    statement-boundary regexes. Line structure is preserved.
    """
    sql = _LINE_COMMENT.sub("", sql)
    sql = _BLOCK_COMMENT.sub("", sql)
    lines = sql.split("\n")
    normalized = [_HORIZONTAL_WS.sub(" ", line) for line in lines]
    return "\n".join(normalized)
