"""SQL*Plus masking recognition table, distinct from execution directives."""

import re
from dataclasses import dataclass
from typing import Tuple


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
            the directive's pattern *and* is recognised by
            ``is_sqlplus_command``.
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
