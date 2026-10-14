"""Statement facts read from one sqlglot AST per lexical statement.

Kept apart from ``statement_facts`` so that importing the fact types never imports sqlglot.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Optional, Tuple

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError, TokenError

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes
from dblift.core.sql_parser.dialects.identifier_tokens import (
    BACKTICK_IDENTIFIER,
    BRACKET_IDENTIFIER,
    DOUBLE_QUOTED_IDENTIFIER,
    strip_identifier_quotes,
)
from dblift.core.sql_parser.statement_facts import (
    DeclaredConstraint,
    NamedObject,
    StatementFacts,
)
from dblift.db.dml_analysis import (
    DEFAULT_QUOTE_PAIRS,
    _dml_target_table,
    _find_top_level_keyword,
    _sqlglot_events,
    _sqlglot_updated_columns,
)

_NAME = rf"(?:{DOUBLE_QUOTED_IDENTIFIER}|{BRACKET_IDENTIFIER}|{BACKTICK_IDENTIFIER}|[\w$]+)"
_HEAD = re.compile(
    rf"^\s*(CREATE|ALTER|DROP)\s+(?:(?:TEMP|TEMPORARY|UNIQUE|IF|NOT|EXISTS)\s+)*"
    rf"(VIRTUAL\s+TABLE|TABLE|VIEW|INDEX|TRIGGER)\s+(?:(?:IF|NOT|EXISTS)\s+)*"
    rf"({_NAME})(?:\s*\.\s*({_NAME}))?",
    re.IGNORECASE,
)
_HEAD_SCAN = re.compile(
    _HEAD.pattern.replace(r"^\s*", r"(?:^|;)\s*", 1), re.IGNORECASE | re.MULTILINE
)
_DML_HEAD = re.compile(
    rf"^\s*(INSERT|REPLACE|UPDATE|DELETE)\s+(?:OR\s+\w+\s+)?(?:(?:INTO|FROM)\s+)?"
    rf"({_NAME})(?:\s*\.\s*({_NAME}))?",
    re.IGNORECASE,
)
_UPDATE_OR = re.compile(
    r"^((?:\s|--[^\n]*\n|/\*.*?\*/)*UPDATE)\s+OR\s+(?:ROLLBACK|ABORT|FAIL|IGNORE|REPLACE)\b",
    re.IGNORECASE | re.DOTALL,
)
_FIRST_WORD = re.compile(r"^\s*([A-Za-z]+)")
_KINDS = {
    **dict.fromkeys(
        ("CREATE", "ALTER", "DROP", "VACUUM", "ANALYZE", "REINDEX", "PRAGMA", "ATTACH", "DETACH"),
        "DDL",
    ),
    **dict.fromkeys(("INSERT", "UPDATE", "DELETE", "REPLACE"), "DML"),
    **dict.fromkeys(("SELECT", "WITH", "VALUES", "EXPLAIN"), "QUERY"),
}


def _named(node: exp.Expression, kind: SqlObjectType, role: str) -> Optional[NamedObject]:
    table = node if isinstance(node, exp.Table) else node.find(exp.Table)
    if isinstance(node, exp.Index):
        name = node.this.name if isinstance(node.this, exp.Identifier) else ""
        return NamedObject(name, kind, role) if name else None
    if not isinstance(table, exp.Table) or not table.name:
        return None
    schema = ".".join(part for part in (table.catalog, table.db) if part) or None
    return NamedObject(table.name, kind, role, schema)


def _qualified_index(
    index: exp.Index,
) -> Optional[Tuple[str, str, str, list[exp.Expression]]]:
    """Schema, index, table and indexed expressions of ``schema.index ON table (...)``.

    sqlglot's SQLite grammar reads the schema as the index name and the table as a call.
    SQLite qualifies the index only; the table is always unqualified.
    """
    params = index.args.get("params")
    called = params.args.get("on") if params else None
    named = index.args.get("table")
    if not (
        isinstance(called, exp.Anonymous)
        and isinstance(index.this, exp.Identifier)
        and isinstance(named, exp.Table)
        and named.name
    ):
        return None
    table = called.this.name if isinstance(called.this, exp.Identifier) else str(called.this)
    return index.this.name, named.name, table, list(called.expressions)


def _reference(node: exp.Reference) -> Tuple[Optional[str], Tuple[str, ...]]:
    target = node.this
    if isinstance(target, exp.Schema):
        table = target.this
        return (
            table.name if isinstance(table, exp.Table) else None,
            tuple(column.name for column in target.expressions),
        )
    return (target.name if isinstance(target, exp.Table) else None, ())


def _declared_constraint(
    node: exp.Expression, columns: Tuple[str, ...] = (), name: Optional[str] = None
) -> Optional[DeclaredConstraint]:
    if isinstance(node, exp.Constraint):
        for child in node.expressions:
            result = _declared_constraint(child, name=node.this.name if node.this else None)
            if result is not None:
                return result
        return None
    if isinstance(node, exp.PrimaryKeyColumnConstraint):
        return DeclaredConstraint("PRIMARY_KEY", columns, name)
    if isinstance(node, exp.PrimaryKey):
        return DeclaredConstraint("PRIMARY_KEY", tuple(x.name for x in node.expressions), name)
    if isinstance(node, exp.Reference):
        table, referenced = _reference(node)
        return DeclaredConstraint("FOREIGN_KEY", columns, name, table, referenced)
    if isinstance(node, exp.ForeignKey):
        reference = node.args.get("reference")
        table, referenced = (
            _reference(reference) if isinstance(reference, exp.Reference) else (None, ())
        )
        return DeclaredConstraint(
            "FOREIGN_KEY", tuple(x.name for x in node.expressions), name, table, referenced
        )
    if isinstance(node, exp.CheckColumnConstraint):
        used = tuple(dict.fromkeys(column.name for column in node.find_all(exp.Column)))
        return DeclaredConstraint("CHECK", columns or used, name)
    if isinstance(node, exp.UniqueColumnConstraint):
        listed = node.this.expressions if isinstance(node.this, exp.Schema) else []
        return DeclaredConstraint("UNIQUE", columns or tuple(x.name for x in listed), name)
    return None


def _referenced(node: exp.Expr, skip: Tuple[exp.Expr, ...] = ()) -> Tuple[NamedObject, ...]:
    """Tables a statement reads: query sources and foreign key targets, not common table names."""
    ctes = {cte.alias.lower() for cte in node.find_all(exp.CTE)}
    found: list[NamedObject] = []
    for table in node.find_all(exp.Table):
        if any(table is excluded for excluded in skip) or not table.name:
            continue
        if not table.db and table.name.lower() in ctes:
            continue
        reference = _named(table, SqlObjectType.TABLE, "referenced")
        if reference is not None and reference not in found:
            found.append(reference)
    return tuple(found)


def _column_constraints(definition: exp.ColumnDef) -> Tuple[DeclaredConstraint, ...]:
    return tuple(
        detail
        for constraint in definition.args.get("constraints", [])
        if (detail := _declared_constraint(constraint.args["kind"], (definition.name,)))
    )


def _merge_referenced(node: exp.Merge) -> Tuple[NamedObject, ...]:
    """Resolve MERGE sources in their own scopes, excluding CTE aliases."""
    from sqlglot.optimizer.scope import traverse_scope

    found: list[NamedObject] = []
    for scope in traverse_scope(node):
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                reference = _named(source, SqlObjectType.TABLE, "referenced")
                if reference is not None and reference not in found:
                    found.append(reference)
    return tuple(found)


def _blanked(sql: str) -> str:
    return strip_comments_preserving_quotes(
        sql, line_prefixes=["--"], has_block_comments=True, nested_block_comments=False
    )


_DML_FORM = {
    "INSERT": re.compile(r"^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\b", re.IGNORECASE),
    "REPLACE": re.compile(r"^\s*REPLACE\s+INTO\b", re.IGNORECASE),
    "UPDATE": re.compile(r"^\s*UPDATE\b", re.IGNORECASE),
    "DELETE": re.compile(r"^\s*DELETE\s+FROM\b", re.IGNORECASE),
}
_NOT_A_TABLE = frozenset({"FROM", "INTO", "WHERE", "SET", "VALUES", "SELECT", "DEFAULT"})
_MAIN_KEYWORDS = ("INSERT", "REPLACE", "UPDATE", "DELETE", "MERGE", "SELECT")


def _top_level_where(text: str) -> Optional[int]:
    """Offset of the WHERE keyword outside quotes, comments and parentheses, or None."""
    at = _find_top_level_keyword(text, "WHERE", DEFAULT_QUOTE_PAIRS)
    return at if at >= 0 else None


def _main_statement(head: str) -> str:
    """The statement behind a WITH clause, from its first top-level write or SELECT keyword."""
    found = {
        at: word
        for word in _MAIN_KEYWORDS
        if (at := _find_top_level_keyword(head, word, DEFAULT_QUOTE_PAIRS)) >= 0
    }
    return head[min(found) :] if found else head


def _head_object(match: "re.Match[str]") -> NamedObject:
    operation = match.group(1).upper()
    object_type = SqlObjectType[match.group(2).upper().replace(" ", "_")]
    name = strip_identifier_quotes(match.group(4) or match.group(3))
    schema = strip_identifier_quotes(match.group(3)) if match.group(4) else None
    role = {"CREATE": "created", "ALTER": "altered", "DROP": "dropped"}[operation]
    return NamedObject(name, object_type, role, schema)


def _head_facts(sql: str, diagnostic: str) -> StatementFacts:
    """Classify a statement from its leading words when sqlglot cannot represent the body."""
    head = _blanked(sql)
    first = _FIRST_WORD.match(head)
    if first and first.group(1).upper() == "WITH":
        head = _main_statement(head)
        first = _FIRST_WORD.match(head)
    operation = first.group(1).upper() if first else "UNKNOWN"
    kind = _KINDS.get(operation, "UNKNOWN")
    objects: Tuple[NamedObject, ...] = ()
    match = _HEAD.match(head)
    if match is None and first is None:
        # Stray characters (a NUL, a lone ``/``) ahead of the statement; the engine reads past them.
        match = _HEAD_SCAN.search(head.replace("\x00", " "))
        if match:
            operation = match.group(1).upper()
            kind = _KINDS[operation]
    dml = _DML_HEAD.match(head)
    if match:
        found = _head_object(match)
        diagnostic = f"{found.type.value.lower().replace('_', ' ')}: {diagnostic}"
        objects = (found,)
    elif dml and _DML_FORM[operation].match(head) and dml.group(2).upper() not in _NOT_A_TABLE:
        schema = strip_identifier_quotes(dml.group(2)) if dml.group(3) else None
        name = strip_identifier_quotes(dml.group(3) or dml.group(2))
        objects = (NamedObject(name, SqlObjectType.TABLE, "altered", schema),)
        target = f"{schema}.{name}" if schema else name
        where = _top_level_where(head)
        events = None if operation == "REPLACE" else frozenset({operation})
        return StatementFacts(
            operation,
            kind,
            objects,
            target,
            head[where:].strip() if where is not None else None,
            events=events,
            diagnostic=diagnostic,
            target_sql=target,
        )
    return StatementFacts(operation, kind, objects, diagnostic=diagnostic)


def read_statement_facts(sql: str, *, dialect: str) -> StatementFacts:
    """Read one already-split statement; never retry a second extractor.

    Text that does not tokenize is reported as an error. A statement the grammar does not
    model is classified from its leading words with an informational diagnostic.
    """
    try:
        ast = parse_one(_UPDATE_OR.sub(r"\1", sql), read=dialect)
    except (ParseError, TokenError) as exc:
        if not _blanked(sql).strip():
            return StatementFacts("UNKNOWN", "UNKNOWN")
        if isinstance(exc, TokenError):
            facts = _head_facts(sql, "")
            return replace(
                facts,
                diagnostic=None,
                error=f"{dialect} statement could not be tokenized (unterminated quote or comment)",
            )
        return _head_facts(sql, f"{dialect} grammar is not modelled for this statement")
    if ast is None or isinstance(ast, (exp.Command, exp.Block)):
        construct = type(ast).__name__ if ast is not None else "empty statement"
        return _head_facts(sql, f"{dialect} {construct} is opaque to statement facts")

    if (
        dialect == "duckdb"  # lint: allow-dialect-string: DuckDB macros lack a fact object type
        and isinstance(ast, (exp.Create, exp.Drop))
        and str(ast.args.get("kind") or "").upper() in {"MACRO", "FUNCTION"}
    ):
        return StatementFacts(
            type(ast).__name__.upper(),
            "DDL",
            diagnostic="duckdb macro identity and body are opaque to statement facts",
        )

    if isinstance(ast, exp.Create):
        kind = str(ast.args.get("kind") or "").upper()
        object_type = SqlObjectType.__members__.get(kind, SqlObjectType.UNKNOWN)
        schema_node = ast.this if isinstance(ast.this, exp.Schema) else None
        subject = schema_node.this if schema_node is not None else ast.this
        properties = ast.args.get("properties")
        virtual = bool(properties and properties.find(exp.VirtualProperty))
        if virtual:
            object_type = SqlObjectType.VIRTUAL_TABLE
        identity = _named(subject, object_type, "created") if subject is not None else None
        if (
            dialect == "duckdb"  # lint: allow-dialect-string: DuckDB schema identity projection
            and object_type == SqlObjectType.SCHEMA
            and isinstance(subject, exp.Table)
            and subject.db
        ):
            identity = NamedObject(subject.db, object_type, "created", subject.catalog or None)
        objects: Tuple[NamedObject, ...] = (identity,) if identity else ()
        indexed_table = None
        indexed_columns = None
        index_items: list[exp.Expression] = []
        if isinstance(subject, exp.Index):
            params = subject.args.get("params")
            index_items = params.args.get("columns", []) if params else []
            table = subject.args.get("table")
            qualified = _qualified_index(subject)
            if qualified is not None:
                schema, index_name, indexed_table, index_items = qualified
                objects = (
                    NamedObject(index_name, object_type, "created", schema),
                    NamedObject(indexed_table, SqlObjectType.TABLE, "referenced"),
                )
            else:
                reference = _named(table, SqlObjectType.TABLE, "referenced") if table else None
                if reference:
                    objects += (reference,)
                    indexed_table = reference.name
        definitions = schema_node.expressions if schema_node is not None else []
        columns = tuple(
            x.name for x in definitions if isinstance(x, (exp.ColumnDef, exp.Identifier))
        )
        constraints = tuple(
            detail
            for definition in definitions
            if isinstance(definition, exp.ColumnDef)
            for detail in _column_constraints(definition)
        ) + tuple(
            detail
            for definition in definitions
            if not isinstance(definition, exp.ColumnDef)
            if (detail := _declared_constraint(definition))
        )
        if isinstance(subject, exp.Index):
            simple = [item.this if isinstance(item, exp.Ordered) else item for item in index_items]
            if all(isinstance(item, exp.Column) for item in simple):
                indexed_columns = tuple(item.name for item in simple)
        if not isinstance(subject, exp.Index) and subject is not None:
            objects += _referenced(ast, tuple(subject.find_all(exp.Table)))
        diagnostic = f"{dialect} virtual table module arguments are opaque" if virtual else None
        if isinstance(subject, exp.Index) and indexed_columns is None:
            diagnostic = f"{dialect} index expression columns are opaque"
        return StatementFacts(
            "CREATE",
            "DDL",
            objects,
            declared_columns=columns,
            declared_constraints=constraints,
            indexed_table=indexed_table,
            indexed_columns=indexed_columns,
            diagnostic=diagnostic,
        )

    if isinstance(ast, exp.Drop):
        kind = str(ast.args.get("kind") or "").upper()
        object_type = SqlObjectType.__members__.get(kind, SqlObjectType.UNKNOWN)
        targets = ast.args.get("tables") or ast.args.get("expressions") or [ast.this]
        dropped_objects = tuple(
            obj
            for node in targets
            if node is not None
            if (obj := _named(node, object_type, "dropped"))
        )
        return StatementFacts("DROP", "DDL", dropped_objects)

    if isinstance(ast, exp.Alter):
        object_type = SqlObjectType.__members__.get(
            str(ast.args.get("kind") or "").upper(), SqlObjectType.UNKNOWN
        )
        identity = _named(ast.this, object_type, "altered")
        actions = ast.args.get("actions") or []
        columns = tuple(action.name for action in actions if isinstance(action, exp.ColumnDef))
        action = "add-column" if columns else None
        added = [item for item in actions if isinstance(item, exp.ColumnDef)]
        return StatementFacts(
            "ALTER",
            "DDL",
            ((identity,) if identity else ())
            + tuple(ref for definition in added for ref in _referenced(definition)),
            declared_columns=columns,
            declared_constraints=tuple(
                detail for definition in added for detail in _column_constraints(definition)
            ),
            action=action,
        )

    if dialect == "duckdb" and isinstance(ast, exp.TruncateTable):
        targets = ast.expressions
        target = targets[0] if len(targets) == 1 else None
        if isinstance(target, exp.Table) and isinstance(target.this, exp.Identifier):
            identity = _named(target, SqlObjectType.TABLE, "altered")
            if identity is not None:
                return StatementFacts("TRUNCATE", "DDL", (identity,))

    if isinstance(ast, (exp.Insert, exp.Update, exp.Delete)) or (
        dialect == "duckdb"  # lint: allow-dialect-string: MERGE facts qualified for DuckDB only
        and isinstance(ast, exp.Merge)
    ):
        operation = type(ast).__name__.upper()
        table = _dml_target_table(ast)
        identity = _named(table, SqlObjectType.TABLE, "altered") if table else None
        target = (
            ".".join(part for part in (table.catalog, table.db, table.name) if part)
            if table
            else None
        )
        where = ast.args.get("where")
        predicate = (
            where.this.sql(dialect=dialect)
            if where is not None and where.this is not None
            else None
        )
        events = _sqlglot_events(ast)
        columns = tuple(_sqlglot_updated_columns(ast))
        if isinstance(ast, exp.Insert) and isinstance(ast.this, exp.Schema):
            columns = tuple(x.name for x in ast.this.expressions)
        references = (
            _merge_referenced(ast)
            if isinstance(ast, exp.Merge)
            else _referenced(ast, (table,) if table is not None else ())
        )
        return StatementFacts(
            operation,
            "DML",
            ((identity,) if identity else ()) + references,
            target,
            predicate,
            affected_columns=columns,
            events=frozenset(events) if events else None,
            target_sql=table.sql(dialect=dialect) if table else None,
        )

    if isinstance(ast, exp.Query):
        return StatementFacts("SELECT", "QUERY", _referenced(ast))
    return _head_facts(sql, f"{dialect} {type(ast).__name__} has no statement facts mapping")
