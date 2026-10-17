"""Record statement facts and the frozen text extraction for every family statement."""

from __future__ import annotations

import functools
import re
from typing import Any, Dict, List, Optional

from tests.support.facts_corpus.canonical import compact_facts
from tests.support.facts_corpus.classes import NO_OLD_FAMILIES
from tests.support.facts_corpus.seed import split

_DML_HEAD = re.compile(r"(INSERT|UPDATE|DELETE|MERGE|WITH|REPLACE)\b", re.IGNORECASE)


def check_arm(arm: str, installed: str, versions: Dict[str, Any]) -> None:
    """Raise unless the installed sqlglot is the one recorded for ``arm``."""
    if arm not in ("floor", "newest"):
        raise RuntimeError(f"unknown arm {arm!r}")
    if installed != versions[arm]:
        raise RuntimeError(
            f"arm {arm!r} records sqlglot {versions[arm]}, but {installed} is installed"
        )


@functools.lru_cache(maxsize=None)
def _quirks(family: str):
    from dblift.db.provider_registry import ProviderRegistry

    return ProviderRegistry.get_quirks(family)


@functools.lru_cache(maxsize=None)
def _factory(family: str):
    from dblift.core.sql_parser.parser_factory import SqlParserFactory

    return SqlParserFactory(family)


@functools.lru_cache(maxsize=None)
def _analyzer(family: str):
    from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer

    return SqlAnalyzer(family)


@functools.lru_cache(maxsize=None)
def _reader(family: str):
    from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader

    return SqlglotStatementFactsReader(_quirks(family).sqlglot_dialect)


def _guarded(call) -> Any:
    try:
        return call()
    except Exception as exc:  # recorded, never raised: a crash is data for the comparison
        return {"raised": f"{type(exc).__name__}: {exc}"}


def _read_facts(family: str, sql: str) -> Any:
    quirks = _quirks(family)
    if quirks.sqlglot_dialect is None and not quirks.supports_statement_facts:
        return None
    if quirks.supports_statement_facts:
        return compact_facts(quirks.statement_facts(sql))
    return compact_facts(_reader(family).read(sql))


def _dml(family: str, sql: str) -> Dict[str, Any]:
    quirks = _quirks(family)
    mutation = quirks.analyze_dml(sql)
    return {
        "table": quirks.statement_dml_table(sql),
        "events": sorted(mutation.events) if mutation.events else None,
        "updated_columns": list(mutation.updated_columns),
        "predicate": quirks.dml_where_predicate(sql),
        "full_table": quirks.is_full_table_dml(sql),
    }


def _read_old(family: str, sql: str) -> Optional[Dict[str, Any]]:
    from dblift.db.dml_analysis import strip_leading_sql_comments

    if _quirks(family).supports_statement_facts:
        return None
    old: Dict[str, Any] = {
        "hybrid": _guarded(
            lambda: [
                [o.object_type.value, o.name, o.schema]
                for o in _factory(family).extract_objects(sql)
            ]
        ),
        "analyzer": _guarded(
            lambda: [
                [o["object_type"], o["object_name"]] for o in _analyzer(family).extract_objects(sql)
            ]
        ),
    }
    if _DML_HEAD.match(strip_leading_sql_comments(sql).lstrip()):
        old["dml"] = _guarded(lambda: _dml(family, sql))
    return old


def record_statement(family: str, sql: str) -> Dict[str, Any]:
    """Return ``facts`` and ``old`` for one statement on the running sqlglot."""
    return {"facts": _guarded(lambda: _read_facts(family, sql)), "old": _read_old(family, sql)}


def _statements(family: str, inputs: List[Dict[str, Any]]) -> Dict[str, List[str]]:
    found: Dict[str, List[str]] = {}
    for row in inputs:
        try:
            pieces = split(family, row["sql"])
        except Exception:  # the splitter refuses some scripts; it has its own gates
            continue
        for piece in pieces:
            if piece.strip():
                ids = found.setdefault(piece, [])
                if row["id"] not in ids:
                    ids.append(row["id"])
    return {sql: sorted(ids) for sql, ids in found.items()}


def normalise(sql: str) -> str:
    """The statement without outer blanks and one trailing terminator."""
    text = sql.strip()
    return text[:-1].rstrip() if text.endswith(";") else text


def is_frozen(family: str) -> bool:
    """Whether the family reads its statements through the reader while still having a recorded
    extraction: that extraction can no longer be recomputed and is only ever carried."""
    return family not in NO_OLD_FAMILIES and _quirks(family).supports_statement_facts


def _carried(
    statements: Dict[str, List[str]], existing: List[Dict[str, Any]]
) -> Dict[str, Dict[str, Any]]:
    """The recorded extraction of each statement: its own row's, else that of a row the split no
    longer produces whose normalised text is the same, else ``None``."""
    kept = {row["sql"]: row for row in existing}
    gone: Dict[str, Dict[str, Any]] = {}
    for sql in sorted(kept):
        if sql not in statements:
            gone.setdefault(normalise(sql), kept[sql])
    found = {}
    for sql in statements:
        source = kept.get(sql) or gone.get(normalise(sql))
        found[sql] = (
            {k: source[k] for k in ("old", "old_newest") if k in source}
            if source
            else {"old": None}
        )
    return found


def record_family(
    family: str,
    arm: str,
    inputs: List[Dict[str, Any]],
    existing: List[Dict[str, Any]],
    frozen: bool = False,
) -> List[Dict[str, Any]]:
    """Return the rows of a family after recording one sqlglot arm.

    The floor arm (re)creates every row; the newest arm adds ``facts_newest`` / ``old_newest``
    only where its output differs from the floor row. A family whose extraction is frozen is only
    recorded with ``frozen=True``: its facts are read again, its extraction is carried over.
    """
    if is_frozen(family) and not frozen:
        raise RuntimeError(
            f"{family}: the recorded extraction is frozen; record it with --frozen "
            "(facts are read again, the extraction is carried over)"
        )
    if frozen and not is_frozen(family):
        raise RuntimeError(f"{family} is not activated: record it without --frozen")
    statements = _statements(family, inputs)
    if arm == "floor":
        carried = _carried(statements, existing) if frozen else {}
        return [
            {
                "sql": sql,
                "inputs": ids,
                **(
                    {"facts": _guarded(lambda: _read_facts(family, sql)), **carried[sql]}
                    if frozen
                    else record_statement(family, sql)
                ),
            }
            for sql, ids in sorted(statements.items())
        ]
    if {row["sql"] for row in existing} != set(statements):
        raise ValueError("record the floor arm first: its rows do not match the inputs")
    rows = []
    for row in existing:
        drop = ("facts_newest",) if frozen else ("facts_newest", "old_newest")
        row = {k: v for k, v in row.items() if k not in drop}
        facts = _guarded(lambda: _read_facts(family, row["sql"]))
        if facts != row["facts"]:
            row["facts_newest"] = facts
        if not frozen:
            old = _read_old(family, row["sql"])
            if old != row["old"]:
                row["old_newest"] = old
        rows.append(row)
    return rows
