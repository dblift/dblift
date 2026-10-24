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
    DmlEffect,
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
# MySQL and MariaDB add two kinds sqlglot reads as an opaque command: a tablespace (MySQL) and a
# sequence (MariaDB). A tablespace has no schema part, see ``_head_facts``.
_MYSQL_HEAD = re.compile(
    _HEAD.pattern.replace("|TRIGGER)", "|TRIGGER|TABLESPACE|SEQUENCE)", 1), re.IGNORECASE
)
# PostgreSQL names more kinds than the generic head and skips its creation modifiers;
# CONCURRENTLY is a modifier after INDEX only, elsewhere an ordinary name.
_POSTGRES_HEAD = re.compile(
    rf"^\s*(CREATE|ALTER|DROP)\s+"
    rf"(?:(?:OR\s+REPLACE|UNLOGGED|TEMP|TEMPORARY|UNIQUE|CONSTRAINT|IF|NOT|EXISTS)\s+)*"
    rf"(VIRTUAL\s+TABLE|MATERIALIZED\s+VIEW|TABLE|VIEW|INDEX|TRIGGER|FUNCTION|PROCEDURE"
    rf"|SEQUENCE|TYPE|SCHEMA|EXTENSION|EVENT\s+TRIGGER|FOREIGN\s+DATA\s+WRAPPER|SERVER|PUBLICATION"
    rf"|OPERATOR\s+CLASS|TEXT\s+SEARCH\s+(?:DICTIONARY|CONFIGURATION|PARSER|TEMPLATE)|TABLESPACE)"
    rf"(?:(?<=INDEX)\s+CONCURRENTLY\b)?\s+"
    rf"(?:(?:IF|NOT|EXISTS)\s+)*"
    rf"(?!(?:IF|NOT|EXISTS|AUTHORIZATION|OR|REPLACE)\b)"
    rf"({_NAME})(?:\s*\.\s*({_NAME}))?",
    re.IGNORECASE,
)
_POSTGRES_HEAD_SCAN = re.compile(
    _POSTGRES_HEAD.pattern.replace(r"^\s*", r"(?:^|;)\s*", 1), re.IGNORECASE | re.MULTILINE
)
# The kinds PostgreSQL does not put in a schema: a dotted name is a syntax error (42601).
_POSTGRES_UNQUALIFIED = frozenset(
    {
        SqlObjectType.EVENT_TRIGGER,
        SqlObjectType.FOREIGN_DATA_WRAPPER,
        SqlObjectType.FOREIGN_SERVER,
        SqlObjectType.PUBLICATION,
        SqlObjectType.TABLESPACE,
    }
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
# `/*!NNNNN … */` runs where NNNNN is not above the server's own version. MariaDB 11 runs up to
# 50699, MySQL 8.0 and 8.4 more: below this floor the text runs on every supported server
# (measured 2026-10-24, docs/sql-parsing/mariadb.md).
_EXECUTABLE_COMMENT_FLOOR = 50700
_EXECUTABLE_COMMENT_OPENER = re.compile(r"/\*!(\d*)")
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


def _mysql_server_view(sql: str) -> Optional[str]:
    """The text a MySQL-family server runs: each executable comment's markers blanked, its content
    kept, so offsets do not move. ``None`` when an executable comment may not run on every
    supported server or cannot be scanned to a single reading: a ``/*M!`` comment, a version
    that is not five digits or is not below the floor, a comment opened inside it, or no ``*/``.
    """
    pieces = []
    at = 0
    for span in _MYSQL_QUOTES_AND_COMMENTS.finditer(sql):
        text = span.group()
        if not text.startswith(("/*!", "/*M!")):
            continue
        opener = _EXECUTABLE_COMMENT_OPENER.match(text)
        if opener is None or not text.endswith("*/") or "/*" in text[opener.end() : -2]:
            return None
        version = opener.group(1)
        if version and (len(version) != 5 or int(version) >= _EXECUTABLE_COMMENT_FLOOR):
            return None
        pieces.append(sql[at : span.start()] + " " * opener.end() + text[opener.end() : -2] + "  ")
        at = span.end()
    return "".join(pieces) + sql[at:]


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


_HEAD_CLAUSE_WORDS = frozenset(
    {"IF", "NOT", "EXISTS", "ONLY", "ADD", "CLONE", "CASCADE", "RESTRICT"}
)
_SNOWFLAKE_CLAUSE_WORDS = _HEAD_CLAUSE_WORDS | {"IDENTIFIER"}


_ROUTINE_CLAUSE_WORDS = frozenset({"IF", "NOT", "EXISTS"})
_PROGRAM_KINDS = frozenset({"FUNCTION", "PROCEDURE", "TRIGGER"})
# The clause words each engine reserves (tests/support/facts_corpus/reserved, from the vendor's
# list); a dialect missing here is not known to allow any of them as a program name.
_RESERVED_ADD_CASCADE = frozenset({"ADD", "CASCADE", "IF", "RESTRICT"})
_RESERVED_CLAUSE_WORDS = {
    "mysql": _RESERVED_ADD_CASCADE,  # lint: allow-dialect-string: reserved words
    "tsql": _RESERVED_ADD_CASCADE,  # lint: allow-dialect-string: reserved words
    "oracle": frozenset({"ADD"}),  # lint: allow-dialect-string: reserved words
    "postgres": frozenset({"ONLY"}),  # lint: allow-dialect-string: reserved words
    "redshift": frozenset({"ONLY"}),  # lint: allow-dialect-string: reserved words
    "duckdb": frozenset({"ONLY"}),  # lint: allow-dialect-string: reserved words
}
_PROGRAM_FOLLOWERS = frozenset({"BEFORE", "AFTER", "INSTEAD", "FOR"})


def _clause_words(dialect: str, routine: bool = False) -> frozenset:
    """Words that are clause keywords, not names, where a truncated statement ends early. A
    program name keeps the words its engine does not reserve, but only before ``(`` or a trigger
    timing word: ``CREATE PROCEDURE cascade`` alone is a truncated statement."""
    if dialect == "snowflake":  # lint: allow-dialect-string: IDENTIFIER() names
        return _SNOWFLAKE_CLAUSE_WORDS
    if routine and dialect in _RESERVED_CLAUSE_WORDS:
        return _ROUTINE_CLAUSE_WORDS | (_HEAD_CLAUSE_WORDS & _RESERVED_CLAUSE_WORDS[dialect])
    return _HEAD_CLAUSE_WORDS


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


def _head_tokens_prove_name(
    sql: str, dialect: str, prefix: str, names: Tuple[str, ...], routine: bool = False
) -> bool:
    """Check that a stripped head names the same source tokens, in the same order."""
    words = _clause_words(dialect, routine)
    if not dialect or any(
        name[0] not in {'"', "`", "["} and name.upper() in words for name in names
    ):
        return False
    follower_needed = routine and any(
        name[0] not in {'"', "`", "["} and name.upper() in _HEAD_CLAUSE_WORDS for name in names
    )
    original_sql, original_prefix = sql, prefix
    tokenizer = Dialect.get_or_raise(dialect)
    try:
        source = tokenizer.tokenize(sql)
    except TokenError:
        leading = original_sql.lstrip(_ASCII_BLANKS)
        if not leading.startswith(original_prefix):
            return False
        rest = _blanked(leading[len(original_prefix) :], dialect).lstrip(_ASCII_BLANKS)
        if rest.startswith((".", "#", "//")):
            return False  # a further name part, or an unhandled line comment, is not bounded
        # A broken tail cannot disprove a name already bounded by the raw source head.
        try:
            source = tokenizer.tokenize(sql[: len(sql) - len(leading) + len(prefix)])
        except TokenError:
            return False
    try:
        proposed = tokenizer.tokenize(prefix)
    except TokenError:
        return False
    if not proposed or (
        proposed[0].token_type.name not in _KINDS and proposed[0].token_type != TokenType.RENAME
    ):
        return False  # a source fragment such as NUL+CREATE is not a proven statement verb
    if any(
        first.token_type == TokenType.STAR
        and second.token_type == TokenType.SLASH
        and first.end + 1 == second.start
        for first, second in zip(source, source[1:])
    ):
        return False  # an unmatched block-comment closer makes the head unreliable
    if source and proposed and source[0].token_type == TokenType.WITH:
        at = 1
        if at < len(source) and source[at].text.upper() == "RECURSIVE":
            at += 1
        while at < len(source):
            if source[at].token_type not in (TokenType.VAR, TokenType.IDENTIFIER):
                return False
            at += 1
            if at < len(source) and source[at].token_type == TokenType.L_PAREN:
                at += 1
                if at >= len(source) or source[at].token_type not in (
                    TokenType.VAR,
                    TokenType.IDENTIFIER,
                ):
                    return False
                at += 1
                while at < len(source) and source[at].token_type == TokenType.COMMA:
                    at += 1
                    if at >= len(source) or source[at].token_type not in (
                        TokenType.VAR,
                        TokenType.IDENTIFIER,
                    ):
                        return False
                    at += 1
                if at >= len(source) or source[at].token_type != TokenType.R_PAREN:
                    return False
                at += 1
            if at >= len(source) or source[at].token_type != TokenType.ALIAS:
                return False
            at += 1
            if at < len(source) and source[at].text.upper() == "NOT":
                at += 1
                if at >= len(source) or source[at].text.upper() != "MATERIALIZED":
                    return False
                at += 1
            elif at < len(source) and source[at].text.upper() == "MATERIALIZED":
                at += 1
            if at >= len(source) or source[at].token_type != TokenType.L_PAREN:
                return False
            depth = 1
            at += 1
            while at < len(source) and depth:
                if source[at].token_type == TokenType.L_PAREN:
                    depth += 1
                elif source[at].token_type == TokenType.R_PAREN:
                    depth -= 1
                at += 1
            if depth or at >= len(source):
                return False
            if source[at].token_type != TokenType.COMMA:
                break
            at += 1
        if at >= len(source) or source[at].token_type.name not in _MAIN_KEYWORDS:
            return False
        token = source[at]
        if token.token_type != proposed[0].token_type:
            return False
        sql = sql[token.start :]
        try:
            source = tokenizer.tokenize(sql)
        except TokenError:
            return False
    if (
        source
        and proposed
        and source[0].token_type == proposed[0].token_type
        and source[0].token_type in (TokenType.REPLACE, TokenType.RENAME)
    ):
        # The MySQL lexer treats these command tails as one token. Re-tokenize the
        # same source bytes under a same-width verb to compare the actual names.
        first_source, first_proposed = source[0], proposed[0]
        replacement = "UPDATE " if first_source.token_type == TokenType.REPLACE else "UPDATE"
        if first_source.end - first_source.start + 1 != len(
            replacement
        ) or first_proposed.end - first_proposed.start + 1 != len(replacement):
            return False
        sql = f"{sql[:first_source.start]}{replacement}{sql[first_source.end + 1:]}"
        prefix = f"{prefix[:first_proposed.start]}{replacement}{prefix[first_proposed.end + 1:]}"
        try:
            source = tokenizer.tokenize(sql)
            proposed = tokenizer.tokenize(prefix)
        except TokenError:
            return False
    if (
        not proposed
        or len(source) < len(proposed)
        or any(
            (actual.token_type, actual.text) != (expected.token_type, expected.text)
            for actual, expected in zip(source, proposed)
        )
    ):
        return False
    if len(source) > len(proposed) and source[len(proposed)].token_type == TokenType.DOT:
        return False  # a further name part means the proposed identity is incomplete
    if len(source) > len(proposed) and source[len(proposed)].token_type in {
        TokenType.L_BRACE,
        TokenType.R_BRACE,
    }:
        return False  # a template brace continues the name
    if follower_needed and not (
        len(source) > len(proposed)
        and (
            source[len(proposed)].token_type == TokenType.L_PAREN
            or source[len(proposed)].text.upper() in _PROGRAM_FOLLOWERS
        )
    ):
        return False
    parts = proposed[-(2 * len(names) - 1) :]
    if len(parts) != 2 * len(names) - 1:
        return False
    for index, name in enumerate(names):
        token = parts[2 * index]
        if token.text != strip_identifier_quotes(name):
            return False
        if name[0] in {'"', "`", "["}:
            if token.token_type != TokenType.IDENTIFIER:
                return False
        elif token.token_type != TokenType.VAR and not (
            dialect == "mysql"  # lint: allow-dialect-string: qualified MySQL IGNORE schema
            and len(names) == 2
            and index == 0
            and token.token_type == TokenType.IGNORE
        ):
            return False
    return all(token.token_type == TokenType.DOT for token in parts[1::2])


def _named(node: exp.Expression, kind: SqlObjectType, role: str) -> Optional[NamedObject]:
    table = node if isinstance(node, exp.Table) else node.find(exp.Table)
    if isinstance(node, exp.Index):
        name = node.this.name if isinstance(node.this, exp.Identifier) else ""
        return NamedObject(name, kind, role) if name else None
    if not isinstance(table, exp.Table) or not table.name:
        return None
    schema = ".".join(part for part in (table.catalog, table.db) if part) or None
    return NamedObject(table.name, kind, role, schema)


def _snowflake_schema_has_discarded_prefix(sql: str, table: exp.Table) -> bool:
    """Catch a source qualifier that sqlglot dropped before its first retained name part."""
    first = table.args.get("catalog") or table.args.get("db")
    if not isinstance(first, exp.Identifier):
        return False
    start = first.meta.get("start")
    if not isinstance(start, int):
        return True
    snowflake = Dialect.get_or_raise("snowflake")  # lint: allow-dialect-string: schema proof
    tokens = snowflake.tokenize(sql)
    index = next((i for i, token in enumerate(tokens) if token.start == start), None)
    return index is None or (index > 0 and tokens[index - 1].token_type == TokenType.DOT)


def _snowflake_materialized_view_log_on(sql: str, ast: exp.Expr) -> bool:
    """Recognize LOG ON at the materialized-view target, not in its query body."""
    if not isinstance(ast, (exp.Create, exp.Drop)) or ast.args.get("kind") != "VIEW":
        return False
    if isinstance(ast, exp.Create):
        properties = ast.args.get("properties")
        if not properties or not properties.find(exp.MaterializedProperty):
            return False
        targets = (ast.this,)
    else:
        if not ast.args.get("materialized"):
            return False
        targets = ast.args.get("tables") or (ast.this,)
    snowflake = Dialect.get_or_raise("snowflake")  # lint: allow-dialect-string: target proof
    tokens = snowflake.tokenize(sql)
    for target in targets:
        if not isinstance(target, exp.Table) or not isinstance(target.this, exp.Identifier):
            continue
        identifier = target.this
        start = identifier.meta.get("start")
        if identifier.name.upper() != "LOG" or not isinstance(start, int):
            continue
        if any(
            token.start == start
            and token.text.upper() == "LOG"
            and tokens[index + 1].token_type == TokenType.ON
            for index, token in enumerate(tokens[:-1])
        ):
            return True
    return False


_SNOWFLAKE_DYNAMIC_NAMES = "snowflake IDENTIFIER() names are not read"


def _unread_names(ast: exp.Expr, dialect: str) -> Optional[str]:
    """Name why a relation is not an identifier written in the statement."""
    if isinstance(ast, exp.Copy):
        return None  # a COPY file path is a string, and the statement is opaque already
    snowflake = dialect == "snowflake"  # lint: allow-dialect-string: IDENTIFIER() and $variables
    if snowflake and any(ast.find_all(exp.DynamicIdentifier)):
        return _SNOWFLAKE_DYNAMIC_NAMES
    routine = (
        isinstance(ast, (exp.Create, exp.Drop))
        and str(ast.args.get("kind") or "").upper() in _PROGRAM_KINDS
    )
    words = _clause_words(dialect, routine)
    for table in ast.find_all(exp.Table):
        parts = [table.args.get(key) for key in ("this", "db", "catalog")]
        if snowflake and any(isinstance(part, (exp.Parameter, exp.Literal)) for part in parts):
            return _SNOWFLAKE_DYNAMIC_NAMES
        if any(
            isinstance(part, exp.Identifier)
            and not part.args.get("quoted")
            and part.name.upper() in words
            for part in parts
        ):
            return f"{dialect} keyword read where an object name belongs"
    return None


def _snowflake_tokens_hold_dynamic_name(sql: str) -> bool:
    """A ``$variable`` or ``IDENTIFIER(`` in a DDL or DML statement the grammar did not model."""
    if _head_facts(sql, "", dialect="snowflake").kind not in {  # lint: allow-dialect-string: head
        "DDL",
        "DML",
    }:
        return False
    try:
        snowflake = Dialect.get_or_raise("snowflake")  # lint: allow-dialect-string: tokens
        tokens = snowflake.tokenize(sql)
    except TokenError:
        return False
    return any(
        (token.token_type == TokenType.PARAMETER and token.text == "$")
        or (
            token.text.upper() == "IDENTIFIER"
            and index + 1 < len(tokens)
            and tokens[index + 1].token_type == TokenType.L_PAREN
        )
        for index, token in enumerate(tokens)
    )


def _snowflake_unread_effect(ast: exp.Expr) -> Optional[str]:
    """Name why a Snowflake statement writes or names an object the shared mappings drop."""
    if any(not isinstance(cte.this, exp.Query) for cte in ast.find_all(exp.CTE)):
        return "snowflake CTE body effects are opaque to statement facts"
    if any(
        isinstance(table.this, exp.Var) and table.name.startswith("@")
        for table in ast.find_all(exp.Table)
    ):
        return "snowflake stage references are not modelled"
    if isinstance(ast, exp.Alter) and any(
        isinstance(action, (exp.AlterRename, exp.SwapTable))
        for action in ast.args.get("actions") or ()
    ):
        return "snowflake ALTER names a second object that is not read"
    return None


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


def _mysql_names_are_proven(table: exp.Table, sql: str) -> bool:
    """Whether the table name, and its schema if written, are identifiers in any SQL mode."""
    return all(
        _mysql_identifier_is_proven(part, sql)
        for part in (table.this, table.args.get("db"))
        if part is not None
    )


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
        in {
            "postgres",  # lint: allow-dialect-string: materialized views
            "oracle",  # lint: allow-dialect-string: materialized views
            "redshift",
            "snowflake",  # lint: allow-dialect-string: materialized views
        }
        and kind == "VIEW"
        and properties
        and properties.find(exp.MaterializedProperty)
    ):
        object_type = SqlObjectType.MATERIALIZED_VIEW
    return object_type


