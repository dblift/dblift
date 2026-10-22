"""Db2 statement facts read from the leading tokens of a statement."""

from __future__ import annotations

from dataclasses import dataclass
from typing import FrozenSet, Iterator, List, Optional, Tuple

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES, DB2_SPEC

COLUMNS_UNAVAILABLE = "db2 column-level facts are unavailable: declared columns, constraints and indexed columns are not read"
UNREAD_NAME = "db2 statement holds U+{code:04X}, which the engine may read as part of a name; its objects are not named"
NOT_CLASSIFIED = "db2 {word} statement: not classified"
CLIENT_COMMAND = "db2 client command: not an SQL statement"
UNTERMINATED_IDENTIFIER = (
    "db2 statement holds an unterminated quoted identifier; its objects are not named"
)
NAME_NOT_READ = "db2 {operation} {type}: name not read"
DATA_CHANGE_QUERY = "db2 data-change query: target not named"
SET_INTEGRITY = "db2 SET INTEGRITY: tables not named"
CALL_EFFECTS_UNAVAILABLE = "db2 CALL: procedure effects are not read"

_DDL = frozenset("CREATE ALTER DROP RENAME COMMENT DECLARE GRANT REVOKE TRUNCATE".split())
_DML = frozenset("INSERT UPDATE DELETE MERGE".split())
_QUERY = frozenset("SELECT WITH VALUES".split())
_TRANSACTION = frozenset("COMMIT ROLLBACK SAVEPOINT RELEASE".split())
_DATA_CHANGE = frozenset("FINAL NEW OLD".split())

#: Words that are never a name part.
STOP_WORDS: FrozenSet[str] = frozenset(
    """TO ON IS IN FOR AS LIKE WITH SET USING VALUES FROM WHERE INTO IF RESTRICT IMMEDIATE ONLY
    FOREIGN DATABASE DB CFG SELECT TABLE AUTHORIZATION NOT EXISTS ADD CLONE CASCADE""".split()
)
#: ``clone`` is no Db2 keyword, so a program or index may carry it before ``(``, a trigger timing
#: word or ``ON``; ``add`` and ``cascade`` stay refused (the reserved-word page is not in the repo).
_PROGRAM_STOP_WORDS: FrozenSet[str] = STOP_WORDS - {"CLONE"}
_PROGRAM_FOLLOWERS: FrozenSet[str] = frozenset({"(", "BEFORE", "AFTER", "INSTEAD", "ON"})
_PROGRAM_TYPES = (
    SqlObjectType.FUNCTION,
    SqlObjectType.PROCEDURE,
    SqlObjectType.TRIGGER,
    SqlObjectType.INDEX,
)

#: Words that follow CREATE / ALTER / DROP TABLE|VIEW|FUNCTION|INDEX in a different statement.
SECOND_WORDS: FrozenSet[str] = frozenset({"HIERARCHY", "MAPPING", "EXTENSION"})

_TYPES = {
    "TABLE": SqlObjectType.TABLE,
    "VIEW": SqlObjectType.VIEW,
    "INDEX": SqlObjectType.INDEX,
    "SEQUENCE": SqlObjectType.SEQUENCE,
    "ALIAS": SqlObjectType.SYNONYM,
    "SCHEMA": SqlObjectType.SCHEMA,
    "TRIGGER": SqlObjectType.TRIGGER,
    "PROCEDURE": SqlObjectType.PROCEDURE,
    "FUNCTION": SqlObjectType.FUNCTION,
}
_DML_PREFIX = {
    "INSERT": ("INSERT", "INTO"),
    "UPDATE": ("UPDATE",),
    "DELETE": ("DELETE", "FROM"),
    "MERGE": ("MERGE", "INTO"),
}
_GRANT_TYPES = ("TABLE", "VIEW", "INDEX", "SEQUENCE", "ALIAS", "SCHEMA", "PROCEDURE", "FUNCTION")


@dataclass(frozen=True)
class Head:
    """A statement head: its words, the optional word groups it skips, and what it names."""

    words: Tuple[str, ...]
    operation: str
    kind: str
    object_type: SqlObjectType
    role: str
    optional: Tuple[Tuple[str, ...], ...] = ()
    max_parts: int = 2
    column_facts: bool = False
    follow: Tuple[str, ...] = ()


