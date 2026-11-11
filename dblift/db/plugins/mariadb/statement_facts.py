"""MariaDB statement forms absent from SQLGlot's shared MySQL grammar."""

from __future__ import annotations

from dataclasses import replace
from typing import TYPE_CHECKING

from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader, StatementFacts

if TYPE_CHECKING:
    from sqlglot.tokens import Token

# Options whose keyword may be followed by one of its separator words, then a required number.
_VALUED_OPTIONS = (
    ("INCREMENT", ("BY", "=")),
    ("MINVALUE", ("=",)),
    ("MAXVALUE", ("=",)),
    ("START", ("WITH", "=")),
    ("CACHE", ("=",)),
)


def _alter_sequence_options_are_proven(sql: str, facts: StatementFacts) -> bool:
    """Read the documented MariaDB ALTER SEQUENCE grammar from MySQL-family tokens."""
    tokens = _complete_statement_tokens(sql)
    if tokens is None:
        return False
    reader = _SequenceTokens(tokens)
    if not _names_the_sequence(reader, facts):
        return False

    seen: set[str] = set()
    while reader.more():
        option = _sequence_option(reader)
        if option is None:
            return False
        # MariaDB rejects AS combined with other options (ER_NOT_SUPPORTED_YET).
        if option in seen or "AS" in seen or (option == "AS" and (seen or reader.more())):
            return False
        seen.add(option)
    return bool(seen)


def _complete_statement_tokens(sql: str) -> list[Token] | None:
    """The MySQL-family tokens of *sql* without a closing ``;``, when they cover all of it."""
    from sqlglot.dialects import Dialect
    from sqlglot.errors import TokenError
    from sqlglot.tokens import TokenType

    try:
        tokens: list[Token] = Dialect.get_or_raise("mysql").tokenize(sql)
    except TokenError:
        return None
    if not tokens or any(
        sql[left.end + 1 : right.start].strip(" \t\n\r\f\v")
        for left, right in zip(tokens, tokens[1:])
    ):
        return None
    if sql[: tokens[0].start].strip(" \t\n\r\f\v") or sql[tokens[-1].end + 1 :].strip(
        " \t\n\r\f\v"
    ):
        return None
    if tokens[-1].token_type == TokenType.SEMICOLON:
        tokens.pop()
    return tokens


class _SequenceTokens:
    """A cursor over an ALTER SEQUENCE statement's tokens that consumes what it matches."""

    def __init__(self, tokens: list[Token]):
        """Start at the first token."""
        self.tokens = tokens
        self.at = 0

    def more(self) -> bool:
        """Whether a token remains at the cursor."""
        return self.at < len(self.tokens)

    def word(self, value: str) -> bool:
        """Consume the keyword or punctuation *value* at the cursor."""
        from sqlglot.tokens import TokenType

        punctuation = {
            ".": TokenType.DOT,
            "=": TokenType.EQ,
            "+": TokenType.PLUS,
            "-": TokenType.DASH,
        }
        keyword_types = {
            "ALTER": TokenType.ALTER,
            "SEQUENCE": TokenType.SEQUENCE,
            "EXISTS": TokenType.EXISTS,
            "WITH": TokenType.WITH,
            "CACHE": TokenType.CACHE,
            "START": TokenType.BEGIN,
            "AS": TokenType.ALIAS,
            "TINYINT": TokenType.TINYINT,
            "SMALLINT": TokenType.SMALLINT,
            "MEDIUMINT": TokenType.MEDIUMINT,
            "INT": TokenType.INT,
            "INTEGER": TokenType.INT,
            "BIGINT": TokenType.BIGINT,
            "SIGNED": TokenType.BIGINT,
            "UNSIGNED": TokenType.UBIGINT,
        }
        tokens, at = self.tokens, self.at
        if (
            at < len(tokens)
            and tokens[at].text.upper() == value
            and (
                tokens[at].token_type == punctuation[value]
                if value in punctuation
                else tokens[at].token_type in {TokenType.VAR, keyword_types.get(value)}
            )
        ):
            self.at += 1
            return True
        return False

    def identifier(self) -> str | None:
        """Consume a name at the cursor."""
        from sqlglot.tokens import TokenType

        if self.at < len(self.tokens) and self.tokens[self.at].token_type in {
            TokenType.VAR,
            TokenType.IDENTIFIER,
        }:
            name = str(self.tokens[self.at].text)
            self.at += 1
            return name
        return None

    def number(self) -> bool:
        """Consume an optionally signed number; whether it is a plain decimal integer."""
        from sqlglot.tokens import TokenType

        self.word("+") or self.word("-")
        if self.at < len(self.tokens) and self.tokens[self.at].token_type == TokenType.NUMBER:
            value = str(self.tokens[self.at].text)
            self.at += 1
            return value.isascii() and value.isdigit()
        return False

    def at_number(self) -> bool:
        """Whether the token at the cursor can start a signed number."""
        from sqlglot.tokens import TokenType

        return self.more() and self.tokens[self.at].token_type in {
            TokenType.NUMBER,
            TokenType.PLUS,
            TokenType.DASH,
        }


