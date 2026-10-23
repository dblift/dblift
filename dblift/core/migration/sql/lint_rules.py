"""Rules ``validate-sql`` applies to one migration script, read from its text alone.

Each statement is the one the hybrid parser split (``script_analysis``); sqlglot parses
it again for the rules that need its structure. A statement sqlglot cannot structure is
reported (``statement-not-analysed``) rather than passed. Nothing connects to a database.

A table created earlier in the same delta (the scripts applied together) has no rows and
nothing deployed uses it yet, so the findings about that table alone are not reported.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import AbstractSet, Any, Dict, FrozenSet, Iterable, List, Optional, Set, Tuple

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from dblift.core.migration.sql.execution_statement import (
    classify_execution_statement,
    execution_units,
)
from dblift.core.migration.sql.script_analysis import (
    AnalysedStatement,
    ScriptAnalysis,
    quiet_sqlglot,
)
from dblift.core.sql_model.dialect import get_sqlglot_dialect
from dblift.db.dml_analysis import strip_leading_sql_comments
from dblift.db.provider_registry import ProviderRegistry

ERROR = "error"
WARNING = "warning"
INFO = "info"
SIZE_NOTE = " (row count unknown — severity not adjusted for table size)"

SEVERITY: Dict[str, str] = {
    "drop-table": ERROR,
    "drop-schema": ERROR,
    "drop-column": ERROR,
    "truncate": ERROR,
    "drop-unread-object": WARNING,
    "dml-no-where": WARNING,
    "add-not-null-no-default": WARNING,
    "rename-column": WARNING,
    "rename-table": WARNING,
    "alter-column-type": WARNING,
    "mixed-transaction-modes": ERROR,
    "pg-index-not-concurrent": WARNING,
    "pg-constraint-not-valid": WARNING,
    "pg-set-not-null": WARNING,
    "pg-missing-lock-timeout": WARNING,
    "statement-not-analysed": INFO,
}

_MESSAGES: Dict[str, str] = {
    "add-not-null-no-default": "adds a NOT NULL column without a DEFAULT: existing rows need a value"
    + SIZE_NOTE,
    "drop-unread-object": "drops an object whose kind or name could not be read: check by hand "
    "that it holds no rows",
    "rename-column": "renames a column: the application already deployed still uses the old name",
    "rename-table": "renames a table: the application already deployed still uses the old name",
    "alter-column-type": "changes a column's type: the engine may rewrite the table" + SIZE_NOTE,
    "mixed-transaction-modes": "needs autocommit while the script's other statements run in a "
    "transaction, so migrate refuses this script; move it to a migration of its own",
    "pg-index-not-concurrent": "CREATE INDEX without CONCURRENTLY blocks writes to the table "
    "while the index builds" + SIZE_NOTE,
    "pg-constraint-not-valid": "adds a FOREIGN KEY or CHECK without NOT VALID, so the whole "
    "table is checked under lock; add it NOT VALID, then VALIDATE CONSTRAINT" + SIZE_NOTE,
    "pg-set-not-null": "SET NOT NULL scans the whole table under an ACCESS EXCLUSIVE lock"
    + SIZE_NOTE,
    "pg-missing-lock-timeout": "takes a table lock with no lock_timeout set earlier in the "
    "script, so queries on the table can queue behind it; start with "
    "SET LOCAL lock_timeout = '5s'",
    "statement-not-analysed": "this ALTER statement could not be analysed; review it by hand",
}

_TYPE_CHANGE = (exp.AlterColumn, exp.ModifyColumn)
# Findings about one table's rows or its users: not reported for a table new in the delta.
_TABLE_CODES = frozenset(
    {
        "drop-table",
        "drop-column",
        "truncate",
        "dml-no-where",
        "rename-column",
        "rename-table",
        "alter-column-type",
        "add-not-null-no-default",
        "pg-set-not-null",
        "pg-constraint-not-valid",
        "pg-index-not-concurrent",
        "pg-missing-lock-timeout",
    }
)
# One identifier as (text, quoted), the text as written.
_Part = Tuple[str, bool]
# A table as (schema or None, name).
_TableKey = Tuple[Optional[_Part], _Part]
_NOT_NULL_EXEMPT = (
    exp.DefaultColumnConstraint,
    exp.ComputedColumnConstraint,
    exp.GeneratedAsIdentityColumnConstraint,
    exp.PrimaryKeyColumnConstraint,
)
_RENAME_TABLE = re.compile(r"^\s*RENAME\s+TABLE\b", re.IGNORECASE)
_SP_RENAME = re.compile(r"\bsp_rename\b(?P<rest>.*)", re.IGNORECASE | re.DOTALL)
_LOCK_TIMEOUT = re.compile(r"^\s*SET\s+(?:LOCAL\s+|SESSION\s+)?lock_timeout\b", re.IGNORECASE)


@dataclass(frozen=True)
class Finding:
    """One rule a statement breaks; ``allowed`` when the script accepts it with ``dblift:allow``."""

    code: str
    severity: str
    statement: int
    message: str
    snippet: str
    allowed: bool = False

    def to_dict(self) -> Dict[str, Any]:
        """JSON-ready form of the finding."""
        return {
            "code": self.code,
            "severity": self.severity,
            "statement": self.statement,
            "message": self.message,
            "snippet": self.snippet,
            "allowed": self.allowed,
        }


def find_issues(
    analysis: ScriptAnalysis,
    dialect: str,
    *,
    created_before: AbstractSet[str] = frozenset(),
    existing_tables: Optional[AbstractSet[str]] = None,
    text: Optional[str] = None,
) -> List[Finding]:
    """Every finding for one analysed script, sorted by statement then code.

    *created_before* names the tables earlier scripts of the delta created, and
    *existing_tables* the tables known to exist, as ``issues_and_created_tables`` reads them.
    """
    return issues_and_created_tables(
        analysis, dialect, created_before, existing_tables=existing_tables, text=text
    )[0]


def issues_and_created_tables(
    analysis: ScriptAnalysis,
    dialect: str,
    created_before: AbstractSet[str] = frozenset(),
    *,
    existing_tables: Optional[AbstractSet[str]] = None,
    text: Optional[str] = None,
) -> Tuple[List[Finding], FrozenSet[str]]:
    """The script's findings, and the tables it creates.

    A table is named ``schema.name``, or ``name`` when the statement gives no schema: an
    unquoted part lower-cased, a quoted one as written between ``"``. A table in
    *created_before*, or created by an earlier statement of the script, is new: a table-scoped
    finding on a statement whose target tables are all new is not reported. A target is new
    when its name matches a new table (both unquoted and equal ignoring case, both quoted
    and byte-equal, or one quoted spelled as the engine stores the unquoted one) and either side
    names no schema or both name the same one: offline the search path is unknown, so
    ``CREATE TABLE users`` also covers ``x.users``. A statement whose names the analysis
    withheld (``names_unread``) is never exempted and creates no new table: the engine may read
    another name than sqlglot does. ``CREATE TABLE IF NOT EXISTS`` creates
    nothing new, since the table may already exist with rows, and neither does a
    ``CREATE TABLE`` of a table matching *existing_tables*, the tables known to exist.
    *text* is the script: a dialect that runs batches judges transaction modes per batch.
    """
    sqlglot_dialect = get_sqlglot_dialect(dialect)
    quirks = ProviderRegistry.get_quirks(dialect)
    pg_locks = quirks.postgresql_lock_rules
    case = quirks.unquoted_identifier_case
    snippets = {s.index: s.snippet for s in analysis.statements}
    findings = [
        Finding(c.code, SEVERITY[c.code], c.statement, c.reason, snippets.get(c.statement, ""))
        for c in analysis.cautions
        if c.code
    ]
    new: Set[_TableKey] = {_key_from_text(name) for name in created_before}
    existing = {_key_from_text(name) for name in existing_tables or ()}
    created: Set[_TableKey] = set()
    on_new_tables: Set[int] = set()
    lock_timeout_set = False
    lock_timeout_reported = not pg_locks
    for stmt in analysis.statements:
        body = strip_leading_sql_comments(stmt.sql)
        tree = _parse(body, sqlglot_dialect)
        targets = _targets(tree)
        if (
            targets
            and not stmt.names_unread
            and all(_matches(target, new, case) for target in targets)
        ):
            on_new_tables.add(stmt.index)
        for code in _statement_codes(body, tree, pg_locks=pg_locks):
            findings.append(_finding(code, stmt))
        if stmt.operation == "ALTER" and tree is None:
            findings.append(_finding("statement-not-analysed", stmt))
        if _LOCK_TIMEOUT.match(body):
            lock_timeout_set = True
        elif (
            not (lock_timeout_set or lock_timeout_reported)
            and stmt.index not in on_new_tables
            and _locks_table(tree)
        ):
            findings.append(_finding("pg-missing-lock-timeout", stmt))
            lock_timeout_reported = True
        table = _created_table(tree)
        if table and not stmt.names_unread and not _matches(table, existing, None):
            created.add(table)
            new.add(table)
    findings = [
        f for f in findings if not (f.code in _TABLE_CODES and f.statement in on_new_tables)
    ]
    # A failed scan is already reported by analysis.errors. Do not scan the refused
    # script again for transaction modes and turn its parse error into an exception.
    if not analysis.errors:
        findings.extend(_mixed_transaction_modes(analysis.statements, dialect, text))
    return sorted(findings, key=lambda f: (f.statement, f.code)), frozenset(
        _text_of(key) for key in created
    )


def _finding(code: str, stmt: AnalysedStatement) -> Finding:
    return Finding(code, SEVERITY[code], stmt.index, _MESSAGES[code], stmt.snippet)


def _parse(sql: str, sqlglot_dialect: Optional[str]) -> Optional[exp.Expression]:
    if not sqlglot_dialect:
        return None
    try:
        with quiet_sqlglot():
            tree = sqlglot.parse_one(sql, read=sqlglot_dialect)
    except (ParseError, TokenError):
        return None
    if not isinstance(tree, exp.Expression) or isinstance(tree, exp.Command):
        return None
    return tree


def _part_of(identifier: Any) -> _Part:
    text = identifier.name
    quoted = bool(identifier.args.get("quoted"))
    return (text, quoted)


def _key_of(table: exp.Table) -> _TableKey:
    schema = table.args.get("db")
    return (_part_of(schema) if schema is not None and schema.name else None, _part_of(table.this))


_QUOTED_OR_BARE = re.compile(r'"((?:[^"]|"")*)"|([^.]+)')


def _key_from_text(text: str) -> _TableKey:
    """Read ``schema.name``, a quoted part written ``"Text"`` (a ``"`` doubled)."""
    parts: List[_Part] = [
        (m.group(1).replace('""', '"'), True) if m.group(2) is None else (m.group(2), False)
        for m in _QUOTED_OR_BARE.finditer(text)
    ]
    return (parts[-2] if len(parts) > 1 else None, parts[-1] if parts else ("", False))


def _text_of(key: _TableKey) -> str:
    def part(p: _Part) -> str:
        return '"' + p[0].replace('"', '""') + '"' if p[1] else p[0].lower()

    schema, name = key
    return f"{part(schema)}.{part(name)}" if schema else part(name)


def _same(a: _Part, b: _Part, case: Optional[str]) -> bool:
    """Two unquoted parts equal ignoring case, two quoted ones byte-equal.

    A quoted part matches an unquoted one only when it is spelled as the engine stores the
    unquoted one (*case*: the dialect's ``unquoted_identifier_case``; any other value reads
    the unquoted text as written). *case* ``None`` ignores quoting and case, for names known
    to exist.
    """
    if case is None:
        return a[0].lower() == b[0].lower()
    if a[1] == b[1]:
        return a[0] == b[0] if a[1] else a[0].lower() == b[0].lower()
    quoted, bare = (a, b) if a[1] else (b, a)
    folded = {"uppercase": bare[0].upper(), "lowercase": bare[0].lower()}.get(case, bare[0])
    return quoted[0] == folded


def _matches(target: _TableKey, tables: AbstractSet[_TableKey], case: Optional[str]) -> bool:
    schema, name = target
    return any(
        _same(name, other_name, case)
        and (schema is None or other_schema is None or _same(schema, other_schema, case))
        for other_schema, other_name in tables
    )


def _table_of(tree: exp.Expression) -> Optional[_TableKey]:
    table = tree.find(exp.Table)
    return _key_of(table) if table is not None and table.name else None


def _targets(tree: Optional[exp.Expression]) -> FrozenSet[_TableKey]:
    """The tables a statement acts on: every table a DROP or TRUNCATE names, every table a CTE
    or the statement writes when a CTE writes, else its first.

    Read from the sqlglot tree only: the analysed objects keep the first table of
    ``DROP TABLE a, b``. A statement sqlglot cannot structure has no targets.
    """
    if isinstance(tree, (exp.Drop, exp.TruncateTable)):
        return frozenset(_key_of(t) for t in tree.find_all(exp.Table) if t.name)
    writers = (exp.Insert, exp.Update, exp.Delete)
    if tree is not None and any(isinstance(cte.this, writers) for cte in tree.find_all(exp.CTE)):
        # A CTE that writes changes its own table: every one of them must be new to exempt.
        written = [tree] if isinstance(tree, writers) else []
        written += [cte.this for cte in tree.find_all(exp.CTE) if isinstance(cte.this, writers)]
        return frozenset(
            _key_of(t) for node in written if (t := node.this.find(exp.Table)) and t.name
        )
    table = _table_of(tree) if tree is not None else None
    return frozenset({table}) if table else frozenset()


def _actions(tree: exp.Expression) -> List[exp.Expression]:
    return list(tree.args.get("actions") or []) if isinstance(tree, exp.Alter) else []


def _added_columns(action: exp.Expression) -> List[exp.ColumnDef]:
    if isinstance(action, exp.ColumnDef):
        return [action]
    if isinstance(action, exp.Schema):  # Oracle: ADD (col type ...)
        return [c for c in action.expressions if isinstance(c, exp.ColumnDef)]
    return []


def _adds_not_null_without_default(column: exp.ColumnDef) -> bool:
    kinds = [c.args.get("kind") for c in column.args.get("constraints") or []]
    return any(isinstance(k, exp.NotNullColumnConstraint) for k in kinds) and not any(
        isinstance(k, _NOT_NULL_EXEMPT) for k in kinds
    )


def _statement_codes(sql: str, tree: Optional[exp.Expression], *, pg_locks: bool) -> List[str]:
    codes: List[str] = []
    rename = _SP_RENAME.search(sql)
    if rename:
        codes.append(
            "rename-column" if "'column'" in rename.group("rest").lower() else "rename-table"
        )
    elif _RENAME_TABLE.match(sql):
        codes.append("rename-table")
    if tree is None:
        return codes
    for action in _actions(tree):
        if isinstance(action, exp.RenameColumn):
            codes.append("rename-column")
        elif isinstance(action, exp.AlterRename):
            codes.append("rename-table")
        elif isinstance(action, _TYPE_CHANGE) and (
            action.args.get("dtype") is not None or not isinstance(action, exp.AlterColumn)
        ):
            codes.append("alter-column-type")
        if any(_adds_not_null_without_default(c) for c in _added_columns(action)):
            codes.append("add-not-null-no-default")
        if (
            pg_locks
            and isinstance(action, exp.AlterColumn)
            and action.args.get("allow_null") is False
        ):
            codes.append("pg-set-not-null")
        if (
            pg_locks
            and isinstance(action, exp.AddConstraint)
            and not tree.args.get("not_valid")
            and (
                action.find(exp.ForeignKey) is not None
                or action.find(exp.CheckColumnConstraint) is not None
            )
        ):
            codes.append("pg-constraint-not-valid")
    if (
        pg_locks
        and isinstance(tree, exp.Create)
        and str(tree.args.get("kind") or "").upper() == "INDEX"
        and not tree.args.get("concurrently")
    ):
        codes.append("pg-index-not-concurrent")
    return codes


def _locks_table(tree: Optional[exp.Expression]) -> bool:
    """True for a statement that takes a strong lock on a table."""
    if tree is None:
        return False
    kind = str(tree.args.get("kind") or "").upper()
    if isinstance(tree, exp.Alter):
        return kind == "TABLE"
    if isinstance(tree, exp.Create):
        return kind == "INDEX" and not tree.args.get("concurrently")
    if isinstance(tree, exp.Drop):
        return kind == "TABLE"
    return isinstance(tree, exp.TruncateTable)


def _created_table(tree: Optional[exp.Expression]) -> Optional[_TableKey]:
    if (
        isinstance(tree, exp.Create)
        and str(tree.args.get("kind") or "").upper() == "TABLE"
        and not tree.args.get("exists")
    ):
        return _table_of(tree)
    return None


def _mixed_transaction_modes(
    statements: Iterable[AnalysedStatement], dialect: str, text: Optional[str] = None
) -> List[Finding]:
    """The execution engine refuses a script mixing autocommit-only and transactional units.

    A unit is a statement, or a batch for a dialect that runs batches (*text* is the script).
    """
    statements = list(statements)
    units = execution_units(text, dialect) if text else None
    if units is None:
        units = [stmt.sql for stmt in statements]
    modes = [(unit, classify_execution_statement(unit, dialect=dialect)) for unit in units]
    autocommit = [(unit, mode) for unit, mode in modes if not mode.can_execute_in_transaction]
    if not autocommit or len(autocommit) == len(modes):
        return []
    unit, mode = autocommit[0]
    stmt = next((s for s in statements if s.sql == unit), None) or next(
        (s for s in statements if s.sql in unit), None
    )
    reason = f"{mode.transaction_reason}: " if mode.transaction_reason else ""
    return [
        Finding(
            "mixed-transaction-modes",
            ERROR,
            stmt.index if stmt else 0,
            reason + _MESSAGES["mixed-transaction-modes"],
            stmt.snippet if stmt else "",
        )
    ]
