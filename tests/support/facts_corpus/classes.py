"""The classes of difference between today's object extraction and the statement-facts reader.

A row is compared against each frozen extraction path (``hybrid`` and ``analyzer``) separately.
The first rule that matches wins, in the order of ``ORDER``:

1. ``raised`` -- a path, the DML helpers or the reader raised.
2. ``no-reader`` / ``no-old-side`` / ``no-old`` -- one side is missing.
3. ``dml-differs`` -- a statement-level field (target, predicate, events, columns, full-table)
   differs; no mechanical class below may hide it.
4. ``role-differs`` -- the statement acts on an object (creates, drops, alters, truncates it) that
   the reader marks only as read, or the reader marks as acted on an object the statement does
   not write to. The extraction carries no roles, so the statement itself is the reference.
5. ``same`` -- identities are equal (unless the reader is opaque and both name nothing).
6. The mechanical classes, each of which explains the whole difference by itself.
7. The classes that need a human reason: ``opaque-reader-gap``, ``facts-fewer``,
   ``facts-adds-acted``, ``disagree``.

Names are compared case-exact, after the schema the extraction assigns to an unqualified name is
removed from both sides. ``case-folded`` is the one exception and is directional: the facts name is
the spelling written in the statement, unquoted, the extraction holds the engine's folding of it,
and the reader is not opaque. Nothing here consults where a statement was harvested from.
"""

from __future__ import annotations

import functools
import logging
import re
from typing import Any, Collection, Dict, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError

RAISED = "raised"
SAME = "same"
NO_READER = "no-reader"
NO_OLD_SIDE = "no-old-side"
NO_OLD = "no-old"
DML_DIFFERS = "dml-differs"
ROLE_DIFFERS = "role-differs"
OLD_CTE_ALIAS = "old-cte-alias"
OLD_KEYWORD = "old-keyword"
TYPE_REFINED = "type-refined"
QUOTE_DECODED = "quote-decoded"
CASE_FOLDED = "case-folded"
FACTS_ADDS_REFERENCED = "facts-adds-referenced"
OPAQUE_SAFETY = "opaque-safety"
OPAQUE_BOTH_EMPTY = "opaque-both-empty"
OPAQUE_READER_GAP = "opaque-reader-gap"
FACTS_FEWER = "facts-fewer"
FACTS_ADDS_ACTED = "facts-adds-acted"
DISAGREE = "disagree"

MECHANICAL = (
    OLD_CTE_ALIAS,
    OLD_KEYWORD,
    TYPE_REFINED,
    QUOTE_DECODED,
    CASE_FOLDED,
    FACTS_ADDS_REFERENCED,
    OPAQUE_SAFETY,
    OPAQUE_BOTH_EMPTY,
)
#: Classes that need a reason in the family's review file.
REVIEW = (
    DML_DIFFERS,
    ROLE_DIFFERS,
    OPAQUE_READER_GAP,
    FACTS_FEWER,
    FACTS_ADDS_ACTED,
    DISAGREE,
    NO_OLD,
    NO_READER,
)
ORDER = (
    (RAISED, NO_READER, NO_OLD_SIDE, NO_OLD, DML_DIFFERS, ROLE_DIFFERS, SAME)
    + MECHANICAL
    + (OPAQUE_READER_GAP, FACTS_FEWER, FACTS_ADDS_ACTED, DISAGREE)
)
PATHS = ("hybrid", "analyzer")

#: Families whose text extraction already is the facts reader: there is nothing to compare.
NO_OLD_FAMILIES = ("sqlite", "duckdb")
#: The sqlglot dialect of each family (``None``: no grammar).
DIALECTS: Dict[str, Optional[str]] = {
    "postgresql": "postgres",
    "mysql": "mysql",
    "oracle": "oracle",
    "sqlserver": "tsql",
    "sqlite": "sqlite",
    "duckdb": "duckdb",
    "redshift": "redshift",
    "snowflake": "snowflake",
    "db2": None,
}
#: The schema the text extraction gives a name written without one.
DEFAULT_SCHEMA: Dict[str, Optional[str]] = {
    "postgresql": "public",
    "redshift": "public",
    "sqlserver": "dbo",
}
#: The direction an engine folds an unquoted name. MySQL and SQL Server fold by setting or
#: collation, so a case-only difference is never accepted there.
FOLD: Dict[str, Optional[str]] = {
    "postgresql": "lower",
    "redshift": "lower",
    "oracle": "upper",
    "snowflake": "upper",
    "db2": "upper",
}
#: ``old`` type -> the facts types it may become without the name changing.
REFINEMENTS = {"VIEW": ("MATERIALIZED_VIEW",)}
ACTED_ROLES = ("created", "altered", "dropped")
UNREAD_NAME_MARK = "may read as part of a name"
_QUOTE_PAIRS = (('"', '"'), ("`", "`"), ("[", "]"))
_ANALYZER_PLACEHOLDER = "default_schema."

