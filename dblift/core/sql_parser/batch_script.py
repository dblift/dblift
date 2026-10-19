"""Batch records of a script cut at separator lines."""

from typing import List, Optional, Sequence, Tuple

from dblift.core.sql_parser.batch_commands import read_command
from dblift.core.sql_parser.batch_division import code_positions, code_spans, divide, has_code
from dblift.core.sql_parser.lexical_spec import BatchScriptRules
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import Token, TokenType


class BatchScript:
    """Group the tokens of a script into batches and build their records.

    Every refusal was raised by the tokenizer, so nothing here raises.
    """

    def __init__(
        self,
        rules: BatchScriptRules,
        source: str,
        client_name: str,
        comments: Sequence[Tuple[int, int]],
        text_blanks: str,
        *,
        origin: int = 0,
    ) -> None:
        """``comments`` are the extents the tokenizer read; ``origin`` is where the text starts."""
        self.rules = rules
        self.source = source
        self.client_name = client_name
        self.comments = comments
        self.text_blanks = text_blanks
        self.origin = origin

    def split(self, tokens: Sequence[Token]) -> List[Tuple[Statement, str]]:
        """``(record, the string execution sends once)`` for every batch that holds code."""
        source = self.source
        extents = list(self.comments)
        lexeme_starts: List[int] = []
        for token in tokens:
            if token.type == TokenType.STRING or (
                token.type == TokenType.IDENTIFIER and token.text[:1] in ('"', "[")
            ):
                extents.append((token.pos, token.pos + len(token.text)))
                lexeme_starts.append(token.pos)
        extents.sort()
        spans = code_spans(source, self.origin, len(source), extents)
        positions = code_positions(self.rules, source, spans, lexeme_starts)
        records: List[Tuple[Statement, str]] = []
        start, line = self.origin, 1
        for token in tokens:
            if token.type != TokenType.DIRECTIVE:
                continue
            cut = (
                token.pos
            )  # only blanks precede a separator on its line; strip(text_blanks) drops them
            newline = source.find("\n", token.pos)
            following = len(source) if newline < 0 else newline + 1
            count = read_command(self.rules, self.client_name, token.text, 0, token.line, False)
            self._add(
                records, spans, positions, start, cut, line, self.rules.separator, count, following
            )
            start, line = following, token.line + 1
        self._add(records, spans, positions, start, len(source), line, None, 1, len(source))
        return records

    def _add(
        self,
        records: List[Tuple[Statement, str]],
        spans: Sequence[Tuple[int, int]],
        positions: Sequence[int],
        start: int,
        cut: int,
        line: int,
        terminator: Optional[str],
        count: Optional[int],
        end: int,
    ) -> None:
        """Append the record of ``source[start:cut]`` when the batch holds code."""
        if not has_code(positions, start, cut - 1):
            return
        raw = self.source[start:cut]
        text = raw.strip(self.text_blanks)
        if not text:
            return
        lead = len(raw) - len(raw.lstrip(self.text_blanks))
        record = Statement(
            text=text,
            line=line + raw.count("\n", 0, lead),
            terminator=terminator,
            repeat=1 if count is None else count,
            analysis_statements=divide(
                self.rules, self.source, start, cut, spans, positions, self.text_blanks
            ),
            source_start=start,
            source_end=end,
        )
        records.append((record, text))
