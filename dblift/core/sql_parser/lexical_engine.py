"""One lexical entry point for splitting and comment masking."""

import logging
from typing import Iterable, List, Optional

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.lexical_spec import BOM, LexicalSpec
from dblift.core.sql_parser.lexical_statement_parser import LexicalStatementParser
from dblift.core.sql_parser.lexical_tokenizer import LexicalTokenizer
from dblift.core.sql_parser.segment_script import SegmentScript
from dblift.core.sql_parser.statement import Statement, analysis_sql
from dblift.core.sql_parser.tokens import Token

logger = logging.getLogger(__name__)


class LexicalEngine:
    """Select rules once; never retry through a second implementation."""

    def __init__(self, spec: LexicalSpec):
        """Bind the immutable plugin specification."""
        self.spec = spec
        self.last_policy_texts: List[Optional[str]] = []

    def _parser(self, script: str) -> LexicalStatementParser:
        tokenizer = LexicalTokenizer(script, spec=self.spec)
        tokens: Iterable[Token]
        segment_records = None
        terminator_records = None
        if tokenizer.delimiter_script is not None:
            if tokenizer.spec.refused_character:
                tokenizer._refuse_character()
            while tokenizer.pos < len(tokenizer.sql):
                tokenizer._next_token()
            tokenizer.delimiter_script.finish()
            tokens = []
        elif self.spec.segment_script is not None:
            if tokenizer.spec.refused_character:
                tokenizer._refuse_character()
            segments = SegmentScript(
                self.spec.segment_script,
                script,
                int(self.spec.leading_bom_is_blank and script.startswith(BOM)),
                self.spec.text_blanks,
                tokenizer.kept,
            )
            try:
                segment_records = segments.records(
                    tokenizer._iter_segment_tokens(self.spec.segment_script)
                )
            except UnsafeStatementSplitError:
                if tokenizer.open_comment is not None:
                    line, col = tokenizer.open_comment
                    raise UnsafeStatementSplitError(
                        f"unterminated block comment opened at line {line}, column {col}"
                    ) from None
                raise
            tokens = []
        elif self.spec.terminator_script is not None:
            if tokenizer.spec.refused_character:
                tokenizer._refuse_character()
            assert tokenizer.terminator_script is not None
            terminator_records = tokenizer.terminator_script.assemble(
                tokenizer._iter_terminator_tokens(),
                tokenizer.marks,
                lambda: tokenizer.open_lexeme,
            )
            tokens = []
        elif self.spec.copy_from_stdin:
            tokens = tokenizer._iter_sql_tokens()
        else:
            tokens = tokenizer.tokenize()
        if tokenizer.open_comment is not None:  # the engine rejects the whole script
            line, col = tokenizer.open_comment
            raise UnsafeStatementSplitError(
                f"unterminated block comment opened at line {line}, column {col}"
            )
        return LexicalStatementParser(
            tokens,
            source=script,
            spec=self.spec,
            comments=tokenizer.comments,
            delimiter_script=tokenizer.delimiter_script,
            terminator_records=terminator_records,
            segment_records=segment_records,
        )

    @staticmethod
    def _report(parser: LexicalStatementParser) -> None:
        for message in parser.warnings:
            logger.warning(message)
        for message in parser.notices:
            logger.info(message)

    def split(self, script: str) -> List[Statement]:
        """Return source-positioned execution units and analysis projections."""
        self.last_policy_texts = []
        parser = self._parser(script)
        records = parser.split()
        masked = script
        if parser._comments:
            parts: List[str] = []
            cursor = 0
            for start, end in parser._comments:
                parts.extend((script[cursor:start], " " * (end - start)))
                cursor = end
            parts.append(script[cursor:])
            masked = "".join(parts)
        batches = parser._batches
        self.last_policy_texts = []
        for record in records:
            view = self._policy_projection(script, masked, record)
            if (
                view is not None
                and batches is not None
                and batches._server_spec is not None
                and record.source_start is not None
                and record.source_end is not None
                and batches._comment_nests(record.source_start, record.source_end)
            ):
                view = self._server_policy_projection(record, batches._server_spec)
            self.last_policy_texts.append(view)
        self._report(parser)
        return records

    @staticmethod
    def _policy_projection(script: str, masked: str, record: Statement) -> Optional[str]:
        """Project comment blanks from the scan that produced this execution unit."""
        sent = record.text if record.execution_text is None else record.execution_text
        if (
            record.source_start is None
            or record.source_end is None
            or record.multi
            or (record.analysis_statements is not None and len(record.analysis_statements) > 1)
        ):
            return None
        offset = script.find(sent, record.source_start, record.source_end)
        if offset < 0:
            return None
        if masked is script:
            return sent
        view = masked[offset : offset + len(sent)]
        return sent if view == sent else view

    @staticmethod
    def _server_policy_projection(record: Statement, spec: LexicalSpec) -> Optional[str]:
        """Read a nested client comment as the server reads just this affected batch."""
        sent = record.text if record.execution_text is None else record.execution_text
        tokenizer = LexicalTokenizer(sent, spec=spec)
        try:
            tokenizer.tokenize()
        except UnsafeStatementSplitError:
            return None
        if tokenizer.open_comment is not None:
            return None
        parts: List[str] = []
        cursor = 0
        for start, end in tokenizer.comments:
            parts.extend((sent[cursor:start], " " * (end - start)))
            cursor = end
        parts.append(sent[cursor:])
        view = "".join(parts)
        return sent if view == sent else view

    def split_statements(self, script: str) -> List[str]:
        """Return execution text, preserving the established terminator contract."""
        parser = self._parser(script)
        statements = parser.split_statements()
        self._report(parser)
        return statements

    def split_for_analysis(self, script: str) -> List[str]:
        """Project the analysis text of each record of the script."""
        return analysis_sql(self.split(script))

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
        if self.spec.segment_script is not None:
            tokenizer._scan_segment_comments()
        else:
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
        if self.spec.segment_script is not None:
            return masked[tokenizer.origin :]  # a segment script's byte order mark is not text
        return masked[1:] if self.spec.sqlite_shell and script.startswith("\ufeff") else masked
