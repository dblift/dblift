"""SQL*Plus execution context: extraction and variable substitution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from dblift.db.plugins.oracle.parser._comments import strip_comments
from dblift.db.plugins.oracle.parser._sqlplus import (
    parse_whenever_sqlerror,
    tokenize_outside_sqlplus_directives,
)

__all__ = [
    "SqlplusContext",
    "extract_sqlplus_context",
    "apply_define_substitution",
    "terminate_sqlplus_directives",
]

# --- Directive detectors (line-level, case-insensitive) ---
_SET_SERVEROUTPUT_ON = re.compile(r"^\s*SET\s+SERVEROUTPUT\s+ON\b", re.IGNORECASE)
_SET_SERVEROUTPUT_OFF = re.compile(r"^\s*SET\s+SERVEROUTPUT\s+OFF\b", re.IGNORECASE)
_SET_DEFINE_OFF = re.compile(r"^\s*SET\s+DEFINE\s+OFF\b", re.IGNORECASE)
_SET_DEFINE_ON = re.compile(r"^\s*SET\s+DEFINE\s+ON\b", re.IGNORECASE)
_DEFINE_VAR = re.compile(r"^\s*DEFINE\s+(\w+)\s*=\s*(.+)", re.IGNORECASE)
_PROMPT = re.compile(r"^\s*PROMPT\s+(.*)", re.IGNORECASE)
_REMARK = re.compile(r"^\s*REM(?:ARK)?\s+(.*)", re.IGNORECASE)
# Matches &var or &&var references in SQL text.
# The optional trailing dot is the SQL*Plus variable terminator: &schema.table means
# variable "schema" (dot consumed), so &schema.table → <VALUE>table.
# Use double-dot to keep the dot: &schema..table → <VALUE>.table.
_DEFINE_REF = re.compile(r"&&?(\w+)\.?", re.IGNORECASE)


@dataclass
class SqlplusContext:
    """SQL*Plus directives that affect execution context, extracted from raw script."""

    serveroutput: bool = False
    define_on: bool = True  # Oracle default: substitution enabled
    defines: Dict[str, str] = field(default_factory=dict)  # DEFINE VAR -> value
    prompts: List[str] = field(
        default_factory=list
    )  # PROMPT messages only (REM/REMARK = silent comments)

    @property
    def wants_session_output(self) -> bool:
        """Generic alias exposed to dialect-agnostic core code.

        Core reads this attribute via ``getattr(ctx, "wants_session_output", False)``
        so it never names the Oracle-specific ``serveroutput`` field.
        """
        return self.serveroutput


def extract_sqlplus_context(raw_sql: str) -> SqlplusContext:
    """Scan raw SQL line-by-line for SQL*Plus context directives.

    Does not parse SQL — works on raw text before the tokeniser runs.
    Line comments (--) and block comments (/* ... */) are stripped first.
    """
    ctx = SqlplusContext()
    for line in strip_comments(raw_sql).splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if _SET_SERVEROUTPUT_ON.match(stripped):
            ctx.serveroutput = True
        elif _SET_SERVEROUTPUT_OFF.match(stripped):
            ctx.serveroutput = False
        elif _SET_DEFINE_OFF.match(stripped):
            ctx.define_on = False
        elif _SET_DEFINE_ON.match(stripped):
            ctx.define_on = True
        elif m := _DEFINE_VAR.match(stripped):
            val = m.group(2).strip().rstrip(";").strip()
            if len(val) >= 2 and val[0] == val[-1] and val[0] in ("'", '"'):
                val = val[1:-1]
            ctx.defines[m.group(1).upper()] = val
        elif m := _PROMPT.match(stripped):
            msg = m.group(1).strip()
            if msg:
                ctx.prompts.append(msg)
        elif _REMARK.match(stripped):
            # SQL*Plus REM/REMARK = comment directive (equivalent to --).
            # Stays silent; not appended to ctx.prompts to avoid the [PROMPT] echo.
            pass
    return ctx


def terminate_sqlplus_directives(raw_sql: str) -> str:
    """Prepare SQL*Plus directive lines for the ``;``/``/`` statement splitter.

    Why: SQL*Plus directives (``SET SERVEROUTPUT ON``, ``DEFINE x=1``,
    ``PROMPT msg``, ``WHENEVER SQLERROR CONTINUE`` …) are line-terminated in
    SQL*Plus but carry no ``;``. The Oracle tokeniser only ends a statement
    on ``;`` or ``/``, so a directive line silently merges with the next
    DDL/DML and either gets dropped wholesale (when the merged text still
    matches ``is_sqlplus_command``) or sent to the driver verbatim and rejected
    (when it does not). Their text is not SQL either: the apostrophe in
    ``PROMPT Creating customer's table`` would open a literal that swallows
    the statements below it.

    Fix: find the directive lines where a statement can begin
    (:func:`tokenize_outside_sqlplus_directives`). A ``WHENEVER SQLERROR``
    line gets a ``;`` appended (unless already terminated by ``;`` / ``/``)
    so it reaches the executor as its own statement; every other directive
    is dropped before execution anyway, so its text is removed (a trailing
    ``--`` comment and the newline stay).
    Other lines pass through unchanged, including lines inside a PL/SQL
    block or a multi-line literal that merely look like a directive
    (``EXECUTE IMMEDIATE '...``).
    """
    if not raw_sql:
        return raw_sql

    _, directive_lines = tokenize_outside_sqlplus_directives(raw_sql)
    out: List[str] = []
    last = 0
    for start, end in directive_lines:
        out.append(raw_sql[last:start])
        last = end
        line = raw_sql[start:end]
        directive = line.rstrip()
        if parse_whenever_sqlerror(line) is None:
            continue
        if directive.endswith(";") or directive.endswith("/"):
            out.append(line)
        else:
            # Insert ';' before any trailing comment / line-ending whitespace.
            out.append(directive + ";" + line[len(directive) :])
    out.append(raw_sql[last:])
    return "".join(out)


def apply_define_substitution(sql: str, ctx: SqlplusContext) -> str:
    """Replace &var and &&var references using defines from ctx.

    When ctx.define_on is False or ctx.defines is empty, returns sql unchanged.
    Unknown variable references are left as-is (matching SQL*Plus behaviour).
    """
    if not ctx.define_on or not ctx.defines:
        return sql

    def _replace(m: re.Match[str]) -> str:
        return ctx.defines.get(m.group(1).upper(), m.group(0))

    return _DEFINE_REF.sub(_replace, sql)
