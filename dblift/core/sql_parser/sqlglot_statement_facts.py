"""Statement facts read from one sqlglot AST per lexical statement.

Kept apart from ``statement_facts`` so that importing the fact types never imports sqlglot.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Optional, Tuple, TypeVar

from sqlglot import exp, parse_one
from sqlglot.dialects import Dialect
from sqlglot.errors import ParseError, TokenError
from sqlglot.tokens import TokenType

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.common.comment_stripping import strip_comments_preserving_quotes
from dblift.core.sql_parser.dialects.identifier_tokens import (
    BACKTICK_IDENTIFIER,
    BRACKET_IDENTIFIER,
    DOUBLE_QUOTED_IDENTIFIER,
    strip_identifier_quotes,
)
from dblift.core.sql_parser.dml_modifiers import (  # noqa: F401  (re-exported)
    MYSQL_DML_MODIFIER,
    MYSQL_DML_MODIFIER_WORDS,
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
# PostgreSQL names more kinds than the generic head and skips its creation modifiers;
# CONCURRENTLY is a modifier after INDEX only, elsewhere an ordinary name.
_POSTGRES_HEAD = re.compile(
    rf"^\s*(CREATE|ALTER|DROP)\s+"
    rf"(?:(?:OR\s+REPLACE|UNLOGGED|TEMP|TEMPORARY|UNIQUE|CONSTRAINT|IF|NOT|EXISTS)\s+)*"
    rf"(VIRTUAL\s+TABLE|MATERIALIZED\s+VIEW|TABLE|VIEW|INDEX|TRIGGER|FUNCTION|PROCEDURE"
    rf"|SEQUENCE|TYPE|SCHEMA|EXTENSION)(?:(?<=INDEX)\s+CONCURRENTLY\b)?\s+"
    rf"(?:(?:IF|NOT|EXISTS)\s+)*"
    rf"(?!(?:IF|NOT|EXISTS|AUTHORIZATION|OR|REPLACE)\b)"
    rf"({_NAME})(?:\s*\.\s*({_NAME}))?",
    re.IGNORECASE,
)
_POSTGRES_HEAD_SCAN = re.compile(
    _POSTGRES_HEAD.pattern.replace(r"^\s*", r"(?:^|;)\s*", 1), re.IGNORECASE | re.MULTILINE
)
# Oracle names more kinds than the generic head, skips its creation modifiers and counts ``#``
# as a name character. ``TYPE BODY`` is not listed (no object type), and the reserved words that
# can follow a kind are never a name.
_ORACLE_NAME = rf"(?:{DOUBLE_QUOTED_IDENTIFIER}|[\w$#]+)"
_ORACLE_HEAD = re.compile(
    rf"^\s*(CREATE|ALTER|DROP)\s+"
    rf"(?:(?:OR\s+REPLACE|NOFORCE|FORCE|EDITIONABLE|NONEDITIONABLE|EDITIONING|NONEDITIONING"
    rf"|PUBLIC|SHARED|UNIQUE|BITMAP|GLOBAL\s+TEMPORARY|PRIVATE\s+TEMPORARY|IF|NOT|EXISTS)\s+)*"
    rf"(MATERIALIZED\s+VIEW(?!\s+LOG(?![\w$#]))|PACKAGE\s+BODY|TABLE|VIEW|INDEX|TRIGGER|FUNCTION|PROCEDURE|PACKAGE"
    rf"|SEQUENCE|TYPE|SYNONYM|DATABASE\s+LINK)\s+(?:(?:IF|NOT|EXISTS)\s+)*"
    rf"(?!(?:IF|NOT|EXISTS|OR|REPLACE|AS|IS|BODY|AUTHID|ACCESSIBLE)\b)"
    rf"({_ORACLE_NAME})(?:\s*\.\s*({_ORACLE_NAME}))?",
    re.IGNORECASE,
)
_ORACLE_MV_LOG = re.compile(
    r"\s*(?:CREATE|DROP|ALTER)\s+MATERIALIZED\s+VIEW\s+LOG(?![\w$#])", re.IGNORECASE
)
_ORACLE_TRUNCATE_TABLE = re.compile(r"\s*TRUNCATE\s+TABLE\b", re.IGNORECASE)
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
# Default MySQL lexical rules from docs/sql-parsing/mysql.md: backslashes escape strings,
# not backticks; -- needs whitespace/control; ordinary block comments do not nest.
_MYSQL_QUOTES_AND_COMMENTS = re.compile(
    r"'(?:''|\\.|[^'\\])*(?:'|\Z)|"
    r'"(?:""|\\.|[^"\\])*(?:"|\Z)|'
    r"`(?:``|[^`])*(?:`|\Z)|"
    r"(?:\#|--(?=[\x00-\x20\x7f]|\Z))[^\n]*|/\*.*?(?:\*/|\Z)",
    re.DOTALL,
)
_KINDS = {
    **dict.fromkeys(
        ("CREATE", "ALTER", "DROP", "VACUUM", "ANALYZE", "REINDEX", "PRAGMA", "ATTACH", "DETACH"),
        "DDL",
    ),
    **dict.fromkeys(("INSERT", "UPDATE", "DELETE", "REPLACE"), "DML"),
    **dict.fromkeys(("SELECT", "WITH", "VALUES", "EXPLAIN"), "QUERY"),
}


# Characters sqlglot reads as blanks while an engine may read them as part of a name (the
# non-ASCII ones str.isspace accepts), and the zero-width characters an engine may read as blanks
# while sqlglot keeps them in a name. Whitespace is all in the BMP; a test checks the full range.
_UNREAD_NAME_CHARACTERS = frozenset(
    c for c in map(chr, range(0x80, 0x10000)) if c.isspace()
) | frozenset({"\u200b", "\u2060", "\ufeff"})
_QUOTED_TOKENS = frozenset(
    {
        TokenType.STRING,
        TokenType.NATIONAL_STRING,
        TokenType.RAW_STRING,
        TokenType.HEREDOC_STRING,
        TokenType.BIT_STRING,
        TokenType.HEX_STRING,
        TokenType.BYTE_STRING,
        TokenType.UNICODE_STRING,
        TokenType.IDENTIFIER,
    }
)
_ASCII_BLANKS = " \t\n\r\f\v"
_NAME_CHARACTERS = frozenset("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_$")


def _first_unread(text: str, start: int, end: int) -> Optional[int]:
    for at in range(start, end):
        if text[at] in _UNREAD_NAME_CHARACTERS:
            return at
    return None


def _first_unread_outside_comments(
    sql: str, start: int, end: int, comments: "dict[str, Optional[str]]", nested: bool
) -> Optional[int]:
    """First unread character in ``sql[start:end]`` (between tokens) that is not in a comment."""
    at = start
    while at < end:
        opener = next((o for o in comments if sql.startswith(o, at)), None)
        if opener is None:
            if sql[at] in _UNREAD_NAME_CHARACTERS:
                return at
            at += 1
            continue
        closer = comments[opener]
        at += len(opener)
        if closer is None:  # line comment
            newline = sql.find("\n", at, end)
            at = end if newline < 0 else newline + 1
            continue
        depth = 1
        while at < end and depth:
            if nested and sql.startswith(opener, at):
                depth += 1
                at += len(opener)
            elif sql.startswith(closer, at):
                depth -= 1
                at += len(closer)
            else:
                at += 1
    return None


def unread_name_character(sql: str, *, dialect: str) -> Optional[int]:
    """Offset of the first character the engine may read inside a name while sqlglot reads a blank
    (or the reverse), outside strings, quoted identifiers and comments; ``None`` when there is none.

    Text that does not tokenize has no spans: any such character in it counts.
    """
    if _first_unread(sql, 0, len(sql)) is None:
        return None
    tokenizer = Dialect.get_or_raise(dialect)
    try:
        tokens = tokenizer.tokenize(sql)
    except TokenError:
        return _first_unread(sql, 0, len(sql))
    comments = tokenizer.tokenizer_class._COMMENTS
    nested = tokenizer.tokenizer_class.NESTED_COMMENTS
    position = 0
    for token in tokens:
        found = _first_unread_outside_comments(sql, position, token.start, comments, nested)
        if found is not None:
            return found
        if token.token_type not in _QUOTED_TOKENS:
            found = _first_unread(sql, token.start, token.end + 1)
            if found is not None:
                return found
        position = token.end + 1
    return _first_unread_outside_comments(sql, position, len(sql), comments, nested)


def _supplementary_name_character(sql: str) -> Optional[str]:
    """First character outside the Basic Multilingual Plane in a MySQL name, or ``None``.

    Scans the text outside string literals and comments, because sqlglot reads statements such
    as ``RENAME TABLE`` as a command whose names are not tokens.
    """
    if sql.isascii() or max(sql) <= "\uffff":
        return None
    at = 0
    for span in _MYSQL_QUOTES_AND_COMMENTS.finditer(sql):
        end = span.end() if span.group().startswith("`") else span.start()
        wide = next((c for c in sql[at:end] if c > "\uffff"), None)
        if wide:
            return str(wide)
        at = span.end()
    return next((str(c) for c in sql[at:] if c > "\uffff"), None)


def readable_dml_target(sql: str, *, dialect: str) -> Optional[str]:
    """The target of an INSERT, UPDATE or DELETE whose name is bounded by ASCII blanks, whatever
    else the statement holds; ``None`` when the name itself is not safely readable."""
    ascii_trimmed = sql.rstrip(_ASCII_BLANKS)
    if ascii_trimmed != ascii_trimmed.rstrip():
        return None  # a non-ASCII blank ends the text: the engine may read it as part of the name
    return _head_facts(sql, "", dialect=dialect).target


def _unread_name_facts(sql: str, dialect: str, at: int) -> StatementFacts:
    """The statement's operation and kind, and nothing it names."""
    head = _head_facts(sql, "", dialect=dialect)
    reason = (
        f"{dialect} statement holds U+{ord(sql[at]):04X}, which the engine may read as part of a "
        "name; its objects are not named"
    )
    try:
        Dialect.get_or_raise(dialect).tokenize(sql)
    except TokenError:
        return StatementFacts(
            head.operation,
            head.kind,
            error=f"{dialect} statement could not be tokenized (unterminated quote or comment)",
        )
    return StatementFacts(head.operation, head.kind, diagnostic=reason)


