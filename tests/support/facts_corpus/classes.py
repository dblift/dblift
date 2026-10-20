"""The classes of difference between today's object extraction and the statement-facts reader.

A row is compared against each frozen extraction path (``hybrid`` and ``analyzer``) separately.
The first rule that matches wins, in the order of ``ORDER``:

1. ``raised`` -- a path, the DML helpers or the reader raised.
2. ``no-reader`` / ``no-old-side`` / ``no-old`` -- one side is missing.
3. ``dml-differs`` -- a statement-level field (target, predicate, events, columns, full-table)
   differs; no mechanical class below may hide it.
4. ``role-differs`` -- a name the statement mentions carries another role in the facts than in the
   statement: created, dropped or altered (a truncated table and a DML target are altered), or only
   referenced (the table under an index, a joined table, a COPY source, a foreign key target). The
   extraction carries no roles, so the statement itself is the reference. A name is its schema and
   its name: the same name in two schemas is two objects, each judged on its own. A rename target
   may be created or altered (the facts have no ``renamed`` role); the body of a stored routine is
   not run by its creation and is not judged, but the query of ``CREATE ... AS`` is.
5. ``same`` -- identities are equal (unless the reader is opaque and both name nothing).
6. The mechanical classes, each of which explains the whole difference by itself.
7. The classes that need a human reason: ``opaque-reader-gap``, ``facts-fewer``,
   ``facts-adds-acted``, ``disagree``.

Names are compared case-exact, after the schema the extraction assigns to an unqualified name is
removed from both sides. ``case-folded`` is the one exception and is directional: the facts name is
the spelling written in the statement, unquoted, the extraction holds the engine's folding of it,
and the reader is not opaque. For a family in ``READER_FOLDS`` (the reader folds the name itself)
the direction is the reverse: the facts hold the folded name and the extraction the spelling.
Nothing here consults where a statement was harvested from.
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
    "db2": "SYSIBM",
}
#: The direction an engine folds an unquoted name, as the plugin quirks' ``unquoted_identifier_case``
#: says (a test ties the two). MySQL (``lower_case_table_names``) and SQL Server (the collation)
#: fold by setting, which the quirks reduce to a default; the corpus cannot know the setting, so
#: a case-only difference is never accepted there.
FOLD: Dict[str, Optional[str]] = {
    "postgresql": "lower",
    "redshift": "lower",
    "oracle": "upper",
    "snowflake": "upper",
    "db2": "upper",
}
#: ``old`` type -> the facts types it may become without the name changing.
REFINEMENTS = {"VIEW": ("MATERIALIZED_VIEW",)}
#: Families whose reader folds the name itself: the facts hold the folded name and the extraction the
#: spelling written in the statement, the reverse of every other family.
READER_FOLDS = frozenset({"db2"})
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


def _after_dot(sql: str, ast: Optional[exp.Expression], word: str) -> bool:
    """The word follows a dot: a reserved word is a legal name there (``schema.order``).

    Where the statement parses, a table of this name with a schema says so, whatever sits between
    the dot and the word (a comment), and a dot in a literal or comment says nothing. The text is
    searched only when there is no parse or the statement creates a procedure, function or trigger,
    whose body the parse holds as a string (``$$ ... $$``); a dot in a literal then refuses too,
    and the row gets a reason.
    """
    if ast is not None and not _is_routine(ast):
        return any(
            t.name.lower() == word.lower() and t.args.get("db") is not None
            for t in ast.find_all(exp.Table)
        )
    return re.search(r"\.\s*" + re.escape(word) + r"(?![\w$])", sql, re.IGNORECASE) is not None


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
    if isinstance(node, (exp.Schema, exp.UserDefinedFunction, exp.OnProperty)):
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
    write that yields no name. A statement nested in a ``CREATE`` of a stored routine is not run
    by it, so it only adds to what is possibly written.
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
        acted |= names if node is ast or not _is_routine(ast) else set()
        touched |= mentioned
    if (found or isinstance(ast, _WRITES)) and not touched:
        return None
    return acted, touched


#: What sqlglot calls the ``kind`` of a ``CREATE`` whose body is stored, not run (``PROC`` is T-SQL).
_ROUTINE_KINDS = frozenset({"PROCEDURE", "PROC", "FUNCTION", "TRIGGER"})


def _is_routine(ast: exp.Expression) -> bool:
    """A ``CREATE`` of a procedure, function or trigger: its body is stored, not run.

    A table, a view or ``CREATE TABLE ... AS <query>`` is read from its parse like any statement.
    """
    return isinstance(ast, exp.Create) and str(ast.args.get("kind") or "").upper() in _ROUTINE_KINDS


def _dml_names(dml_table: str) -> Set[str]:
    return {part.strip('"`[]').lower() for part in dml_table.split(".")} - {""}


def _write_targets(
    ast: Optional[exp.Expression], family: str, dml_table: str
) -> Optional[Set[str]]:
    """Lower-cased names the statement may write to; ``None`` when they cannot be established."""
    targets = _targets(ast, family)
    return None if targets is None else targets[1] | _dml_names(dml_table)


def _subject(item: Optional[exp.Expression]) -> Optional[exp.Expression]:
    """The node carrying the name of a written object (``Schema``, function and index unwrapped)."""
    if isinstance(item, (exp.Schema, exp.UserDefinedFunction, exp.StoredProcedure)):
        item = item.this
    return item.this if isinstance(item, exp.Index) else item


def _index_on(subject: Optional[exp.Expression]) -> Optional[exp.Expression]:
    """The table of ``CREATE INDEX schema.index ON table``, which sqlglot reads as an index named
    by the schema, on a table named by the index, with the real table as an ``ON`` argument."""
    params = subject.args.get("params") if isinstance(subject, exp.Index) else None
    return params.args.get("on") if params is not None else None


RoleKey = Tuple[Optional[str], str]  # (schema, name), lower-cased, the default schema removed


def _role_key(schema: Optional[str], name: str, family: str) -> RoleKey:
    schema = (schema or "").lower()
    return (None if schema in ("", (DEFAULT_SCHEMA.get(family) or "").lower()) else schema), (
        name.lower()
    )


def _expected_roles(
    ast: Optional[exp.Expression], family: str
) -> Optional[Dict[RoleKey, Set[str]]]:
    """The roles the statement gives each name it mentions; ``None`` when it cannot be read.

    A name is a schema and a name: ``archive.orders`` and ``public.orders`` are two objects, and the
    schema the extraction assigns to an unqualified name is removed, as for identities. A written
    object is created, dropped or altered (a truncated table and a DML target are altered, as the
    reader says); every other table is only referenced, the table under an index, a joined table, a
    COPY source and a foreign key target included. A rename target may be read as created or
    altered: the facts have no ``renamed`` role, and the reader does not emit the target today. A
    name written only inside a routine body has no role here: creating the routine does not run it.
    """
    if ast is None or _targets(ast, family) is None:
        return None
    roles: Dict[RoleKey, Set[str]] = {}
    free: Set[RoleKey] = set()
    given: Set[int] = set()

    def key_of(node: exp.Expression, schema: Optional[str] = None) -> RoleKey:
        parts = (
            [node.args.get("catalog"), node.args.get("db")] if isinstance(node, exp.Table) else []
        )
        written = ".".join(part.name for part in parts if part is not None)
        return _role_key(schema or written, node.name, family)

    def give(
        item: Optional[exp.Expression],
        allowed: Set[str],
        nested: bool = False,
        schema: Optional[str] = None,
    ) -> None:
        node = _subject(item)
        if not isinstance(node, (exp.Table, exp.Identifier, exp.Var, exp.Column)) or not node.name:
            return
        given.add(id(node))
        key = key_of(node, schema)
        if nested:
            free.add(key)
        else:
            roles.setdefault(key, set()).update(allowed)

    for node in ast.walk():
        nested = node is not ast and _is_routine(ast)
        if isinstance(node, exp.Drop):
            for item in node.args.get("tables") or node.args.get("expressions") or [node.this]:
                give(item, {"dropped"}, nested)
            on = node.args.get("cluster")  # DROP INDEX ix ON t
            on = on.this if isinstance(on, exp.OnProperty) else None
            if isinstance(on, (exp.Table, exp.Identifier)) and on.name and not nested:
                roles.setdefault(key_of(on), set()).add("referenced")
        elif isinstance(node, exp.TruncateTable):
            for item in node.expressions:
                give(item, {"altered"}, nested)
        elif isinstance(node, exp.Create):
            on = _index_on(node.this)
            if on is None:
                give(node.this, {"created"}, nested)
            else:  # sqlglot reads the schema as the index and the index as the table
                index = node.this
                give(index.args.get("table"), {"created"}, nested, schema=index.this.name)
                if on.name and not nested:
                    roles.setdefault(key_of(on), set()).add("referenced")
        elif isinstance(node, exp.Alter):
            give(node.this, {"altered"}, nested)
            for action in node.args.get("actions") or []:
                if isinstance(action, exp.AlterRename):
                    give(action.this, {"created", "altered"}, nested)
                elif isinstance(action, exp.SwapTable):
                    give(action.this, {"altered"}, nested)
        elif isinstance(node, exp.Delete):
            for item in [node.this] + list(node.args.get("tables") or []):
                give(item, {"altered"}, nested)
        elif isinstance(node, (exp.Insert, exp.Update, exp.Merge, exp.LoadData)):
            give(node.this, {"altered"}, nested)
        elif isinstance(node, exp.Copy) and node.args.get("kind"):
            give(node.this, {"altered"}, nested)  # COPY ... FROM imports; TO only reads
        elif isinstance(node, exp.Into):
            give(node.this, {"created"}, nested or family not in SELECT_INTO_CREATES)
    for table in ast.find_all(exp.Table):
        if table.name and id(table) not in given:
            roles.setdefault(key_of(table), set()).add("referenced")
    return {key: allowed for key, allowed in roles.items() if key not in free}


def _roles_differ(ast: Optional[exp.Expression], family: str, facts: Dict[str, Any]) -> bool:
    """For a name the statement mentions, the reader's role is not the statement's.

    Wrong when the reader gives a role the statement does not, or only reads an object the
    statement creates, drops or alters. A name is matched by schema (catalog and schema for a
    three-part name); when only one side qualifies it, by its bare name if exactly one name of the
    statement has that spelling. With two (``archive.orders``, ``public.orders``) the reader's bare
    name cannot be attributed and is not judged.
    """
    expected = _expected_roles(ast, family)
    if expected is None:
        return False
    spelled: Dict[str, List[RoleKey]] = {}
    for key in expected:
        spelled.setdefault(key[1], []).append(key)
    found: Dict[RoleKey, Set[str]] = {}
    for name, _kind, role, schema in facts.get("objects", []):
        key = _role_key(schema, name, family)
        if key not in expected:  # qualified on one side only: the bare name, if it is unambiguous
            key = spelled[key[1]][0] if len(spelled.get(key[1], ())) == 1 else key
        found.setdefault(key, set()).add(role)
    return any(
        got - expected[key] or (expected[key] & set(ACTED_ROLES) and got <= {"referenced"})
        for key, got in found.items()
        if key in expected
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


def _name_identifiers(ast: Optional[exp.Expression]) -> Tuple[Set[str], Set[str]]:
    """``(unquoted, quoted)`` identifiers that name an object in the statement: the parts of every
    table and the name of what a statement creates, drops or alters (not a column, literal or
    comment)."""
    parts: List[exp.Expression] = []
    for table in (ast.find_all(exp.Table) if ast is not None else ()):
        parts += [table.args.get(key) for key in ("this", "db", "catalog")]
    for node in ast.walk() if ast is not None else ():
        if isinstance(node, (exp.Create, exp.Alter)):
            parts.append(_subject(node.this))
    names = [part for part in parts if isinstance(part, exp.Identifier)]
    return (
        {part.name for part in names if not part.args.get("quoted")},
        {part.name for part in names if part.args.get("quoted")},
    )


def _spelled_unquoted(ast: Optional[exp.Expression], name: str) -> bool:
    """Every part of ``name`` is written exactly so as an unquoted object name in the statement,
    and never quoted: a quoted spelling of it is another object."""
    unquoted, quoted = _name_identifiers(ast)
    return all(part in unquoted and part not in quoted for part in name.split("."))


def _case_folded(
    ast: Optional[exp.Expression], family: str, opaque: bool, old: Identity, new: Identity
) -> bool:
    """The reader keeps the unquoted spelling of the statement; the extraction holds the engine's
    folding of it. The reverse only for a family in ``READER_FOLDS``, and never from an opaque
    reader."""
    if opaque or old[0] != new[0] or old[1] == new[1]:
        return False
    if family in READER_FOLDS:
        return _fold(family, old[1]) == new[1] and _spelled_unquoted(ast, old[1])
    return _fold(family, new[1]) == old[1] and _spelled_unquoted(ast, new[1])


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
    written to, and the reader (not opaque) names everything else. A word after a dot is a name:
    ``schema.order`` is an object the reader lost."""
    ast = _parse(sql, DIALECTS[family])
    targets = _write_targets(ast, family, dml_table)
    words = {word.upper() for word in reserved}
    return (
        targets is not None
        and bool(new)
        and all(
            item[1].upper() in words
            and _unquoted(sql, item[1])
            and not _after_dot(sql, ast, item[1])
            and item[1].lower() not in targets
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
        ast = _parse(sql, DIALECTS[family])
        if _bijection(missing, extra, _type_refined):
            return TYPE_REFINED
        if _bijection(missing, extra, lambda o, n: _quote_decoded(sql, o, n)):
            return QUOTE_DECODED
        if _bijection(missing, extra, lambda o, n: _case_folded(ast, family, opaque, o, n)):
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
    if _roles_differ(_parse(sql, DIALECTS[family]), family, facts):
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
