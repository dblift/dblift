"""Oracle SQL object extraction (Phase-Oracle-04 — ADR-0012).

Extracts tables, views, sequences, procedures/functions, and indexes
from Oracle SQL via regex, applying Oracle's case rules:

  * unquoted identifier  → upper-cased (Oracle folds unquoted names).
  * quoted identifier    → preserved verbatim.

Pure function, no class state. Patterns are compiled once at module
load.

All ADR-0012 §Follow-up quirks for this module are closed:

  * ``CREATE [GLOBAL|PRIVATE] TEMPORARY TABLE`` — the CREATE TABLE
    regex allows the optional ``GLOBAL TEMPORARY`` / ``PRIVATE
    TEMPORARY`` modifier, so the table name is extracted (PR-A).
  * ``CREATE [OR REPLACE] [[NO]FORCE] [NON]EDITIONABLE VIEW`` — the
    view regex allows the optional ``[NO]FORCE`` and
    ``[NON]EDITIONABLE`` modifiers (PR-A).
  * ``CREATE FUNCTION foo`` — own pattern, emitted as a
    :class:`Procedure` with ``is_function=True`` so ``object_type``
    is :attr:`SqlObjectType.FUNCTION` (PR-B).
  * Unqualified names + truthy ``default_schema`` — the legacy
    branching silently dropped the default; the ``_resolve_schema``
    helper now falls back to ``default_schema.upper()`` when neither
    capture group fires (PR-C).
"""

from __future__ import annotations

import re
from typing import Callable, List, Optional, Tuple

from dblift.core.sql_model.base import SqlObject
from dblift.core.sql_model.index import Index
from dblift.core.sql_model.procedure import Procedure
from dblift.core.sql_model.sequence import Sequence
from dblift.core.sql_model.table import Table
from dblift.core.sql_model.view import View

__all__ = ["extract_objects"]


# Schema-qualified-name shape: optional quoted-or-unquoted schema,
# followed by a quoted-or-unquoted name. Four capture groups:
#   (1) quoted schema   (2) unquoted schema
#   (3) quoted name     (4) unquoted name
_QUALIFIED_NAME = r'(?:(?:"([^"]+)"|([a-zA-Z0-9_$#]+))\.)?' r'(?:"([^"]+)"|([a-zA-Z0-9_$#]+))'

_TABLE_RE = re.compile(
    # `CREATE [GLOBAL|PRIVATE] TEMPORARY TABLE`, `ALTER TABLE`, `DROP TABLE`.
    # ALTER/DROP never carry the TEMPORARY modifier; the optional group
    # is scoped to the CREATE branch.
    rf"(?:CREATE(?:\s+(?:GLOBAL|PRIVATE)\s+TEMPORARY)?|ALTER|DROP)"
    rf"\s+TABLE\s+{_QUALIFIED_NAME}",
    re.IGNORECASE,
)
_VIEW_RE = re.compile(
    # `CREATE [OR REPLACE] [[NO]FORCE] [EDITIONABLE|NONEDITIONABLE] VIEW`.
    rf"CREATE\s+(?:OR\s+REPLACE\s+)?(?:(?:NO)?FORCE\s+)?"
    rf"(?:(?:NON)?EDITIONABLE\s+)?VIEW\s+{_QUALIFIED_NAME}",
    re.IGNORECASE,
)
_SEQUENCE_RE = re.compile(
    rf"CREATE\s+SEQUENCE\s+{_QUALIFIED_NAME}",
    re.IGNORECASE,
)
_PROCEDURE_RE = re.compile(
    rf"CREATE\s+(?:OR\s+REPLACE\s+)?PROCEDURE\s+{_QUALIFIED_NAME}",
    re.IGNORECASE,
)
_FUNCTION_RE = re.compile(
    rf"CREATE\s+(?:OR\s+REPLACE\s+)?FUNCTION\s+{_QUALIFIED_NAME}",
    re.IGNORECASE,
)


def _build_function(**kwargs: object) -> SqlObject:
    """Construct a :class:`Procedure` with ``is_function=True``.

    Both procedures and functions share the same concrete class but
    differ on the ``is_function`` flag (which drives
    ``object_type == SqlObjectType.FUNCTION``).
    """
    return Procedure(**kwargs, is_function=True)  # type: ignore[arg-type]