def _names_the_sequence(reader: _SequenceTokens, facts: StatementFacts) -> bool:
    """Whether the head is ``ALTER SEQUENCE [IF EXISTS] [schema.]name`` naming the facts' object."""
    if not (reader.word("ALTER") and reader.word("SEQUENCE")):
        return False
    if reader.word("IF") and not reader.word("EXISTS"):
        return False
    first = reader.identifier()
    if first is None:
        return False
    if reader.word("."):
        schema, name = first, reader.identifier()
    else:
        schema, name = None, first
    if name is None or len(facts.objects) != 1:
        return False
    return (facts.objects[0].name, facts.objects[0].schema) == (name, schema)


def _sequence_option(reader: _SequenceTokens) -> str | None:
    """The option the tokens at the cursor spell, consumed; ``None`` when they spell none."""
    if reader.word("NO"):
        return (
            "MINVALUE"
            if reader.word("MINVALUE")
            else "MAXVALUE" if reader.word("MAXVALUE") else None
        )
    if reader.word("NOMINVALUE"):
        return "MINVALUE"
    if reader.word("NOMAXVALUE"):
        return "MAXVALUE"
    if reader.word("NOCYCLE") or reader.word("CYCLE"):
        return "CYCLE"
    if reader.word("NOCACHE"):
        return "CACHE"
    if reader.word("AS"):
        return "AS" if _sequence_type(reader) else None
    for option, separators in _VALUED_OPTIONS:
        if reader.word(option):
            any(reader.word(separator) for separator in separators)
            return option if reader.number() else None
    if reader.word("RESTART"):
        return "RESTART" if _restart_value(reader) else None
    return None


def _sequence_type(reader: _SequenceTokens) -> bool:
    """Consume ``AS``'s integer type and optional signedness; whether a type was named."""
    if not any(
        reader.word(type_name)
        for type_name in ("TINYINT", "SMALLINT", "MEDIUMINT", "INT", "INTEGER", "BIGINT")
    ):
        return False
    reader.word("SIGNED") or reader.word("UNSIGNED")
    return True


def _restart_value(reader: _SequenceTokens) -> bool:
    """Consume ``RESTART``'s optional value; whether any value it spells is a number."""
    if (reader.word("WITH") or reader.word("=")) and not reader.number():
        return False
    return not (reader.at_number() and not reader.number())


class MariadbStatementFactsReader(SqlglotStatementFactsReader):
    """Recognize MariaDB's ALTER SEQUENCE without widening MySQL facts."""

    def read(self, sql: str) -> StatementFacts:
        """Return typed sequence facts only when the complete MariaDB form is proven."""
        facts = super().read(sql)
        if (
            facts.diagnostic == "sequence: mysql Command is opaque to statement facts"
            and facts.error is None
            and _alter_sequence_options_are_proven(sql, facts)
        ):
            return replace(facts, diagnostic=None)
        return facts
