"""Keep string literals out of failure messages: identify a statement, mask its text."""

import re
import warnings
from typing import List, Optional, Tuple, Type

from dblift.core.sql_parser.base_tokenizer import BaseTokenizer
from dblift.core.sql_parser.tokens import Token, TokenType

_MAX_IDENTITY_LENGTH = 80
_MASKED_LITERAL = "'?'"
# Words that lead a statement before its target; the first other word is the target.
_LEADING_WORDS = frozenset("""
    INSERT UPDATE DELETE MERGE REPLACE UPSERT SELECT CREATE ALTER DROP TRUNCATE RENAME GRANT
    REVOKE COMMENT CALL EXEC EXECUTE SET COPY LOAD ANALYZE VACUUM REINDEX REFRESH USE DO
    INTO FROM ON OR IF NOT EXISTS ONLY UNIQUE TEMP TEMPORARY GLOBAL LOCAL MATERIALIZED
    UNLOGGED CONCURRENTLY CLUSTERED NONCLUSTERED FULLTEXT
    TABLE VIEW INDEX USER ROLE SCHEMA DATABASE SEQUENCE FUNCTION PROCEDURE TRIGGER TYPE
    EXTENSION COLUMN CONSTRAINT PACKAGE BODY SYNONYM LOGIN DOMAIN TABLESPACE
    ALL PRIVILEGES USAGE REFERENCES CONNECT
    """.split())
_PRINCIPALS = frozenset(("USER", "ROLE", "LOGIN", "GROUP"))
_NAME_SYMBOLS = frozenset('."[]`')
_WORD_TYPES = (TokenType.IDENTIFIER, TokenType.KEYWORD)


def _is_name_part(token: Token) -> bool:
    return token.type in _WORD_TYPES or token.text in _NAME_SYMBOLS


def describe_statement(sql: str, dialect: Optional[str] = None) -> str:
    """Leading verb words and the first object name of *sql*, nothing after it.

    ``CREATE USER bob IDENTIFIED BY pw`` gives ``CREATE USER bob``. Falls back
    to the first word when the text cannot be tokenized.
    """
    try:
        tokens = _tokens(sql, dialect)
        words: List[str] = []
        i = 0
        while i < len(tokens) and (
            tokens[i].text == ","
            or tokens[i].type in _WORD_TYPES
            and (not words or tokens[i].text.upper() in _LEADING_WORDS)
        ):
            words.append(tokens[i].text)
            i += 1
        if i < len(tokens) and (tokens[i].type in _WORD_TYPES or tokens[i].text in _NAME_SYMBOLS):
            end = tokens[i].pos + len(tokens[i].text)
            j = i + 1
            while j < len(tokens) and tokens[j].pos == end and _is_name_part(tokens[j]):
                end = tokens[j].pos + len(tokens[j].text)
                j += 1
            words.append(sql[tokens[i].pos : end])
        identity = " ".join(words).replace(" ,", ",")
    except Exception:  # fail closed: the first word only
        match = re.match(r"\s*\w+", sql)
        identity = match.group().strip() if match else ""
    return identity[:_MAX_IDENTITY_LENGTH]


def _tokens(sql: str, dialect: Optional[str]) -> List[Token]:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        tokens = _dialect_tokenizer(dialect)(sql).tokenize()
    return [t for t in tokens if t.type not in (TokenType.COMMENT, TokenType.EOF)]


def _dialect_tokenizer(dialect: Optional[str]) -> Type[BaseTokenizer]:
    if dialect:
        try:
            from dblift.core.sql_parser.parser_factory import SqlParserFactory

            parser = SqlParserFactory(dialect, parser_type="regex").get_parser()
            tokenizer = getattr(parser, "tokenizer_class", None)
            if isinstance(tokenizer, type) and issubclass(tokenizer, BaseTokenizer):
                return tokenizer
        except Exception:  # the generic tokenizer still masks
            pass
    return BaseTokenizer


def _closing_quote(sql: str, start: int) -> int:
    """End of the double-quoted name opening at *start*; ``""`` is an escaped quote."""
    i = start + 1
    while True:
        i = sql.index('"', i)  # ValueError when unterminated: the caller fails closed
        if sql[i + 1 : i + 2] != '"':
            return i + 1
        i += 2


def _credential_span(
    sql: str, tokens: List[Token], k: int, principal_ddl: bool
) -> Optional[Tuple[int, int]]:
    """Span of the unquoted value after ``IDENTIFIED BY`` (or ``PASSWORD`` in principal DDL)."""
    word = tokens[k].text.upper()
    after_identified = word == "BY" and k and tokens[k - 1].text.upper() == "IDENTIFIED"
    if not (after_identified or (word == "PASSWORD" and principal_ddl)):
        return None
    i = k + 1
    if i < len(tokens) and tokens[i].text == "=":
        i += 1
    if i >= len(tokens) or not _is_name_part(tokens[i]):
        return None
    start = tokens[i].pos
    if sql[start] == '"':
        return start, _closing_quote(sql, start)
    end = start + len(tokens[i].text)
    j = i + 1
    while j < len(tokens) and tokens[j].pos == end and _is_name_part(tokens[j]):
        end = tokens[j].pos + len(tokens[j].text)
        j += 1
    return start, end


def mask_string_literals(sql: str, dialect: Optional[str] = None) -> str:
    """Replace string literals and the value after ``IDENTIFIED BY`` / ``PASSWORD`` with ``?``.

    Keeps the statement's shape. Falls back to :func:`describe_statement` when
    the text cannot be tokenized, so a failure to mask never leaks the values.
    """
    try:
        tokens = _tokens(sql, dialect)
        spans = []
        principal_ddl = (
            len(tokens) > 1
            and tokens[0].text.upper() in ("CREATE", "ALTER")
            and tokens[1].text.upper() in _PRINCIPALS
        )
        for k, token in enumerate(tokens):
            if token.type in (TokenType.STRING, TokenType.COPY_DATA):
                spans.append((token.pos, token.pos + len(token.text), _MASKED_LITERAL))
                if sql[spans[-1][0] : spans[-1][1]] != token.text:
                    return describe_statement(sql, dialect)
            else:
                credential = _credential_span(sql, tokens, k, principal_ddl)
                if credential:
                    spans.append((*credential, "?"))
        parts, last = [], 0
        for start, end, mask in sorted(spans):
            if start < last:
                continue
            parts += [sql[last:start], mask]
            last = end
        return "".join(parts) + sql[last:]
    except Exception:  # fail closed: identity only
        return describe_statement(sql, dialect)
