"""One lexical entry point for splitting and comment masking."""

import logging
from typing import List

from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_statement_parser import LexicalStatementParser
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.statement import Statement

logger = logging.getLogger(__name__)


class LexicalEngine:
    """Select rules once; never retry through a second implementation."""

    def __init__(self, spec: LexicalSpec):
        """Bind the immutable plugin specification."""
        self.spec = spec

    def _parser(self, script: str) -> LexicalStatementParser:
        tokenizer = LexicalTokenizer(script, spec=self.spec)
        tokens = tokenizer.tokenize()
        return LexicalStatementParser(
            tokens, source=script, spec=self.spec, comments=tokenizer.comments
        )

    @staticmethod
    def _report(parser: LexicalStatementParser) -> None:
        for message in parser.warnings:
            logger.warning(message)
        for message in parser.notices:
            logger.info(message)

    def split(self, script: str, *, include_comment_only: bool = False) -> List[Statement]:
        """Return source-positioned execution units and analysis projections."""
        parser = self._parser(script)
        records = parser.split(include_comment_only=include_comment_only)
        self._report(parser)
        return records

    def split_statements(self, script: str) -> List[str]:
        """Return execution text, preserving the established terminator contract."""
        parser = self._parser(script)
        statements = parser.split_statements()
        self._report(parser)
        return statements

    def split_for_analysis(self, script: str) -> List[str]:
        """Include SQLite comment-only segments in the shared scan's projection."""
        return [record.text for record in self.split(script, include_comment_only=True)]

    def blank_comments(self, script: str) -> str:
        """Replace each scanned comment with a space, preserving quoted text."""
        tokenizer = LexicalTokenizer(script, spec=self.spec)
        tokens = tokenizer.tokenize()
        LexicalStatementParser(
            tokens, source=script, spec=self.spec, comments=tokenizer.comments
        ).split()
        parts: List[str] = []
        last = 0
        for start, end in tokenizer.comments:
            parts.extend((script[last:start], " "))
            last = end
        parts.append(script[last:])
        masked = "".join(parts)
        return masked[1:] if self.spec.sqlite_shell and script.startswith("\ufeff") else masked
