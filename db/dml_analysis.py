"""Dialect-agnostic SQL scanning for data undo-safety analysis.

Pure mechanics only — quote/comment/parenthesis tracking, SET-clause
extraction and DML classification. No dialect names or vendor SQL
literals live here: the dialect-specific markers (upsert clauses,
identifier quoting) are owned by the plugin's
:class:`~db.base_quirks.BaseQuirks` and passed in by the caller. This
keeps the data layer free of per-database
knowledge while the scanning algorithm stays in one shared place.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

import sqlglot
from sqlglot import exp

#: Quote delimiters understood by the scanner: opening char -> closing char.
#: Union of every dialect's string/identifier quoting so the mechanics are
#: safe regardless of dialect; plugins may narrow this via quirks.
DEFAULT_QUOTE_PAIRS: Dict[str, str] = {"'": "'", '"': '"', "`": "`", "[": "]"}

#: Default phrase whose presence makes an INSERT also take the UPDATE path
#: without a following ``SET`` keyword (MySQL upsert).
DEFAULT_UPSERT_SET_MARKERS: Tuple[str, ...] = ("ON DUPLICATE KEY UPDATE",)

#: Default two-token upsert markers (both must appear) that introduce a
#: standard ``... DO UPDATE SET`` clause (PostgreSQL / SQLite upsert).
DEFAULT_UPSERT_MARKER_PAIRS: Tuple[Tuple[str, str], ...] = (("ON CONFLICT", "DO UPDATE"),)

_IDENTIFIER = (
    r'(?:`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][\w$]*)'
    r'(?:\s*\.\s*(?:`[^`]+`|"[^"]+"|\[[^\]]+\]|[A-Za-z_][\w$]*))*'
)


@dataclass(frozen=True)
class DmlMutation:
    """Undo-safety facts extracted from a single DML statement.

    ``events`` is ``None`` when the firing events cannot be determined,
    which callers must treat conservatively (as if every event matched).
    """

    table: str
    events: Optional[Set[str]]
    updated_columns: List[str]


def analyze_dml(
    statement: str,
    *,
    sqlglot_dialect: Optional[str] = None,
    quote_pairs: Dict[str, str] = DEFAULT_QUOTE_PAIRS,
    upsert_set_markers: Sequence[str] = DEFAULT_UPSERT_SET_MARKERS,
    upsert_marker_pairs: Sequence[Tuple[str, str]] = DEFAULT_UPSERT_MARKER_PAIRS,
) -> DmlMutation:
    """Classify a DML statement for undo-safety: table, events, updated columns.

    Prefers the ``sqlglot`` AST (dialect-correct, no hand-rolled SQL knowledge)
    and falls back to the regex scanner only when sqlglot cannot parse the
    statement or does not recognise it as DML — mirroring the hybrid-parser
    philosophy used elsewhere.
    """
    mutation = _analyze_dml_sqlglot(statement, sqlglot_dialect)
    if mutation is not None:
        return mutation
    return DmlMutation(
        table=statement_dml_table(statement),
        events=_statement_dml_events(statement, upsert_set_markers, upsert_marker_pairs),
        updated_columns=_updated_column_names(statement, quote_pairs, upsert_set_markers),
    )


def _analyze_dml_sqlglot(statement: str, dialect: Optional[str]) -> Optional[DmlMutation]:
    """AST-based analysis via sqlglot, or ``None`` to defer to the regex scanner."""
    text = strip_leading_sql_comments(statement).lstrip()
    if not text:
        return DmlMutation(table="", events=set(), updated_columns=[])
    try:
        ast = sqlglot.parse_one(text, read=dialect)
    except Exception:
        return None
    if ast is None or not isinstance(ast, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
        return None
    return DmlMutation(
        table=_sqlglot_table(ast),
        events=_sqlglot_events(ast),
        updated_columns=_sqlglot_updated_columns(ast),
    )


def _sqlglot_table(ast: "exp.Expression") -> str:
    target = ast.this if isinstance(ast, exp.Insert) else ast
    table = target.find(exp.Table)
    if table is None:
        return ""
    return ".".join(part for part in (table.catalog, table.db, table.name) if part)


def _sqlglot_events(ast: "exp.Expression") -> Optional[Set[str]]:
    if isinstance(ast, exp.Update):
        return {"UPDATE"}
    if isinstance(ast, exp.Delete):
        return {"DELETE"}
    if isinstance(ast, exp.Insert):
        events = {"INSERT"}
        conflict = ast.args.get("conflict")
        if conflict is not None and conflict.args.get("expressions"):
            events.add("UPDATE")
        return events
    if isinstance(ast, exp.Merge):
        merge_events: Set[str] = set()
        for then in _merge_then_clauses(ast):
            if isinstance(then, exp.Update):
                merge_events.add("UPDATE")
            elif isinstance(then, exp.Insert):
                merge_events.add("INSERT")
            elif isinstance(then, exp.Delete) or then.sql().strip().upper().startswith("DELETE"):
                merge_events.add("DELETE")
        return merge_events or None
    return None


def _sqlglot_updated_columns(ast: "exp.Expression") -> List[str]:
    if isinstance(ast, exp.Update):
        return _eq_target_columns(ast.args.get("expressions"))
    if isinstance(ast, exp.Insert):
        conflict = ast.args.get("conflict")
        return _eq_target_columns(conflict.args.get("expressions")) if conflict is not None else []
    if isinstance(ast, exp.Merge):
        columns: List[str] = []
        for then in _merge_then_clauses(ast):
            if isinstance(then, exp.Update):
                columns.extend(_eq_target_columns(then.args.get("expressions")))
        return columns
    return []


def _merge_then_clauses(ast: "exp.Merge") -> List["exp.Expression"]:
    whens = ast.args.get("whens")
    expressions = whens.expressions if whens is not None else []
    return [when.args.get("then") for when in expressions if when.args.get("then") is not None]


def _eq_target_columns(expressions: Any) -> List[str]:
    columns: List[str] = []
    for assignment in expressions or []:
        if isinstance(assignment, exp.EQ):
            target = assignment.this
            name = getattr(target, "name", "") or target.sql()
            if name:
                columns.append(name)
    return columns


def dml_where_predicate(
    statement: str,
    *,
    sqlglot_dialect: Optional[str] = None,
) -> Optional[str]:
    """Return the WHERE condition of an UPDATE/DELETE, without the keyword.

    Used to capture exactly the rows a data correction affects (``SELECT ...
    FROM t WHERE <predicate>``) instead of a whole-table sample. ``None`` means
    the statement is not a parseable single UPDATE/DELETE, or it has no WHERE
    (a full-table mutation) — callers must treat ``None`` conservatively (the
    statement may touch every row). The predicate is rendered by ``sqlglot``
    for ``sqlglot_dialect`` so it round-trips into a dialect-correct SELECT.
    """
    text = strip_leading_sql_comments(statement).lstrip()
    if not text:
        return None
    try:
        ast = sqlglot.parse_one(text, read=sqlglot_dialect)
    except Exception:
        return None
    if not isinstance(ast, (exp.Update, exp.Delete)):
        return None
    where = ast.args.get("where")
    if where is None or where.this is None:
        return None
    return str(where.this.sql(dialect=sqlglot_dialect))


_UNRESOLVED = object()


def _literal_python_value(node: "exp.Expression") -> Any:
    """Python value of a literal AST node, or ``_UNRESOLVED`` for non-literals."""
    if isinstance(node, exp.Null):
        return None
    if isinstance(node, exp.Boolean):
        return bool(node.this)
    if isinstance(node, exp.Neg):
        inner = _literal_python_value(node.this)
        return -inner if isinstance(inner, (int, float)) else _UNRESOLVED
    if isinstance(node, exp.Literal):
        if node.is_string:
            return str(node.this)
        text = str(node.this)
        try:
            return int(text)
        except ValueError:
            try:
                return float(text)
            except ValueError:
                return _UNRESOLVED
    return _UNRESOLVED


def insert_value_rows(
    statement: str,
    *,
    sqlglot_dialect: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Column→value dicts for an ``INSERT ... (cols) VALUES (...)`` statement.

    Lets the capture layer learn the primary-key values of explicitly-inserted
    rows so an INSERT correction can be undone (delete those rows) without
    RETURNING. Each returned dict maps a column to its literal Python value;
    columns whose value is *not* a literal (``DEFAULT``, a function, a sequence
    call) are omitted, so a row missing a PK column signals an auto-generated
    key that cannot be captured here.

    Returns ``None`` when the statement is not a parseable ``INSERT`` with an
    explicit column list and a ``VALUES`` clause (e.g. ``INSERT ... SELECT``,
    or no column list) — the caller treats that as an unkeyable insert.
    """
    text = strip_leading_sql_comments(statement).lstrip()
    if not text:
        return None
    try:
        ast = sqlglot.parse_one(text, read=sqlglot_dialect)
    except Exception:
        return None
    if not isinstance(ast, exp.Insert):
        return None
    schema = ast.this
    if not isinstance(schema, exp.Schema):
        return None
    columns = [str(col.name) for col in schema.expressions if getattr(col, "name", "")]
    values = ast.expression
    if not columns or not isinstance(values, exp.Values):
        return None
    rows: List[Dict[str, Any]] = []
    for tup in values.expressions:
        exprs = tup.expressions if isinstance(tup, exp.Tuple) else None
        if exprs is None or len(exprs) != len(columns):
            return None
        row: Dict[str, Any] = {}
        for column, value_node in zip(columns, exprs):
            value = _literal_python_value(value_node)
            if value is not _UNRESOLVED:
                row[column] = value
        rows.append(row)
    return rows