Identity = Tuple[str, str]  # (type, qualified name)


def _facts_identities(facts: Dict[str, Any], default: Optional[str]) -> Dict[Identity, Set[str]]:
    found: Dict[Identity, Set[str]] = {}
    for name, kind, role, schema in facts.get("objects", []):
        qualified = name if schema in (None, default) else f"{schema}.{name}"
        found.setdefault((kind, qualified), set()).add(role)
    return found


def _old_identities(path: str, value: List[Any], default: Optional[str]) -> Set[Identity]:
    found: Set[Identity] = set()
    for entry in value:
        if path == "hybrid":
            kind, name, schema = entry
            found.add((kind, name if schema in (None, default) else f"{schema}.{name}"))
            continue
        kind, qualified = entry
        for prefix in (_ANALYZER_PLACEHOLDER, f"{default}." if default else None):
            if prefix and qualified.startswith(prefix):
                qualified = qualified[len(prefix) :]
                break
        found.add((kind, qualified))
    return found


def _facts_dml(facts: Dict[str, Any]) -> Dict[str, Any]:
    """The statement-level fields a consumer reads from the reader."""
    events = sorted(facts["events"]) if facts.get("events") else None
    predicate = facts.get("predicate")
    return {
        "table": facts.get("target_sql") or "",
        "events": events,
        "updated_columns": (
            list(facts.get("affected_columns", [])) if events and "UPDATE" in events else []
        ),
        "predicate": predicate,
        "full_table": facts.get("operation") in ("UPDATE", "DELETE") and not predicate,
    }


def _quoted_in(sql: str, part: str) -> bool:
    return any(
        re.search(re.escape(o) + re.escape(part) + re.escape(c), sql, re.IGNORECASE)
        for o, c in _QUOTE_PAIRS
    )


def _unquoted(sql: str, qualified: str) -> bool:
    return not any(_quoted_in(sql, part) for part in qualified.split("."))


@functools.lru_cache(maxsize=4096)
def _parse(sql: str, dialect: Optional[str]) -> Optional[exp.Expression]:
    log = logging.getLogger("sqlglot")
    level = log.level
    log.setLevel(logging.ERROR)  # a Command fallback is expected here and not worth a warning
    try:
        return sqlglot.parse_one(sql, read=dialect)
    except SqlglotError:
        return None
    finally:
        log.setLevel(level)


Targets = Tuple[Set[str], Set[str]]  # (acted on, possibly written to), lower-cased names

#: Statements that write somewhere; every other statement that is not a query is unreadable here.
_WRITES = (
    exp.Create,
    exp.Alter,
    exp.Drop,
    exp.TruncateTable,
    exp.Insert,
    exp.MultitableInserts,
    exp.Update,
    exp.Delete,
    exp.Merge,
    exp.Copy,
    exp.LoadData,
)


def _names_of(node: Optional[exp.Expression]) -> Targets:
    """``(acted, touched)`` for one expression a statement writes to.

    ``acted`` holds only names certain to be created, dropped or altered; ``touched`` also holds
    every table the expression mentions (a join, the table an index is on).
    """
    if isinstance(node, (exp.Schema, exp.UserDefinedFunction)):
        node = node.this
    if node is None:
        return set(), set()
    touched = {t.name.lower() for t in node.find_all(exp.Table) if t.name}
    if isinstance(node, exp.Index) and node.this is not None:
        node = node.this
    own = (
        {node.name.lower()} - {""}
        if isinstance(node, (exp.Table, exp.Identifier, exp.Var, exp.Column))
        else set()
    )
    return own, touched | own


def _write_node(node: exp.Expression) -> Targets:
    acted: Set[str] = set()
    touched: Set[str] = set()

    def add(item: Optional[exp.Expression], certain: bool = True) -> None:
        names, mentioned = _names_of(item)
        acted.update(names if certain else ())
        touched.update(mentioned)

    if isinstance(node, (exp.Drop, exp.TruncateTable)):
        for item in node.args.get("tables" if isinstance(node, exp.Drop) else "expressions") or []:
            add(item)
        add(node.args.get("cluster"), certain=False)
    elif isinstance(node, (exp.Copy, exp.LoadData)):
        add(node.this, certain=False)  # COPY reads or writes by direction
    else:
        add(node.this)
        if isinstance(node, exp.Delete):
            for item in node.args.get("tables") or []:
                add(item)
        if isinstance(node, exp.Create):
            add(node.args.get("properties"), certain=False)
        if isinstance(node, exp.Alter):
            for action in node.args.get("actions") or []:
                if isinstance(action, (exp.AlterRename, exp.SwapTable)):
                    add(action.this)
    return acted, touched