def _head_name_is_bounded(text: str, match: "re.Match[str]", groups: Tuple[int, ...]) -> bool:
    """Each name part starts after an ASCII blank, ``.`` or ``(`` and ends before a character
    that cannot continue a name; an engine may read anything else as part of the name."""
    spans = [match.span(group) for group in groups if match.span(group)[0] >= 0]
    for start, end in spans:
        if start and text[start - 1] not in _ASCII_BLANKS + ".(":
            return False
        if end < len(text) and not (text[end].isascii() and text[end] not in _NAME_CHARACTERS):
            return False
    # A trailing ``.`` means another part follows that the pattern could not read.
    return not spans or spans[-1][1] >= len(text) or text[spans[-1][1]] != "."


def _named(node: exp.Expression, kind: SqlObjectType, role: str) -> Optional[NamedObject]:
    table = node if isinstance(node, exp.Table) else node.find(exp.Table)
    if isinstance(node, exp.Index):
        name = node.this.name if isinstance(node.this, exp.Identifier) else ""
        return NamedObject(name, kind, role) if name else None
    if not isinstance(table, exp.Table) or not table.name:
        return None
    schema = ".".join(part for part in (table.catalog, table.db) if part) or None
    return NamedObject(table.name, kind, role, schema)


def _mysql_identifier_is_proven(identifier: exp.Expression, sql: str) -> bool:
    """Accept only source tokens stable without knowing the server's SQL mode."""
    if not isinstance(identifier, exp.Identifier) or not identifier.name:
        return False
    start, end = identifier.meta.get("start"), identifier.meta.get("end")
    if not isinstance(start, int) or not isinstance(end, int):
        return False
    # sqlglot skips non-ASCII spaces that MySQL reads as part of the identifier.
    if any(not c.isascii() for c in sql[max(start - 1, 0) : start] + sql[end + 1 : end + 2]):
        return False
    mysql = Dialect.get_or_raise("mysql")  # lint: allow-dialect-string: MySQL tokens
    tokens = mysql.tokenize(sql[start : end + 1])
    return tokens[0].token_type in {TokenType.VAR, TokenType.IDENTIFIER}


def _mysql_on_table_name(on: exp.OnProperty, sql: str) -> Optional[str]:
    """The table named by ``ON`` when it is one proven bare identifier, else ``None``.

    Newer sqlglot wraps the identifier in a ``Table``; 30.18 leaves it bare.
    """
    table = on.this
    if isinstance(table, exp.Table):
        if any(value for key, value in table.args.items() if key != "this"):
            return None
        table = table.this
    return table.name if _mysql_identifier_is_proven(table, sql) else None


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


def _created_object_type(ast: exp.Create, dialect: str) -> SqlObjectType:
    """Select the created object type, including dialect-specific view properties."""
    kind = str(ast.args.get("kind") or "").upper()
    object_type = SqlObjectType.__members__.get(kind, SqlObjectType.UNKNOWN)
    if dialect == "tsql" and kind in {  # lint: allow-dialect-string: T-SQL index modifiers
        "CLUSTERED INDEX",
        "NONCLUSTERED INDEX",
    }:
        object_type = SqlObjectType.INDEX
    properties = ast.args.get("properties")
    if properties and properties.find(exp.VirtualProperty):
        object_type = SqlObjectType.VIRTUAL_TABLE
    if (
        dialect
        in {"postgres", "oracle", "redshift"}  # lint: allow-dialect-string: materialized views
        and kind == "VIEW"
        and properties
        and properties.find(exp.MaterializedProperty)
    ):
        object_type = SqlObjectType.MATERIALIZED_VIEW
    return object_type


