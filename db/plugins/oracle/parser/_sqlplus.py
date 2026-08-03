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
from dataclasses import dataclass
from typing import Optional, Tuple

__all__ = [
    "SQLPLUS_DIRECTIVES",
    "SqlplusDirective",
    "is_sqlplus_command",
    "parse_whenever_sqlerror",
]


@dataclass(frozen=True)
class SqlplusDirective:
    """A single SQL*Plus directive: pattern, examples, and executor routing flag.

    Attributes:
        name: Short identifier used in tests and diagnostics. Unique within
            ``SQLPLUS_DIRECTIVES``.
        pattern: Compiled regex matched against an upper-cased, ``;``-stripped
            statement. Always anchored at the start (``^``) — matching is
            done with ``Pattern.match``.
        examples: Realistic SQL*Plus lines that *must* be classified by this
            directive. The structural corpus test asserts each example matches
            the directive's pattern *and* round-trips through
            ``terminate_sqlplus_directives`` + ``is_sqlplus_command``.
        filter_from_execution: When ``True`` (default) the directive is dropped
            from the executor-bound statement stream. ``False`` for
            ``WHENEVER SQLERROR …`` — those flow through to the executor
            so positional ``CONTINUE`` / ``EXIT`` semantics work.
    """

    name: str
    pattern: re.Pattern[str]
    examples: Tuple[str, ...]
    filter_from_execution: bool = True


