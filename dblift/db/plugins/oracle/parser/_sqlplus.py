"""Oracle SQL*Plus directive recognition (Phase-Oracle-03 — ADR-0012).

SQL*Plus is the Oracle command-line client. Its scripts intermix
executable SQL with client-side directives (``SET``, ``SPOOL``,
``@``, ``PROMPT``, ``EXIT`` …) that are not valid statements under
the native driver. The statement splitter calls :func:`is_sqlplus_command` after
comment stripping to drop those directives before handing the result
to the executor.

Single source of truth — :data:`SQLPLUS_DIRECTIVES`
---------------------------------------------------
Every SQL*Plus directive recognised by dblift is declared once as a
:class:`SqlplusDirective` entry in :data:`SQLPLUS_DIRECTIVES`. From
that single tuple we derive:

  * ``_SQLPLUS_PATTERNS`` — regex list consumed by
    :func:`is_sqlplus_command` (filters before execution),
  * ``_WHENEVER_SQLERROR_CONTINUE`` / ``_WHENEVER_SQLERROR_EXIT`` —
    single-purpose patterns for :func:`parse_whenever_sqlerror`
    (these directives flow through the executor for positional policy
    tracking and are deliberately *not* in the filter list),
  * the canonical example corpus the structural test
    ``tests/unit/test_oracle_sqlplus_directive_corpus.py`` walks to
    prove every declared directive parses, terminates, and is dropped
    correctly end-to-end.

Adding a new directive is now a one-liner — bump
:data:`SQLPLUS_DIRECTIVES`. The structural test will refuse to ship
without an example, so the corpus stays in sync.

Behaviour notes inherited from PR-E (ADR-0012 §Follow-ups closed):

  * ``SET ROLE admin`` — was filtered (false positive, broad
    ``SET `` prefix). Now retained as valid Oracle SQL.
  * ``WHENEVER NOT FOUND ...`` — was filtered (false positive, broad
    ``WHENEVER `` prefix). Now retained.
  * ``START TRANSACTION``, ``START WITH`` — were filtered. Now retained.
  * ``CONN``, ``COL``, ``TIMING``, ``!``, ``EXEC``/``EXECUTE``, ``@@``
    — were not filtered (false negatives). Now correctly dropped.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from dblift.db.plugins.oracle.parser.masking_rules import SQLPLUS_DIRECTIVES, SqlplusDirective

__all__ = [
    "SQLPLUS_DIRECTIVES",
    "SqlplusDirective",
    "is_sqlplus_command",
    "parse_whenever_sqlerror",
]

_SQLPLUS_PATTERNS: Tuple[re.Pattern[str], ...] = tuple(
    d.pattern for d in SQLPLUS_DIRECTIVES if d.filter_from_execution
)


def _directive(name: str) -> SqlplusDirective:
    for d in SQLPLUS_DIRECTIVES:
        if d.name == name:
            return d
    raise KeyError(f"Unknown SqlplusDirective: {name!r}")


_WHENEVER_SQLERROR_CONTINUE = _directive("WHENEVER_SQLERROR_CONTINUE").pattern
_WHENEVER_SQLERROR_EXIT = _directive("WHENEVER_SQLERROR_EXIT").pattern


def is_sqlplus_command(stmt: str) -> bool:
    """Return ``True`` if ``stmt`` is a SQL*Plus client-side directive.

    The input is expected to be a single statement (already split) but
    may carry leading whitespace, mixed case, and a trailing ``;`` —
    this function normalises all three internally. An empty string
    returns ``False``.

    Note: ``WHENEVER SQLERROR`` is intentionally *not* in
    ``_SQLPLUS_PATTERNS`` so it reaches the executor for positional
    policy tracking. Use :func:`parse_whenever_sqlerror` to detect
    and handle it there.
    """
    stmt_upper = stmt.upper().strip()
    if stmt_upper.endswith(";"):
        stmt_upper = stmt_upper[:-1].rstrip()
    return any(p.match(stmt_upper) for p in _SQLPLUS_PATTERNS)


def parse_whenever_sqlerror(stmt: str) -> Optional[str]:
    """Return the WHENEVER SQLERROR policy encoded in *stmt*, or ``None``.

    Returns ``"continue"`` for ``WHENEVER SQLERROR CONTINUE``,
    ``"exit"`` for ``WHENEVER SQLERROR EXIT``, and ``None`` for anything else.
    The executor calls this inline so that policy changes take effect
    positionally rather than globally.
    """
    if _WHENEVER_SQLERROR_CONTINUE.match(stmt):
        return "continue"
    if _WHENEVER_SQLERROR_EXIT.match(stmt):
        return "exit"
    return None
