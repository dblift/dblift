"""SQL*Plus execution context: extraction and variable substitution."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List

from dblift.db.plugins.oracle.parser._comments import strip_comments
from dblift.db.plugins.oracle.parser._sqlplus import is_sqlplus_command, parse_whenever_sqlerror

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
    """Append ``;`` to lines holding a SQL*Plus directive or WHENEVER SQLERROR.

    Why: SQL*Plus directives (``SET SERVEROUTPUT ON``, ``DEFINE x=1``,
    ``PROMPT msg``, ``WHENEVER SQLERROR CONTINUE`` …) are line-terminated in
    SQL*Plus but carry no ``;``. The Oracle tokeniser only ends a statement
    on ``;`` or ``/``, so a directive line silently merges with the next
    DDL/DML and either gets dropped wholesale (when the merged text still
    matches ``is_sqlplus_command``) or sent to the driver verbatim and rejected
    (when it does not). Either way the user's actual statement disappears
    or fails.

    Fix: walk the script line-by-line and append ``;`` to any line that
    matches ``is_sqlplus_command`` *or* ``parse_whenever_sqlerror`` and is
    not already terminated by ``;`` / ``/``. Other lines pass through
    unchanged so multi-line DDL keeps its original layout. Lines inside a
    block comment are left alone — comments are stripped only for the
    detection step, never written back.
    """
    if not raw_sql:
        return raw_sql

    src_lines = raw_sql.splitlines(keepends=True)
    bare_lines = [line.rstrip("\r\n") for line in src_lines]

    # Track whether each source line is *currently* inside a /* ... */ block.
    in_block_comment = False
    inside_block: List[bool] = []
    for line in bare_lines:
        inside_block.append(in_block_comment)
        i = 0
        while i < len(line):
            two = line[i : i + 2]
            if not in_block_comment and two == "/*":
                in_block_comment = True
                i += 2
                continue
            if in_block_comment and two == "*/":
                in_block_comment = False
                i += 2
                continue
            i += 1

    out: List[str] = []
    for src_line, bare, in_block in zip(src_lines, bare_lines, inside_block):
        if in_block:
            out.append(src_line)
            continue

        # Strip line comment (--) for directive detection only.
        detect = bare.split("--", 1)[0]
        stripped = detect.strip()
        if not stripped:
            out.append(src_line)
            continue
        if stripped.endswith(";") or stripped.endswith("/"):
            out.append(src_line)
            continue
        if not (is_sqlplus_command(stripped) or parse_whenever_sqlerror(stripped) is not None):
            out.append(src_line)
            continue

        # Insert ';' before any trailing comment / line-ending whitespace.
        idx = src_line.find("--")
        if idx == -1:
            # No inline comment: insert before trailing newline characters.
            trail_start = len(src_line)
            while trail_start > 0 and src_line[trail_start - 1] in ("\n", "\r"):
                trail_start -= 1
            new_line = src_line[:trail_start].rstrip() + ";" + src_line[trail_start:]
        else:
            new_line = src_line[:idx].rstrip() + "; " + src_line[idx:]
        out.append(new_line)

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