def _heads() -> Tuple[Head, ...]:
    or_replace, if_exists = ("OR", "REPLACE"), ("IF", "EXISTS")
    heads = [
        Head(
            ("CREATE", "TABLE"),
            "CREATE",
            "DDL",
            SqlObjectType.TABLE,
            "created",
            (("GLOBAL", "TEMPORARY"), ("IF", "NOT", "EXISTS")),
            column_facts=True,
        ),
        Head(
            ("DECLARE", "GLOBAL", "TEMPORARY", "TABLE"),
            "DECLARE",
            "DDL",
            SqlObjectType.TABLE,
            "created",
            column_facts=True,
        ),
        Head(("CREATE", "VIEW"), "CREATE", "DDL", SqlObjectType.VIEW, "created", (or_replace,)),
        Head(
            ("CREATE", "INDEX"),
            "CREATE",
            "DDL",
            SqlObjectType.INDEX,
            "created",
            (("UNIQUE",),),
            column_facts=True,
        ),
        Head(("CREATE", "SCHEMA"), "CREATE", "DDL", SqlObjectType.SCHEMA, "created", max_parts=1),
    ]
    for word in ("SEQUENCE", "ALIAS", "TRIGGER", "PROCEDURE", "FUNCTION"):
        heads.append(
            Head(("CREATE", word), "CREATE", "DDL", _TYPES[word], "created", (or_replace,))
        )
    for word in ("TABLE", "VIEW", "SEQUENCE", "TRIGGER", "PROCEDURE", "FUNCTION", "SCHEMA"):
        heads.append(
            Head(
                ("ALTER", word),
                "ALTER",
                "DDL",
                _TYPES[word],
                "altered",
                max_parts=1 if word == "SCHEMA" else 2,
                column_facts=word == "TABLE",
            )
        )
    for word, otype in _TYPES.items():
        heads.append(
            Head(
                ("DROP", word),
                "DROP",
                "DDL",
                otype,
                "dropped",
                (if_exists,),
                max_parts=1 if word == "SCHEMA" else 2,
            )
        )
    heads.append(
        Head(("RENAME", "INDEX"), "RENAME", "DDL", SqlObjectType.INDEX, "altered", follow=("TO",))
    )
    heads.append(
        Head(
            ("RENAME",),
            "RENAME",
            "DDL",
            SqlObjectType.TABLE,
            "altered",
            (("TABLE",),),
            follow=("TO",),
        )
    )
    for word, otype in _TYPES.items():
        heads.append(
            Head(
                ("COMMENT", "ON", word),
                "COMMENT",
                "DDL",
                otype,
                "altered",
                max_parts=1 if word == "SCHEMA" else 2,
                follow=("IS",),
            )
        )
    heads.append(
        Head(
            ("COMMENT", "ON", "COLUMN"),
            "COMMENT",
            "DDL",
            SqlObjectType.TABLE,
            "altered",
            max_parts=3,
            follow=("IS",),
        )
    )
    heads.append(
        Head(("TRUNCATE",), "TRUNCATE", "DDL", SqlObjectType.TABLE, "altered", (("TABLE",),))
    )
    for verb in ("GRANT", "REVOKE"):
        heads.append(Head((verb,), verb, "DDL", SqlObjectType.TABLE, "referenced"))
    heads.append(Head(("LOCK", "TABLE"), "LOCK", "UNKNOWN", SqlObjectType.TABLE, "referenced"))
    heads.append(Head(("CALL",), "CALL", "UNKNOWN", SqlObjectType.PROCEDURE, "referenced"))
    return tuple(heads)


HEADS = _heads()


def fold_name(token_text: str) -> str:
    """Fold one name part as Db2 does: quoted exact, unquoted to the engine's case."""
    if token_text.startswith('"'):
        return _unquote(token_text)
    from dblift.db.plugins.db2.quirks import Db2Quirks

    return token_text.upper() if Db2Quirks.unquoted_identifier_case == "uppercase" else token_text


