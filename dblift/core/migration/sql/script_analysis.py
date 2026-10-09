"""What a SQL script does, read from its text alone.

Built on the dialect's hybrid parser: the regex parser splits the script (procedural bodies,
dollar quotes, ``GO`` batches) and classifies each statement; sqlglot is consulted only for the
statements it can read. Nothing here connects to a database or runs a statement, and nothing
here raises into a command: a script the parser cannot read yields ``errors`` and no cautions.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from dblift.core.sql_model.base import SqlObject, SqlObjectType
from dblift.core.sql_parser.parser_factory import SqlParserFactory
from dblift.db.base_quirks import BaseQuirks
from dblift.db.dml_analysis import (
    cte_outer_statement_type,
    statement_dml_table,
    strip_leading_sql_comments,
)
from dblift.db.provider_registry import ProviderRegistry

DESTROYS = "destroys"
CHANGES_ROWS = "changes_rows"
SNIPPET = 120
_FIRST_WORD = re.compile(r"^([A-Za-z]+)")
_DROP_COLUMN = re.compile(r"\bDROP\s+COLUMN\b", re.IGNORECASE)
_TRUNCATE_TARGET = re.compile(
    r"^\s*TRUNCATE\s+(?:TABLE\s+)?([A-Za-z_][\w$.\"`\[\]]*)", re.IGNORECASE
)
_DROP_TARGET = re.compile(
    r"^\s*DROP\s+(TABLE|MATERIALIZED\s+VIEW|SCHEMA|DATABASE)\s+(?:IF\s+EXISTS\s+)?([^\s;,(]+)",
    re.IGNORECASE,
)
# Objects whose DROP discards rows; dropping an index, a sequence or a routine does not.
_DATA_HOLDERS = frozenset(
    {
        SqlObjectType.TABLE.value,
        SqlObjectType.VIRTUAL_TABLE.value,
        SqlObjectType.VIEW.value,
        SqlObjectType.MATERIALIZED_VIEW.value,
        SqlObjectType.SCHEMA.value,
        SqlObjectType.DATABASE.value,
    }
)
_SCHEMA_HOLDERS = frozenset({SqlObjectType.SCHEMA.value, SqlObjectType.DATABASE.value})
_ROW_HOLDERS = frozenset(
    {
        SqlObjectType.TABLE.value,
        SqlObjectType.VIRTUAL_TABLE.value,
        SqlObjectType.MATERIALIZED_VIEW.value,
    }
)
_DDL = frozenset({"CREATE", "ALTER", "DROP", "TRUNCATE", "COMMENT", "GRANT", "REVOKE", "DDL"})
_DML = frozenset({"INSERT", "UPDATE", "DELETE", "MERGE", "CALL", "EXECUTE", "DML"})
_QUERY = frozenset({"SELECT", "QUERY"})


@dataclass(frozen=True)
class AnalysedObject:
    """An object a statement names: its type (a ``SqlObjectType`` value), name and schema."""

    type: str
    name: str
    schema: Optional[str]


@dataclass(frozen=True)
class AnalysedStatement:
    """One statement of a script: its leading keyword, kind, objects and full-table DML flag."""

    index: int
    operation: str
    kind: str
    objects: Tuple[AnalysedObject, ...]
    full_table: bool
    snippet: str
    # The whole statement, for rules that parse it; not part of the JSON payload.
    sql: str = field(default="", repr=False, compare=False)


@dataclass(frozen=True)
class Caution:
    """Why a statement deserves a second look: ``destroys`` or ``changes_rows``, and the reason."""

    level: str
    statement: int
    reason: str
    # The ``validate-sql`` rule this caution stands for, or None when it only describes.
    code: Optional[str] = None


@dataclass(frozen=True)
class ScriptAnalysis:
    """What a script does: its statements, the cautions among them, and the parser's errors."""

    statements: Tuple[AnalysedStatement, ...]
    cautions: Tuple[Caution, ...]
    errors: Tuple[str, ...]

    def to_dict(self) -> Dict[str, Any]:
        """The analysis as plain lists and dicts, ready for ``--format json``."""
        return {
            "statements": [
                {
                    "index": s.index,
                    "operation": s.operation,
                    "kind": s.kind,
                    "objects": [
                        {"type": o.type, "name": o.name, "schema": o.schema} for o in s.objects
                    ],
                    "full_table": s.full_table,
                    "snippet": s.snippet,
                }
                for s in self.statements
            ],
            "cautions": [
                {"level": c.level, "statement": c.statement, "reason": c.reason, "code": c.code}
                for c in self.cautions
            ],
            "errors": list(self.errors),
        }


def operation_of(statement: str) -> str:
    """The statement's leading keyword, upper-cased, after any leading comments."""
    text = strip_leading_sql_comments(statement).lstrip()
    match = _FIRST_WORD.match(text)
    return match.group(1).upper() if match else "UNKNOWN"


def dialect_of(config: Any) -> Optional[str]:
    """The configured database type, lower-cased, or ``None``."""
    database = getattr(config, "database", None)
    kind = getattr(database, "type", None)
    return str(kind).lower() if kind else None


