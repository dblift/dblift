"""Rules ``validate-sql`` applies to one migration script, read from its text alone.

Each statement is the one the hybrid parser split (``script_analysis``); sqlglot parses
it again for the rules that need its structure. A statement sqlglot cannot structure is
reported (``statement-not-analysed``) rather than passed. Nothing connects to a database.
"""

from __future__ import annotations

import logging
import re
from contextlib import contextmanager
from dataclasses import dataclass
from typing import Any, Dict, Iterable, Iterator, List, Optional, Set

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError, TokenError

from dblift.core.migration.sql.execution_statement import (
    classify_execution_statement,
    is_comment_only_statement,
)
from dblift.core.migration.sql.script_analysis import AnalysedStatement, ScriptAnalysis
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

_SQLGLOT_LOG = logging.getLogger("sqlglot")
# ``ModifyColumn`` (MySQL MODIFY / CHANGE) exists from sqlglot 30.18; older releases
# parse MODIFY as ``AlterColumn``.
_TYPE_CHANGE = tuple(
    node for node in (exp.AlterColumn, exp.__dict__.get("ModifyColumn")) if node is not None
)
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


def find_issues(analysis: ScriptAnalysis, dialect: str) -> List[Finding]:
    """Every finding for one analysed script, sorted by statement then code."""
    sqlglot_dialect = get_sqlglot_dialect(dialect)
    pg_locks = ProviderRegistry.get_quirks(dialect).postgresql_lock_rules
    snippets = {s.index: s.snippet for s in analysis.statements}
    findings = [
        Finding(c.code, SEVERITY[c.code], c.statement, c.reason, snippets.get(c.statement, ""))
        for c in analysis.cautions
        if c.code
    ]
    created: Set[str] = set()
    lock_timeout_set = False
    lock_timeout_reported = not pg_locks
    for stmt in analysis.statements:
        body = strip_leading_sql_comments(stmt.sql)
        tree = _parse(body, sqlglot_dialect)
        for code in _statement_codes(body, tree, pg_locks=pg_locks, created=created):
            findings.append(_finding(code, stmt))
        if stmt.operation == "ALTER" and tree is None:
            findings.append(_finding("statement-not-analysed", stmt))
        if _LOCK_TIMEOUT.match(body):
            lock_timeout_set = True
        elif not (lock_timeout_set or lock_timeout_reported) and _locks_table(tree, created):
            findings.append(_finding("pg-missing-lock-timeout", stmt))
            lock_timeout_reported = True
        name = _created_table(tree)
        if name:
            created.add(name)
    findings.extend(_mixed_transaction_modes(analysis.statements, dialect))
    return sorted(findings, key=lambda f: (f.statement, f.code))


def _finding(code: str, stmt: AnalysedStatement) -> Finding:
    return Finding(code, SEVERITY[code], stmt.index, _MESSAGES[code], stmt.snippet)


@contextmanager
def _quiet_sqlglot() -> Iterator[None]:
    """sqlglot logs a warning for each statement it falls back on; the finding says it."""
    previous = _SQLGLOT_LOG.level
    _SQLGLOT_LOG.setLevel(logging.ERROR)
    try:
        yield
    finally:
        _SQLGLOT_LOG.setLevel(previous)


def _parse(sql: str, sqlglot_dialect: Optional[str]) -> Optional[exp.Expression]:
    if not sqlglot_dialect:
        return None
    try:
        with _quiet_sqlglot():
            tree = sqlglot.parse_one(sql, read=sqlglot_dialect)
    except (ParseError, TokenError):
        return None
    if not isinstance(tree, exp.Expression) or isinstance(tree, exp.Command):
        return None
    return tree


def _table_of(tree: exp.Expression) -> str:
    table = tree.find(exp.Table)
    return table.name.lower() if table is not None else ""


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


def _statement_codes(
    sql: str, tree: Optional[exp.Expression], *, pg_locks: bool, created: Set[str]
) -> List[str]:
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
    new_table = _table_of(tree) in created
    for action in _actions(tree):
        if isinstance(action, exp.RenameColumn):
            codes.append("rename-column")
        elif isinstance(action, exp.AlterRename):
            codes.append("rename-table")
        elif isinstance(action, _TYPE_CHANGE) and (
            action.args.get("dtype") is not None or not isinstance(action, exp.AlterColumn)
        ):
            codes.append("alter-column-type")
        if new_table:
            continue
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
        and not new_table
    ):
        codes.append("pg-index-not-concurrent")
    return codes


def _locks_table(tree: Optional[exp.Expression], created: Set[str]) -> bool:
    """True for a statement that takes a strong lock on a table the script did not create."""
    if tree is None or _table_of(tree) in created:
        return False
    kind = str(tree.args.get("kind") or "").upper()
    if isinstance(tree, exp.Alter):
        return kind == "TABLE"
    if isinstance(tree, exp.Create):
        return kind == "INDEX" and not tree.args.get("concurrently")
    if isinstance(tree, exp.Drop):
        return kind == "TABLE"
    return isinstance(tree, exp.TruncateTable)


def _created_table(tree: Optional[exp.Expression]) -> str:
    if isinstance(tree, exp.Create) and str(tree.args.get("kind") or "").upper() == "TABLE":
        return _table_of(tree)
    return ""


def _mixed_transaction_modes(
    statements: Iterable[AnalysedStatement], dialect: str
) -> List[Finding]:
    """The execution engine refuses a script mixing autocommit-only and transactional statements."""
    modes = [
        (stmt, classify_execution_statement(stmt.sql, dialect=dialect))
        for stmt in statements
        if stmt.sql and not is_comment_only_statement(stmt.sql)
    ]
    autocommit = [(stmt, mode) for stmt, mode in modes if not mode.can_execute_in_transaction]
    if not autocommit or len(autocommit) == len(modes):
        return []
    stmt, mode = autocommit[0]
    reason = f"{mode.transaction_reason}: " if mode.transaction_reason else ""
    return [
        Finding(
            "mixed-transaction-modes",
            ERROR,
            stmt.index,
            reason + _MESSAGES["mixed-transaction-modes"],
            stmt.snippet,
        )
    ]