_CTE_WRITES = (exp.Insert, exp.Update, exp.Delete)


def _cte_name(identifier: exp.Expr, upper: bool = False) -> str:
    """The name an unquoted identifier folds to (lower case, upper for Snowflake); a quoted one
    is exact."""
    if identifier.args.get("quoted"):
        return identifier.name
    return identifier.name.upper() if upper else identifier.name.lower()


def _names_a_visible_cte(table: exp.Table, upper: bool = False) -> bool:
    """Whether an unqualified table name resolves to a CTE at its place in the text.

    A body sees the CTEs before it (all of them under ``RECURSIVE``), the rest of the statement
    sees every CTE of the nearest ``WITH`` that encloses it, and the innermost match wins.
    """
    if table.db or table.catalog or not isinstance(table.this, exp.Identifier):
        return False
    wanted = _cte_name(table.this, upper)
    child: exp.Expr = table
    parent = table.parent
    while parent is not None:
        if isinstance(parent, exp.CTE) and isinstance(parent.parent, exp.With):
            siblings = parent.parent.expressions
            visible = (
                siblings
                if parent.parent.args.get("recursive")
                else siblings[: next(i for i, c in enumerate(siblings) if c is parent)]
            )
            if any(_cte_name(cte.args["alias"].this, upper) == wanted for cte in visible):
                return True
        else:
            clause = parent.args.get("with_")
            if clause is not None and child is not clause:
                if any(
                    _cte_name(cte.args["alias"].this, upper) == wanted for cte in clause.expressions
                ):
                    return True
        child, parent = parent, parent.parent
    return False