def _unquote(text: str) -> str:
    return text[1:-1].replace('""', '"') if text.startswith('"') else text


def _opaque(operation: str, kind: str, diagnostic: str) -> StatementFacts:
    return StatementFacts(operation, kind, diagnostic=diagnostic)


def _unterminated(operation: str, kind: str) -> StatementFacts:
    return StatementFacts(operation, kind, error=UNTERMINATED_IDENTIFIER)


def _kind(word: str) -> str:
    if word in _DDL:
        return "DDL"
    if word in _DML:
        return "DML"
    return "QUERY" if word in _QUERY else "UNKNOWN"


def _words(tokens: List[Token]) -> List[Token]:
    """The tokens that are not comments, without a trailing terminator."""
    words = [t for t in tokens if t.type not in (TokenType.COMMENT, TokenType.EOF)]
    while words and words[-1].type is TokenType.SYMBOL and words[-1].text == ";":
        words.pop()
    return words


def _skip_optional(ups: List[str], at: int, groups: Tuple[Tuple[str, ...], ...]) -> int:
    moved = True
    while moved:
        moved = False
        for group in groups:
            if tuple(ups[at : at + len(group)]) == group:
                at += len(group)
                moved = True
    return at


def _match(ups: List[str], head: Head) -> Optional[int]:
    """The index after the head's words, or None when the statement does not start with them."""
    at = 0
    for word in head.words:
        at = _skip_optional(ups, at, head.optional) if at else 0
        if ups[at : at + 1] != [word]:
            return None
        at += 1
    return _skip_optional(ups, at, head.optional)


def _is_part(token: Token) -> bool:
    return token.type in (TokenType.KEYWORD, TokenType.IDENTIFIER)


def _name_run(words: List[Token], at: int) -> Tuple[List[Token], int]:
    """The word and quoted-identifier tokens joined by dots from ``at``, and the index after them."""
    i = at
    run: List[Token] = []
    while i < len(words) and _is_part(words[i]):
        run.append(words[i])
        i += 1
        if i + 1 < len(words) and _is_symbol(words[i], ".") and _is_part(words[i + 1]):
            i += 1
        else:
            break
    return run, i


def _read_name(
    words: List[Token], at: int, max_parts: int, stop: FrozenSet[str] = STOP_WORDS
) -> Optional[Tuple[Tuple[str, ...], int, int]]:
    """The folded parts of the name at ``at``, its source offset and the index after it."""
    run, i = _name_run(words, at)
    if not run or len(run) > max_parts or (i < len(words) and _is_symbol(words[i], ".")):
        return None
    if any(t.text == '""' for t in run):
        return None
    if any(t.type is TokenType.KEYWORD and t.text.upper() in stop for t in run):
        return None
    return tuple(fold_name(t.text) for t in run), run[0].pos, i


def _skip_group(words: List[Token], at: int) -> int:
    """Skip one parenthesised group starting at ``at``, if any."""
    if at < len(words) and _is_symbol(words[at], "("):
        for i, token, depth in _walk(words, at):
            if depth == 0 and _is_symbol(token, ")"):
                return i + 1
    return at


def _object(parts: Tuple[str, ...], otype: SqlObjectType, role: str) -> NamedObject:
    return NamedObject(parts[-1], otype, role, parts[-2] if len(parts) > 1 else None)


