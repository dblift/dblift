"""Statement facts read from one sqlglot AST per lexical statement.

Kept apart from ``statement_facts`` so that importing the fact types never imports sqlglot.
"""

from __future__ import annotations

import re
from dataclasses import replace
from typing import Optional, Tuple

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
    properties = ast.args.get("properties")
    if properties and properties.find(exp.VirtualProperty):
        object_type = SqlObjectType.VIRTUAL_TABLE
    if (
        dialect == "postgres"  # lint: allow-dialect-string: PostgreSQL materialized views
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
        diagnostic="postgres CTE source scopes or effects are opaque to statement facts",
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
    object_type = SqlObjectType["_".join(match.group(2).upper().split())]
    name = strip_identifier_quotes(match.group(4) or match.group(3))
    schema = strip_identifier_quotes(match.group(3)) if match.group(4) else None
    role = {"CREATE": "created", "ALTER": "altered", "DROP": "dropped"}[operation]
    return NamedObject(name, object_type, role, schema)


def _head_facts(sql: str, diagnostic: str, *, dialect: str = "") -> StatementFacts:
    """Classify a statement from its leading words when sqlglot cannot represent the body."""
    head = _blanked(sql)
    first = _FIRST_WORD.match(head)
    if first and first.group(1).upper() == "WITH":
        head = _main_statement(head)
        first = _FIRST_WORD.match(head)
    operation = first.group(1).upper() if first else "UNKNOWN"
    kind = _KINDS.get(operation, "UNKNOWN")
    if (
        dialect == "mysql"  # lint: allow-dialect-string: unread MySQL mutations may be multi-target
        and operation in {"UPDATE", "DELETE"}
    ):
        return StatementFacts(operation, kind, diagnostic=diagnostic)
    if (
        dialect == "oracle"  # lint: allow-dialect-string: unread Oracle targets may be expressions
        and operation in {"INSERT", "UPDATE", "DELETE"}
    ):
        return StatementFacts(operation, kind, diagnostic=diagnostic)
    if dialect == "duckdb":  # lint: allow-dialect-string: preserve DuckDB opaque metadata kinds
        kind = {"COMMENT": "DDL", "SHOW": "QUERY", "EXECUTE": "DML"}.get(operation, kind)
    objects: Tuple[NamedObject, ...] = ()
    match = _HEAD.match(head)
    if match is None and first is None:
        # Stray characters (a NUL, a lone ``/``) ahead of the statement; the engine reads past them.
        match = _HEAD_SCAN.search(head.replace("\x00", " "))
        if match:
            operation = match.group(1).upper()
            kind = _KINDS[operation]
    dml = _DML_HEAD.match(head)
    if match and not _head_name_is_bounded(head, match, (3, 4)):
        match = None
    if dml and not _head_name_is_bounded(head, dml, (2, 3)):
        dml = None
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
    try:
        ast = parse_one(_UPDATE_OR.sub(r"\1", sql), read=dialect)
    except (ParseError, TokenError) as exc:
        if not _blanked(sql).strip():
            return StatementFacts("UNKNOWN", "UNKNOWN")
        if isinstance(exc, TokenError):
            facts = _head_facts(sql, "", dialect=dialect)
            return replace(
                facts,
                diagnostic=None,
                error=f"{dialect} statement could not be tokenized (unterminated quote or comment)",
            )
        return _head_facts(
            sql, f"{dialect} grammar is not modelled for this statement", dialect=dialect
        )
    if ast is None or isinstance(ast, (exp.Command, exp.Block)):
        construct = type(ast).__name__ if ast is not None else "empty statement"
        return _head_facts(
            sql, f"{dialect} {construct} is opaque to statement facts", dialect=dialect
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

    if dialect == "duckdb":  # lint: allow-dialect-string: DuckDB metadata statement mappings
        if isinstance(ast, exp.Comment) and ast.args.get("kind") == "TABLE":
            identity = _named(ast.this, SqlObjectType.TABLE, "altered")
            return StatementFacts("COMMENT", "DDL", (identity,) if identity else ())
        if isinstance(ast, (exp.Show, exp.Describe)):
            operation = "SHOW" if isinstance(ast, exp.Show) else "DESCRIBE"
            return StatementFacts(operation, "QUERY", _referenced(ast))

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
        objects: Tuple[NamedObject, ...] = (identity,) if identity else ()
        indexed_table = None
        indexed_columns = None
        index_items: Optional[list[exp.Expression]] = []
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
            dialect == "postgres"  # lint: allow-dialect-string: PostgreSQL materialized views
            and kind == "VIEW"
            and ast.args.get("materialized")
        ):
            object_type = SqlObjectType.MATERIALIZED_VIEW
        targets = ast.args.get("tables") or ast.args.get("expressions") or [ast.this]
        if (
            dialect == "duckdb"  # lint: allow-dialect-string: DuckDB schema identity projection
            and object_type == SqlObjectType.SCHEMA
        ):
            dropped_objects = tuple(
                NamedObject(node.db, object_type, "dropped", node.catalog or None)
                for node in targets
                if isinstance(node, exp.Table) and node.db
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
        identity = _named(table, SqlObjectType.TABLE, "altered") if table else None
        target = (
            ".".join(part for part in (table.catalog, table.db, table.name) if part)
            if table
            else None
        )
        where = ast.args.get("where")
        predicate = (
            where.this.sql(dialect=dialect)
            if isinstance(where, exp.Where) and where.this is not None
            else None
        )
        events = _sqlglot_events(ast)
        columns = tuple(_sqlglot_updated_columns(ast))
        skipped_references: Tuple[exp.Expression, ...] = (table,) if table is not None else ()
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
            dialect in {"duckdb", "mysql"}  # lint: allow-dialect-string: bare mutation targets
            and table is not None
            and (table.args.get("alias") or table.args.get("joins") or table.args.get("only"))
        ):
            target_table = table.copy()
            target_table.set("alias", None)
            target_table.set("joins", None)
            target_table.set("only", None)
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
        return StatementFacts("SELECT", "QUERY", _referenced(ast))
    return _head_facts(
        sql, f"{dialect} {type(ast).__name__} has no statement facts mapping", dialect=dialect
    )
