"""Dialect-agnostic DML analysis for data undo-safety.

Classifies a DML statement (table, events, updated columns, WHERE predicate) from a plugin's
statement facts or, for a plugin with no reader, the sqlglot AST. A statement neither can read
comes back unread; nothing is guessed from the text. Quote/comment/parenthesis scanning helpers
live here too. No dialect names or vendor SQL literals: the plugin's
:class:`~db.base_quirks.BaseQuirks` owns the dialect knowledge. The upsert-marker parameters and
quirks attributes are kept for signature compatibility; nothing consumes them any more.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Dict, List, Optional, Sequence, Set, Tuple

from dblift.core.sql_parser.dml_modifiers import MYSQL_DML_MODIFIER, MYSQL_DML_MODIFIER_WORDS

if TYPE_CHECKING:
    from sqlglot import exp

    from dblift.db.base_quirks import BaseQuirks

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

_DML_VERB = re.compile(r"(?:UPDATE|DELETE|INSERT)\b", re.IGNORECASE)
_DML_MODIFIER_WORDS = MYSQL_DML_MODIFIER_WORDS
_DML_MODIFIER = MYSQL_DML_MODIFIER
# The ONLY keyword right after ``UPDATE`` / ``DELETE FROM``; ``only.t`` is a qualified name.
_DML_ONLY = re.compile(
    r"(?:UPDATE|DELETE(?:\s|/\*.*?\*/)+FROM)(?:\s|/\*.*?\*/)*ONLY(?![\w$#]|\s*\.)",
    re.IGNORECASE | re.DOTALL,
)
_DML_TOP = re.compile(r"\s*TOP\s*\(", re.IGNORECASE)
_DML_PERCENT = re.compile(r"\s*PERCENT\b", re.IGNORECASE)


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
    quirks: Optional["BaseQuirks"] = None,
    quote_pairs: Dict[str, str] = DEFAULT_QUOTE_PAIRS,
    upsert_set_markers: Sequence[str] = DEFAULT_UPSERT_SET_MARKERS,
    upsert_marker_pairs: Sequence[Tuple[str, str]] = DEFAULT_UPSERT_MARKER_PAIRS,
) -> DmlMutation:
    """Classify a DML statement for undo-safety: table, events, updated columns.

    A plugin's own statement facts reader, when ``quirks`` has one, answers.
    Without one the ``sqlglot`` AST does; a statement it cannot parse, or does
    not recognise as DML, comes back unread (empty table, ``events=None``), never
    guessed from the text.
    """
    if quirks is not None and quirks.supports_statement_facts:
        facts = quirks.statement_facts(statement)
        return DmlMutation(
            facts.target or "",
            set(facts.events) if facts.events else None,
            list(facts.affected_columns) if facts.events and "UPDATE" in facts.events else [],
        )

    from dblift.core.sql_parser.unread_names import names_unreadable

    dialect = quirks.sqlglot_dialect if quirks is not None else None
    mutation = (
        None if names_unreadable(statement, dialect) else _analyze_dml_sqlglot(statement, dialect)
    )
    return mutation or DmlMutation(table="", events=None, updated_columns=[])


def _without_dml_modifiers(text: str) -> str:
    """Drop what sits between the DML verb and its target (``LOW_PRIORITY``,
    ``IGNORE``, T-SQL ``TOP (n)``, Oracle hints) so every parser sees the target first."""
    verb = _DML_VERB.match(text)
    if verb is None:
        return text
    pos = verb.end()
    while True:
        modifier = _DML_MODIFIER[verb.group().upper()].match(text, pos)
        if modifier:
            pos = modifier.end()
            continue
        top = _DML_TOP.match(text, pos)
        if top is None:
            break
        depth = 1
        end = top.end()
        while end < len(text) and depth:
            depth += {"(": 1, ")": -1}.get(text[end], 0)
            end += 1
        if depth:
            break
        percent = _DML_PERCENT.match(text, end)
        pos = percent.end() if percent else end
    return text if pos == verb.end() else f"{text[: verb.end()]} {text[pos:].lstrip()}"


def _analyze_dml_sqlglot(statement: str, dialect: Optional[str]) -> Optional[DmlMutation]:
    """AST-based analysis via sqlglot, or ``None`` when it cannot read the statement as DML."""
    text = _without_dml_modifiers(strip_leading_sql_comments(statement).lstrip())
    if not text:
        return DmlMutation(table="", events=set(), updated_columns=[])
    import sqlglot
    from sqlglot import exp

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
    table = _dml_target_table(ast)
    if table is None:
        return ""
    return ".".join(part for part in (table.catalog, table.db, table.name) if part)


def _dml_target_table(ast: "exp.Expression") -> Optional["exp.Table"]:
    """The table a DML statement writes to: resolves ``DELETE <alias> FROM`` and
    ``UPDATE <alias> ... FROM <table> AS <alias>`` (T-SQL) targets to the table."""
    from sqlglot import exp

    targets = ast.args.get("tables") if isinstance(ast, exp.Delete) else None
    source = ast.this
    if not isinstance(source, exp.Expression):
        # ``DELETE t WHERE ...`` (no FROM; Oracle, T-SQL) keeps its target in ``tables``.
        source = targets[0] if targets else None
    if source is None:
        return None
    if (
        isinstance(ast, exp.Update)
        and isinstance(source, exp.Table)
        and not source.alias
        and not source.db
        and not source.catalog
    ):
        from_ = ast.args.get("from_") or ast.args.get("from")
        if from_ is not None:
            from_tables: List[exp.Table] = list(from_.find_all(exp.Table))
            for table in from_tables:
                if table.alias == source.name:
                    return table
    candidates: List[exp.Table] = list(source.find_all(exp.Table))
    if not candidates:
        return None
    if targets:
        wanted = targets[0].name
        for table in candidates:
            if wanted in (table.alias, table.name):
                return table
    return candidates[0]


def _sqlglot_events(ast: "exp.Expression") -> Optional[Set[str]]:
    from sqlglot import exp

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
    from sqlglot import exp

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
    from sqlglot import exp

    columns: List[str] = []
    for assignment in expressions or []:
        if isinstance(assignment, exp.EQ):
            target = assignment.this
            targets = target.expressions if isinstance(target, exp.Tuple) else [target]
            for column in targets:
                if isinstance(column, exp.Paren):
                    column = column.this
                name = getattr(column, "name", "") or column.sql()
                if name:
                    columns.append(name)
    return columns


def dml_where_predicate(
    statement: str,
    *,
    quirks: Optional["BaseQuirks"] = None,
) -> Optional[str]:
    """Return the WHERE condition of an UPDATE/DELETE, without the keyword.

    Used to capture exactly the rows a data correction affects (``SELECT ...
    FROM t WHERE <predicate>``) instead of a whole-table sample. ``None`` means
    the statement is not a parseable single UPDATE/DELETE, or it has no WHERE
    (a full-table mutation) — callers must treat ``None`` conservatively (the
    statement may touch every row). The predicate is rendered by ``sqlglot``
    for the plugin's dialect so it round-trips into a dialect-correct SELECT.
    """
    if quirks is not None and quirks.supports_statement_facts:
        return quirks.statement_facts(statement).predicate
    dialect = quirks.sqlglot_dialect if quirks is not None else None

    text = strip_leading_sql_comments(statement).lstrip()
    if not text:
        return None
    import sqlglot
    from sqlglot import exp

    try:
        ast = sqlglot.parse_one(text, read=dialect)
    except Exception:
        return None
    if not isinstance(ast, (exp.Update, exp.Delete)):
        return None
    where = ast.args.get("where")
    if not isinstance(where, exp.Where) or where.this is None:
        return None
    return str(where.this.sql(dialect=dialect))


_UNRESOLVED = object()


def _literal_python_value(node: "exp.Expression") -> Any:
    """Python value of a literal AST node, or ``_UNRESOLVED`` for non-literals."""
    from sqlglot import exp

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
    import sqlglot
    from sqlglot import exp

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
    quirks: Optional["BaseQuirks"] = None,
    quote_pairs: Dict[str, str] = DEFAULT_QUOTE_PAIRS,
    upsert_set_markers: Sequence[str] = DEFAULT_UPSERT_SET_MARKERS,
) -> bool:
    """Whether the statement may assign any of ``restore_key_columns``.

    A statement that cannot be read (``events is None``) answers ``True``: unread is not untouched.
    """
    keys = {str(column).strip().strip('"`[]').lower() for column in restore_key_columns}
    if not keys:
        return False
    mutation = analyze_dml(
        statement,
        quirks=quirks,
        quote_pairs=quote_pairs,
        upsert_set_markers=upsert_set_markers,
    )
    if mutation.events is None and statement.strip():
        return True  # unread: assume the key may be assigned
    return any(column.lower() in keys for column in mutation.updated_columns)


def is_full_table_dml(
    statement: str,
    *,
    quirks: Optional["BaseQuirks"] = None,
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
    if quirks is not None and quirks.supports_statement_facts:
        facts = quirks.statement_facts(statement)
        return facts.operation in ("UPDATE", "DELETE") and (not facts.predicate)
    dialect = quirks.sqlglot_dialect if quirks is not None else None

    text = strip_leading_sql_comments(statement).lstrip()
    if not text:
        return False
    import sqlglot
    from sqlglot import exp

    try:
        ast = sqlglot.parse_one(text, read=dialect)
    except Exception:
        ast = None
    if ast is not None:
        if not isinstance(ast, (exp.Update, exp.Delete)):
            return False
    elif not re.match(r"^(UPDATE|DELETE)\b", text, flags=re.IGNORECASE):
        return False
    return _find_top_level_keyword(text, "WHERE", quote_pairs) < 0


#: Outer-statement keywords a CTE list can feed, split by whether the
#: statement modifies data. Used only by the keyword-scan fallback below.
_CTE_OUTER_DML_KEYWORDS: Tuple[str, ...] = ("INSERT", "UPDATE", "DELETE", "MERGE")
_CTE_OUTER_QUERY_KEYWORDS: Tuple[str, ...] = ("SELECT", "VALUES", "TABLE")

#: PostgreSQL dollar-quote opening tag: ``$$`` or ``$tag$``. Its delimiters
#: are a variable-length matched pair, not a single character, so it can't
#: be expressed through ``quote_pairs`` (char -> char) the way ``'``/``"``/
#: backtick/``[...]`` are.
_DOLLAR_QUOTE_OPEN_RE = re.compile(r"\$([A-Za-z_][A-Za-z0-9_]*)?\$")


def _skip_dollar_quote(text: str, i: int) -> int:
    """Index just past a dollar-quoted region starting at ``i``, or -1 when none."""
    match = _DOLLAR_QUOTE_OPEN_RE.match(text, i)
    if not match:
        return -1
    tag = match.group(0)
    end = text.find(tag, match.end())
    return len(text) if end == -1 else end + len(tag)


def cte_outer_statement_type(
    statement: str,
    *,
    sqlglot_dialect: Optional[str] = None,
    quote_pairs: Dict[str, str] = DEFAULT_QUOTE_PAIRS,
) -> Optional[str]:
    """Outer statement kind of a ``WITH ...`` statement: ``"QUERY"`` or ``"DML"``.

    A CTE list can feed a ``SELECT`` (a query) or an ``INSERT``/``UPDATE``/
    ``DELETE``/``MERGE`` (a modifying statement, even when a CTE inside it
    uses ``RETURNING``) — the leading ``WITH`` keyword alone cannot tell
    those apart. Tries ``sqlglot`` first; when a trailing clause the dialect
    grammar doesn't model gets in the way (DB2's ``OPTIMIZE FOR``/``WITH
    UR``, ...), falls back to a deterministic scan instead of guessing: a
    CTE's own body always sits inside ``(...)``, so the first keyword found
    outside every paren is the outer statement's real verb, no full parse
    needed — including when that body is dollar-quoted (``$$...$$`` /
    ``$tag$...$tag$``), which ``sqlglot_dialect=None`` doesn't model either
    and whose parentheses would otherwise be counted as real ones. Returns
    ``None`` when neither path finds an answer: empty text, no recognisable
    keyword at all, or a paren/dollar-quote that never closes (the scan
    cannot tell what follows it) — the caller keeps its own default then.
    Guessing wrong is worse than surrendering, so an ambiguous scan returns
    ``None`` rather than a confident wrong keyword. Doesn't know whether the
    outer statement itself returns rows via a clause of its own
    (``RETURNING``/``OUTPUT`` on the outer verb, as opposed to inside a CTE)
    — the sqlglot path above has that same limitation, so this isn't a new
    gap.
    """
    text = strip_leading_sql_comments(statement).lstrip()
    if not text:
        return None
    import sqlglot
    from sqlglot import exp

    try:
        ast = sqlglot.parse_one(text, read=sqlglot_dialect)
    except Exception:
        ast = None
    if ast is not None:
        if isinstance(ast, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
            return "DML"
        if isinstance(ast, (exp.Select, exp.Union)):
            return "QUERY"
    return scan_cte_outer_statement_type(text, quote_pairs=quote_pairs)


def scan_cte_outer_statement_type(
    statement: str, *, quote_pairs: Dict[str, str] = DEFAULT_QUOTE_PAIRS, strict: bool = False
) -> Optional[str]:
    """Classify a CTE's outer verb with the existing quote-aware lexical scan."""
    text = strip_leading_sql_comments(statement).lstrip()
    if not text or (strict and not _cte_scan_is_balanced(text, quote_pairs)):
        return None
    positions = {
        keyword: _find_top_level_keyword(text, keyword, quote_pairs)
        for keyword in (*_CTE_OUTER_DML_KEYWORDS, *_CTE_OUTER_QUERY_KEYWORDS)
    }
    found = {keyword: pos for keyword, pos in positions.items() if pos >= 0}
    if not found:
        return None
    first_keyword = min(found, key=lambda keyword: found[keyword])
    return "DML" if first_keyword in _CTE_OUTER_DML_KEYWORDS else "QUERY"