def _head_facts(
    words: List[Token], ups: List[str], head: Head, at: int
) -> Tuple[Optional[StatementFacts], int]:
    """The facts of a DDL head and the index its name reading reached (None when unreadable)."""
    otype, grants = head.object_type, head.operation in ("GRANT", "REVOKE")
    if grants:
        on = _depth0(words, 0, "ON")
        if on is None:
            return None, at
        at = on + 1
        if ups[at : at + 1] and ups[at] in _GRANT_TYPES:
            otype, at = _TYPES[ups[at]], at + 1
    name = _read_name(words, at, head.max_parts)
    if name is None and otype in _PROGRAM_TYPES:
        relaxed = _read_name(words, at, head.max_parts, _PROGRAM_STOP_WORDS)
        if (
            relaxed is not None
            and relaxed[2] < len(words)
            and words[relaxed[2]].text.upper() in _PROGRAM_FOLLOWERS
        ):
            name = relaxed
    if name is None:
        return None, at
    parts, _, end = name
    if head.operation in ("CREATE", "ALTER", "DROP") and _second_word_taken(words, ups, at, end):
        return None, end
    if not _may_follow(words, ups, head, end):
        return None, end
    if head.words[-1] == "COLUMN":
        parts = parts[:-1]
    if not parts:
        return None, end
    if grants and ups[end : end + 1] not in (["TO"], ["FROM"]):
        return None, end
    after = _skip_group(words, end)
    if head.follow and ups[after : after + 1] != list(head.follow):
        return None, end
    objects = [_object(parts, otype, head.role)]
    indexed_table = None
    if head.words == ("CREATE", "INDEX"):
        if ups[end : end + 1] != ["ON"]:
            return None, end
        table = _read_name(words, end + 1, 2)
        if table is None:
            return None, end + 1
        end = table[2]
        indexed_table = ".".join(table[0])
        objects.append(_object(table[0], SqlObjectType.TABLE, "referenced"))
    diagnostic = (
        CALL_EFFECTS_UNAVAILABLE
        if head.operation == "CALL"
        else COLUMNS_UNAVAILABLE if head.column_facts else None
    )
    return (
        StatementFacts(
            head.operation,
            head.kind,
            tuple(objects),
            indexed_table=indexed_table,
            diagnostic=diagnostic,
        ),
        end,
    )


def _may_follow(words: List[Token], ups: List[str], head: Head, end: int) -> bool:
    """Whether what follows the name is something the head's form allows after a name."""
    if end >= len(words):
        return True
    if head.operation == "DROP":
        return _is_symbol(words[end], "(") or ups[end] in ("RESTRICT", "CASCADE")
    return words[end].type is not TokenType.SYMBOL or words[end].text == "("


def _is_unterminated(token: Token) -> bool:
    """Whether a quoted identifier lacks its closing quote (a doubled quote does not close it)."""
    text = token.text
    return (
        token.type is TokenType.IDENTIFIER
        and text.startswith('"')
        and (len(text) < 2 or not text.endswith('"') or '"' in text[1:-1].replace('""', ""))
    )


def _second_word_taken(words: List[Token], ups: List[str], at: int, end: int) -> bool:
    """Whether the name is HIERARCHY / MAPPING / EXTENSION followed by the real name."""
    if ups[at] not in SECOND_WORDS or end >= len(words) or not _is_part(words[end]):
        return False
    return not (ups[0] == "DROP" and ups[end] in ("RESTRICT", "CASCADE"))


def _is_symbol(token: Token, text: str) -> bool:
    return token.type is TokenType.SYMBOL and token.text == text


def _walk(words: List[Token], start: int) -> Iterator[Tuple[int, Token, int]]:
    """Each token from ``start`` with the parenthesis depth it sits at (a group's own parentheses sit outside it)."""
    depth = 0
    for i in range(start, len(words)):
        if _is_symbol(words[i], ")"):
            depth -= 1
        yield i, words[i], depth
        if _is_symbol(words[i], "("):
            depth += 1


def _depth0(words: List[Token], start: int, word: str) -> Optional[int]:
    """Index of the first keyword ``word`` at parenthesis depth 0 from ``start``."""
    for i, token, depth in _walk(words, start):
        if depth == 0 and token.type is TokenType.KEYWORD and token.text.upper() == word:
            return i
    return None


def _predicate(sql: str, words: List[Token], where: int) -> str:
    """The source text after the WHERE at ``where``, up to the last non-comment token."""
    return sql[words[where + 1].pos : words[-1].pos + len(words[-1].text)].strip()


def _value_end(words: List[Token], start: int) -> int:
    """Index of the depth-0 comma, WHERE or WHEN (outside CASE ... END) that ends the value at ``start``."""
    cases = 0
    for i, token, depth in _walk(words, start):
        up = token.text.upper() if token.type is TokenType.KEYWORD else ""
        if depth:
            continue
        if up == "CASE":
            cases += 1
        elif up == "END":
            cases -= 1
        elif _is_symbol(token, ",") or (not cases and up in ("WHERE", "WHEN")):
            return i
    return len(words)


