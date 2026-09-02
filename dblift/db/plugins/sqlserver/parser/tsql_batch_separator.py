"""Detect T-SQL batch separators (``GO``) that must not be executed by the native driver."""

import re

# GO is an SSMS/sqlcmd batch terminator, not server T-SQL. Optional BOM, optional
# trailing semicolon, optional line comment (same rules as statement-end detection).
_TSQL_BATCH_SEPARATOR = re.compile(r"(?is)^\ufeff?\s*GO\s*;?\s*(?:--[^\n]*)?\s*$")


def is_tsql_batch_separator(sql: str) -> bool:
    """Return True if *sql* is only a batch separator line (no executable T-SQL)."""
    if not sql or not sql.strip():
        return False
    return bool(_TSQL_BATCH_SEPARATOR.match(sql.strip()))