def _cte_scan_is_balanced(text: str, quote_pairs: Dict[str, str]) -> bool:
    """Refuse a lexical CTE decision when quoted text or parentheses are open."""
    depth = 0
    quote = ""
    i = 0
    while i < len(text):
        if quote:
            i, quote = _skip_quote(text, i, quote)
            continue
        if text.startswith("/*", i):
            end = text.find("*/", i + 2)
            if end < 0 or text.find("/*", i + 2, end) >= 0:
                return False  # Nested comments are dialect-specific; do not guess their extent.
            i = end + 2
            continue
        comment_end = _skip_comment(text, i)
        if comment_end >= 0:
            i = comment_end
            continue
        if text[i] == "$":
            match = _DOLLAR_QUOTE_OPEN_RE.match(text, i)
            if match:
                end = text.find(match.group(0), match.end())
                if end < 0:
                    return False
                i = end + len(match.group(0))
                continue
        char = text[i]
        if char in quote_pairs:
            quote = quote_pairs[char]
        elif char == "(":
            depth += 1
        elif char == ")":
            depth -= 1
            if depth < 0:
                return False
        i += 1
    return not quote and depth == 0


def statement_dml_table(statement: str, *, quirks: Optional["BaseQuirks"] = None) -> str:
    """Table targeted by a DML statement, including ``MERGE INTO``.

    A plugin's statement facts reader answers when it has one. Otherwise the
    dialect-correct sqlglot AST does, and ``Table.sql`` re-emits the
    verbatim-quoted form so the result stays a valid SQL reference for
    downstream raw interpolation. A statement sqlglot cannot parse gives ``""``,
    never a guess from the text.
    """
    if quirks is not None and quirks.supports_statement_facts:
        return quirks.statement_facts(statement).target_sql or ""

    from dblift.core.sql_parser.unread_names import names_unreadable

    sqlglot_dialect = quirks.sqlglot_dialect if quirks is not None else None
    if names_unreadable(statement, sqlglot_dialect):
        return ""
    text = _without_dml_modifiers(strip_leading_sql_comments(statement).lstrip())
    return _sqlglot_dml_table_sql(text, sqlglot_dialect)