def _assigned_columns(words: List[Token], start: int) -> Tuple[str, ...]:
    """The columns on the left of each depth-0 assignment of a SET list starting at ``start``."""
    columns: List[str] = []
    i, n = start, len(words)
    while i < n:
        grouped = _is_symbol(words[i], "(")
        i += grouped
        while i < n:
            run, i = _name_run(words, i)
            if run:
                columns.append(_unquote(run[-1].text))
            if not (grouped and i < n and _is_symbol(words[i], ",")):
                break
            i += 1
        if grouped:
            i += i < n and _is_symbol(words[i], ")")
        if not (i < n and _is_symbol(words[i], "=")):
            break
        i = _value_end(words, i + 1)
        if i < n and _is_symbol(words[i], ","):
            i += 1
        else:
            break
    return tuple(columns)


def _merge_events(words: List[Token], start: int) -> frozenset:
    """The UPDATE / INSERT / DELETE words that follow a depth-0 THEN."""
    events = set()
    at = _depth0(words, start, "THEN")
    while at is not None:
        following = words[at + 1].text.upper() if at + 1 < len(words) else ""
        if following in ("UPDATE", "INSERT", "DELETE"):
            events.add(following)
        at = _depth0(words, at + 1, "THEN")
    return frozenset(events)


def _merge_columns(words: List[Token], start: int) -> Tuple[str, ...]:
    columns: Tuple[str, ...] = ()
    at = _depth0(words, start, "UPDATE")
    while at is not None:
        if at + 1 < len(words) and words[at + 1].text.upper() == "SET":
            columns += _assigned_columns(words, at + 2)
        at = _depth0(words, at + 1, "UPDATE")
    return columns


def _read_dml(sql: str, words: List[Token], ups: List[str], first: str) -> StatementFacts:
    """Facts of INSERT / UPDATE / DELETE / MERGE with a plain table name, else opaque."""
    unread = _opaque(first, "DML", NAME_NOT_READ.format(operation=first, type="TABLE"))
    prefix = _DML_PREFIX[first]
    name = _read_name(words, len(prefix), 2) if tuple(ups[: len(prefix)]) == prefix else None
    if name is None:
        return unread
    parts, start, after = name
    n = len(words)
    if first != "INSERT":
        as_alias = ups[after : after + 1] == ["AS"]
        after += as_alias
        if after < n and _is_part(words[after]) and ups[after] not in STOP_WORDS:
            after += 1
        elif as_alias:
            return unread
    word = ups[after] if after < n else ""
    allowed = {
        "INSERT": word in ("VALUES", "SELECT", "WITH")
        or after == n
        or _is_symbol(words[after], "("),
        "UPDATE": word == "SET",
        "DELETE": after == n or word in ("WHERE", "WITH"),
        "MERGE": word == "USING",
    }
    where = _depth0(words, after, "WHERE") if first in ("UPDATE", "DELETE") else None
    if not allowed[first] or (where is not None and where + 1 >= n):
        return unread
    last = words[after - 1]
    return StatementFacts(
        first,
        "DML",
        (_object(parts, SqlObjectType.TABLE, "altered"),),
        target=".".join(parts),
        predicate=_predicate(sql, words, where) if where is not None else None,
        affected_columns=(
            _assigned_columns(words, after + 1)
            if first == "UPDATE"
            else _merge_columns(words, after) if first == "MERGE" else ()
        ),
        events=_merge_events(words, after) if first == "MERGE" else frozenset({first}),
        target_sql=sql[start : last.pos + len(last.text)],
    )


def _unread_character(sql: str, words: List[Token], head_end: int) -> Optional[int]:
    """Offset of the first non-ASCII character the engine may read as part of a head name."""
    for token in words[:head_end]:
        if token.type is TokenType.SYMBOL:
            for k, char in enumerate(token.text):
                if ord(char) > 127:
                    return token.pos + k
        elif token.type is TokenType.KEYWORD:
            for at in (token.pos - 1, token.pos + len(token.text)):
                if 0 <= at < len(sql) and ord(sql[at]) > 127:
                    return at
    return None


