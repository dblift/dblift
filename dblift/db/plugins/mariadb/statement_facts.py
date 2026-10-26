"""MariaDB statement forms absent from SQLGlot's shared MySQL grammar."""

from __future__ import annotations

from dataclasses import replace

from sqlglot.dialects import Dialect
from sqlglot.errors import TokenError
from sqlglot.tokens import TokenType

from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader, StatementFacts


def _alter_sequence_options_are_proven(sql: str, facts: StatementFacts) -> bool:
    """Read the documented MariaDB ALTER SEQUENCE grammar from MySQL-family tokens."""
    try:
        tokens = Dialect.get_or_raise("mysql").tokenize(sql)
    except TokenError:
        return False
    if not tokens or any(
        sql[left.end + 1 : right.start].strip(" \t\n\r\f\v")
        for left, right in zip(tokens, tokens[1:])
    ):
        return False
    if sql[: tokens[0].start].strip(" \t\n\r\f\v") or sql[tokens[-1].end + 1 :].strip(
        " \t\n\r\f\v"
    ):
        return False
    if tokens[-1].token_type == TokenType.SEMICOLON:
        tokens.pop()
    at = 0

    def word(value: str) -> bool:
        nonlocal at
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
        if (
            at < len(tokens)
            and tokens[at].text.upper() == value
            and (
                tokens[at].token_type == punctuation[value]
                if value in punctuation
                else tokens[at].token_type in {TokenType.VAR, keyword_types.get(value)}
            )
        ):
            at += 1
            return True
        return False

    def identifier() -> str | None:
        nonlocal at
        if at < len(tokens) and tokens[at].token_type in {
            TokenType.VAR,
            TokenType.IDENTIFIER,
        }:
            name = str(tokens[at].text)
            at += 1
            return name
        return None

    def number() -> bool:
        nonlocal at
        word("+") or word("-")
        if at < len(tokens) and tokens[at].token_type == TokenType.NUMBER:
            value = str(tokens[at].text)
            at += 1
            return value.isascii() and value.isdigit()
        return False

    if not (word("ALTER") and word("SEQUENCE")):
        return False
    if word("IF") and not word("EXISTS"):
        return False
    first = identifier()
    if first is None:
        return False
    if word("."):
        schema, name = first, identifier()
    else:
        schema, name = None, first
    if name is None or len(facts.objects) != 1:
        return False
    if (facts.objects[0].name, facts.objects[0].schema) != (name, schema):
        return False

    seen: set[str] = set()
    while at < len(tokens):
        if word("NO"):
            option = (
                "MINVALUE"
                if word("MINVALUE")
                else "MAXVALUE" if word("MAXVALUE") else "CYCLE" if word("CYCLE") else None
            )
            if option is None:
                return False
        elif word("NOMINVALUE"):
            option = "MINVALUE"
        elif word("NOMAXVALUE"):
            option = "MAXVALUE"
        elif word("NOCYCLE") or word("CYCLE"):
            option = "CYCLE"
        elif word("AS"):
            option = "AS"
            if not any(
                word(type_name)
                for type_name in ("TINYINT", "SMALLINT", "MEDIUMINT", "INT", "INTEGER", "BIGINT")
            ):
                return False
            word("SIGNED") or word("UNSIGNED")
        elif word("INCREMENT"):
            option = "INCREMENT"
            word("BY") or word("=")
            if not number():
                return False
        elif word("MINVALUE"):
            option = "MINVALUE"
            word("=")
            if not number():
                return False
        elif word("MAXVALUE"):
            option = "MAXVALUE"
            word("=")
            if not number():
                return False
        elif word("START"):
            option = "START"
            word("WITH") or word("=")
            if not number():
                return False
        elif word("CACHE"):
            option = "CACHE"
            word("=")
            if not number():
                return False
        elif word("RESTART"):
            option = "RESTART"
            if (word("WITH") or word("=")) and not number():
                return False
            if (
                at < len(tokens)
                and tokens[at].token_type
                in {
                    TokenType.NUMBER,
                    TokenType.PLUS,
                    TokenType.DASH,
                }
                and not number()
            ):
                return False
        else:
            return False
        if option in seen:
            return False
        seen.add(option)
    return bool(seen)


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