def _write_effect(node: exp.Expression, dialect: str) -> Optional[DmlEffect]:
    """The table, predicate, events and assigned columns of an INSERT, UPDATE or DELETE."""
    table = _dml_target_table(node)
    if not isinstance(table, exp.Table) or _named(table, SqlObjectType.TABLE, "altered") is None:
        return None
    bare = table.copy()
    for key in ("alias", "joins", "only"):
        bare.set(key, None)
    where = node.args.get("where")
    return DmlEffect(
        type(node).__name__.upper(),
        ".".join(part for part in (table.catalog, table.db, table.name) if part),
        bare.sql(dialect=dialect),
        where.this.sql(dialect=dialect) if isinstance(where, exp.Where) else None,
        frozenset(_sqlglot_events(node) or ()),
        tuple(_sqlglot_updated_columns(node)),
    )


def _unread_cte_reason(ast: exp.Expr, dialect: str) -> Optional[str]:
    """Why the CTEs of a statement cannot be read, or ``None`` when they can."""
    ctes = list(ast.find_all(exp.CTE))
    for cte in ctes:
        body = cte.this
        if isinstance(body, exp.Merge):
            return f"{dialect} CTE body is a MERGE, which is not read"
        if not isinstance(body, (exp.Query, exp.Values) + _CTE_WRITES):
            return f"{dialect} CTE body effects are not read"
        if not isinstance(body, _CTE_WRITES):
            continue
        if dialect == "redshift":  # lint: allow-dialect-string: Redshift has no writing CTE
            return "redshift rejects a data-modifying CTE"
        if cte.parent is not ast.args.get("with_"):
            return f"{dialect} reads a data-modifying WITH only at the top level of a statement"
        if _write_effect(body, dialect) is None:
            return f"{dialect} CTE write target is not a plain table"
    if dialect == "redshift":  # lint: allow-dialect-string: Redshift scoping was not measured
        # Only a scope that needs no rule of the engine is read: one flat, non-recursive WITH
        # whose bodies name no CTE of their own position or after it.
        clauses = list(ast.find_all(exp.With))
        aliases = [cte.args["alias"].this for cte in ctes]
        if (
            len(clauses) != 1
            or clauses[0].args.get("recursive")
            or any(alias.args.get("quoted") for alias in aliases)
            or any(
                not table.db
                and any(
                    table.name.lower() == aliases[j].name.lower() for j in range(i, len(aliases))
                )
                for i, cte in enumerate(ctes)
                for table in cte.this.find_all(exp.Table)
            )
        ):
            return f"{dialect} CTE source scopes are opaque to statement facts"
    return None


