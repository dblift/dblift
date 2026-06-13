"""Oracle-specific introspection helpers.

These helpers serve introspection paths that touch Oracle catalogs
specifically (system-column filtering, partition-bound normalisation,
``DBMS_METADATA`` XML aggregation cleanup). They live here — in a
neutral utility module under ``core.introspection`` — instead of as
duplicated copies on ``SchemaIntrospector`` / each extractor, so a
fix lands once and every consumer sees it.

Wave F.3 cleanup: previous copies existed in
``schema_introspector.py`` (static methods), ``index_extractor.py``
(instance method), ``misc_extractor.py`` (instance-method wrapper)
and ``procedure_extractor.py`` (module-level function). All four
were structurally identical; they now delegate here.
"""

from __future__ import annotations

import html
import re
from typing import Any, Optional

_HIDDEN_COLUMN_PREFIXES = ("SYS_", "SYS$")


def is_hidden_column(name: Optional[str]) -> bool:
    """Return ``True`` when *name* is an Oracle system-generated hidden column.

    Oracle prefixes its internally-generated columns (function-based-index
    proxies, virtual columns, ROWID pseudo-columns) with ``SYS_`` or
    ``SYS$``. They should be filtered from user-facing catalog output.
    """
    if not name:
        return False
    upper_name = str(name).strip().upper()
    return upper_name.startswith(_HIDDEN_COLUMN_PREFIXES)


_TO_DATE_PARTITION_BOUND = re.compile(
    r"""^TO_DATE\(\s*'(?P<datetime>[^']+)',\s*'SYYYY-MM-DD HH24:MI:SS',\s*'NLS_CALENDAR=GREGORIAN'\s*\)$""",
    re.IGNORECASE,
)


def normalize_partition_bound(value: Optional[Any]) -> Optional[Any]:
    """Normalize Oracle partition boundary expressions for readability.

    Oracle returns range-partition bounds as fully-qualified
    ``TO_DATE('...', 'SYYYY-MM-DD HH24:MI:SS', 'NLS_CALENDAR=GREGORIAN')``
    expressions. When the time component is midnight, collapses to the
    short ``TO_DATE('YYYY-MM-DD','YYYY-MM-DD')`` form that matches what
    a typical migration author would write.

    Non-string values and unrecognised expressions pass through unchanged.
    """
    if value is None or not isinstance(value, str):
        return value

    text = value.strip()
    match = _TO_DATE_PARTITION_BOUND.match(text)
    if not match:
        return text

    datetime_str = match.group("datetime").strip()
    parts = datetime_str.split()
    date_part = parts[0]
    time_part = parts[1] if len(parts) > 1 else None

    if not time_part or time_part == "00:00:00":
        return f"TO_DATE('{date_part}','YYYY-MM-DD')"
    return text


def clean_source_text(text: Optional[str]) -> Optional[str]:
    """Normalize Oracle XML-aggregated source text.

    ``DBMS_METADATA.GET_DDL`` returns multi-line source as
    ``<E>line1</E><E>line2</E>...`` XML fragments. Joins those back
    into a real newline-separated string and html-unescapes any
    encoded characters.
    """
    if not text:
        return text
    cleaned = text.replace("</E><E>", "\n")
    cleaned = cleaned.replace("<E>", "").replace("</E>", "")
    return html.unescape(cleaned)