def updates_restore_key(
    statement: str,
    restore_key_columns: Sequence[str],
    *,
    sqlglot_dialect: Optional[str] = None,
    quote_pairs: Dict[str, str] = DEFAULT_QUOTE_PAIRS,
    upsert_set_markers: Sequence[str] = DEFAULT_UPSERT_SET_MARKERS,
) -> bool:
    """Whether the statement assigns any of ``restore_key_columns``."""
    keys = {str(column).strip().strip('"`[]').lower() for column in restore_key_columns}
    if not keys:
        return False
    columns = analyze_dml(
        statement,
        sqlglot_dialect=sqlglot_dialect,
        quote_pairs=quote_pairs,
        upsert_set_markers=upsert_set_markers,
    ).updated_columns
    return any(column.lower() in keys for column in columns)


def is_full_table_dml(
    statement: str,
    *,
    sqlglot_dialect: Optional[str] = None,
    quote_pairs: Dict[str, str] = DEFAULT_QUOTE_PAIRS,
) -> bool:
    """Whether the statement is an UPDATE/DELETE with no top-level ``WHERE``.

    A full-table UPDATE/DELETE rewrites every row and is what the
    ``allow_full_table`` governance policy guards against. ``sqlglot``
    classifies the statement (so INSERT/MERGE and comment-prefixed text are
    handled), while the top-level ``WHERE`` decision uses the dialect-quote-safe
    scanner — ``sqlglot`` parsed with the wrong dialect can mis-read a quoted
    column named ``where`` as a clause.
    """
    text = strip_leading_sql_comments(statement).lstrip()
    if not text:
        return False
    try:
        ast = sqlglot.parse_one(text, read=sqlglot_dialect)
    except Exception:
        ast = None
    if ast is not None:
        if not isinstance(ast, (exp.Update, exp.Delete)):
            return False
    elif not re.match(r"^(UPDATE|DELETE)\b", text, flags=re.IGNORECASE):
        return False
    return _find_top_level_keyword(text, "WHERE", quote_pairs) < 0


