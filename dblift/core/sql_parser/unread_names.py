"""Whether a statement's object names can be trusted to match what the engine reads.

The regex extractors and sqlglot disagree with several engines on characters inside a name: a
no-break space is a blank to sqlglot and a name character to PostgreSQL, a combining accent ends
the name the extractors read. Naming ``t`` for ``t<NBSP>`` makes an undo drop the user's own
``t``, so such a statement is read as naming nothing.
"""

from __future__ import annotations

import re
from typing import Any, Iterable, List, Optional, Sequence, Tuple

from dblift.core.sql_parser.statement import Statement

_NAME_CHARACTER = re.compile(r"[\w$]")
# What is not a name: the first match from the left wins, so a quote inside a comment is the
# comment's. An opener that never closes matches nothing and its text stays, which only
# over-reports.
_NOT_NAMES = re.compile(
    r"""'(?:''|[^'])*'|"(?:""|[^"])*"|`[^`]*`|\[[^\]]*\]|--[^\n]*|/\*.*?\*/""", re.S
)


def _cut_short(sql: str, name: str) -> bool:
    """Whether ``name`` stands in ``sql`` right next to a non-ASCII character: the extractors
    stop at one they do not know, so the name the engine reads is a longer one."""
    sql = _NOT_NAMES.sub(" ", sql)
    for match in re.finditer(re.escape(name), sql, re.IGNORECASE):
        before = sql[match.start() - 1] if match.start() else ""
        after = sql[match.end()] if match.end() < len(sql) else ""
        if before and before.isascii() and _NAME_CHARACTER.match(before):
            continue
        if (before and not before.isascii()) or (after and not after.isascii()):
            return True
    return False


def names_unreadable(sql: str, sqlglot_dialect: Optional[str], names: Iterable[str] = ()) -> bool:
    """Whether the object names read from ``sql`` cannot be trusted.

    True when one of the 22 characters sqlglot and the engines read differently stands outside
    strings, quoted identifiers and comments, or when one of ``names`` (as the extractors read
    them) stands next to a non-ASCII character that cut it short.
    """
    if sql.isascii():
        return False
    # Imported here: sqlglot is not loaded for the ASCII statements that are nearly all of them.
    from dblift.core.sql_parser.sqlglot_statement_facts import unread_name_character

    try:
        at = unread_name_character(sql, dialect=sqlglot_dialect or "")
    except ValueError:  # sqlglot does not know the dialect: the rule does not depend on it
        at = unread_name_character(sql, dialect="")
    if at is not None:
        return True
    return any(
        _cut_short(sql, part) for name in names for part in str(name).split(".") if part.strip()
    )


def _without_blanks_before_terminator(span: str, record: Statement) -> str:
    """``span`` without the blanks the scanner trimmed between the text and its terminator, if any.

    The engine reads those as blanks, so the name before them ends the statement as it does with
    no terminator. A character the scanner kept in the text stays in the span.
    """
    terminator = record.terminator or ""
    if not span.endswith(terminator):
        return span
    body = span[: len(span) - len(terminator)]
    if len(body) > len(record.text) and body.startswith(record.text):
        return record.text + terminator
    return span


def statement_sources(scanner: Any, script: str, statements: Sequence[str]) -> List[Optional[str]]:
    """Each statement as it stands in ``script``: the scanner's own span for it, untrimmed
    except for the blanks the engine reads between the text and its terminator.

    The analysis split trims the blanks that end a statement, so a name that ends its statement
    is seen without the character the engine reads as part of it. ``statements`` are matched, in
    order, to the constituents of the scanner's records; one that matches none (its text was
    rewritten) is ``None``: nothing can be said about its name. An ASCII script has no such
    character and is returned as it is.
    """
    if script.isascii():
        return list(statements)
    records = scanner.split(script)
    spans: List[Tuple[str, Optional[str]]] = []
    for record in records:
        if record.kind == "directive" or record.repeat <= 0:
            continue
        span = None
        if record.source_start is not None and record.source_end is not None:
            span = _without_blanks_before_terminator(
                script[record.source_start : record.source_end], record
            )
        texts = (
            record.analysis_statements if record.analysis_statements is not None else (record.text,)
        )
        spans.extend((text, span) for text in texts)
    sources: List[Optional[str]] = []
    cursor = 0
    for text in statements:
        found = next((n for n in range(cursor, len(spans)) if spans[n][0] == text), None)
        if found is None:
            sources.append(None)
            continue
        sources.append(spans[found][1])
        cursor = found + 1
    return sources
