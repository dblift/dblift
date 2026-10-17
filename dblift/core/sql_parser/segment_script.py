"""Records of a segment script: the segments between ``;`` tokens."""

from typing import List, Sequence

from dblift.core.sql_parser.lexical_spec import SegmentScriptRules
from dblift.core.sql_parser.statement import Statement
from dblift.core.sql_parser.tokens import Token


class SegmentScript:
    """The records of a segment script from its tokens."""

    def __init__(self, rules: SegmentScriptRules, source: str, origin: int) -> None:
        """Bind the rules to the source; ``origin`` is the length of the byte order mark."""
        self.rules = rules
        self.source = source
        self.origin = origin

    def records(self, tokens: Sequence[Token], include_comment_only: bool) -> List[Statement]:
        """The records of the script; comment-only segments only when asked."""
        return []