SQLPLUS_DIRECTIVES: Tuple[SqlplusDirective, ...] = (
    SqlplusDirective(
        name="SHOW",
        pattern=re.compile(r"^SHOW\s+(?:ERRORS?|ALL|USER|LINESIZE|PAGESIZE|SERVEROUTPUT)"),
        examples=("SHOW ERRORS", "SHOW USER", "SHOW LINESIZE"),
    ),
    SqlplusDirective(
        name="SET",
        pattern=re.compile(
            r"^SET\s+(?:SERVEROUTPUT|LINESIZE|PAGESIZE|FEEDBACK|ECHO|VERIFY|HEADING"
            r"|DEFINE|NULL|TERMOUT|SCAN|SUFFIX|FLAGGER|ESCAPE|TIME|TIMING)"
        ),
        examples=(
            "SET SERVEROUTPUT ON",
            "SET DEFINE OFF",
            "SET LINESIZE 200",
            "SET FEEDBACK OFF",
        ),
    ),
    SqlplusDirective(
        name="SPOOL",
        pattern=re.compile(r"^SPOOL(?:\s+|\s*$)"),
        examples=("SPOOL output.log", "SPOOL OFF", "SPOOL"),
    ),
    SqlplusDirective(
        name="WHENEVER_OSERROR",
        pattern=re.compile(r"^WHENEVER\s+OSERROR"),
        examples=("WHENEVER OSERROR EXIT", "WHENEVER OSERROR CONTINUE"),
    ),
    SqlplusDirective(
        name="PROMPT",
        pattern=re.compile(r"^PROMPT(?:\s+|\s*$)"),
        examples=("PROMPT Starting migration", "PROMPT", "PROMPT Done"),
    ),
    SqlplusDirective(
        name="ACCEPT",
        pattern=re.compile(r"^ACCEPT\s+"),
        examples=("ACCEPT schema_name CHAR PROMPT 'Schema: '",),
    ),
    SqlplusDirective(
        name="REMARK",
        pattern=re.compile(r"^REM(?:ARK)?(?:\s|\s*$)"),
        examples=("REMARK This is a comment", "REM short form", "REMARK"),
    ),
    SqlplusDirective(
        name="DEFINE",
        pattern=re.compile(r"^DEFINE\s+"),
        examples=("DEFINE schema_name = APP", "DEFINE x = 1"),
    ),
    SqlplusDirective(
        name="UNDEFINE",
        pattern=re.compile(r"^UNDEFINE\s+"),
        examples=("UNDEFINE schema_name",),
    ),
    SqlplusDirective(
        name="COLUMN",
        pattern=re.compile(r"^COLUMN\s+"),
        examples=("COLUMN name FORMAT A30",),
    ),
    SqlplusDirective(
        name="COL",
        pattern=re.compile(r"^COL\s+"),
        examples=("COL name FORMAT A30",),
    ),
    SqlplusDirective(
        name="TIMING",
        pattern=re.compile(r"^TIMING\s+"),
        examples=("TIMING START migration",),
    ),
    SqlplusDirective(
        name="CONNECT",
        # Negative lookahead excludes "CONNECT TO ...": the SQL*Plus CONNECT
        # command is always "CONNECT [user][/password][@identifier]" and never
        # uses TO, whereas "CONNECT TO user IDENTIFIED BY password" is Oracle
        # DDL syntax for CREATE DATABASE LINK. Without this, a multi-line
        # CREATE DATABASE LINK ... CONNECT TO ... USING '...' statement gets a
        # spurious ";" inserted after the CONNECT TO line, splitting the
        # statement in two.
        pattern=re.compile(r"^CONNECT\s+(?!TO\b)"),
        examples=("CONNECT user/pass@db",),
    ),
    SqlplusDirective(
        name="CONN",
        pattern=re.compile(r"^CONN\s+"),
        examples=("CONN user/pass@db",),
    ),
    SqlplusDirective(
        name="DISCONNECT",
        pattern=re.compile(r"^DISCONNECT\s*"),
        examples=("DISCONNECT", "DISCONNECT "),
    ),
    SqlplusDirective(
        name="EXIT",
        pattern=re.compile(r"^EXIT\s*"),
        examples=("EXIT", "EXIT 0"),
    ),
    SqlplusDirective(
        name="QUIT",
        pattern=re.compile(r"^QUIT\s*"),
        examples=("QUIT", "QUIT 0"),
    ),
    SqlplusDirective(
        name="DESCRIBE",
        pattern=re.compile(r"^DESC(?:RIBE)?\s+"),
        examples=("DESC users", "DESCRIBE users"),
    ),
    SqlplusDirective(
        name="HOST",
        pattern=re.compile(r"^HOST\s+"),
        examples=("HOST ls -l",),
    ),
    SqlplusDirective(
        name="BANG",
        pattern=re.compile(r"^!\s*"),
        examples=("!", "! ls"),
    ),
    SqlplusDirective(
        name="AT_SCRIPT",
        pattern=re.compile(r"^@@?\s*[^\s]"),
        examples=(
            "@script.sql",
            "@ /tmp/other_script.sql",
            "@@nested.sql",
            "@@ relative_script.sql",
        ),
    ),
    SqlplusDirective(
        name="EXECUTE",
        pattern=re.compile(r"^EXEC(?:UTE)?\s+"),
        examples=("EXEC dbms_output.put_line('hi')", "EXECUTE proc()"),
    ),
    SqlplusDirective(
        name="CLEAR",
        pattern=re.compile(r"^CLEAR\s+"),
        examples=("CLEAR SCREEN", "CLEAR BUFFER"),
    ),
    SqlplusDirective(
        name="BREAK",
        pattern=re.compile(r"^BREAK\s+"),
        examples=("BREAK ON deptno",),
    ),
    SqlplusDirective(
        name="COMPUTE",
        pattern=re.compile(r"^COMPUTE\s+"),
        examples=("COMPUTE SUM OF salary ON deptno",),
    ),
    SqlplusDirective(
        name="TITLE",
        pattern=re.compile(r"^(?:T|B)TITLE\s+"),
        examples=("TTITLE 'Report'", "BTITLE 'Footer'"),
    ),
    SqlplusDirective(
        name="REPHEADER_FOOTER",
        pattern=re.compile(r"^REP(?:HEADER|FOOTER)\s+"),
        examples=("REPHEADER 'Header'", "REPFOOTER 'Footer'"),
    ),
    SqlplusDirective(
        name="VARIABLE",
        pattern=re.compile(r"^VARIABLE\s+"),
        examples=("VARIABLE x NUMBER",),
    ),
    SqlplusDirective(
        name="PRINT",
        pattern=re.compile(r"^PRINT\s+"),
        examples=("PRINT x",),
    ),
    SqlplusDirective(
        name="PAUSE",
        pattern=re.compile(r"^PAUSE\s*"),
        examples=("PAUSE", "PAUSE Press any key"),
    ),
    SqlplusDirective(
        name="WHENEVER_SQLERROR_CONTINUE",
        pattern=re.compile(r"^\s*WHENEVER\s+SQLERROR\s+CONTINUE\b", re.IGNORECASE),
        examples=("WHENEVER SQLERROR CONTINUE",),
        filter_from_execution=False,
    ),
    SqlplusDirective(
        name="WHENEVER_SQLERROR_EXIT",
        pattern=re.compile(r"^\s*WHENEVER\s+SQLERROR\s+EXIT\b", re.IGNORECASE),
        examples=(
            "WHENEVER SQLERROR EXIT",
            "WHENEVER SQLERROR EXIT FAILURE",
            "WHENEVER SQLERROR EXIT SQL.SQLCODE",
        ),
        filter_from_execution=False,
    ),
)


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