def extract_dml_table_name(statement: str) -> str:
    """Best-effort table extraction when the dialect parser cannot provide one."""
    # The table is followed by whitespace, ``;``, ``(`` (INSERT column list) or
    # end-of-string. A trailing ``\b`` fails when the identifier ends in a quote
    # char (``"`` / `` ` `` / ``]``), so use an explicit lookahead instead — this
    # is what lets quoted/bracketed INSERT and DELETE targets resolve (the UPDATE
    # pattern is unaffected because it ends in ``SET``).
    _after = r"(?=\s|;|\(|$)"
    patterns = (
        rf"^\s*UPDATE\s+({_IDENTIFIER})\s+SET\b",
        rf"^\s*DELETE\s+FROM\s+({_IDENTIFIER}){_after}",
        rf"^\s*INSERT\s+INTO\s+({_IDENTIFIER}){_after}",
    )
    for pattern in patterns:
        match = re.search(pattern, statement, flags=re.IGNORECASE)
        if match:
            return re.sub(r"\s*\.\s*", ".", match.group(1))
    return ""


def statement_dml_table(statement: str, dialect: Optional[str] = None) -> str:
    """Table targeted by a DML statement, including ``MERGE INTO``.

    When *dialect* is given, the dialect-correct sqlglot AST is preferred: it
    resolves quoted / bracketed / schema-qualified targets that the regex
    scanner can mishandle, and ``Table.sql`` re-emits the verbatim-quoted form
    so the result stays a valid SQL reference for downstream raw interpolation.
    Falls back to the regex scanner when no dialect is known or sqlglot cannot
    parse the statement — mirroring the hybrid-parser philosophy used by
    :func:`analyze_dml`.
    """
    text = strip_leading_sql_comments(statement).lstrip()
    if dialect:
        ast_table = _sqlglot_dml_table_sql(text, dialect)
        if ast_table:
            return ast_table
    table = extract_dml_table_name(text)
    if table:
        return table
    match = re.search(rf"^\s*MERGE\s+INTO\s+({_IDENTIFIER})\b", text, flags=re.IGNORECASE)
    if match:
        return re.sub(r"\s*\.\s*", ".", match.group(1))
    return ""


