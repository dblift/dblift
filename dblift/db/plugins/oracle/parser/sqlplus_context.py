"""SQL*Plus execution context the executor reads: ``SET SERVEROUTPUT`` and ``PROMPT``."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List

from dblift.db.plugins.oracle.parser._comments import strip_comments

__all__ = ["SqlplusContext", "extract_sqlplus_context"]

# --- Directive detectors (line-level, case-insensitive) ---
# SET options may be abbreviated to their documented minimum (spec section 6).
_SET_SERVEROUTPUT_ON = re.compile(r"^\s*SET\s+SERVEROUT(?:P(?:U(?:T)?)?)?\s+ON\b", re.IGNORECASE)
_SET_SERVEROUTPUT_OFF = re.compile(r"^\s*SET\s+SERVEROUT(?:P(?:U(?:T)?)?)?\s+OFF\b", re.IGNORECASE)
_PROMPT = re.compile(r"^\s*PROMPT\s+(.*)", re.IGNORECASE)
_REMARK = re.compile(r"^\s*REM(?:ARK)?\s+(.*)", re.IGNORECASE)


@dataclass
class SqlplusContext:
    """SQL*Plus directives the executor reads, extracted from the raw script."""

    serveroutput: bool = False
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
    """Scan raw SQL line-by-line for the directives the executor reads.

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
        elif m := _PROMPT.match(stripped):
            msg = m.group(1).strip()
            if msg:
                ctx.prompts.append(msg)
        elif _REMARK.match(stripped):
            # SQL*Plus REM/REMARK = comment directive (equivalent to --).
            # Stays silent; not appended to ctx.prompts to avoid the [PROMPT] echo.
            pass
    return ctx
