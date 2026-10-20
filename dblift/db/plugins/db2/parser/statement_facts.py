"""Db2 statement facts read from the leading tokens of a statement."""

from __future__ import annotations

from typing import List, Optional

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.statement_facts import StatementFacts
from dblift.core.sql_parser.tokens import Token, TokenType
from dblift.db.plugins.db2.parser.lexical_spec import DB2_RULES, DB2_SPEC

COLUMNS_UNAVAILABLE = "db2 column-level facts are unavailable: declared columns, constraints and indexed columns are not read"
UNREAD_NAME = "db2 statement holds U+{code:04X}, which the engine may read as part of a name; its objects are not named"
NOT_CLASSIFIED = "db2 {word} statement: not classified"
CLIENT_COMMAND = "db2 client command: not an SQL statement"
NAME_NOT_READ = "db2 {operation} {type}: name not read"
DATA_CHANGE_QUERY = "db2 data-change query: target not named"
SET_INTEGRITY = "db2 SET INTEGRITY: tables not named"

_DDL = frozenset("CREATE ALTER DROP RENAME COMMENT LABEL DECLARE GRANT REVOKE TRUNCATE".split())
_DML = frozenset("INSERT UPDATE DELETE MERGE".split())
_QUERY = frozenset("SELECT WITH VALUES".split())
_TRANSACTION = frozenset("COMMIT ROLLBACK SAVEPOINT RELEASE".split())
_DATA_CHANGE = frozenset("FINAL NEW OLD".split())


def fold_name(token_text: str) -> str:
    """Fold one name part as Db2 does: quoted exact, unquoted to the engine's case."""
    if token_text.startswith('"'):
        return token_text[1:-1].replace('""', '"')
    from dblift.db.plugins.db2.quirks import Db2Quirks

    return token_text.upper() if Db2Quirks.unquoted_identifier_case == "uppercase" else token_text


def _kind(word: str) -> str:
    if word in _DDL:
        return "DDL"
    if word in _DML:
        return "DML"
    return "QUERY" if word in _QUERY else "UNKNOWN"


def _opaque(operation: str, kind: str, diagnostic: str) -> StatementFacts:
    return StatementFacts(operation, kind, diagnostic=diagnostic)


def _words(tokens: List[Token]) -> List[Token]:
    """The tokens that are not comments, without a trailing terminator."""
    words = [t for t in tokens if t.type not in (TokenType.COMMENT, TokenType.EOF)]
    while words and words[-1].type is TokenType.SYMBOL and words[-1].text == ";":
        words.pop()
    return words


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
        try:
            tokens = LexicalTokenizer(sql, spec=self.spec).tokenize()
        except (UnsafeStatementSplitError, UnsupportedMetaCommandError) as exc:
            first = sql.split()[0].upper() if sql.split() else "UNKNOWN"
            return StatementFacts(
                first, _kind(first), error=f"db2 statement could not be tokenized: {exc}"
            )
        words = _words(tokens)
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
            if any(a in _DATA_CHANGE and b == "TABLE" for a, b in zip(ups, ups[1:])):
                return _opaque(first, kind, DATA_CHANGE_QUERY)
            return StatementFacts(first, kind)
        return _opaque(first, kind, NOT_CLASSIFIED.format(word=first))