def _sqlglot_dml_table_sql(text: str, dialect: str) -> str:
    """Dialect-quoted table reference for a DML statement via the sqlglot AST.

    Returns the quoted ``schema.table`` (any table alias stripped) or ``""``
    when sqlglot cannot parse *text* or it is not DML, letting the caller fall
    back to the regex scanner. Unlike :func:`_sqlglot_table` — which returns the
    bare unquoted name for table *matching* — this preserves quoting because the
    result is interpolated into raw SQL (e.g. a capture ``SELECT ... FROM``).
    """
    try:
        ast = sqlglot.parse_one(text, read=dialect)
    except Exception:
        return ""
    if ast is None or not isinstance(ast, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
        return ""
    target = ast.this if isinstance(ast, exp.Insert) else ast
    table = target.find(exp.Table)
    if table is None:
        return ""
    if table.args.get("alias"):
        table = table.copy()
        table.set("alias", None)
    return table.sql(dialect=dialect)


def strip_leading_sql_comments(statement: str) -> str:
    """Drop leading line/block comments so the first keyword is reachable."""
    text = statement
    while True:
        stripped = text.lstrip()
        if stripped.startswith("--"):
            end = stripped.find("\n")
            if end < 0:
                return ""
            text = stripped[end + 1 :]
            continue
        if stripped.startswith("/*"):
            end = stripped.find("*/", 2)
            if end < 0:
                return ""
            text = stripped[end + 2 :]
            continue
        return stripped


def _statement_dml_events(
    statement: str,
    upsert_set_markers: Sequence[str],
    upsert_marker_pairs: Sequence[Tuple[str, str]],
) -> Optional[Set[str]]:
    text = strip_leading_sql_comments(statement).lstrip()
    if not text:
        return set()
    upper = text.upper()
    if re.match(r"^INSERT\b", upper):
        events = {"INSERT"}
        if _is_upsert_with_update(upper, upsert_set_markers, upsert_marker_pairs):
            # Upsert clauses take the UPDATE path on a key collision and
            # fire UPDATE triggers too.
            events.add("UPDATE")
        return events
    if re.match(r"^UPDATE\b", upper):
        return {"UPDATE"}
    if re.match(r"^DELETE\b", upper):
        return {"DELETE"}
    if re.match(r"^MERGE\b", upper):
        merge_events = {
            match.group(1).upper()
            for match in re.finditer(r"\bTHEN\s+(INSERT|UPDATE|DELETE)\b", upper)
        }
        return merge_events or None
    return None


def _is_upsert_with_update(
    upper_statement: str,
    upsert_set_markers: Sequence[str],
    upsert_marker_pairs: Sequence[Tuple[str, str]],
) -> bool:
    if any(marker.upper() in upper_statement for marker in upsert_set_markers):
        return True
    for first, second in upsert_marker_pairs:
        pattern = _phrase_regex(first) + r".*?" + _phrase_regex(second)
        if re.search(pattern, upper_statement, flags=re.DOTALL):
            return True
    return False


def _phrase_regex(phrase: str) -> str:
    return r"\b" + r"\s+".join(re.escape(word) for word in phrase.split()) + r"\b"


def _updated_column_names(
    statement: str,
    quote_pairs: Dict[str, str],
    upsert_set_markers: Sequence[str],
) -> List[str]:
    columns: List[str] = []
    for marker in upsert_set_markers:
        marker_pos = _find_top_level_keyword(statement, marker, quote_pairs)
        if marker_pos >= 0:
            assignment_start = marker_pos + len(marker)
            columns.extend(
                _updated_column_names_from_clause(statement, quote_pairs, assignment_start)
            )

    search_start = 0
    while True:
        update_pos = _find_top_level_keyword(statement, "UPDATE", quote_pairs, start=search_start)
        if update_pos < 0:
            break
        set_pos = _find_top_level_keyword(statement, "SET", quote_pairs, start=update_pos + 6)
        if set_pos < 0:
            search_start = update_pos + 6
            continue
        assignment_start = set_pos + 3
        columns.extend(_updated_column_names_from_clause(statement, quote_pairs, assignment_start))
        search_start = assignment_start
    return columns


def _updated_column_names_from_clause(
    statement: str, quote_pairs: Dict[str, str], assignment_start: int
) -> List[str]:
    end_pos = _find_update_assignment_end(statement, quote_pairs, start=assignment_start)
    set_clause = statement[assignment_start : end_pos if end_pos >= 0 else len(statement)]
    columns: List[str] = []
    for assignment in _split_top_level_commas(set_clause, quote_pairs):
        eq_pos = _find_top_level_char(assignment, "=", quote_pairs)
        if eq_pos <= 0:
            continue
        column = _normalize_assignment_target(assignment[:eq_pos])
        if column:
            columns.append(column)
    return columns


def _find_update_assignment_end(statement: str, quote_pairs: Dict[str, str], start: int) -> int:
    positions = [
        _find_top_level_keyword(statement, keyword, quote_pairs, start=start)
        for keyword in ("FROM", "WHERE", "RETURNING", "OUTPUT", "ORDER", "LIMIT")
    ]
    positions.append(_find_top_level_when_outside_case(statement, quote_pairs, start=start))
    semicolon_pos = _find_top_level_char(statement[start:], ";", quote_pairs)
    if semicolon_pos >= 0:
        positions.append(start + semicolon_pos)
    candidates = [pos for pos in positions if pos >= 0]
    return min(candidates) if candidates else -1


def _skip_quote(text: str, i: int, quote: str) -> Tuple[int, str]:
    """Advance one position inside an open quote, returning (index, quote)."""
    ch = text[i]
    if ch == quote:
        if quote == "'" and i + 1 < len(text) and text[i + 1] == "'":
            return i + 2, quote
        return i + 1, ""
    return i + 1, quote


def _skip_comment(text: str, i: int) -> int:
    """Index just past a comment starting at ``i``, or -1 when none."""
    nxt = text[i : i + 2]
    if nxt == "--":
        end = text.find("\n", i + 2)
        return len(text) if end == -1 else end + 1
    if nxt == "/*":
        end = text.find("*/", i + 2)
        return len(text) if end == -1 else end + 2
    return -1


def _find_top_level_when_outside_case(
    statement: str, quote_pairs: Dict[str, str], start: int = 0
) -> int:
    depth = 0
    quote = ""
    case_depth = 0
    i = start
    while i < len(statement):
        if quote:
            i, quote = _skip_quote(statement, i, quote)
            continue
        comment_end = _skip_comment(statement, i)
        if comment_end >= 0:
            i = comment_end
            continue
        ch = statement[i]
        if ch in quote_pairs:
            quote = quote_pairs[ch]
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0:
            if _matches_keyword_at(statement, i, "CASE"):
                case_depth += 1
                i += 4
                continue
            if _matches_keyword_at(statement, i, "END") and case_depth > 0:
                case_depth -= 1
                i += 3
                continue
            if _matches_keyword_at(statement, i, "WHEN") and case_depth == 0:
                return i
        i += 1
    return -1


def _find_top_level_keyword(
    statement: str, keyword: str, quote_pairs: Dict[str, str], start: int = 0
) -> int:
    depth = 0
    quote = ""
    i = start
    while i < len(statement):
        if quote:
            i, quote = _skip_quote(statement, i, quote)
            continue
        comment_end = _skip_comment(statement, i)
        if comment_end >= 0:
            i = comment_end
            continue
        ch = statement[i]
        if ch in quote_pairs:
            quote = quote_pairs[ch]
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif depth == 0 and _matches_keyword_at(statement, i, keyword):
            return i
        i += 1
    return -1


def _matches_keyword_at(statement: str, position: int, keyword: str) -> bool:
    if statement[position : position + len(keyword)].upper() != keyword.upper():
        return False
    before = statement[position - 1] if position > 0 else " "
    after_pos = position + len(keyword)
    after = statement[after_pos] if after_pos < len(statement) else " "
    return not (before.isalnum() or before == "_") and not (after.isalnum() or after == "_")


def _split_top_level_commas(text: str, quote_pairs: Dict[str, str]) -> List[str]:
    parts: List[str] = []
    start = 0
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        if quote:
            i, quote = _skip_quote(text, i, quote)
            continue
        ch = text[i]
        if ch in quote_pairs:
            quote = quote_pairs[ch]
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == "," and depth == 0:
            parts.append(text[start:i].strip())
            start = i + 1
        i += 1
    tail = text[start:].strip()
    if tail:
        parts.append(tail)
    return parts


def _find_top_level_char(text: str, target: str, quote_pairs: Dict[str, str]) -> int:
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        if quote:
            i, quote = _skip_quote(text, i, quote)
            continue
        ch = text[i]
        if ch in quote_pairs:
            quote = quote_pairs[ch]
        elif ch == "(":
            depth += 1
        elif ch == ")":
            depth = max(0, depth - 1)
        elif ch == target and depth == 0:
            return i
        i += 1
    return -1


def _normalize_assignment_target(target: str) -> str:
    token = target.strip()
    if "." in token:
        token = token.rsplit(".", 1)[-1].strip()
    return token.strip('"`[]').strip()
