"""Records of a segment script: the segments between ``;`` tokens."""

from typing import List, Optional, Sequence

from dblift.core.sql_parser.lexical_spec import SegmentScriptRules
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import Token, TokenType


class SegmentScript:
    """The records of a segment script from its tokens."""

    def __init__(
        self, rules: SegmentScriptRules, source: str, origin: int, text_blanks: str
    ) -> None:
        """Bind the rules to the source; ``origin`` is the length of the byte order mark."""
        self.rules = rules
        self.text_blanks = text_blanks
        self.source = source
        self.origin = origin

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
        blanks = self.text_blanks
        raw = self.source[start:end]
        if not code and not (include_comment_only and raw.strip(blanks)):
            return
        text = raw.lstrip(blanks)
        lead = len(raw) - len(text)
        found.append(
            Statement(
                text=text.rstrip(blanks),
                line=line + raw.count("\n", 0, lead),
                terminator=terminator,
                source_start=start + lead,
                source_end=end + (terminator is not None),
            )
        )
