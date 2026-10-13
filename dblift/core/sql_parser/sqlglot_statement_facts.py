"""Statement facts read from one sqlglot AST per lexical statement.

Kept apart from ``statement_facts`` so that importing the fact types never imports sqlglot.
"""

from __future__ import annotations

import re
from typing import Optional, Tuple

from sqlglot import exp, parse_one
from sqlglot.errors import ParseError, TokenError

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.dialects.identifier_tokens import (
    BACKTICK_IDENTIFIER,
    BRACKET_IDENTIFIER,
    DOUBLE_QUOTED_IDENTIFIER,
    strip_identifier_quotes,
)
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.statement_facts import (
    DeclaredConstraint,
    NamedObject,
    StatementFacts,
)
from dblift.db.dml_analysis import _dml_target_table, _sqlglot_events, _sqlglot_updated_columns

_NAME = rf"(?:{DOUBLE_QUOTED_IDENTIFIER}|{BRACKET_IDENTIFIER}|{BACKTICK_IDENTIFIER}|[\w$]+)"
_HEAD = re.compile(
    rf"^\s*(CREATE|ALTER|DROP)\s+(?:(?:TEMP|TEMPORARY|UNIQUE|IF|NOT|EXISTS)\s+)*"
    rf"(VIRTUAL\s+TABLE|TABLE|VIEW|INDEX|TRIGGER)\s+(?:(?:IF|NOT|EXISTS)\s+)*"
    rf"({_NAME})(?:\s*\.\s*({_NAME}))?",
    re.IGNORECASE,
)
_FIRST_WORD = re.compile(r"^\s*([A-Za-z]+)")
_DDL = frozenset({"CREATE", "ALTER", "DROP"})
_DML = frozenset({"INSERT", "UPDATE", "DELETE"})


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
    if isinstance(node, exp.UniqueColumnConstraint):
        listed = node.this.expressions if isinstance(node.this, exp.Schema) else []
        return DeclaredConstraint("UNIQUE", columns or tuple(x.name for x in listed), name)
    return None


def _head_facts(sql: str, diagnostic: str, spec: LexicalSpec) -> StatementFacts:
    """Read only a statement head when sqlglot cannot represent the body."""
    head = LexicalEngine(spec).blank_comments(sql)
    first = _FIRST_WORD.match(head)
    operation = first.group(1).upper() if first else "UNKNOWN"
    kind = (
        "DDL"
        if operation in _DDL
        else (
            "DML"
            if operation in _DML
            else "QUERY" if operation in ("SELECT", "WITH") else "UNKNOWN"
        )
    )
    match = _HEAD.match(head)
    objects: Tuple[NamedObject, ...] = ()
    if match:
        type_name = match.group(2).upper().replace(" ", "_")
        diagnostic = f"{type_name.lower().replace('_', ' ')}: {diagnostic}"
        object_type = SqlObjectType[type_name]
        name = strip_identifier_quotes(match.group(4) or match.group(3))
        schema = strip_identifier_quotes(match.group(3)) if match.group(4) else None
        role = {"CREATE": "created", "ALTER": "altered", "DROP": "dropped"}[operation]
        objects = (NamedObject(name, object_type, role, schema),)
    return StatementFacts(operation, kind, objects, diagnostic=diagnostic)


def read_statement_facts(sql: str, *, dialect: str, spec: LexicalSpec) -> StatementFacts:
    """Read one already-split statement; never retry a second extractor."""
    try:
        ast = parse_one(sql, read=dialect)
    except (ParseError, TokenError) as exc:
        if not LexicalEngine(spec).blank_comments(sql).strip():
            return StatementFacts("UNKNOWN", "UNKNOWN")
        reason = (
            exc.errors[0]["description"] if isinstance(exc, ParseError) and exc.errors else str(exc)
        )
        return _head_facts(sql, f"{dialect} syntax could not be parsed: {reason}", spec)
    if ast is None or isinstance(ast, (exp.Command, exp.Block)):
        construct = type(ast).__name__ if ast is not None else "empty statement"
        return _head_facts(sql, f"{dialect} {construct} is opaque to statement facts", spec)

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
            for constraint in definition.args.get("constraints", [])
            if (detail := _declared_constraint(constraint.args["kind"], (definition.name,)))
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
        return StatementFacts(
            "ALTER", "DDL", (identity,) if identity else (), declared_columns=columns, action=action
        )

    if isinstance(ast, (exp.Insert, exp.Update, exp.Delete)):
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
        return StatementFacts(
            operation,
            "DML",
            (identity,) if identity else (),
            target,
            predicate,
            affected_columns=columns,
            events=frozenset(events) if events else None,
            target_sql=table.sql(dialect=dialect) if table else None,
        )

    if isinstance(ast, exp.Query):
        return StatementFacts("SELECT", "QUERY")
    return _head_facts(sql, f"{dialect} {type(ast).__name__} has no statement facts mapping", spec)