def _resolve_schema(
    quoted: Optional[str],
    unquoted: Optional[str],
    default_schema: Optional[str],
) -> Optional[str]:
    """Apply Oracle case rules to a captured schema with default fallback.

    * Quoted identifier → preserved verbatim.
    * Unquoted identifier → upper-cased (Oracle folds unquoted names).
    * Neither captured → fall back to ``default_schema`` (upper-cased
      under the same rule; the caller is expected to pass an unquoted
      schema name here).
    * No default either → ``None``.
    """
    if quoted is not None:
        return quoted
    if unquoted is not None:
        return unquoted.upper()
    if default_schema is not None:
        return default_schema.upper()
    return None


# Index: qualified index name + ON + qualified table name + ( columns ).
# Nine capture groups — the first eight mirror two `_QUALIFIED_NAME`
# blocks; the ninth is the column list.
_INDEX_RE = re.compile(
    r"CREATE\s+(?:UNIQUE\s+)?(?:BITMAP\s+)?INDEX\s+"
    + _QUALIFIED_NAME
    + r"\s+ON\s+"
    + _QUALIFIED_NAME
    + r"\s*\(\s*([^)]+)\s*\)",
    re.IGNORECASE,
)

# Patterns whose only per-kind difference is the SqlObject subclass.
# `Callable[..., SqlObject]` — not `Type[SqlObject]` — because each
# concrete subclass hardcodes ``object_type`` in its own ``__init__``
# signature, whereas the base class requires it. We only call the
# constructors with ``name=...`` and ``schema=...``.
_Builder = Callable[..., SqlObject]
_SIMPLE_PATTERNS: Tuple[Tuple[re.Pattern[str], _Builder], ...] = (
    (_TABLE_RE, Table),
    (_VIEW_RE, View),
    (_SEQUENCE_RE, Sequence),
    (_PROCEDURE_RE, Procedure),
    (_FUNCTION_RE, _build_function),
)


def extract_objects(sql: str, default_schema: Optional[str] = None) -> List[SqlObject]:
    """Extract SQL objects using regex patterns optimised for Oracle.

    Oracle case handling rules:

      * unquoted identifiers become upper-case in Oracle;
      * quoted identifiers preserve case exactly;
      * both the quoted and the unquoted spelling are extracted, and
        returned with the case they would have inside Oracle.
    """
    objects: List[SqlObject] = []

    for pattern, cls in _SIMPLE_PATTERNS:
        for match in pattern.finditer(sql):
            name = match.group(3) or match.group(4)
            if not name:
                continue

            if match.group(3):  # Quoted identifier
                actual_name = match.group(3)
            else:  # Unquoted identifier
                actual_name = match.group(4).upper()

            actual_schema = _resolve_schema(match.group(1), match.group(2), default_schema)

            objects.append(cls(name=actual_name, schema=actual_schema))

    # Indexes — pattern: CREATE [UNIQUE] [BITMAP] INDEX [schema.]index_name
    # ON [schema.]table_name (columns)
    for match in _INDEX_RE.finditer(sql):
        index_name = match.group(3) or match.group(4)
        table_name = match.group(7) or match.group(8)
        columns_str = match.group(9)

        if not (index_name and table_name):
            continue

        if match.group(3):  # Quoted index name
            actual_index_name = match.group(3)
        else:
            actual_index_name = match.group(4).upper()

        if match.group(7):  # Quoted table name
            actual_table_name = match.group(7)
        else:
            actual_table_name = match.group(8).upper()

        actual_index_schema = _resolve_schema(match.group(1), match.group(2), default_schema)
        actual_table_schema = _resolve_schema(match.group(5), match.group(6), default_schema)

        # Guard: skip empty column entries to avoid IndexError on split()[0].
        columns = [
            parts[0] for col in columns_str.split(",") if (parts := col.strip().strip('"').split())
        ]

        objects.append(
            Index(
                name=actual_index_name,
                table_name=actual_table_name,
                columns=columns,
                schema=actual_index_schema,
                table_schema=actual_table_schema,
            )
        )

    return objects
