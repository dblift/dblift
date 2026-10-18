"""Records of a segment script: the segments between ``;`` tokens."""

from typing import List, Optional, Sequence

from dblift.core.exceptions import UnsafeStatementSplitError
from dblift.core.sql_parser.blank_pass import differs_alone, kept_alone_only
from dblift.core.sql_parser.lexical_spec import SegmentScriptRules
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import Token, TokenType


class SegmentScript:
    """The records of a segment script from its tokens."""

    def __init__(
        self, rules: SegmentScriptRules, source: str, origin: int, kept: Sequence[int] = ()
    ) -> None:
        """Bind the rules to the source; ``origin`` is the length of the byte order mark.

        ``kept`` are the stretches where the engine's pass keeps blanks, found by the tokenizer.
        """
        self.rules = rules
        self.source = source
        self.origin = origin
        self.kept = kept

    def records(self, tokens: Sequence[Token], include_comment_only: bool) -> List[Statement]:
        """The records of the script, read with one cursor over ``tokens``.

        A segment runs from just after a ``;`` to the next one (or the end). It is a record when it
        holds a token that is not a comment, or, for analysis, a character outside ``text_blanks``.
        The text is the segment without those characters at both ends; comments stay in it.
        """
        found: List[Statement] = []
        start, line, code = self.origin, 1, False
        for index in range(len(tokens)):
            token = tokens[index]
            if token.type == TokenType.DELIMITER:
                self._finish(found, start, token.pos, ";", line, code, include_comment_only)
                start, line, code = token.pos + 1, token.line, False
            elif token.type != TokenType.COMMENT:
                code = True
        self._finish(found, start, len(self.source), None, line, code, include_comment_only)
        return found

    def _finish(
        self,
        found: List[Statement],
        start: int,
        end: int,
        terminator: Optional[str],
        line: int,
        code: bool,
        include_comment_only: bool,
    ) -> None:
        """Append the record of the segment ``source[start:end]``, if it is one."""
        blanks = self.rules.text_blanks
        raw = self.source[start:end]
        if not code and not (include_comment_only and raw.strip(blanks)):
            return
        text = raw.lstrip(blanks)
        lead = len(raw) - len(text)
        text = text.rstrip(blanks)
        if code:
            self._refuse_read_differently_alone(start + lead, text)
        found.append(
            Statement(
                text=text,
                line=line + raw.count("\n", 0, lead),
                terminator=terminator,
                source_start=start + lead,
                source_end=end + (terminator is not None),
            )
        )

    def _refuse_read_differently_alone(self, lo: int, text: str) -> None:
        """Refuse a statement with a blank the engine reads differently alone than in its script."""
        hi = lo + len(text)
        pos = differs_alone(self.source, lo, hi, self.kept, self.rules)
        how = "where the engine keeps this blank in a word and, run alone, replaces it"
        if pos < 0:
            pos = kept_alone_only(self.source, lo, hi, self.kept, self.rules)
            how = "this blank is kept when run alone, replaced in its script"
        if pos < 0:
            return
        line = self.source.count("\n", 0, pos) + 1
        column = pos - self.source.rfind("\n", 0, pos)
        raise UnsafeStatementSplitError(
            f"U+{ord(self.source[pos]):04X} at line {line}, column {column}: the statement reads "
            f"differently run alone than in its script, {how}"
        )