def _head_end(words: List[Token], at: int) -> int:
    """The head words and the next eight tokens, cut after the first opening parenthesis."""
    end = min(len(words), at + 8)
    for i, token in enumerate(words[:end]):
        if token.type is TokenType.SYMBOL and token.text == "(":
            return i + 1
    return end


def _holds_data_change(ups: List[str]) -> bool:
    """Whether the tokens hold FINAL TABLE, NEW TABLE or OLD TABLE."""
    return any(a in _DATA_CHANGE and b == "TABLE" for a, b in zip(ups, ups[1:]))


def _is_client_command(ups: List[str]) -> bool:
    if ups[0] in DB2_RULES.command_words:
        return True
    return any(tuple(ups[: len(phrase)]) == phrase for phrase in DB2_RULES.command_phrases)


class Db2StatementFactsReader:
    """Classify a Db2 statement from its head and name the objects it targets."""

    def __init__(self, dialect: Optional[str], spec: Optional[LexicalSpec] = None):
        """Bind the Db2 lexical spec unless the plugin supplies another."""
        self.dialect = dialect
        self.spec = spec or DB2_SPEC

    def read(self, sql: str) -> StatementFacts:
        """Read one already-split statement."""
        # The tokenizer drops a leading BOM, which would shift every token offset.
        sql = sql[1:] if sql.startswith("\ufeff") else sql
        words = _words(LexicalTokenizer(sql, spec=self.spec).tokenize())
        if not words:
            return _opaque("UNKNOWN", "UNKNOWN", NOT_CLASSIFIED.format(word="UNKNOWN"))
        ups = [t.text.upper() if t.type is TokenType.KEYWORD else "" for t in words]
        first = ups[0] or "UNKNOWN"
        kind = _kind(first)
        if ups[0] and _is_client_command(ups):
            return _opaque(first, kind, CLIENT_COMMAND)
        if first in _TRANSACTION:
            return StatementFacts(first, "UNKNOWN")
        if first == "SET":
            if ups[1:2] == ["INTEGRITY"]:
                return _opaque(first, "UNKNOWN", SET_INTEGRITY)
            return StatementFacts(first, "UNKNOWN")
        if first in _QUERY:
            if _holds_data_change(ups):
                return _opaque(first, kind, DATA_CHANGE_QUERY)
            return StatementFacts(first, kind)
        for head in HEADS:
            at = _match(ups, head)
            if at is None:
                continue
            facts, reached = _head_facts(words, ups, head, at)
            end = reached + 1 if head.operation in ("GRANT", "REVOKE") else _head_end(words, at)
            if any(_is_unterminated(t) for t in words[:end]):
                return _unterminated(head.operation, head.kind)
            char = _unread_character(sql, words, end)
            if char is not None:
                return _opaque(head.operation, head.kind, UNREAD_NAME.format(code=ord(sql[char])))
            if facts is not None:
                return facts
            return _opaque(
                head.operation,
                head.kind,
                NAME_NOT_READ.format(operation=head.operation, type=head.object_type.name),
            )
        prefix = _DML_PREFIX.get(first)
        if prefix and tuple(ups[: len(prefix)]) == prefix:
            window = _head_end(words, len(prefix))
            if any(_is_unterminated(t) for t in words[:window]):
                return _unterminated(first, kind)
            char = _unread_character(sql, words, window)
            if char is not None:
                return _opaque(first, kind, UNREAD_NAME.format(code=ord(sql[char])))
            if _holds_data_change(ups):
                return _opaque(first, kind, DATA_CHANGE_QUERY)
            return _read_dml(sql, words, ups, first)
        return _opaque(first, kind, NOT_CLASSIFIED.format(word=first))


class Db2FactsParser(StatementFactsParser):
    """The generic statement-facts parser, bound to the Db2 plugin."""

    def __init__(self) -> None:
        """Bind the Db2 plugin's spec and facts reader."""
        from dblift.db.provider_registry import ProviderRegistry

        super().__init__(ProviderRegistry.get_quirks("db2"))