def analyse_script(text: str, dialect: str) -> ScriptAnalysis:
    """Analyse one script's text in *dialect*; never raises."""
    try:
        parsed = SqlParserFactory(dialect).parse_sql(text)
        quirks = ProviderRegistry.get_quirks(dialect)
    except Exception as error:  # the parser is not supposed to raise; the command must go on
        return ScriptAnalysis((), (), (f"parser error: {error}",))

    statements: List[AnalysedStatement] = []
    cautions: List[Caution] = []
    for stmt in parsed.statements or []:
        body = (getattr(stmt, "sql_text", "") or "").strip()
        if not body:
            continue
        index = len(statements)
        operation = operation_of(body)
        kind = _kind_of(getattr(stmt, "statement_type", None), operation, body, quirks)
        full_table = operation in ("UPDATE", "DELETE", "WITH") and _full_table(body, quirks)
        # The regex parser fills ``affected_objects``; ``objects`` stays empty.
        found = getattr(stmt, "affected_objects", None) or getattr(stmt, "objects", None) or []
        objects = tuple(_object_of(o) for o in found)
        if not objects:
            objects = _fallback_objects(operation, kind, body, quirks)
        objects = _drop_target_objects(operation, body, objects)
        analysed = AnalysedStatement(
            index, operation, kind, objects, full_table, _snippet(body), sql=body
        )
        statements.append(analysed)
        caution = _caution_for(analysed, body)
        if caution is not None:
            cautions.append(caution)
    return ScriptAnalysis(tuple(statements), tuple(cautions), tuple(parsed.errors or []))


def _kind_of(statement_type: Any, operation: str, body: str, quirks: BaseQuirks) -> str:
    value = getattr(statement_type, "value", statement_type)
    value = str(value).upper() if value else ""
    if operation == "WITH":
        outer = cte_outer_statement_type(
            body, sqlglot_dialect=quirks.sqlglot_dialect, quote_pairs=quirks.sql_scan_quote_pairs
        )
        if outer:
            return outer
    if value in _DDL or operation in _DDL:
        return "DDL"
    if value in _DML or operation in _DML:
        return "DML"
    if value in _QUERY or operation in _QUERY:
        return "QUERY"
    return "UNKNOWN"


def _full_table(body: str, quirks: BaseQuirks) -> bool:
    try:
        return bool(quirks.is_full_table_dml(body))
    except Exception:
        return False


def _object_of(obj: SqlObject) -> AnalysedObject:
    kind = getattr(obj, "object_type", None)
    return AnalysedObject(
        type=str(getattr(kind, "value", kind) or SqlObjectType.UNKNOWN.value),
        name=str(getattr(obj, "name", "") or ""),
        schema=getattr(obj, "schema", None) or None,
    )


def _fallback_objects(
    operation: str, kind: str, body: str, quirks: BaseQuirks
) -> Tuple[AnalysedObject, ...]:
    """The target table of a statement the parser left without objects (DML, TRUNCATE)."""
    name = ""
    if operation == "TRUNCATE":
        match = _TRUNCATE_TARGET.match(strip_leading_sql_comments(body))
        name = match.group(1).rstrip(";") if match else ""
    elif operation in ("INSERT", "UPDATE", "DELETE", "MERGE") or (
        operation == "WITH" and kind == "DML"
    ):
        try:
            name = statement_dml_table(body, dialect=quirks.sqlglot_dialect)
        except Exception:
            name = ""
    return (AnalysedObject("TABLE", name, None),) if name else ()


def _drop_target_objects(
    operation: str, body: str, objects: Tuple[AnalysedObject, ...]
) -> Tuple[AnalysedObject, ...]:
    """Type the targets of DROP TABLE / MATERIALIZED VIEW / SCHEMA / DATABASE from the keyword.

    Some regex parsers leave these targets out or untyped, or type a materialized view as a view.
    """
    match = _DROP_TARGET.match(strip_leading_sql_comments(body)) if operation == "DROP" else None
    if match is None:
        return objects
    kind = "_".join(match.group(1).upper().split())
    if objects:
        return tuple(AnalysedObject(kind, o.name, o.schema) for o in objects)
    parts = [part.strip('"`[]') for part in match.group(2).split(".")]
    if kind in _SCHEMA_HOLDERS or len(parts) == 1:
        return (AnalysedObject(kind, ".".join(parts), None),)
    return (AnalysedObject(kind, parts[-1], ".".join(parts[:-1])),)


def _snippet(body: str) -> str:
    flat = " ".join(body.split())
    return flat if len(flat) <= SNIPPET else flat[: SNIPPET - 1] + "…"


def _names(objects: Tuple[AnalysedObject, ...]) -> str:
    names = [f"{o.schema}.{o.name}" if o.schema else o.name for o in objects if o.name]
    return ", ".join(names) if names else "its target"


def _caution_for(stmt: AnalysedStatement, body: str) -> Optional[Caution]:
    op = stmt.operation
    if op == "TRUNCATE":
        return Caution(DESTROYS, stmt.index, f"TRUNCATE empties {_names(stmt.objects)}", "truncate")
    if op == "DROP":
        held = tuple(o for o in stmt.objects if o.type in _DATA_HOLDERS)
        if not held:
            return None
        if any(o.type in _SCHEMA_HOLDERS for o in held):
            code: Optional[str] = "drop-schema"
        elif any(o.type in _ROW_HOLDERS for o in held):
            code = "drop-table"
        else:
            code = None
        return Caution(
            DESTROYS,
            stmt.index,
            f"DROP {held[0].type.replace('_', ' ')} discards {_names(held)} and its rows",
            code,
        )
    if op == "ALTER" and _DROP_COLUMN.search(body):
        return Caution(
            DESTROYS,
            stmt.index,
            f"DROP COLUMN discards a column of {_names(stmt.objects)}",
            "drop-column",
        )
    if op in ("UPDATE", "DELETE") or (op == "WITH" and stmt.kind == "DML"):
        if stmt.full_table:
            return Caution(
                DESTROYS,
                stmt.index,
                f"{op} without WHERE rewrites every row of {_names(stmt.objects)}",
                "dml-no-where",
            )
        return Caution(CHANGES_ROWS, stmt.index, f"{op} changes rows of {_names(stmt.objects)}")
    if op == "MERGE":
        return Caution(CHANGES_ROWS, stmt.index, f"MERGE changes rows of {_names(stmt.objects)}")
    return None