#: Families where ``SELECT ... INTO name`` creates a table (elsewhere it assigns a variable).
SELECT_INTO_CREATES = ("postgresql", "redshift", "sqlserver")


def _targets(ast: Optional[exp.Expression], family: str) -> Optional[Targets]:
    """What the statement writes to; ``None`` when that cannot be established.

    Covers every write form sqlglot has: CREATE, ALTER (including RENAME TO and SWAP WITH), DROP and
    TRUNCATE of several tables, INSERT (also ``INSERT ALL``), UPDATE and DELETE (also the
    multi-table forms), MERGE, COPY, and ``SELECT ... INTO``. A statement that is neither a query
    nor one of those (a ``Command`` fallback, ``COMMENT``, ``GRANT``) is unreadable, and so is a
    write that yields no name. A statement nested in a ``CREATE`` (a routine body) is not run by
    it, so it only adds to what is possibly written.
    """
    if ast is None or not isinstance(ast, (exp.Query,) + _WRITES):
        return None
    acted: Set[str] = set()
    touched: Set[str] = set()
    found = False
    for node in ast.walk():
        if isinstance(node, _WRITES):
            found = True
            names, mentioned = _write_node(node)
        elif isinstance(node, exp.Into):
            names, mentioned = _names_of(node.this)
            names = names if family in SELECT_INTO_CREATES else set()
        else:
            continue
        acted |= names if node is ast or not isinstance(ast, exp.Create) else set()
        touched |= mentioned
    if (found or isinstance(ast, _WRITES)) and not touched:
        return None
    return acted, touched


def _dml_names(dml_table: str) -> Set[str]:
    return {part.strip('"`[]').lower() for part in dml_table.split(".")} - {""}


def _write_targets(
    ast: Optional[exp.Expression], family: str, dml_table: str
) -> Optional[Set[str]]:
    """Lower-cased names the statement may write to; ``None`` when they cannot be established."""
    targets = _targets(ast, family)
    return None if targets is None else targets[1] | _dml_names(dml_table)


def _roles_differ(
    ast: Optional[exp.Expression], family: str, facts: Dict[str, Any], dml_table: str
) -> bool:
    """An object the statement acts on is only read by the reader, or the reverse."""
    targets = _targets(ast, family)
    if ast is None or targets is None:
        return False
    acted, touched = targets
    read = {t.name.lower() for t in ast.find_all(exp.Table)} - touched - _dml_names(dml_table)
    roles: Dict[str, Set[str]] = {}
    for name, _kind, role, _schema in facts.get("objects", []):
        roles.setdefault(name.lower(), set()).add(role)
    return any(
        (name in acted and found == {"referenced"}) or (name in read and found & set(ACTED_ROLES))
        for name, found in roles.items()
    )


def _bijection(a: Set[Identity], b: Set[Identity], pair) -> bool:
    """Whether every identity of ``a`` pairs with a distinct one of ``b`` and none is left."""
    if not a or len(a) != len(b):
        return False
    remaining = set(b)
    for item in sorted(a):
        match = next((other for other in sorted(remaining) if pair(item, other)), None)
        if match is None:
            return False
        remaining.discard(match)
    return not remaining


def _fold(family: str, name: str) -> Optional[str]:
    direction = FOLD.get(family)
    if direction is None:
        return None
    return name.lower() if direction == "lower" else name.upper()


def _spelled_unquoted(sql: str, name: str) -> bool:
    """Every part of ``name`` is written exactly so in the statement, and never quoted."""
    return all(
        re.search(r"(?<![\w$#\"`\[])" + re.escape(part) + r"(?![\w$#\"`\]])", sql)
        and not _quoted_in(sql, part)
        for part in name.split(".")
    )


def _case_folded(sql: str, family: str, opaque: bool, old: Identity, new: Identity) -> bool:
    """The reader keeps the unquoted spelling of the statement; the extraction holds the engine's
    folding of it. Never the reverse, and never from an opaque reader."""
    return (
        not opaque
        and old[0] == new[0]
        and old[1] != new[1]
        and _fold(family, new[1]) == old[1]
        and _spelled_unquoted(sql, new[1])
    )


def _quote_decoded(sql: str, old: Identity, new: Identity) -> bool:
    cut = len(old[1])
    quote = new[1][cut : cut + 1]
    return (
        old[0] == new[0]
        and new[1].startswith(old[1])
        and quote in ('"', "`", "]")
        and quote * 2 in sql
    )


def _type_refined(old: Identity, new: Identity) -> bool:
    if old[1] != new[1] or old[0] == new[0]:
        return False
    return old[0] == "UNKNOWN" or new[0] in REFINEMENTS.get(old[0], ())