def _cte_statement_facts(ast: exp.Expr, dialect: str) -> Optional[StatementFacts]:
    """Read INSERT, UPDATE, DELETE or SELECT whose WITH names writing or shadowing CTEs.

    The outer statement keeps its target, predicate and events; every writing CTE adds the table
    it changes and its own events; a name inside a body is a CTE only where the scope says so.
    """
    top = ast.args.get("with_")
    nodes = (
        [cte.this for cte in top.expressions if isinstance(cte.this, _CTE_WRITES)] if top else []
    )
    if isinstance(ast, _CTE_WRITES):
        nodes.insert(0, ast)
    elif not isinstance(ast, exp.Query) or _select_into_table(ast) is not None:
        return None
    effects: list[DmlEffect] = []
    targets: list[exp.Expr] = []
    objects: list[NamedObject] = []
    for node in nodes:
        effect = _write_effect(node, dialect)
        table = _dml_target_table(node)
        altered = _named(table, SqlObjectType.TABLE, "altered") if table is not None else None
        if effect is None or table is None or altered is None:
            return None
        effects.append(effect)
        targets.append(table)
        if altered not in objects:
            objects.append(altered)
    for table in ast.find_all(exp.Table):
        if any(table is target for target in targets) or not table.name:
            continue
        reference = _named(table, SqlObjectType.TABLE, "referenced")
        if reference is not None and reference not in objects and not _names_a_visible_cte(table):
            objects.append(reference)
    if not isinstance(ast, _CTE_WRITES):
        return StatementFacts(
            "SELECT", "DML" if effects else "QUERY", tuple(objects), cte_writes=tuple(effects)
        )
    outer = effects[0]
    return StatementFacts(
        outer.operation,
        "DML",
        tuple(objects),
        outer.target,
        outer.predicate,
        affected_columns=outer.affected_columns,
        events=outer.events or None,
        target_sql=outer.target_sql,
        cte_writes=tuple(effects[1:]),
    )


def _postgresql_opaque_cte(ast: exp.Expr, dialect: str) -> Optional[StatementFacts]:
    """Read a WITH the flat reference filter cannot prove, or retain the outer identity."""
    clauses = list(ast.find_all(exp.With))
    if not clauses:
        return None
    ctes = list(ast.find_all(exp.CTE))
    aliases = {cte.alias.lower() for cte in ctes}
    writes = any(isinstance(cte.this, _CTE_WRITES) for cte in ctes)
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

    reason = _unread_cte_reason(ast, dialect)
    if reason is None and not isinstance(ast, exp.Create):
        facts = _cte_statement_facts(ast, dialect)
        if facts is not None:
            return facts
        reason = (
            f"{dialect} SELECT INTO behind a data-modifying CTE is not read"
            if writes
            else f"{dialect} CTE source scopes or effects are opaque to statement facts"
        )
    elif reason is None:
        reason = (
            f"{dialect} CREATE with a data-modifying CTE is not read"
            if writes
            else f"{dialect} CTE source scopes or effects are opaque to statement facts"
        )

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
        diagnostic=reason,
    )


def _merge_referenced(node: exp.Merge, upper: bool = False) -> Tuple[NamedObject, ...]:
    """Resolve MERGE sources in their own scopes, excluding CTE aliases."""
    from sqlglot.optimizer.scope import traverse_scope

    found: list[NamedObject] = []
    for scope in traverse_scope(node):
        for source in scope.sources.values():
            if isinstance(source, exp.Table) and not _names_a_visible_cte(source, upper):
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
    """Read literal-file COPY (DuckDB, Redshift)."""
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


# ``'x'``, ``$$x$$``, ``E'x'`` and ``U&'x'`` all name a file in PostgreSQL 16.14.
_STRING_LITERALS = frozenset(
    {
        TokenType.STRING,
        TokenType.HEREDOC_STRING,
        TokenType.BYTE_STRING,
        TokenType.UNICODE_STRING,
    }
)


def _postgres_copy_facts(node: exp.Copy, sql: str) -> StatementFacts:
    """Read ``COPY t [(cols)] FROM|TO source [options]``: the options cannot change the table.

    The source is a literal file, ``STDIN``/``STDOUT`` (either word, in either direction: both are
    the client stream) or ``PROGRAM '...'``; the head is checked
    against the tokens because the grammar reads the old ``COPY BINARY t`` as a table BINARY.
    """
    schema = node.this if isinstance(node.this, exp.Schema) else None
    table = schema.this if schema is not None else node.this
    columns = schema.expressions if schema is not None else []
    opaque = StatementFacts(
        "COPY", "UNKNOWN", diagnostic="postgres COPY source or destination is opaque"
    )
    if not (
        isinstance(table, exp.Table)
        and isinstance(table.this, exp.Identifier)
        and table.name
        and table.args.get("catalog") is None
        and (table.args.get("db") is None or table.db)
        and not any(value for key, value in table.args.items() if key not in {"this", "db"})
        and (schema is None or columns)
        and all(isinstance(column, exp.Identifier) and column.name for column in columns)
        and len(node.args.get("files") or []) == 1
        and not any(
            value
            for key, value in node.args.items()
            if key not in {"this", "kind", "files", "params", "credentials"}
        )
        and not any((node.args.get("credentials") or exp.Credentials()).args.values())
    ):
        return opaque
    grammar = "postgres"  # lint: allow-dialect-string: this reader is PostgreSQL's
    tokens = Dialect.get_or_raise(grammar).tokenize(sql)
    if tokens[0].token_type != TokenType.COPY:
        return opaque
    at = 1
    names = 2 if table.db else 1
    for position in range(names):
        if at >= len(tokens) or tokens[at].token_type in {
            TokenType.L_PAREN,
            TokenType.DOT,
            TokenType.FROM,
            TokenType.SEMICOLON,
        }:
            return opaque
        at += 1
        if position + 1 < names:
            if at >= len(tokens) or tokens[at].token_type != TokenType.DOT:
                return opaque
            at += 1
    if schema is not None:
        close = next(
            (i for i in range(at, len(tokens)) if tokens[i].token_type == TokenType.R_PAREN), None
        )
        if at >= len(tokens) or tokens[at].token_type != TokenType.L_PAREN or close is None:
            return opaque
        at = close + 1
    if at >= len(tokens):
        return opaque
    word = tokens[at].text.upper()
    importing = tokens[at].token_type == TokenType.FROM
    if not (importing or (tokens[at].token_type == TokenType.VAR and word == "TO")):
        return opaque
    if importing != (node.args.get("kind") is True):
        return opaque
    source = tokens[at + 1 :]
    # The grammar reads STDIN and STDOUT as the same client stream in either direction.
    program = False
    if (
        source
        and source[0].token_type == TokenType.VAR
        and source[0].text.upper() in {"STDIN", "STDOUT"}
    ):
        rest, stream = source[1:], True
    elif source and source[0].token_type in _STRING_LITERALS:
        rest, stream = source[1:], False
    elif (
        len(source) > 1
        and source[0].token_type == TokenType.VAR
        and source[0].text.upper() == "PROGRAM"
        and source[1].token_type in _STRING_LITERALS
    ):
        rest, stream, program = source[2:], False, True
    else:
        return opaque
    # The tail is not parsed, but what PostgreSQL 16.14 rejects outright is not read as a load:
    # an empty list, a second direction, the removed OIDS.
    for position, token in enumerate(rest):
        following = rest[position + 1 : position + 2]
        if (
            token.token_type == TokenType.FROM
            or (token.token_type == TokenType.VAR and token.text.upper() in {"TO", "OIDS"})
            or (
                token.token_type == TokenType.L_PAREN
                and following
                and following[0].token_type == TokenType.R_PAREN
            )
        ):
            return opaque
    # Options follow the source as words or a parenthesised list; an operator or a comma does not.
    if rest and not (
        rest[0].token_type in {TokenType.L_PAREN, TokenType.SEMICOLON}
        or rest[0].text.replace("_", "").isalpha()
    ):
        return opaque
    if any(token.token_type == TokenType.SEMICOLON for token in rest[:-1]):
        return opaque
    identity = _named(table, SqlObjectType.TABLE, "altered" if importing else "referenced")
    target = ".".join(part for part in (table.catalog, table.db, table.name) if part)
    return StatementFacts(
        "COPY",
        "DML" if importing else "QUERY",
        (identity,) if identity else (),
        target if importing else None,
        affected_columns=tuple(column.name for column in columns) if importing else (),
        events=frozenset({"INSERT"}) if importing else None,
        target_sql=table.sql(dialect=grammar) if importing else None,
        # The server runs the command or writes the file, whichever the table's direction.
        action=(
            f"copy-{'from' if importing else 'to'}-program"
            if program
            else None if stream or importing else "copy-to-file"
        ),
    )