def _sqlglot_dml_table_sql(text: str, dialect: Optional[str]) -> str:
    """Dialect-quoted table reference for a DML statement via the sqlglot AST.

    Returns the quoted ``schema.table`` (any table alias and, for a joined
    DELETE naming the FROM-anchor, its JOIN clause stripped) or ``""`` when
    sqlglot cannot parse *text* or it is not DML. Unlike :func:`_sqlglot_table` — which returns the
    bare unquoted name for table *matching* — this preserves quoting because the
    result is interpolated into raw SQL (e.g. a capture ``SELECT ... FROM``).
    """
    import sqlglot
    from sqlglot import exp

    try:
        ast = sqlglot.parse_one(text, read=dialect)
    except Exception:
        return ""
    if ast is None or not isinstance(ast, (exp.Insert, exp.Update, exp.Delete, exp.Merge)):
        return ""
    table = _dml_target_table(ast)
    if table is None:
        return ""
    if table.args.get("only") and not _DML_ONLY.match(text):
        return ""  # ``only.t`` is a schema-qualified name sqlglot read as the ONLY keyword
    if table.args.get("alias") or table.args.get("joins") or table.args.get("only"):
        table = table.copy()
        table.set("alias", None)
        table.set("joins", None)
        table.set("only", None)
    return table.sql(dialect=dialect)


def strip_leading_sql_comments(statement: str, *, strict: bool = False) -> str:
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
            if strict and stripped.find("/*", 2, end) >= 0:
                raise ValueError("Cannot classify nested leading SQL comment")
            text = stripped[end + 2 :]
            continue
        return stripped


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


def _find_top_level_keyword(
    statement: str,
    keyword: str,
    quote_pairs: Dict[str, str],
    start: int = 0,
) -> int:
    """Index of ``keyword`` outside quotes/comments/dollar quotes/parens, or -1."""
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
        if statement[i] == "$":
            dollar_end = _skip_dollar_quote(statement, i)
            if dollar_end >= 0:
                i = dollar_end
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
