"""YugabyteDB statement facts that account for its index-head modifier."""

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader, StatementFacts
from dblift.core.sql_parser.tokens import Token, TokenType


def _next_head_token(tokenizer: LexicalTokenizer) -> Token | None:
    while tokenizer.pos < len(tokenizer.sql):
        token = tokenizer._next_token()
        if token is not None and token.type is not TokenType.COMMENT:
            return token
    return None


def _word(token: Token | None, text: str) -> bool:
    return (
        token is not None
        and token.type in (TokenType.KEYWORD, TokenType.IDENTIFIER)
        and token.text.upper() == text
    )


class YugabyteStatementFactsReader(SqlglotStatementFactsReader):
    """Keep unread NONCONCURRENTLY index heads opaque for this engine."""

    def read(self, sql: str) -> StatementFacts:
        """Read AST facts, then refuse index identities behind this modifier."""
        facts = super().read(sql)
        if facts.operation != "CREATE" or facts.kind != "DDL" or facts.opaque:
            return facts
        if not any(
            obj.type is SqlObjectType.INDEX and obj.role == "created" for obj in facts.objects
        ):
            return facts

        assert self.spec is not None
        tokenizer = LexicalTokenizer(sql, spec=self.spec)
        if not _word(_next_head_token(tokenizer), "CREATE"):
            return facts
        token = _next_head_token(tokenizer)
        if _word(token, "UNIQUE"):
            token = _next_head_token(tokenizer)
        if not _word(token, "INDEX") or not _word(_next_head_token(tokenizer), "NONCONCURRENTLY"):
            return facts
        return StatementFacts(
            "CREATE", "DDL", diagnostic="YugabyteDB NONCONCURRENTLY index head is not read"
        )