def _nests_block_comments(dialect: str) -> bool:
    """Whether the engine nests ``/* /* */ */``: its lexical spec says so, or sqlglot's does."""
    # SQL Server nests on the server (docs/sql-parsing/sqlserver.md) while its lexical spec is flat,
    # because the spec describes the sqlcmd client; the OR takes the server's reading.
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


def _upper_case_name(name: str, *, ascii_only: bool = False) -> Optional[str]:
    """The name Oracle and Snowflake store for an unquoted one: each letter in its one-character
    upper-case form (Oracle 23.26.3: ``ı`` is ``I``, ``µ`` is the Greek capital MU; ``ß``, ``ﬁ``
    and ``ŉ`` stay; not measured on Snowflake). ``None`` when a letter's upper-case form is not
    one character: the probes covered only those three, so the name is not guessed. With
    ``ascii_only`` (Snowflake rejects an unquoted non-ASCII name) any other name is unread."""
    if name.isascii():
        return name.upper()
    if ascii_only:
        return None
    folded = [letter.upper() for letter in name]
    return "".join(folded) if all(len(letter) == 1 for letter in folded) else None


def _head_object_type(match: "re.Match[str]") -> SqlObjectType:
    """The object type a head's kind words name: the words joined by ``_``, except that the
    PostgreSQL ``SERVER`` is the ``FOREIGN_SERVER`` member."""
    words = "_".join(match.group(2).upper().split())
    return SqlObjectType["FOREIGN_SERVER" if words == "SERVER" else words]


def _head_object(
    match: "re.Match[str]", *, fold: bool = False, ascii_only: bool = False
) -> Optional[NamedObject]:
    operation = match.group(1).upper()
    object_type = _head_object_type(match)
    name = strip_identifier_quotes(match.group(4) or match.group(3))
    schema = strip_identifier_quotes(match.group(3)) if match.group(4) else None
    if fold:  # an unquoted name is stored upper-cased, a quoted one as written
        folded_name: Optional[str] = name
        folded_schema = schema
        if not (match.group(4) or match.group(3)).startswith('"'):
            folded_name = _upper_case_name(name, ascii_only=ascii_only)
        if schema is not None and not match.group(3).startswith('"'):
            folded_schema = _upper_case_name(schema, ascii_only=ascii_only)
        if folded_name is None or (schema is not None and folded_schema is None):
            return None
        name, schema = folded_name, folded_schema
    role = {"CREATE": "created", "ALTER": "altered", "DROP": "dropped"}[operation]
    return NamedObject(name, object_type, role, schema)


_ORACLE_INDEX_ON = re.compile(
    rf"\s+ON\s+(?!CLUSTER\b)({_ORACLE_NAME})(?:\s*\.\s*({_ORACLE_NAME}))?\s*\(", re.IGNORECASE
)


