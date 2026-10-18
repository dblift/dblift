"""One lexical entry point for splitting and comment masking."""

import logging
from typing import List

from dblift.core.sql_parser.lexical_spec import LexicalSpec
from dblift.core.sql_parser.lexical_statement_parser import LexicalStatementParser
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.segment_script import SegmentScript
from dblift.core.sql_parser.statement import Statement, analysis_sql

logger = logging.getLogger(__name__)


class LexicalEngine:
    """Select rules once; never retry through a second implementation."""

    def __init__(self, spec: LexicalSpec):
        """Bind the immutable plugin specification."""
        self.spec = spec

    def _parser(self, script: str) -> LexicalStatementParser:
        tokenizer = LexicalTokenizer(script, spec=self.spec)
        tokens = tokenizer.tokenize()
        records = tokenizer.assemble(tokens) if self.spec.terminator_script is not None else None
        return LexicalStatementParser(
            tokens,
            source=script,
            spec=self.spec,
            comments=tokenizer.comments,
            delimiter_script=tokenizer.delimiter_script,
            terminator_records=records,
            segment_script=(
                None
                if self.spec.segment_script is None
                else SegmentScript(
                    self.spec.segment_script, script, tokenizer.origin, tokenizer.kept
                )
            ),
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
        """Project executed batch constituents, retaining SQLite comment-only segments."""
        if (
            self.spec.batch_script is not None
            or self.spec.delimiter_script is not None
            or self.spec.terminator_script is not None
        ):
            return analysis_sql(self.split(script))
        return [record.text for record in self.split(script, include_comment_only=True)]

    def blank_comments(self, script: str) -> str:
        """Replace each scanned comment with a space, preserving quoted text."""
        if self.spec.delimiter_script is not None:
            raise NotImplementedError(
                "comments of a delimiter script are blanked by the dialect's own tokenizer"
            )
        if self.spec.terminator_script is not None:
            raise NotImplementedError(
                "comments of a terminator script are not blanked by the engine"
            )
        tokenizer = LexicalTokenizer(script, spec=self.spec)
        tokens = tokenizer.tokenize()
        if self.spec.segment_script is None:
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
        if self.spec.segment_script is not None:
            return masked[tokenizer.origin :]  # a segment script's byte order mark is not text
        return masked[1:] if self.spec.sqlite_shell and script.startswith("\ufeff") else masked