def _postgresql_opaque_cte(ast: exp.Expr, dialect: str) -> Optional[StatementFacts]:
    """Retain outer identities when the flat CTE reference filter cannot prove the body."""
    clauses = list(ast.find_all(exp.With))
    if not clauses:
        return None
    ctes = list(ast.find_all(exp.CTE))
    aliases = {cte.alias.lower() for cte in ctes}
    effects_unknown = any(not isinstance(cte.this, exp.Query) for cte in ctes)
    query = ast.args.get("expression") if isinstance(ast, exp.Create) else ast
    if not (
        effects_unknown
        or len(clauses) != 1
        or clauses[0].parent is not query
        or clauses[0].args.get("recursive")
        or any(cte.args["alias"].this.args.get("quoted") for cte in ctes)
        or any(
            not table.db and table.name.lower() in aliases
            for cte in ctes
            for table in cte.this.find_all(exp.Table)
        )
        or any(
            not table.db
            and table.name.lower() in aliases
            and isinstance(table.this, exp.Identifier)
            and table.this.args.get("quoted")
            for table in ast.find_all(exp.Table)
        )
    ):
        return None

    operation = type(ast).__name__.upper()
    kind = "UNKNOWN"
    identity = None
    if isinstance(ast, exp.Query):
        operation = "SELECT"
        kind = "UNKNOWN" if effects_unknown else "QUERY"
    elif isinstance(ast, exp.Create):
        kind = "DDL"
        identity = _named(ast.this, _created_object_type(ast, dialect), "created")
    elif isinstance(ast, (exp.Insert, exp.Update, exp.Delete)):
        kind = "DML"
        table = _dml_target_table(ast)
        identity = _named(table, SqlObjectType.TABLE, "altered") if table is not None else None
    return StatementFacts(
        operation,
        kind,
        (identity,) if identity is not None else (),
        diagnostic=f"{dialect} CTE source scopes or effects are opaque to statement facts",
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


def _is_merge_column(column: exp.Expr) -> bool:
    """Whether a MERGE action names one nonempty, unqualified whole column."""
    return (
        isinstance(column, exp.Column)
        and isinstance(column.this, exp.Identifier)
        and bool(column.name)
        and all(column.args.get(part) is None for part in ("catalog", "db", "table"))
    )


def _postgres_merge_facts(node: exp.Merge) -> Optional[StatementFacts]:
    """Read explicit MERGE actions; affected columns describe UPDATE assignments only."""
    from sqlglot.optimizer.scope import traverse_scope

    table = node.this
    if not isinstance(table, exp.Table) or not isinstance(table.this, exp.Identifier):
        return None
    if any(
        not isinstance(source.this, exp.Identifier)
        or not source.name
        or source.args.get("catalog") is not None
        or (source.args.get("db") is not None and not source.db)
        for source in node.find_all(exp.Table)
    ):
        return None
    if (
        table.args.get("joins")
        or not node.args.get("on")
        or node.args.get("using_cond") is not False
    ):
        return None
    if not isinstance(node.args.get("using"), (exp.Table, exp.Subquery, exp.Values)):
        return None
    if any(clause.args.get("recursive") for clause in node.find_all(exp.With)) or any(
        not isinstance(cte.this, exp.Query) for cte in node.find_all(exp.CTE)
    ):
        return None
    whens = node.args.get("whens")
    if whens is None or not whens.expressions:
        return None
    events: set[str] = set()
    for when in whens.expressions:
        action = when.args.get("then")
        if action is not None and action.args.get("where") is not None:
            return None
        matches_target = when.args.get("matched") or when.args.get("source")
        if isinstance(action, exp.Update) and matches_target:
            if not action.expressions:
                return None
            for assignment in action.expressions:
                if not isinstance(assignment, exp.EQ):
                    return None
                columns = (
                    assignment.this.expressions
                    if isinstance(assignment.this, exp.Tuple)
                    else [assignment.this]
                )
                if not columns or not all(_is_merge_column(column) for column in columns):
                    return None
            events.add("UPDATE")
        elif isinstance(action, exp.Insert) and not matches_target:
            insert_columns = action.this.expressions if isinstance(action.this, exp.Tuple) else []
            if action.this is not None and (
                not insert_columns or not all(_is_merge_column(column) for column in insert_columns)
            ):
                return None
            values = action.expression
            if values is None:
                # sqlglot represents DEFAULT VALUES as a single unquoted DEFAULT column.
                if (
                    len(insert_columns) != 1
                    or insert_columns[0].name.upper() != "DEFAULT"
                    or insert_columns[0].this.args.get("quoted")
                ):
                    return None
            elif not isinstance(values, exp.Tuple) or not values.expressions:
                return None
            events.add("INSERT")
        elif isinstance(action, exp.Var) and action.name.upper() == "DELETE" and matches_target:
            events.add("DELETE")
        elif not (isinstance(action, exp.Var) and action.name.upper() == "DO NOTHING"):
            return None

    # Scope lookup folds unquoted PostgreSQL identifiers, but facts keep the written names.
    scoped = node.copy()
    originals = {
        id(source): _named(source, SqlObjectType.TABLE, "referenced")
        for source in scoped.find_all(exp.Table)
    }
    dialect = Dialect.get_or_raise("postgres")  # lint: allow-dialect-string: PostgreSQL scopes
    for identifier in scoped.find_all(exp.Identifier):
        dialect.normalize_identifier(identifier)
    references: list[NamedObject] = []
    seen_tables = {id(scoped.this)}
    for scope in traverse_scope(scoped):
        if scope.is_udtf:
            return None
        seen_tables.update(id(source) for source in scope.tables)
        if isinstance(scope.expression, exp.Table):
            seen_tables.add(id(scope.expression))
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                reference = originals[id(source)]
                if reference is not None and reference not in references:
                    references.append(reference)
    if any(id(source) not in seen_tables for source in scoped.find_all(exp.Table)):
        return None
    identity = _named(table, SqlObjectType.TABLE, "altered")
    target_table = table.copy()
    target_table.set("alias", None)
    return StatementFacts(
        "MERGE",
        "DML",
        ((identity,) if identity else ()) + tuple(references),
        target=".".join(part for part in (table.catalog, table.db, table.name) if part),
        target_sql=target_table.sql(dialect=dialect),
        affected_columns=tuple(_sqlglot_updated_columns(node)),
        events=frozenset(events),
    )


def _copy_query_referenced(query: exp.Subquery, sql: str) -> Optional[Tuple[NamedObject, ...]]:
    """Resolve query export sources, refusing table functions rather than omitting them."""
    from sqlglot.optimizer.scope import traverse_scope

    query = query.copy()
    original_names = {
        id(table): _named(table, SqlObjectType.TABLE, "referenced")
        for table in query.find_all(exp.Table)
    }
    # Scope lookup must use DuckDB's case rules while facts preserve the written identities.
    dialect = Dialect.get_or_raise("duckdb")
    for identifier in query.find_all(exp.Identifier):
        dialect.normalize_identifier(identifier)

    found: list[NamedObject] = []
    for scope in traverse_scope(query):
        if scope.is_udtf:
            return None
        for source in scope.sources.values():
            if isinstance(source, exp.Table):
                if not isinstance(source.this, exp.Identifier) or not source.name:
                    return None
                # sqlglot represents a single-quoted file source as a quoted table identifier.
                start = source.this.meta.get("start")
                if source.this.args.get("quoted") and (start is None or sql[start] != '"'):
                    return None
                reference = original_names[id(source)]
                if reference is not None and reference not in found:
                    found.append(reference)
    return tuple(found)


def _copy_facts(node: exp.Copy, sql: str, *, dialect: str = "duckdb") -> StatementFacts:
    """Read literal-file COPY; PostgreSQL permits only option-free table transfers."""
    schema = node.this if isinstance(node.this, exp.Schema) else None
    table = schema.this if schema is not None else node.this
    direction = node.args.get("kind")
    query = table if isinstance(table, exp.Subquery) and isinstance(table.this, exp.Query) else None
    files = node.args.get("files") or []
    columns = schema.expressions if schema is not None else []
    opaque = StatementFacts(
        "COPY", "UNKNOWN", diagnostic=f"{dialect} COPY source or destination is opaque"
    )
    if not (
        (
            (isinstance(table, exp.Table) and isinstance(table.this, exp.Identifier))
            or (query is not None and direction is False)
        )
        and (direction is True or direction is False)
        and all(isinstance(column, exp.Identifier) for column in columns)
        and len(files) == 1
        and isinstance(files[0], exp.Literal)
        and files[0].is_string
        # A path concatenation can be misread as a COPY option named ``||``.
        and all(parameter.name.isidentifier() for parameter in node.args.get("params") or [])
        and not any(parameter.find(exp.Query) for parameter in node.args.get("params") or [])
    ):
        return opaque
    if dialect == "postgres":  # lint: allow-dialect-string: narrow PostgreSQL file COPY facts
        if not (
            isinstance(table, exp.Table)
            and table.name
            and table.args.get("catalog") is None
            and (table.args.get("db") is None or table.db)
            and not any(value for key, value in table.args.items() if key not in {"this", "db"})
            and (schema is None or columns)
            and all(column.name for column in columns)
            and not node.args.get("params")
            and not any(
                value
                for key, value in node.args.items()
                if key not in {"this", "kind", "files", "params", "credentials"}
            )
            and not any((node.args.get("credentials") or exp.Credentials()).args.values())
        ):
            return opaque
    importing = direction is True
    # sqlglot defaults a missing direction to FROM; require the actual keyword before the path.
    tokens = Dialect.get_or_raise(dialect).tokenize(sql)
    path_at = next(
        (i for i, token in enumerate(tokens) if token.start == files[0].meta.get("start")), 0
    )
    expected = (TokenType.FROM, "FROM") if importing else (TokenType.VAR, "TO")
    if (
        not path_at
        or (tokens[path_at - 1].token_type, tokens[path_at - 1].text.upper()) != expected
    ):
        return opaque
    if dialect == "postgres":  # lint: allow-dialect-string: reject unmodelled COPY suffixes
        suffix = tokens[path_at + 1 :]
        if suffix and not (len(suffix) == 1 and suffix[0].token_type == TokenType.SEMICOLON):
            return opaque
    if query is not None:
        references = _copy_query_referenced(query, sql)
        return StatementFacts("COPY", "QUERY", references) if references is not None else opaque
    identity = _named(table, SqlObjectType.TABLE, "altered" if importing else "referenced")
    target = ".".join(part for part in (table.catalog, table.db, table.name) if part)
    return StatementFacts(
        "COPY",
        "DML" if importing else "QUERY",
        (identity,) if identity else (),
        target if importing else None,
        affected_columns=tuple(column.name for column in columns) if importing else (),
        events=frozenset({"INSERT"}) if importing else None,
        target_sql=table.sql(dialect=dialect) if importing else None,
    )


def _nests_block_comments(dialect: str) -> bool:
    """Whether the engine nests ``/* /* */ */``: its lexical spec says so, or sqlglot's does."""
    if not dialect:  # no engine named: sqlglot's base dialect nests, which no caller means
        return False
    from dblift.db.provider_registry import ProviderRegistry

    spec = ProviderRegistry.get_quirks(dialect).lexical_spec()
    return bool(spec and spec.nested_comments) or bool(
        Dialect.get_or_raise(dialect).tokenizer_class.NESTED_COMMENTS
    )


def _blanked(sql: str, dialect: str = "") -> str:
    return strip_comments_preserving_quotes(
        sql,
        line_prefixes=["--"],
        has_block_comments=True,
        nested_block_comments=_nests_block_comments(dialect),
    )


_DML_FORM = {
    "INSERT": re.compile(r"^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\b", re.IGNORECASE),
    "REPLACE": re.compile(r"^\s*REPLACE\s+INTO\b", re.IGNORECASE),
    "UPDATE": re.compile(r"^\s*UPDATE\b", re.IGNORECASE),
    "DELETE": re.compile(r"^\s*DELETE\s+FROM\b", re.IGNORECASE),
}
_MYSQL_NAME = r"(?:`[^`]*`|[\w$]+)"
_MYSQL_QUALIFIED = rf"{_MYSQL_NAME}(?:\s*\.\s*{_MYSQL_NAME})?"
_MYSQL_SINGLE_TARGET = re.compile(
    rf"^\s*(?:UPDATE\s+{_MYSQL_QUALIFIED}\s+SET\b"
    rf"|DELETE\s+FROM\s+{_MYSQL_QUALIFIED}(?:\s*;?\s*$|\s+(?:WHERE|ORDER|LIMIT)\b))",
    re.IGNORECASE | re.ASCII,
)


def _mysql_single_target(sql: str, head: str) -> bool:
    """The head text proves one target and every quote in it closes; a non-ASCII statement may
    hide a name character that comment stripping trimmed, so it proves nothing. ``#`` opens a MySQL
    comment and a backslash escapes a quote; the head blanking knows neither, so either proves
    nothing."""
    if not sql.isascii() or "#" in sql or "\\" in sql or not _MYSQL_SINGLE_TARGET.match(head):
        return False
    try:
        Dialect.get_or_raise("mysql").tokenize(head)  # lint: allow-dialect-string: MySQL tokens
    except TokenError:
        return False
    return True


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


def _oracle_fold_name(name: str) -> Optional[str]:
    """The name Oracle stores for an unquoted one: each letter in its one-character upper-case
    form (23.26.3: ``ı`` is ``I``, ``µ`` is the Greek capital MU; ``ß``, ``ﬁ`` and ``ŉ`` stay).
    ``None`` when a letter's upper-case form is not one character: the probes covered only those
    three, so the name is not guessed."""
    if name.isascii():
        return name.upper()
    folded = [letter.upper() for letter in name]
    return "".join(folded) if all(len(letter) == 1 for letter in folded) else None


def _head_object(match: "re.Match[str]", *, fold: bool = False) -> Optional[NamedObject]:
    operation = match.group(1).upper()
    object_type = SqlObjectType["_".join(match.group(2).upper().split())]
    name = strip_identifier_quotes(match.group(4) or match.group(3))
    schema = strip_identifier_quotes(match.group(3)) if match.group(4) else None
    if fold:  # an unquoted name is stored upper-cased, a quoted one as written
        folded_name: Optional[str] = name
        folded_schema = schema
        if not (match.group(4) or match.group(3)).startswith('"'):
            folded_name = _oracle_fold_name(name)
        if schema is not None and not match.group(3).startswith('"'):
            folded_schema = _oracle_fold_name(schema)
        if folded_name is None or (schema is not None and folded_schema is None):
            return None
        name, schema = folded_name, folded_schema
    role = {"CREATE": "created", "ALTER": "altered", "DROP": "dropped"}[operation]
    return NamedObject(name, object_type, role, schema)


_ORACLE_INDEX_ON = re.compile(
    rf"\s+ON\s+(?!CLUSTER\b)({_ORACLE_NAME})(?:\s*\.\s*({_ORACLE_NAME}))?\s*\(", re.IGNORECASE
)


def _oracle_index_table(head: str, created: "re.Match[str]") -> Optional[NamedObject]:
    """The table of ``CREATE INDEX [s.]ix ON [s.]t (...)`` read after the index name, folded as
    Oracle stores it; ``None`` for a cluster index or a name the text does not bound."""
    on = _ORACLE_INDEX_ON.match(head, created.end())
    if on is None or not _head_name_is_bounded(head, on, (1, 2)):
        return None
    if re.search(r"\bFROM\b", head[on.end() :], re.IGNORECASE):
        return None  # a bitmap join index also reads the tables of its FROM clause
    parts = [raw for raw in (on.group(1), on.group(2)) if raw]
    folded = [
        strip_identifier_quotes(raw) if raw.startswith('"') else _oracle_fold_name(raw)
        for raw in parts
    ]
    if any(name is None for name in folded):
        return None
    names = [name for name in folded if name is not None]
    return NamedObject(
        names[-1], SqlObjectType.TABLE, "referenced", names[0] if len(names) > 1 else None
    )


def _head_facts(sql: str, diagnostic: str, *, dialect: str = "") -> StatementFacts:
    """Classify a statement from its leading words when sqlglot cannot represent the body."""
    head = _blanked(sql, dialect)
    first = _FIRST_WORD.match(head)
    if first and first.group(1).upper() == "WITH":
        head = _main_statement(head)
        first = _FIRST_WORD.match(head)
    operation = first.group(1).upper() if first else "UNKNOWN"
    kind = _KINDS.get(operation, "UNKNOWN")
    if dialect == "tsql":  # lint: allow-dialect-string: unread T-SQL names are not proven
        if operation == "MERGE":
            kind = "DML"
        elif operation == "TRUNCATE":
            kind = "DDL"
        return StatementFacts(operation, kind, diagnostic=diagnostic)
    if (
        dialect == "mysql"  # lint: allow-dialect-string: unread MySQL mutations may be multi-target
        and operation in {"UPDATE", "DELETE"}
        and not _mysql_single_target(sql, head)
    ):
        return StatementFacts(operation, kind, diagnostic=diagnostic)
    if (
        dialect == "oracle"  # lint: allow-dialect-string: unread Oracle targets may be expressions
        and operation in {"INSERT", "UPDATE", "DELETE"}
    ):
        return StatementFacts(operation, kind, diagnostic=diagnostic)
    if dialect == "duckdb":  # lint: allow-dialect-string: preserve DuckDB opaque metadata kinds
        kind = {"COMMENT": "DDL", "SHOW": "QUERY", "EXECUTE": "DML"}.get(operation, kind)
    postgres = dialect == "postgres"  # lint: allow-dialect-string: PostgreSQL head kinds
    if postgres:
        kind = "DDL" if operation == "COMMENT" else kind
    objects: Tuple[NamedObject, ...] = ()
    oracle = dialect == "oracle"  # lint: allow-dialect-string: Oracle head kinds and folding
    match = (_ORACLE_HEAD if oracle else _POSTGRES_HEAD if postgres else _HEAD).match(head)
    if match is None and first is None:
        # Stray characters (a NUL, a lone ``/``) ahead of the statement; the engine reads past them.
        scan = _POSTGRES_HEAD_SCAN if postgres else _HEAD_SCAN
        match = scan.search(head.replace("\x00", " "))
        if match:
            operation = match.group(1).upper()
            kind = _KINDS[operation]
    dml = _DML_HEAD.match(head)
    if match and not _head_name_is_bounded(head, match, (3, 4)):
        match = None
    if oracle and match and match.group(4) and match.group(2).upper().startswith("DATABASE"):
        match = None  # a link name is global: ``a.b`` is one name with a domain, not a schema
    if dml and not _head_name_is_bounded(head, dml, (2, 3)):
        dml = None
    if match:
        found = _head_object(match, fold=oracle)
        if found is not None:
            diagnostic = f"{found.type.value.lower().replace('_', ' ')}: {diagnostic}"
            objects = (found,)
    elif dml and _DML_FORM[operation].match(head) and dml.group(2).upper() not in _NOT_A_TABLE:
        schema = strip_identifier_quotes(dml.group(2)) if dml.group(3) else None
        name = strip_identifier_quotes(dml.group(3) or dml.group(2))
        objects = (NamedObject(name, SqlObjectType.TABLE, "altered", schema),)
        target = f"{schema}.{name}" if schema else name
        where = _top_level_where(head)
        predicate = head[where:].strip() if where is not None else None
        if (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL single-target text
            and operation in {"UPDATE", "DELETE"}
            and predicate
        ):
            predicate = predicate[len("WHERE") :].strip()
        events = None if operation == "REPLACE" else frozenset({operation})
        return StatementFacts(
            operation,
            kind,
            objects,
            target,
            predicate,
            events=events,
            diagnostic=diagnostic,
            target_sql=target,
        )
    if oracle and match and operation == "CREATE" and objects and objects[0].type.name == "INDEX":
        table = _oracle_index_table(head, match)
        if table is not None:
            return StatementFacts(
                operation, kind, objects + (table,), diagnostic=diagnostic, indexed_table=table.name
            )
    return StatementFacts(operation, kind, objects, diagnostic=diagnostic)


def _mysql_unresolved_mutation_target(ast: exp.Expression) -> bool:
    """Refuse multiple or unproven targets before projecting singular mutation facts."""
    if isinstance(ast, exp.Delete):
        targets = ast.args.get("tables") or []
        using = ast.args.get("using")
        table = _dml_target_table(ast)
        if using or len(targets) > 1 or table is None:
            return True
        if targets:
            wanted = targets[0]
            return (
                wanted.name != table.alias_or_name
                or bool(wanted.db and wanted.db != table.db)
                or bool(wanted.catalog and wanted.catalog != table.catalog)
            )
        return False
    if not isinstance(ast, exp.Update) or not isinstance(ast.this, exp.Table):
        return False
    table = ast.this
    if not table.args.get("joins"):
        return False
    # A JOIN is not itself evidence of multiple write targets. Every SET left-hand
    # side must explicitly name the leading target; unqualified columns need a catalogue.
    for assignment in ast.expressions:
        column = assignment.this
        if (
            not isinstance(column, exp.Column)
            or column.table != table.alias_or_name
            or (column.db and column.db != table.db)
            or (column.catalog and column.catalog != table.catalog)
        ):
            return True
    return False


def _fold_oracle_names(ast: exp.Expr) -> bool:
    """Fold the unquoted table and index names of an Oracle statement as Oracle stores them; a
    quoted name keeps its spelling. Columns and aliases are left as written. ``True`` when a name
    holds a letter whose upper-case form is not one character: the statement is then unread."""
    unsafe = False

    def fold(part: object) -> None:
        nonlocal unsafe
        if isinstance(part, exp.Identifier) and not part.args.get("quoted"):
            part.meta["written"] = part.name
            folded = _oracle_fold_name(part.name)
            if folded is None:
                unsafe = True
            else:
                part.set("this", folded)

    for node in ast.find_all(exp.Table, exp.Index):
        for key in ("this", "db", "catalog") if isinstance(node, exp.Table) else ("this",):
            fold(node.args.get(key))
    if isinstance(ast, exp.Comment) and isinstance(ast.this, exp.Column):
        for key in ("table", "db", "catalog"):  # COMMENT ON COLUMN s.t.c names its table
            fold(ast.this.args.get(key))
    return unsafe


def _oracle_names_a_remote_object(sql: str) -> bool:
    """Whether the statement uses a database link (``emp@lnk``, ``emp @ lnk``, an ``@`` after a
    comment): no local object has such a name. An ``@`` inside a string, a quoted name or a
    comment is not one. Oracle 23.26.3 accepts blanks and comments around the ``@``."""
    try:
        tokens = Dialect.get_or_raise("oracle").tokenize(sql)  # lint: allow-dialect-string: links
    except TokenError:
        return False
    return any(token.token_type not in _QUOTED_TOKENS and "@" in token.text for token in tokens)


_Node = TypeVar("_Node", bound=exp.Expression)


def _oracle_as_written(node: _Node) -> _Node:
    """The node with its table names spelled as the statement spells them: ``target_sql`` and
    ``predicate`` are text a consumer sends back, where Oracle folds unquoted names itself."""
    written = node.copy()
    for part in written.find_all(exp.Identifier):
        if "written" in part.meta:
            part.set("this", part.meta["written"])
    return written


def _postgres_comment_identity(ast: exp.Comment) -> Optional[NamedObject]:
    """The object ``COMMENT ON`` changes; a column comment changes its table."""
    kind = str(ast.args.get("kind") or "").upper()
    node = ast.this
    if kind == "COLUMN" and isinstance(node, exp.Column):
        node = exp.Table(
            this=node.args.get("table"), db=node.args.get("db"), catalog=node.args.get("catalog")
        )
        kind = "TABLE"
    elif kind == "VIEW" and ast.args.get("materialized"):
        kind = "MATERIALIZED_VIEW"
    object_type = SqlObjectType.__members__.get(kind)
    if object_type is None or not isinstance(node, exp.Table):
        return None
    return _named(node, object_type, "altered")


def _select_into_table(ast: exp.Expr) -> Optional[exp.Expression]:
    """The table of a top-level ``SELECT ... INTO``, also when it leads a set operation."""
    first: exp.Expr = ast
    while isinstance(first, exp.SetOperation):
        first = first.this
    into = first.args.get("into")
    return into.this if isinstance(into, exp.Into) else None


_MYSQL_QUALIFIED = rf"({_NAME})(?:\s*\.\s*({_NAME}))?"
_MYSQL_RENAME_PAIR = rf"{_MYSQL_QUALIFIED}\s+TO\s+{_MYSQL_QUALIFIED}"
_MYSQL_RENAME = re.compile(
    rf"^\s*RENAME\s+TABLE\s+{_MYSQL_RENAME_PAIR}(?:\s*,\s*{_MYSQL_RENAME_PAIR})*\s*;?\s*$",
    re.IGNORECASE,
)
_MYSQL_RENAME_SOURCE = re.compile(rf"{_MYSQL_QUALIFIED}\s+TO\s+{_MYSQL_QUALIFIED}", re.IGNORECASE)
_MYSQL_DEFINER_USER = r"(?:`(?:``|[^`])*`|'(?:''|[^'])*'|[\w$]+)"
_MYSQL_PROGRAM = re.compile(
    rf"^\s*(?:(CREATE)\s+(?:OR\s+REPLACE\s+)?"
    rf"(?:DEFINER\s*=\s*(?:CURRENT_USER(?:\s*\(\s*\))?|{_MYSQL_DEFINER_USER}"
    rf"(?:\s*@\s*(?:{_MYSQL_DEFINER_USER}|[\w$.%-]+))?)\s+)?"
    rf"(FUNCTION|PROCEDURE|EVENT|TRIGGER)\s+(?:IF\s+NOT\s+EXISTS\s+)?"
    rf"|(DROP)\s+(EVENT)\s+(?:IF\s+EXISTS\s+)?)"
    rf"{_MYSQL_QUALIFIED}"
    rf"(?:\s+(?:BEFORE|AFTER)\s+(?:INSERT|UPDATE|DELETE)\s+ON\s+{_MYSQL_QUALIFIED})?",
    re.IGNORECASE,
)


def _mysql_program_facts(sql: str, diagnostic: str) -> Optional[StatementFacts]:
    """The program a CREATE / DROP of a function, procedure, event or trigger names, read from the
    head alone; the body is not read."""
    head = _blanked(sql)
    match = _MYSQL_PROGRAM.match(head)
    if match is None:
        return None
    operation = (match.group(1) or match.group(3)).upper()
    kind = SqlObjectType[(match.group(2) or match.group(4)).upper()]
    parts = [match.group(i) for i in (5, 6)]
    if not _head_name_is_bounded(head, match, (5, 6, 7, 8)):
        return None
    schema, name = (parts[0], parts[1]) if parts[1] else (None, parts[0])
    role = "created" if operation == "CREATE" else "dropped"
    objects = [
        NamedObject(
            strip_identifier_quotes(name),
            kind,
            role,
            strip_identifier_quotes(schema) if schema else None,
        )
    ]
    if match.group(7):
        t_schema, t_name = (
            (match.group(7), match.group(8)) if match.group(8) else (None, match.group(7))
        )
        objects.append(
            NamedObject(
                strip_identifier_quotes(t_name),
                SqlObjectType.TABLE,
                "referenced",
                strip_identifier_quotes(t_schema) if t_schema else None,
            )
        )
    return StatementFacts(operation, "DDL", tuple(objects), diagnostic=diagnostic)


_MYSQL_SPECIAL_INDEX = re.compile(
    rf"^\s*CREATE\s+(?:FULLTEXT|SPATIAL)\s+INDEX\s+({_NAME})\s+ON\s+{_MYSQL_QUALIFIED}\s*\(",
    re.IGNORECASE,
)


def _mysql_command_facts(sql: str) -> Optional[StatementFacts]:
    """RENAME TABLE and CREATE FULLTEXT / SPATIAL INDEX, which sqlglot's MySQL grammar leaves as
    an opaque command."""
    head = _blanked(sql)
    first = _FIRST_WORD.match(head)
    if first and first.group(1).upper() == "RENAME":
        if not _MYSQL_RENAME.match(head):
            return StatementFacts(
                "RENAME", "DDL", diagnostic="mysql RENAME form is opaque to statement facts"
            )
        body = re.sub(r"^\s*RENAME\s+TABLE\s+", "", head, flags=re.IGNORECASE)
        sources = []
        for pair in _MYSQL_RENAME_SOURCE.finditer(body):
            schema, name = (
                (pair.group(1), pair.group(2)) if pair.group(2) else (None, pair.group(1))
            )
            sources.append(
                NamedObject(
                    strip_identifier_quotes(name),
                    SqlObjectType.TABLE,
                    "altered",
                    strip_identifier_quotes(schema) if schema else None,
                )
            )
        return StatementFacts("RENAME", "DDL", tuple(sources))
    match = _MYSQL_SPECIAL_INDEX.match(head)
    if match is None:
        return None
    schema, name = (match.group(2), match.group(3)) if match.group(3) else (None, match.group(2))
    table = strip_identifier_quotes(name)
    schema = strip_identifier_quotes(schema) if schema else None
    return StatementFacts(
        "CREATE",
        "DDL",
        (
            NamedObject(strip_identifier_quotes(match.group(1)), SqlObjectType.INDEX, "created"),
            NamedObject(table, SqlObjectType.TABLE, "referenced", schema),
        ),
        indexed_table=f"{schema}.{table}" if schema else table,
        diagnostic="mysql index columns are opaque to statement facts",
    )


_MYSQL_DML_VERB = re.compile(
    r"^((?:\s|#[^\n]*\n|--\s[^\n]*\n|/\*.*?\*/)*(UPDATE|DELETE|INSERT|REPLACE))\b",
    re.IGNORECASE | re.DOTALL,
)


# The shared pattern skips only block comments (``#`` starts a T-SQL temporary table elsewhere);
# MySQL also ends a modifier gap with ``# ...`` and ``-- ...`` line comments.
_MYSQL_MODIFIER_GAP = {
    verb: re.compile(
        r"\s*(?:#[^\n]*(?:\n|$)|--(?=[\x00-\x20\x7f])[^\n]*(?:\n|$)|"
        + pattern.pattern.removeprefix(r"\s*(?:"),
        pattern.flags,
    )
    for verb, pattern in MYSQL_DML_MODIFIER.items()
}


def _without_mysql_dml_modifiers(sql: str) -> str:
    """Drop the modifier words and comments between a DML verb and its target.

    sqlglot's MySQL grammar does not read these modifiers.
    """
    verb = _MYSQL_DML_VERB.match(sql)
    if verb is None:
        return sql
    pos = verb.end()
    while modifier := _MYSQL_MODIFIER_GAP[verb.group(2).upper()].match(sql, pos):
        pos = modifier.end()
    return sql if pos == verb.end() else f"{sql[: verb.end()]} {sql[pos:].lstrip()}"


_REDSHIFT_NAME_LEADERS = frozenset(
    {"TABLE", "VIEW", "INDEX", "EXISTS", "INTO", "FROM", "UPDATE", "ONLY", "ON", "JOIN", "SCHEMA"}
)
_REDSHIFT_NAMED_STATEMENTS = frozenset(
    {"CREATE", "ALTER", "DROP", "INSERT", "UPDATE", "DELETE", "WITH", "TRUNCATE", "COMMENT", "COPY"}
)


def _redshift_bracketed_name(sql: str, dialect: str) -> Optional[StatementFacts]:
    """A statement with ``[`` where a name belongs, or ``None``.

    Redshift drops the brackets around a name (``[t]`` is ``t``, ``["a""b"]`` is ``a"b``) and
    rejects a space or ``;`` inside them, so the text between the brackets is not the name. A
    ``[`` after a name or a call is a SUPER subscript, and one inside a string or a quoted
    identifier is no token at all: both are read normally.
    """
    try:
        tokens = Dialect.get_or_raise(dialect).tokenize(sql)
    except TokenError:
        return None
    if not tokens or tokens[0].text.upper() not in _REDSHIFT_NAMED_STATEMENTS:
        return None
    for before, token in zip(tokens, tokens[1:]):
        if token.token_type == TokenType.L_BRACKET and (
            before.token_type == TokenType.DOT or before.token_type.name in _REDSHIFT_NAME_LEADERS
        ):
            head = _head_facts(sql, "", dialect=dialect)
            return StatementFacts(
                head.operation, head.kind, diagnostic="redshift bracketed name is not modelled"
            )
    return None


def _redshift_facts(ast: exp.Expr, sql: str, dialect: str) -> Optional[StatementFacts]:
    """The statements Redshift reads differently from the generic reading, or ``None``.

    Measured on Redshift Serverless 1.0.485645 (docs/sql-parsing/redshift.md): ``COPY`` loads (the
    unload direction is ``UNLOAD``), ``TRUNCATE`` takes one table, a two-part schema name is
    database.schema, and ``SELECT ... INTO`` creates the table.
    """
    opaque_cte = _postgresql_opaque_cte(ast, dialect)
    if opaque_cte is not None:
        return opaque_cte
    if isinstance(ast, exp.Copy):
        # The options follow the source and cannot change the table it loads; sqlglot misreads
        # some (``IGNOREHEADER 1``), so only the table, columns and source are checked.
        loaded = ast.copy()
        loaded.set("params", None)
        return _copy_facts(loaded, sql, dialect=dialect)
    if isinstance(ast, exp.Merge):
        table = ast.this
        identity = (
            _named(table, SqlObjectType.TABLE, "altered")
            if isinstance(table, exp.Table) and isinstance(table.this, exp.Identifier)
            else None
        )
        bare = table.copy() if identity is not None else None
        if bare is not None:
            bare.set("alias", None)
        return StatementFacts(
            "MERGE",
            "DML",
            (identity,) if identity else (),
            target=(
                ".".join(part for part in (table.catalog, table.db, table.name) if part)
                if identity
                else None
            ),
            target_sql=bare.sql(dialect=dialect) if bare is not None else None,
            diagnostic="redshift MERGE sources and actions are not read",
        )
    if isinstance(ast, (exp.Grant, exp.Revoke)):
        return StatementFacts(
            type(ast).__name__.upper(),
            "DDL",
            diagnostic=f"redshift {type(ast).__name__} privilege targets are not modelled",
        )
    if isinstance(ast, exp.Comment):
        identity = _postgres_comment_identity(ast)
        if identity is not None and identity.type in {SqlObjectType.TABLE, SqlObjectType.VIEW}:
            return StatementFacts("COMMENT", "DDL", (identity,))
        return StatementFacts(
            "COMMENT", "DDL", diagnostic="redshift COMMENT target is not modelled"
        )
    if isinstance(ast, exp.TruncateTable):
        target = ast.expressions[0] if len(ast.expressions) == 1 else None
        identity = (
            _named(target, SqlObjectType.TABLE, "altered")
            if isinstance(target, exp.Table)
            and isinstance(target.this, exp.Identifier)
            and not target.catalog
            and not target.args.get("only")
            and not any(value for key, value in ast.args.items() if key != "expressions")
            else None
        )
        if identity is None:
            return StatementFacts(
                "TRUNCATE", "DDL", diagnostic="redshift TRUNCATE target is not a single table"
            )
        return StatementFacts("TRUNCATE", "DDL", (identity,))
    if (
        isinstance(ast, (exp.Create, exp.Drop))
        and str(ast.args.get("kind") or "").upper() == "SCHEMA"
    ):
        role = "created" if isinstance(ast, exp.Create) else "dropped"
        targets = [ast.this] if isinstance(ast, exp.Create) else list(ast.args.get("tables") or [])
        # Schema names sit in Table.db; a name with a second part is database.schema.
        schemas = tuple(
            NamedObject(target.db, SqlObjectType.SCHEMA, role)
            for target in targets
            if isinstance(target, exp.Table)
            and target.db
            and not target.catalog
            and not target.name
        )
        if len(schemas) == len(targets) == 1:
            return StatementFacts(type(ast).__name__.upper(), "DDL", schemas)
        return StatementFacts(
            type(ast).__name__.upper(),
            "DDL",
            diagnostic="redshift schema name has a database part or is not a plain name",
        )
    if isinstance(ast, exp.Query):
        into = _select_into_table(ast)
        if into is not None and (created := _named(into, SqlObjectType.TABLE, "created")):
            sources = _referenced(ast, tuple(into.find_all(exp.Table)))
            return StatementFacts("SELECT", "DML", (created,) + sources)
    return None


def read_statement_facts(sql: str, *, dialect: str) -> StatementFacts:
    """Read one already-split statement; never retry a second extractor.

    Text that does not tokenize is reported as an error. A statement the grammar does not
    model is classified from its leading words with an informational diagnostic.
    """
    # MariaDB shares this grammar; without engine/version context both markers are opaque.
    if (
        dialect == "mysql"  # lint: allow-dialect-string: MySQL-family executable comments
        and ("/*!" in sql or "/*M!" in sql)
        and any(
            match.group().startswith(("/*!", "/*M!"))
            for match in _MYSQL_QUOTES_AND_COMMENTS.finditer(sql)
        )
    ):
        return StatementFacts(
            "UNKNOWN", "UNKNOWN", diagnostic="mysql executable comment is opaque to statement facts"
        )
    unread = unread_name_character(sql, dialect=dialect)
    if unread is not None:
        return _unread_name_facts(sql, dialect, unread)
    wide = (
        _supplementary_name_character(sql)
        if dialect == "mysql"  # lint: allow-dialect-string: MySQL name characters
        else None
    )
    if wide:
        head = _head_facts(sql, "", dialect=dialect)
        return StatementFacts(
            head.operation,
            head.kind,
            diagnostic=(
                f"mysql statement holds U+{ord(wide):04X} in a name, which MySQL stores as ? "
                "and MariaDB rejects; its objects are not named"
            ),
        )
    if dialect == "tsql" and re.match(  # lint: allow-dialect-string: foreign OR DML modifiers
        r"^\s*(?:INSERT|UPDATE|DELETE)\s+OR\s+(?:IGNORE|REPLACE)\b", _blanked(sql, dialect), re.I
    ):
        return _head_facts(sql, "tsql OR DML modifier is not modelled", dialect=dialect)
    if dialect == "mysql":  # lint: allow-dialect-string: MySQL DML modifiers
        sql = _without_mysql_dml_modifiers(sql)
    if dialect == "redshift":  # lint: allow-dialect-string: Redshift bracketed names
        bracketed = _redshift_bracketed_name(sql, dialect)
        if bracketed is not None:
            return bracketed
    try:
        ast = parse_one(_UPDATE_OR.sub(r"\1", sql), read=dialect)
        if dialect == "oracle" and ast is not None:  # lint: allow-dialect-string: Oracle folding
            unread_reason = (
                "oracle name holds a letter whose upper-case form is not one character"
                if _fold_oracle_names(ast)
                else (
                    "oracle statement names an object through a database link"
                    if _oracle_names_a_remote_object(sql)
                    else None
                )
            )
            if unread_reason is not None:
                head = _head_facts(sql, "", dialect=dialect)
                return StatementFacts(head.operation, head.kind, diagnostic=unread_reason)
    except (ParseError, TokenError) as exc:
        if not isinstance(exc, TokenError) and not _blanked(sql, dialect).strip():
            return StatementFacts("UNKNOWN", "UNKNOWN")
        if isinstance(exc, TokenError):
            facts = _head_facts(sql, "", dialect=dialect)
            return replace(
                facts,
                diagnostic=None,
                error=f"{dialect} statement could not be tokenized (unterminated quote or comment)",
            )
        reason = f"{dialect} grammar is not modelled for this statement"
        if (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL stored programs and events
            and (program := _mysql_program_facts(sql, reason)) is not None
        ):
            return program
        return _head_facts(sql, reason, dialect=dialect)
    if (
        dialect == "mysql"  # lint: allow-dialect-string: sqlglot reads these MySQL forms as Command
        and isinstance(ast, exp.Command)
        and (command := _mysql_command_facts(sql)) is not None
    ):
        return command
    if ast is None or isinstance(ast, (exp.Command, exp.Block)):
        construct = type(ast).__name__ if ast is not None else "empty statement"
        if (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL stored programs and events
            and ast is not None
            and (
                program := _mysql_program_facts(
                    sql, f"{dialect} {construct} is opaque to statement facts"
                )
            )
            is not None
        ):
            return program
        return _head_facts(
            sql, f"{dialect} {construct} is opaque to statement facts", dialect=dialect
        )

    if dialect == "redshift":  # lint: allow-dialect-string: Redshift statement forms
        redshift_facts = _redshift_facts(ast, sql, dialect)
        if redshift_facts is not None:
            return redshift_facts

    if dialect == "tsql":  # lint: allow-dialect-string: T-SQL multi-part names and modules
        ctes = tuple(ast.find_all(exp.CTE))
        schema_targets: tuple[exp.Expression, ...] = ()
        if isinstance(ast, exp.Create) and str(ast.args.get("kind") or "").upper() == "SCHEMA":
            schema_targets = (ast.this,)
        elif isinstance(ast, exp.Drop) and str(ast.args.get("kind") or "").upper() == "SCHEMA":
            schema_targets = tuple(ast.args.get("tables") or ())
        if any(not isinstance(cte.this, exp.Query) for cte in ctes):
            operation = type(ast).__name__.upper()
            kind = "DML" if operation in {"INSERT", "UPDATE", "DELETE"} else "QUERY"
            return StatementFacts(
                operation,
                kind,
                diagnostic="tsql CTE body effects are opaque to statement facts",
            )
        cte_target = _dml_target_table(ast) if isinstance(ast, (exp.Update, exp.Delete)) else None
        if (
            isinstance(cte_target, exp.Table)
            and not cte_target.db
            and not cte_target.catalog
            and any(cte_target.name.lower() == cte.alias.lower() for cte in ctes)
        ):
            return StatementFacts(
                type(ast).__name__.upper(),
                "DML",
                diagnostic="tsql CTE write target is not resolved to a base table",
            )
        if any(
            isinstance(table.this, exp.Identifier)
            and (table.this.args.get("temporary") or table.this.args.get("global_"))
            for table in ast.find_all(exp.Table)
        ):
            head = _head_facts(sql, "tsql temporary table identity is opaque", dialect=dialect)
            if isinstance(ast, exp.Query) and _select_into_table(ast) is not None:
                return replace(head, kind="DML")
            return head
        if any(
            (
                not isinstance(table.this, exp.Identifier)
                and not (
                    any(table is subject for subject in schema_targets)
                    and table.this is None
                    and isinstance(table.args.get("db"), exp.Identifier)
                    and not table.catalog
                )
            )
            or (table.args.get("catalog") is not None and not table.db)
            for table in ast.find_all(exp.Table)
        ):
            return _head_facts(
                sql, "tsql table identity has unmodelled name parts", dialect=dialect
            )
        if isinstance(ast, exp.Create) and str(ast.args.get("kind") or "").upper() in {
            "PROCEDURE",
            "FUNCTION",
            "TRIGGER",
        }:
            return _head_facts(sql, "tsql program body effects are opaque", dialect=dialect)
        if (
            isinstance(ast, exp.Create)
            and str(ast.args.get("kind") or "").upper() == "VIEW"
            and ast.args.get("properties")
            and ast.args["properties"].find(exp.MaterializedProperty)
        ) or (isinstance(ast, exp.Drop) and ast.args.get("materialized")):
            return _head_facts(sql, "tsql materialized view effects are opaque", dialect=dialect)
        if (
            isinstance(ast, exp.Query)
            and _select_into_table(ast) is not None
            and any(
                into.args.get("temporary") or into.args.get("unlogged")
                for into in ast.find_all(exp.Into)
            )
        ):
            return replace(
                _head_facts(sql, "tsql SELECT INTO scope is opaque", dialect=dialect),
                kind="DML",
            )

    if (
        dialect == "postgres"  # lint: allow-dialect-string: qualified PostgreSQL MERGE facts
        and isinstance(ast, exp.Merge)
    ):
        merge_facts = _postgres_merge_facts(ast)
        if merge_facts is not None:
            return merge_facts
        return _head_facts(sql, "postgres MERGE effects are not modelled", dialect=dialect)

    if dialect == "postgres":  # lint: allow-dialect-string: PostgreSQL COPY and CTE boundaries
        if isinstance(ast, exp.Copy):
            return _copy_facts(ast, sql, dialect=dialect)
        opaque_cte = _postgresql_opaque_cte(ast, dialect)
        if opaque_cte is not None:
            return opaque_cte

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

    if (
        dialect == "duckdb"  # lint: allow-dialect-string: COPY facts qualified for DuckDB only
        and isinstance(ast, exp.Copy)
    ):
        return _copy_facts(ast, sql)

    if dialect == "postgres" and isinstance(  # lint: allow-dialect-string: PostgreSQL COMMENT ON
        ast, exp.Comment
    ):
        identity = _postgres_comment_identity(ast)
        if identity is not None:
            return StatementFacts("COMMENT", "DDL", (identity,))

    if (
        dialect == "oracle"  # lint: allow-dialect-string: Oracle COMMENT ON TABLE, COLUMN, MV
        and isinstance(ast, exp.Comment)
        and (
            str(ast.args.get("kind") or "").upper() in {"TABLE", "COLUMN"}
            or (str(ast.args.get("kind") or "").upper() == "VIEW" and ast.args.get("materialized"))
        )
    ):
        identity = _postgres_comment_identity(ast)
        if identity is not None:
            return StatementFacts("COMMENT", "DDL", (identity,))

    if (
        dialect == "oracle"  # lint: allow-dialect-string: Oracle TRUNCATE TABLE takes one table
        and isinstance(ast, exp.TruncateTable)
        and len(ast.expressions) == 1
        and not ast.args.get("option")  # CASCADE also truncates child tables
        and not ast.args.get("is_database")
        and _ORACLE_TRUNCATE_TABLE.match(_blanked(sql))  # ``TRUNCATE t`` is ORA-03290
    ):
        target = ast.expressions[0]
        if (
            isinstance(target, exp.Table)
            and isinstance(target.this, exp.Identifier)
            and not any(v for k, v in target.args.items() if k not in {"this", "db"})
        ):
            identity = _named(target, SqlObjectType.TABLE, "altered")
            if identity is not None:
                return StatementFacts("TRUNCATE", "DDL", (identity,))

    if dialect == "duckdb":  # lint: allow-dialect-string: DuckDB metadata statement mappings
        if isinstance(ast, exp.Comment) and ast.args.get("kind") == "TABLE":
            identity = _named(ast.this, SqlObjectType.TABLE, "altered")
            return StatementFacts("COMMENT", "DDL", (identity,) if identity else ())
        if isinstance(ast, (exp.Show, exp.Describe)):
            operation = "SHOW" if isinstance(ast, exp.Show) else "DESCRIBE"
            return StatementFacts(operation, "QUERY", _referenced(ast))

    if dialect == "oracle" and (  # lint: allow-dialect-string: PL/SQL bodies are not read
        (
            isinstance(ast, exp.Create)
            and str(ast.args.get("kind") or "").upper() in {"PROCEDURE", "FUNCTION", "TRIGGER"}
        )
        or _ORACLE_MV_LOG.match(_blanked(sql))  # sqlglot reads the log as a view named LOG
    ):
        return _head_facts(
            sql, "oracle PL/SQL bodies and materialized view logs are not read", dialect=dialect
        )

    if isinstance(ast, exp.Create):
        object_type = _created_object_type(ast, dialect)
        schema_node = ast.this if isinstance(ast.this, exp.Schema) else None
        subject = schema_node.this if schema_node is not None else ast.this
        properties = ast.args.get("properties")
        virtual = bool(properties and properties.find(exp.VirtualProperty))
        identity = _named(subject, object_type, "created") if subject is not None else None
        if (
            dialect == "duckdb"  # lint: allow-dialect-string: DuckDB schema identity projection
            and object_type == SqlObjectType.SCHEMA
            and isinstance(subject, exp.Table)
            and subject.db
        ):
            identity = NamedObject(subject.db, object_type, "created", subject.catalog or None)
        if (
            dialect == "postgres"  # lint: allow-dialect-string: PostgreSQL schema identity only
            and object_type == SqlObjectType.SCHEMA
            and isinstance(subject, exp.Table)
            and subject.db
            and not subject.catalog
            and not subject.name
        ):
            identity = NamedObject(subject.db, object_type, "created")
        if (
            dialect == "tsql"  # lint: allow-dialect-string: T-SQL schema name is in Table.db
            and object_type == SqlObjectType.SCHEMA
            and isinstance(subject, exp.Table)
            and subject.db
            and not subject.catalog
            and not subject.name
        ):
            identity = NamedObject(subject.db, object_type, "created")
        if (
            dialect == "postgres"  # lint: allow-dialect-string: PostgreSQL trigger name
            and object_type == SqlObjectType.TRIGGER
            and isinstance(subject, exp.Identifier)
            and subject.name
        ):
            identity = NamedObject(subject.name, object_type, "created")
        if (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL names a schema as a database
            and object_type == SqlObjectType.SCHEMA
            and isinstance(subject, exp.Table)
            and subject.db
            and not subject.catalog
            and not subject.name
        ):
            identity = NamedObject(subject.db, object_type, "created")
        if (
            dialect
            == "mysql"  # lint: allow-dialect-string: MySQL names a trigger by its identifier
            and object_type == SqlObjectType.TRIGGER
            and _mysql_identifier_is_proven(subject, sql)
        ):
            identity = NamedObject(subject.name, object_type, "created")
        objects: Tuple[NamedObject, ...] = (identity,) if identity else ()
        indexed_table = None
        indexed_columns = None
        index_items: Optional[list[exp.Expression]] = []
        if isinstance(subject, exp.Index):
            params = subject.args.get("params")
            index_items = params.args.get("columns", []) if params else []
            table = subject.args.get("table")
            qualified = _qualified_index(subject)
            if dialect == "tsql":  # lint: allow-dialect-string: T-SQL indexes belong to tables
                reference = (
                    _named(table, SqlObjectType.TABLE, "referenced")
                    if isinstance(table, exp.Table)
                    else None
                )
                if (
                    qualified is not None
                    or not isinstance(subject.this, exp.Identifier)
                    or reference is None
                ):
                    return _head_facts(sql, "tsql index relation is opaque", dialect=dialect)
                objects = (
                    NamedObject(subject.this.name, object_type, "created", reference.schema),
                    reference,
                )
                indexed_table = ".".join(
                    part for part in (reference.schema, reference.name) if part
                )
            elif qualified is not None:
                schema, index_name, indexed_table, index_items = qualified
                objects = (
                    NamedObject(index_name, object_type, "created", schema),
                    NamedObject(indexed_table, SqlObjectType.TABLE, "referenced"),
                )
            else:
                if (
                    dialect == "mysql"  # lint: allow-dialect-string: MySQL has no CONCURRENTLY
                    and ast.args.get("concurrently")
                    and not subject.this
                ):
                    # The word is the index name.
                    objects = (NamedObject("CONCURRENTLY", object_type, "created"),)
                elif (
                    dialect == "mysql"  # lint: allow-dialect-string: MySQL has no CONCURRENTLY
                    and ast.args.get("concurrently")
                ):
                    # The word is the index name and the engine rejects what follows it.
                    objects = ()
                    index_items = None
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
        if isinstance(subject, exp.Index) and index_items is not None:
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
        if (
            dialect
            in {"postgres", "oracle", "redshift"}  # lint: allow-dialect-string: materialized views
            and kind == "VIEW"
            and ast.args.get("materialized")
        ):
            object_type = SqlObjectType.MATERIALIZED_VIEW
        targets = ast.args.get("tables") or ast.args.get("expressions") or [ast.this]
        if (
            dialect in {"duckdb", "postgres"}  # lint: allow-dialect-string: schema identity
            and object_type == SqlObjectType.SCHEMA
        ):
            dropped_objects = tuple(
                NamedObject(node.db, object_type, "dropped", node.catalog or None)
                for node in targets
                if isinstance(node, exp.Table) and node.db
            )
        elif (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL names a schema as a database
            and object_type == SqlObjectType.SCHEMA
        ):
            dropped_objects = tuple(
                NamedObject(node.db, object_type, "dropped")
                for node in targets
                if isinstance(node, exp.Table) and node.db and not node.catalog and not node.name
            )
        elif (
            dialect == "tsql"  # lint: allow-dialect-string: T-SQL schema name is in Table.db
            and object_type == SqlObjectType.SCHEMA
        ):
            dropped_objects = tuple(
                NamedObject(node.db, object_type, "dropped")
                for node in targets
                if isinstance(node, exp.Table) and node.db and not node.catalog and not node.name
            )
        else:
            dropped_objects = tuple(
                obj
                for node in targets
                if node is not None
                if (obj := _named(node, object_type, "dropped"))
            )
        indexed_table = None
        on = ast.args.get("cluster")
        if (
            dialect == "tsql"  # lint: allow-dialect-string: T-SQL DROP INDEX names owning table
            and object_type == SqlObjectType.INDEX
        ):
            reference = (
                _named(on.this, SqlObjectType.TABLE, "referenced")
                if isinstance(on, exp.OnProperty) and isinstance(on.this, exp.Table)
                else None
            )
            index = targets[0] if len(targets) == 1 else None
            if (
                not isinstance(index, exp.Table)
                or not isinstance(index.this, exp.Identifier)
                or index.db
                or index.catalog
                or reference is None
            ):
                return _head_facts(sql, "tsql index relation is opaque", dialect=dialect)
            return StatementFacts(
                "DROP",
                "DDL",
                (
                    NamedObject(index.name, object_type, "dropped", reference.schema),
                    reference,
                ),
                indexed_table=".".join(part for part in (reference.schema, reference.name) if part),
            )
        if (
            object_type == SqlObjectType.INDEX
            and isinstance(on, exp.OnProperty)
            and dialect
            not in {"mysql", "tsql"}  # lint: allow-dialect-string: DROP INDEX ON grammar
        ):
            return StatementFacts(
                "DROP",
                "DDL",
                dropped_objects,
                diagnostic=f"index: {dialect} grammar is not modelled for this statement",
            )
        if (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL DROP INDEX names its table
            and object_type == SqlObjectType.INDEX
        ):
            index = targets[0]
            if not (
                isinstance(index, exp.Table)
                and index.args.get("db") is None
                and _mysql_identifier_is_proven(index.this, sql)
                and isinstance(on, exp.OnProperty)
                and (indexed_table := _mysql_on_table_name(on, sql))
            ) or any(
                value
                for key, value in ast.args.items()
                if key not in {"tables", "kind", "cluster", "exists"}
            ):
                return StatementFacts(
                    "DROP", "DDL", dropped_objects, diagnostic="mysql DROP INDEX relation is opaque"
                )
            dropped_objects += (NamedObject(indexed_table, SqlObjectType.TABLE, "referenced"),)
        return StatementFacts("DROP", "DDL", dropped_objects, indexed_table=indexed_table)

    if isinstance(ast, exp.Alter):
        object_type = SqlObjectType.__members__.get(
            str(ast.args.get("kind") or "").upper(), SqlObjectType.UNKNOWN
        )
        identity = _named(ast.this, object_type, "altered") if ast.this is not None else None
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
            diagnostic=None if ast.this is not None else f"{dialect} ALTER names no object",
        )

    if (
        dialect == "postgres"  # lint: allow-dialect-string: PostgreSQL explicit TRUNCATE targets
        and isinstance(ast, exp.TruncateTable)
        and ast.expressions
        and ast.args.get("identity") in (None, "RESTART", "CONTINUE")
        and str(ast.args.get("option") or "").upper() in ("", "CASCADE", "RESTRICT")
        and not any(
            value
            for key, value in ast.args.items()
            if key not in {"expressions", "identity", "option"}
        )
        and all(
            isinstance(target, exp.Table)
            and isinstance(target.this, exp.Identifier)
            and target.name
            and target.args.get("catalog") is None
            and (target.args.get("db") is None or target.db)
            and not any(
                value
                for key, value in target.args.items()
                if key not in {"this", "db", "catalog", "only"}
            )
            for target in ast.expressions
        )
    ):
        # Named targets only: inheritance, CASCADE and identity-sequence effects need a catalogue.
        identities = tuple(
            identity
            for target in ast.expressions
            if (identity := _named(target, SqlObjectType.TABLE, "altered")) is not None
        )
        return StatementFacts("TRUNCATE", "DDL", identities)

    if dialect == "tsql" and isinstance(  # lint: allow-dialect-string: T-SQL single-table TRUNCATE
        ast, exp.TruncateTable
    ):
        targets = ast.expressions
        target = targets[0] if len(targets) == 1 else None
        if (
            isinstance(target, exp.Table)
            and isinstance(target.this, exp.Identifier)
            and all(not value for key, value in ast.args.items() if key != "expressions")
            and not any(
                value for key, value in target.args.items() if key not in {"this", "db", "catalog"}
            )
        ):
            identity = _named(target, SqlObjectType.TABLE, "altered")
            if identity is not None:
                return StatementFacts("TRUNCATE", "DDL", (identity,))
        return _head_facts(sql, "tsql TRUNCATE scope is opaque", dialect=dialect)

    if dialect in {
        "duckdb",
        "mysql",  # lint: allow-dialect-string: MySQL TRUNCATE takes exactly one table
    } and isinstance(ast, exp.TruncateTable):
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
        if dialect == "oracle":  # lint: allow-dialect-string: Oracle expression write targets
            subject = ast.this
            if isinstance(ast, exp.Insert) and isinstance(subject, exp.Schema):
                subject = subject.this
            if isinstance(ast, exp.Delete) and not subject:
                targets = ast.args.get("tables") or []
                subject = targets[0] if len(targets) == 1 else None
            alias = subject.args.get("alias") if isinstance(subject, exp.Table) else None
            # Older sqlglot reads partition restrictions as aliases (INSERT loses the arguments),
            # newer versions as a `partition` argument: prove the target by its shape instead.
            restricted_alias = alias is not None and (
                alias.args.get("columns")
                or (
                    alias.name.upper() in {"PARTITION", "SUBPARTITION"}
                    and not alias.this.args.get("quoted")
                )
            )
            plain_table = isinstance(subject, exp.Table) and not any(
                value
                for key, value in subject.args.items()
                if key not in {"this", "db", "catalog", "alias"}
            )
            # `DELETE t FROM u` names a target list apart from its source.
            split_delete = isinstance(ast, exp.Delete) and ast.this and ast.args.get("tables")
            if not (
                plain_table
                and isinstance(subject.this, exp.Identifier)
                and subject.name
                and not restricted_alias
                and not split_delete
            ):
                return StatementFacts(
                    operation,
                    "DML",
                    diagnostic="oracle mutation target is not a direct named table",
                )
        if (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL permits multi-target mutations
            and _mysql_unresolved_mutation_target(ast)
        ):
            return StatementFacts(
                operation, "DML", diagnostic="mysql mutation has multiple or unproven targets"
            )
        table = _dml_target_table(ast)
        if (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL modifier words are not tables
            and not isinstance(ast, exp.Delete)  # DELETE's table follows FROM
            and table is not None
            and isinstance(table.this, exp.Identifier)
            and not table.this.args.get("quoted")
            and not table.db
            and table.name.upper() in MYSQL_DML_MODIFIER_WORDS[operation].split("|")
        ):
            return StatementFacts(
                operation, "DML", diagnostic="mysql modifier word read where a table belongs"
            )
        identity = _named(table, SqlObjectType.TABLE, "altered") if table else None
        target = (
            ".".join(part for part in (table.catalog, table.db, table.name) if part)
            if table
            else None
        )
        where = ast.args.get("where")
        predicate_node = where.this if isinstance(where, exp.Where) else None
        if predicate_node is not None:
            if dialect == "oracle":  # lint: allow-dialect-string: Oracle spelling
                predicate_node = _oracle_as_written(predicate_node)
        predicate = predicate_node.sql(dialect=dialect) if predicate_node is not None else None
        events = _sqlglot_events(ast)
        columns = tuple(_sqlglot_updated_columns(ast))
        skipped_references: Tuple[exp.Expression, ...] = (table,) if table is not None else ()
        if dialect == "tsql":  # lint: allow-dialect-string: write aliases are not source tables
            if isinstance(ast, exp.Update) and isinstance(ast.this, exp.Table):
                skipped_references += (ast.this,)
            if isinstance(ast, exp.Delete):
                skipped_references += tuple(ast.args.get("tables") or [])
        if (
            dialect == "mysql"  # lint: allow-dialect-string: MySQL DELETE target lists are writes
            and isinstance(ast, exp.Delete)
        ):
            # DELETE's target list names write targets, not additional read sources.
            skipped_references += tuple(ast.args.get("tables") or [])
        references = (
            _merge_referenced(ast)
            if isinstance(ast, exp.Merge)
            else _referenced(ast, skipped_references)
        )
        target_table = table
        if (
            dialect
            in {
                "duckdb",
                "mysql",  # lint: allow-dialect-string: bare targets
                "postgres",  # lint: allow-dialect-string: bare targets
                "redshift",
                "tsql",
            }
            and table is not None
            and (table.args.get("alias") or table.args.get("joins") or table.args.get("only"))
        ):
            target_table = table.copy()
            target_table.set("alias", None)
            target_table.set("joins", None)
            target_table.set("only", None)
        if dialect == "oracle" and target_table is not None:  # lint: allow-dialect-string: spelling
            target_table = _oracle_as_written(target_table)
        return StatementFacts(
            operation,
            "DML",
            ((identity,) if identity else ()) + references,
            target,
            predicate,
            affected_columns=columns,
            events=frozenset(events) if events else None,
            target_sql=target_table.sql(dialect=dialect) if target_table is not None else None,
        )

    if isinstance(ast, exp.Query):
        if dialect in {
            "postgres",  # lint: allow-dialect-string: PostgreSQL SELECT INTO
            "tsql",  # lint: allow-dialect-string: T-SQL SELECT INTO
        }:
            into = _select_into_table(ast)
            if into is not None:
                created = _named(into, SqlObjectType.TABLE, "created")
                if created is not None:
                    sources = _referenced(ast, tuple(into.find_all(exp.Table)))
                    return StatementFacts("SELECT", "DML", (created,) + sources)
        return StatementFacts("SELECT", "QUERY", _referenced(ast))
    if (
        dialect == "postgres"  # lint: allow-dialect-string: PostgreSQL privileges are DDL
        and isinstance(ast, (exp.Grant, exp.Revoke))
    ):
        return StatementFacts(
            type(ast).__name__.upper(),
            "DDL",
            diagnostic=f"{dialect} {type(ast).__name__} privilege targets are not modelled",
        )
    return _head_facts(
        sql, f"{dialect} {type(ast).__name__} has no statement facts mapping", dialect=dialect
    )