def _old_cte_alias(sql: str, family: str, missing: Set[Identity], dml_table: str) -> bool:
    """Every name the reader does not have is a CTE alias, and none is written to."""
    ast = _parse(sql, DIALECTS[family])
    targets = _write_targets(ast, family, dml_table)
    if ast is None or targets is None:
        return False
    aliases = {cte.alias.lower() for cte in ast.find_all(exp.CTE)}
    names = {item[1].lower() for item in missing}
    return names <= aliases and not names & targets


def _old_keyword(
    sql: str,
    family: str,
    missing: Set[Identity],
    new: Dict[Identity, Set[str]],
    reserved: Collection[str],
    dml_table: str,
) -> bool:
    """Every name the reader does not have is an unquoted word the engine reserves, none is
    written to, and the reader (not opaque) names everything else."""
    targets = _write_targets(_parse(sql, DIALECTS[family]), family, dml_table)
    words = {word.upper() for word in reserved}
    return (
        targets is not None
        and bool(new)
        and all(
            item[1].upper() in words and _unquoted(sql, item[1]) and item[1].lower() not in targets
            for item in missing
        )
    )


def _mechanical(
    sql: str,
    family: str,
    facts: Dict[str, Any],
    old: Set[Identity],
    new: Dict[Identity, Set[str]],
    reserved: Collection[str],
    dml_table: str,
) -> Optional[str]:
    """The mechanical class that explains the whole difference, if one does."""
    missing = old - set(new)  # named by the extraction, not by the reader
    extra = set(new) - old  # named by the reader, not by the extraction
    opaque = "diagnostic" in facts or "error" in facts
    if missing and not extra:
        if _old_cte_alias(sql, family, missing, dml_table):
            return OLD_CTE_ALIAS
        if not opaque and _old_keyword(sql, family, missing, new, reserved, dml_table):
            return OLD_KEYWORD
    if missing and extra:
        if _bijection(missing, extra, _type_refined):
            return TYPE_REFINED
        if _bijection(missing, extra, lambda o, n: _quote_decoded(sql, o, n)):
            return QUOTE_DECODED
        if _bijection(missing, extra, lambda o, n: _case_folded(sql, family, opaque, o, n)):
            return CASE_FOLDED
    if extra and not missing and all(new[item] == {"referenced"} for item in extra):
        return FACTS_ADDS_REFERENCED
    if opaque and UNREAD_NAME_MARK in facts.get("diagnostic", ""):
        return OPAQUE_SAFETY
    if opaque and not old and not new:
        return OPAQUE_BOTH_EMPTY
    return None


def classify(
    sql: str,
    facts: Optional[Dict[str, Any]],
    old: Optional[Dict[str, Any]],
    family: str,
    reserved: Collection[str],
    path: str,
) -> str:
    """The class of one statement against one frozen extraction path (``hybrid``/``analyzer``)."""
    dml = old.get("dml") if old else None
    if isinstance(facts, dict) and "raised" in facts:
        return RAISED
    if old and any(
        isinstance(old.get(key), dict) and "raised" in old[key] for key in (path, "dml")
    ):
        return RAISED
    if facts is None:
        return NO_READER
    if old is None:
        return NO_OLD_SIDE if family in NO_OLD_FAMILIES else NO_OLD
    default = DEFAULT_SCHEMA.get(family)
    if dml is not None and _facts_dml(facts) != {
        "table": dml["table"],
        "events": dml["events"],
        "updated_columns": dml["updated_columns"],
        "predicate": dml["predicate"],
        "full_table": dml["full_table"],
    }:
        return DML_DIFFERS
    if _roles_differ(_parse(sql, DIALECTS[family]), family, facts, dml["table"] if dml else ""):
        return ROLE_DIFFERS
    before = _old_identities(path, old[path], default)
    after = _facts_identities(facts, default)
    opaque = "diagnostic" in facts or "error" in facts
    if before == set(after) and (before or not opaque):
        return SAME  # an opaque reader that names nothing is not agreement; see OPAQUE_BOTH_EMPTY
    mechanical = _mechanical(
        sql, family, facts, before, after, reserved, dml["table"] if dml else ""
    )
    if mechanical is not None:
        return mechanical
    missing = before - set(after)
    extra = set(after) - before
    if opaque and before:
        return OPAQUE_READER_GAP
    if missing and not extra:
        return FACTS_FEWER
    if extra and not missing:
        return FACTS_ADDS_ACTED
    return DISAGREE


def classify_row(row: Dict[str, Any], family: str, reserved: Collection[str]) -> Dict[str, str]:
    """The class of a corpus row (already reduced to one arm) against each extraction path."""
    return {
        path: classify(row["sql"], row["facts"], row["old"], family, reserved, path)
        for path in PATHS
    }
