"""One lexical entry point for splitting and comment masking."""

from typing import List

from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_statement_parser import LexicalStatementParser
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.statement import Statement


class LexicalEngine:
    """Select rules once; never retry through a second implementation."""

    def __init__(self, spec: LexicalSpec):
        """Bind the immutable plugin specification."""
        self.spec = spec

    def _parser(self, script: str) -> LexicalStatementParser:
        tokens = LexicalTokenizer(script, spec=self.spec).tokenize()
        return LexicalStatementParser(tokens, source=script, spec=self.spec)

    def split(self, script: str, *, include_comment_only: bool = False) -> List[Statement]:
        """Return source-positioned execution units and analysis projections."""
        return self._parser(script).split(include_comment_only=include_comment_only)

    def split_statements(self, script: str) -> List[str]:
        """Return execution text, preserving the established terminator contract."""
        return self._parser(script).split_statements()

    def split_for_analysis(self, script: str) -> List[str]:
        """Include SQLite comment-only segments in the shared scan's projection."""
        return [record.text for record in self.split(script, include_comment_only=True)]

    def blank_comments(self, script: str) -> str:
        """Replace each scanned comment with a space, preserving quoted text."""
        tokenizer = LexicalTokenizer(script, spec=self.spec)
        tokens = tokenizer.tokenize()
        LexicalStatementParser(tokens, source=script, spec=self.spec).split()
        parts: List[str] = []
        last = 0
        for start, end in tokenizer.comments:
            parts.extend((script[last:start], " "))
            last = end
        parts.append(script[last:])
        masked = "".join(parts)
        return masked[1:] if self.spec.sqlite_shell and script.startswith("\ufeff") else masked