def _oracle_index_table(sql: str, head: str, created: "re.Match[str]") -> Optional[NamedObject]:
    """The table of ``CREATE INDEX [s.]ix ON [s.]t (...)`` read after the index name, folded as
    Oracle stores it; ``None`` for a cluster index or a name the text does not bound."""
    on = _ORACLE_INDEX_ON.match(head, created.end())
    if (
        on is None
        or not _head_name_is_bounded(head, on, (1, 2))
        or not _head_tokens_prove_name(
            sql,
            "oracle",  # lint: allow-dialect-string: Oracle index head proof
            head[: on.end() - 1].rstrip(),
            tuple(part for part in (on.group(1), on.group(2)) if part),
        )
    ):
        return None
    if re.search(r"\bFROM\b", head[on.end() :], re.IGNORECASE):
        return None  # a bitmap join index also reads the tables of its FROM clause
    parts = [raw for raw in (on.group(1), on.group(2)) if raw]
    folded = [
        strip_identifier_quotes(raw) if raw.startswith('"') else _upper_case_name(raw)
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
    folds = oracle or dialect == "snowflake"  # lint: allow-dialect-string: upper-case names
    mysql = dialect == "mysql"  # lint: allow-dialect-string: MySQL head kinds
    match = (
        _ORACLE_HEAD if oracle else _POSTGRES_HEAD if postgres else _MYSQL_HEAD if mysql else _HEAD
    ).match(head)
    if match is None and first is None:
        # Stray characters (a NUL, a lone ``/``) ahead of the statement; the engine reads past them.
        scan = _POSTGRES_HEAD_SCAN if postgres else _HEAD_SCAN
        match = scan.search(head.replace("\x00", " "))
        if match:
            operation = match.group(1).upper()
            kind = _KINDS[operation]
    dml = _DML_HEAD.match(head)
    if match and (
        match.start() != 0
        or not _head_name_is_bounded(head, match, (3, 4))
        or not _head_tokens_prove_name(
            sql,
            dialect,
            head[: match.end()],
            tuple(match.group(i) for i in (3, 4) if match.group(i)),
            routine=match.group(2).upper() in _PROGRAM_KINDS,
        )
    ):
        match = None
    if oracle and match and match.group(4) and match.group(2).upper().startswith("DATABASE"):
        match = None  # a link name is global: ``a.b`` is one name with a domain, not a schema
    if postgres and match and match.group(4) and _head_object_type(match) in _POSTGRES_UNQUALIFIED:
        match = None  # the engine rejects ``s.name`` for these: a dot never makes a schema
    if mysql and match and match.group(4) and match.group(2).upper() == "TABLESPACE":
        match = None  # a tablespace is global: ``a.b`` is a syntax error (1064), not a schema
    if dml and (
        not _head_name_is_bounded(head, dml, (2, 3))
        or not _head_tokens_prove_name(
            sql, dialect, head[: dml.end()], tuple(dml.group(i) for i in (2, 3) if dml.group(i))
        )
    ):
        dml = None
    if match:
        snowflake_head = dialect == "snowflake"  # lint: allow-dialect-string: ASCII-only names
        found = _head_object(match, fold=folds, ascii_only=snowflake_head)
        if found is not None:
            diagnostic = f"{found.type.value.lower().replace('_', ' ')}: {diagnostic}"
            objects = (found,)
    elif dml and _DML_FORM[operation].match(head) and dml.group(2).upper() not in _NOT_A_TABLE:
        schema = strip_identifier_quotes(dml.group(2)) if dml.group(3) else None
        name = strip_identifier_quotes(dml.group(3) or dml.group(2))
        if dialect == "snowflake":  # lint: allow-dialect-string: upper-case DML target
            raw_schema, raw_name = dml.group(2) if dml.group(3) else None, dml.group(
                3
            ) or dml.group(2)
            schema = raw_schema and (
                strip_identifier_quotes(raw_schema)
                if raw_schema.startswith('"')
                else _upper_case_name(raw_schema, ascii_only=True)
            )
            folded = (
                strip_identifier_quotes(raw_name)
                if raw_name.startswith('"')
                else _upper_case_name(raw_name, ascii_only=True)
            )
            if folded is None or (raw_schema and schema is None):
                return StatementFacts(operation, kind, diagnostic=diagnostic)
            name = folded
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
        table = _oracle_index_table(sql, head, match)
        if table is not None:
            return StatementFacts(
                operation, kind, objects + (table,), diagnostic=diagnostic, indexed_table=table.name
            )
    return StatementFacts(operation, kind, objects, diagnostic=diagnostic)


_CREATE_MODIFIERS = frozenset(
    {"OR", "REPLACE", "UNLOGGED", "TEMP", "TEMPORARY", "GLOBAL", "LOCAL", "UNIQUE", "MATERIALIZED"}
)


def _postgres_tablespace_clause(sql: str) -> bool:
    """Whether a CREATE TABLE, INDEX or MATERIALIZED VIEW carries a ``TABLESPACE`` clause.

    The clause is a ``TABLESPACE`` outside any parenthesis after the object's name: ``CREATE
    TABLESPACE`` names the kind of object, and a table named ``tablespace`` follows the kind word.
    """
    grammar = "postgres"  # lint: allow-dialect-string: this reader is PostgreSQL's
    try:
        tokens = Dialect.get_or_raise(grammar).tokenize(sql)
    except TokenError:
        return False
    words = [token.text.upper() for token in tokens]
    if not words or words[0] != "CREATE":
        return False
    kind = 1
    while kind < len(words) and words[kind] in _CREATE_MODIFIERS:
        kind += 1
    if kind >= len(words) or words[kind] not in {"TABLE", "INDEX", "VIEW"}:
        return False
    name = kind + 1
    if words[name : name + 1] == ["CONCURRENTLY"]:
        name += 1
    if words[name : name + 3] == ["IF", "NOT", "EXISTS"]:
        name += 3
    depth = 0
    for at in range(name, len(tokens)):
        depth += (tokens[at].token_type == TokenType.L_PAREN) - (
            tokens[at].token_type == TokenType.R_PAREN
        )
        if (
            depth == 0
            and at > name
            and tokens[at].token_type == TokenType.VAR
            and words[at] == "TABLESPACE"
        ):
            return True
    return False


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


def _fold_unquoted_names(ast: exp.Expr, *, ascii_only: bool = False) -> bool:
    """Fold the unquoted table and index names of an Oracle or Snowflake statement as the engine
    stores them; a quoted name keeps its spelling. Columns and aliases are left as written.
    ``True`` when a name holds a letter whose upper-case form is not one character: the statement
    is then unread."""
    unsafe = False

    def fold(part: object) -> None:
        nonlocal unsafe
        if isinstance(part, exp.Identifier) and not part.args.get("quoted"):
            part.meta["written"] = part.name
            folded = _upper_case_name(part.name, ascii_only=ascii_only)
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
    if not _head_tokens_prove_name(
        sql,
        "mysql",  # lint: allow-dialect-string: MySQL program head proof
        head[: match.end(6 if match.group(6) else 5)],
        tuple(part for part in parts if part),
        routine=kind.name in _PROGRAM_KINDS,
    ):
        return StatementFacts(operation, "DDL", diagnostic=diagnostic)
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
    if match.group(7) and _head_tokens_prove_name(
        sql,
        "mysql",  # lint: allow-dialect-string: MySQL trigger ON relation proof
        head[: match.end(8 if match.group(8) else 7)],
        tuple(match.group(i) for i in (7, 8) if match.group(i)),
    ):
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
        pairs = tuple(_MYSQL_RENAME_SOURCE.finditer(head))
        tokenizer = Dialect.get_or_raise("mysql")  # lint: allow-dialect-string: MySQL command
        try:
            source_command = tokenizer.tokenize(sql)
            head_command = tokenizer.tokenize(head)
        except TokenError:
            return StatementFacts(
                "RENAME", "DDL", diagnostic="mysql RENAME names are opaque to statement facts"
            )
        if (
            not source_command
            or not head_command
            or source_command[0].token_type != TokenType.RENAME
            or head_command[0].token_type != TokenType.RENAME
        ):
            return StatementFacts(
                "RENAME", "DDL", diagnostic="mysql RENAME names are opaque to statement facts"
            )
        source_verb, head_verb = source_command[0], head_command[0]
        try:
            source = tokenizer.tokenize(
                f"{sql[:source_verb.start]}UPDATE{sql[source_verb.end + 1:]}"
            )
            proposed = tokenizer.tokenize(
                f"{head[:head_verb.start]}UPDATE{head[head_verb.end + 1:]}"
            )
        except TokenError:
            return StatementFacts(
                "RENAME", "DDL", diagnostic="mysql RENAME names are opaque to statement facts"
            )
        if (
            len(source) != len(proposed)
            or any(
                (actual.token_type, actual.text) != (expected.token_type, expected.text)
                for actual, expected in zip(source, proposed)
            )
            or any(
                left.token_type == TokenType.STAR
                and right.token_type == TokenType.SLASH
                and left.end + 1 == right.start
                for left, right in zip(source, source[1:])
            )
        ):
            return StatementFacts(
                "RENAME", "DDL", diagnostic="mysql RENAME names are opaque to statement facts"
            )
        head_tokens = {(token.start, token.end + 1): token for token in proposed}
        sources = []
        for pair in pairs:
            for group in (1, 2, 3, 4):
                name = pair.group(group)
                if name is None:
                    continue
                token = head_tokens.get(pair.span(group))
                quoted = name[0] in {'"', "`", "["}
                if (
                    token is None
                    or token.text != strip_identifier_quotes(name)
                    or (
                        token.token_type != TokenType.IDENTIFIER
                        if quoted
                        else token.token_type != TokenType.VAR
                        and not (
                            group in (1, 3)
                            and pair.group(group + 1)
                            and token.token_type == TokenType.IGNORE
                        )
                    )
                    or (not quoted and name.upper() in {"IF", "NOT", "EXISTS", "ONLY"})
                ):
                    return StatementFacts(
                        "RENAME",
                        "DDL",
                        diagnostic="mysql RENAME names are opaque to statement facts",
                    )
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
    diagnostic = "mysql index columns are opaque to statement facts"
    if not _head_tokens_prove_name(
        sql,
        "mysql",  # lint: allow-dialect-string: MySQL index head proof
        head[: match.end(1)],
        (match.group(1),),
    ):
        return StatementFacts("CREATE", "DDL", diagnostic=diagnostic)
    index = NamedObject(strip_identifier_quotes(match.group(1)), SqlObjectType.INDEX, "created")
    table_groups = (2, 3) if match.group(3) else (2,)
    if not _head_tokens_prove_name(
        sql,
        "mysql",  # lint: allow-dialect-string: MySQL index ON relation proof
        head[: match.end(3 if match.group(3) else 2)],
        tuple(match.group(group) for group in table_groups),
    ):
        return StatementFacts("CREATE", "DDL", (index,), diagnostic=diagnostic)
    schema, name = (match.group(2), match.group(3)) if match.group(3) else (None, match.group(2))
    table = strip_identifier_quotes(name)
    schema = strip_identifier_quotes(schema) if schema else None
    return StatementFacts(
        "CREATE",
        "DDL",
        (
            index,
            NamedObject(table, SqlObjectType.TABLE, "referenced", schema),
        ),
        indexed_table=f"{schema}.{table}" if schema else table,
        diagnostic=diagnostic,
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


# The securable kinds a written ``GRANT ... ON <kind> name`` proves; no keyword names a table.
_GRANT_SECURABLES = {
    "": SqlObjectType.TABLE,
    "TABLE": SqlObjectType.TABLE,
    "SEQUENCE": SqlObjectType.SEQUENCE,
    "FUNCTION": SqlObjectType.FUNCTION,
    "PROCEDURE": SqlObjectType.PROCEDURE,
    "SCHEMA": SqlObjectType.SCHEMA,
    "DATABASE": SqlObjectType.DATABASE,
    "TYPE": SqlObjectType.TYPE,
}
_MYSQL_GRANT_KINDS = frozenset({"", "TABLE", "FUNCTION", "PROCEDURE"})
# Dialects whose GRANT and REVOKE name their securable, each checked against the engine.
_GRANT_DIALECTS = frozenset({"postgres", "mysql"})  # lint: allow-dialect-string: privileges


def _grant_facts(ast: exp.Grant | exp.Revoke, sql: str, dialect: str) -> StatementFacts:
    """GRANT and REVOKE are DDL that only reference the securable they name.

    The securable is named when the grammar holds it as one plain identifier whose kind is
    written (or absent, which means a table); every other form is left opaque.
    """
    operation = type(ast).__name__.upper()
    opaque = StatementFacts(
        operation,
        "DDL",
        diagnostic=f"{dialect} {type(ast).__name__} privilege targets are not modelled",
    )
    kind = str(ast.args.get("kind") or "").upper()
    securable = ast.args.get("securable")
    object_type = _GRANT_SECURABLES.get(kind)
    if (
        object_type is None
        or not isinstance(securable, exp.Table)
        or not isinstance(securable.this, exp.Identifier)
        or any(value for key, value in securable.args.items() if key not in {"this", "db"})
        or (securable.db and object_type in {SqlObjectType.SCHEMA, SqlObjectType.DATABASE})
    ):
        return opaque
    if dialect == "mysql":  # lint: allow-dialect-string: MySQL identifiers and securables
        if (
            kind not in _MYSQL_GRANT_KINDS
            # ``ON v`` names an account, not a table.
            or any(
                privilege.name.upper() == "PROXY" for privilege in ast.args.get("privileges", ())
            )
            or not _mysql_names_are_proven(securable, sql)
        ):
            return opaque
    identity = _named(securable, object_type, "referenced")
    return StatementFacts(operation, "DDL", (identity,)) if identity else opaque


def _metadata_facts(ast: exp.Show | exp.Describe, read: exp.Expr) -> StatementFacts:
    """SHOW and DESCRIBE read the tables of ``read``; they change nothing."""
    operation = "SHOW" if isinstance(ast, exp.Show) else "DESCRIBE"
    return StatementFacts(operation, "QUERY", _referenced(read))


def _mysql_metadata_table(ast: exp.Show | exp.Describe, sql: str) -> Optional[exp.Table]:
    """The one table ``DESCRIBE t`` or ``SHOW CREATE TABLE | COLUMNS | INDEX`` names, if proven."""
    if isinstance(ast, exp.Describe):
        table, read_keys = ast.this, {"this"}
    else:
        target = ast.args.get("target")
        if ast.name.upper() not in {"CREATE TABLE", "COLUMNS", "INDEX"} or not isinstance(
            target, exp.Identifier
        ):
            return None
        table = exp.Table(this=target, db=ast.args.get("db"))
        read_keys = {"this", "target", "db", "full"}
    if (
        not isinstance(table, exp.Table)
        or not isinstance(table.this, exp.Identifier)
        or any(value for key, value in ast.args.items() if key not in read_keys)
        or any(value for key, value in table.args.items() if key not in {"this", "db"})
        or _unread_names(table, "mysql") is not None  # lint: allow-dialect-string: MySQL words
        or not _mysql_names_are_proven(table, sql)
    ):
        return None
    return table


def read_statement_facts(sql: str, *, dialect: str) -> StatementFacts:
    """Read one already-split statement; never retry a second extractor.

    Text that does not tokenize is reported as an error. A statement the grammar does not
    model is classified from its leading words with an informational diagnostic.
    """
    # MariaDB shares this grammar. Without the server version only the executable comments that
    # run on every supported server are read, as the server reads them; the rest stay opaque.
    if dialect == "mysql" and (  # lint: allow-dialect-string: MySQL-family executable comments
        "/*!" in sql or "/*M!" in sql
    ):
        served = _mysql_server_view(sql)
        if served is None:
            return StatementFacts(
                "UNKNOWN",
                "UNKNOWN",
                diagnostic="mysql executable comment is opaque to statement facts",
            )
        sql = served
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
                if _fold_unquoted_names(ast)
                else (
                    "oracle statement names an object through a database link"
                    if _oracle_names_a_remote_object(sql)
                    else None
                )
            )
            if unread_reason is not None:
                head = _head_facts(sql, "", dialect=dialect)
                return StatementFacts(head.operation, head.kind, diagnostic=unread_reason)
        if (
            dialect == "snowflake"  # lint: allow-dialect-string: Snowflake stores upper case
            and ast is not None
            and _fold_unquoted_names(ast, ascii_only=True)
        ):
            head = _head_facts(sql, "", dialect=dialect)
            return StatementFacts(
                head.operation,
                head.kind,
                diagnostic="snowflake unquoted name holds a non-ASCII letter (rejected natively)",
            )
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
            dialect == "snowflake"  # lint: allow-dialect-string: unread names
            and _snowflake_tokens_hold_dynamic_name(sql)
        ):
            head = _head_facts(sql, "", dialect=dialect)
            return StatementFacts(head.operation, head.kind, diagnostic=_SNOWFLAKE_DYNAMIC_NAMES)
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
    if (
        dialect == "snowflake"  # lint: allow-dialect-string: unread names in a Command
        and isinstance(ast, exp.Command)
        and _snowflake_tokens_hold_dynamic_name(sql)
    ):
        head = _head_facts(sql, "", dialect=dialect)
        return StatementFacts(head.operation, head.kind, diagnostic=_SNOWFLAKE_DYNAMIC_NAMES)
    if (
        dialect == "postgres"  # lint: allow-dialect-string: sqlglot has no TABLESPACE clause
        and isinstance(ast, exp.Command)
        and _postgres_tablespace_clause(sql)
    ):
        return _head_facts(
            sql, "postgres TABLESPACE clause is not modelled by the grammar", dialect=dialect
        )
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

    if (
        dialect != "tsql"  # lint: allow-dialect-string: T-SQL has its own name guard
        and not (
            dialect == "oracle"  # lint: allow-dialect-string: Oracle program body is opaque
            and isinstance(ast, exp.Create)
            and str(ast.args.get("kind") or "").upper() in {"PROCEDURE", "FUNCTION", "TRIGGER"}
        )
        and any(len(table.parts) > 3 for table in ast.find_all(exp.Table))
    ):
        head = _head_facts(sql, "", dialect=dialect)
        return StatementFacts(
            head.operation,
            head.kind,
            diagnostic=f"{dialect} relation qualification is not fully represented",
        )

    unread_names = _unread_names(ast, dialect)
    if unread_names is not None:
        head = _head_facts(sql, "", dialect=dialect)
        return StatementFacts(head.operation, head.kind, diagnostic=unread_names)

    if dialect == "snowflake":  # lint: allow-dialect-string: unread Snowflake effects
        unread_effect = _snowflake_unread_effect(ast)
        if unread_effect is not None:
            return _head_facts(sql, unread_effect, dialect=dialect)

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
            return _postgres_copy_facts(ast, sql)
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
            return _metadata_facts(ast, ast)

    if dialect == "mysql" and isinstance(  # lint: allow-dialect-string: MySQL DESCRIBE and SHOW
        ast, (exp.Show, exp.Describe)
    ):
        metadata_table = _mysql_metadata_table(ast, sql)
        if metadata_table is not None:
            return _metadata_facts(ast, metadata_table)

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

    if (
        dialect == "snowflake"  # lint: allow-dialect-string: unmodelled materialized view logs
        and _snowflake_materialized_view_log_on(sql, ast)
    ):
        return StatementFacts(
            type(ast).__name__.upper(),
            "DDL",
            diagnostic="snowflake materialized view log identity is not modelled",
        )

    if isinstance(ast, exp.Create):
        object_type = _created_object_type(ast, dialect)
        if (
            dialect == "snowflake"  # lint: allow-dialect-string: unmodelled Snowflake DDL
            and object_type == SqlObjectType.UNKNOWN
        ):
            return StatementFacts(
                "CREATE",
                "DDL",
                diagnostic=f"snowflake {ast.args.get('kind') or 'object'} identity is not modelled",
            )
        schema_node = ast.this if isinstance(ast.this, exp.Schema) else None
        subject = schema_node.this if schema_node is not None else ast.this
        if (
            dialect == "snowflake"  # lint: allow-dialect-string: Snowflake schema source proof
            and object_type == SqlObjectType.SCHEMA
            and isinstance(subject, exp.Table)
            and _snowflake_schema_has_discarded_prefix(sql, subject)
        ):
            return StatementFacts(
                "CREATE", "DDL", diagnostic="snowflake schema qualification is not fully read"
            )
        properties = ast.args.get("properties")
        virtual = bool(properties and properties.find(exp.VirtualProperty))
        identity = _named(subject, object_type, "created") if subject is not None else None
        if (
            dialect
            in {"duckdb", "snowflake"}  # lint: allow-dialect-string: schema identity projection
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
        if (
            dialect == "snowflake"  # lint: allow-dialect-string: Snowflake object not read
            and identity is None
            and not isinstance(subject, exp.Index)
        ):
            return _head_facts(
                sql,
                f"snowflake {ast.args.get('kind') or 'object'} identity is not read",
                dialect=dialect,
            )
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
        if (
            dialect == "snowflake"  # lint: allow-dialect-string: CLONE source has the clone's type
            and ast.args.get("clone") is not None
            and object_type != SqlObjectType.TABLE
        ):
            objects = tuple(
                replace(obj, type=object_type) if obj.role == "referenced" else obj
                for obj in objects
            )
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
        if dialect == "snowflake" and (  # lint: allow-dialect-string: unmodelled Snowflake DDL
            object_type == SqlObjectType.UNKNOWN or kind == "ROLE"
        ):
            return StatementFacts(
                "DROP", "DDL", diagnostic=f"snowflake {kind or 'object'} identity is not modelled"
            )
        if (
            dialect
            in {
                "postgres",  # lint: allow-dialect-string: materialized views
                "oracle",  # lint: allow-dialect-string: materialized views
                "redshift",
                "snowflake",  # lint: allow-dialect-string: materialized views
            }
            and kind == "VIEW"
            and ast.args.get("materialized")
        ):
            object_type = SqlObjectType.MATERIALIZED_VIEW
        targets = ast.args.get("tables") or ast.args.get("expressions") or [ast.this]
        if (
            dialect == "snowflake"  # lint: allow-dialect-string: Snowflake schema source proof
            and object_type == SqlObjectType.SCHEMA
            and any(
                isinstance(node, exp.Table) and _snowflake_schema_has_discarded_prefix(sql, node)
                for node in targets
            )
        ):
            return StatementFacts(
                "DROP", "DDL", diagnostic="snowflake schema qualification is not fully read"
            )
        if (
            dialect
            in {"duckdb", "postgres", "snowflake"}  # lint: allow-dialect-string: schema identity
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

    if dialect == "snowflake" and isinstance(  # lint: allow-dialect-string: single-table TRUNCATE
        ast, exp.TruncateTable
    ):
        target = ast.expressions[0] if len(ast.expressions) == 1 else None
        if (
            isinstance(target, exp.Table)
            and isinstance(target.this, exp.Identifier)
            and all(not v for k, v in ast.args.items() if k not in {"expressions", "exists"})
            and all(not v for k, v in target.args.items() if k not in {"this", "db", "catalog"})
            and not _snowflake_schema_has_discarded_prefix(sql, target)
        ):
            identity = _named(target, SqlObjectType.TABLE, "altered")
            if identity is not None:
                return StatementFacts("TRUNCATE", "DDL", (identity,))
        return _head_facts(sql, "snowflake TRUNCATE target is not read", dialect=dialect)

    if dialect == "snowflake" and isinstance(  # lint: allow-dialect-string: COMMENT ON a relation
        ast, exp.Comment
    ):
        kind = str(ast.args.get("kind") or "").upper()
        subject = ast.this
        if (
            kind in {"TABLE", "VIEW", "SEQUENCE"}
            and isinstance(subject, exp.Table)
            and isinstance(subject.this, exp.Identifier)
            and not _snowflake_schema_has_discarded_prefix(sql, subject)
        ) or (kind == "COLUMN" and isinstance(subject, exp.Column)):
            identity = _postgres_comment_identity(ast)
            if identity is not None:
                return StatementFacts("COMMENT", "DDL", (identity,))
        return _head_facts(sql, "snowflake COMMENT ON target is not read", dialect=dialect)

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
        dialect in {"duckdb", "snowflake"}  # lint: allow-dialect-string: qualified MERGE facts
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
        if dialect == "snowflake" and (  # lint: allow-dialect-string: unread target
            table is None or not table.name
        ):
            return StatementFacts(
                operation, "DML", diagnostic="snowflake mutation target is not read"
            )
        if (
            dialect == "snowflake"  # lint: allow-dialect-string: MERGE actions must be read
            and isinstance(ast, exp.Merge)
            and (
                not _sqlglot_events(ast)
                # A CTE named like the target leaves it unsaid which of the two is written.
                or any(
                    cte.alias.lower() == table.name.lower()
                    for cte in ast.find_all(exp.CTE)
                    if table is not None and not table.db
                )
            )
        ):
            return StatementFacts(
                operation, "DML", diagnostic="snowflake MERGE actions or CTE scopes are not read"
            )
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
            if dialect in {"oracle", "snowflake"}:  # lint: allow-dialect-string: as written
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
            _merge_referenced(ast, dialect == "snowflake")  # lint: allow-dialect-string: folding
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
                "snowflake",  # lint: allow-dialect-string: bare targets
                "tsql",
            }
            and table is not None
            and (table.args.get("alias") or table.args.get("joins") or table.args.get("only"))
        ):
            target_table = table.copy()
            target_table.set("alias", None)
            target_table.set("joins", None)
            target_table.set("only", None)
        if (
            dialect in {"oracle", "snowflake"}  # lint: allow-dialect-string: spelling
            and target_table is not None
        ):
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
    if dialect in _GRANT_DIALECTS and isinstance(ast, (exp.Grant, exp.Revoke)):
        return _grant_facts(ast, sql, dialect)
    return _head_facts(
        sql, f"{dialect} {type(ast).__name__} has no statement facts mapping", dialect=dialect
    )
