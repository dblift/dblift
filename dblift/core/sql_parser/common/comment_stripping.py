"""Quote-aware comment stripping shared by every dialect's object extraction.

Extracted from ``EnhancedRegexParser._strip_comments_preserving_quotes`` so a
dialect that does not go through that base class (Oracle's regex parser,
which needs its own splitting and object model) can strip comments the same
way instead of re-deciding string/comment boundaries on its own.

The scan is a small state machine (``_Scanner``): one method per construct
it can be inside (line comment, block comment, dollar-quoted body) or can
start (a quote of some kind, a comment), so each stays simple enough to
reason about — and to add a dialect rule to — on its own.
"""

from __future__ import annotations

import re
from typing import List, Optional


def strip_comments_preserving_quotes(
    sql: str,
    *,
    line_prefixes: List[str],
    has_block_comments: bool,
    nested_block_comments: bool,
    supports_dollar_quoting: bool = False,
) -> str:
    """Remove comments without touching text inside a quoted span.

    A comment marker inside a single-quoted string, a double-quoted /
    backtick / bracket-quoted identifier, or (when ``supports_dollar_quoting``)
    a dollar-quoted body is not a comment and must be left alone. Doubled
    quote characters (``''``, ``""``, `` `` ``, ``]]``) are the escape form
    for a literal quote inside the span and do not end it. Block comments
    nest (``/* outer /* inner */ outer */``) only when
    ``nested_block_comments`` is true; otherwise the first ``*/`` closes,
    matching statement splitting for the same dialect.
    """
    markers = list(line_prefixes) + (["/*"] if has_block_comments else [])
    if not any(marker in sql for marker in markers):
        return sql.strip()

    scanner = _Scanner(
        sql,
        line_prefixes=line_prefixes,
        has_block_comments=has_block_comments,
        nested_block_comments=nested_block_comments,
        supports_dollar_quoting=supports_dollar_quoting,
    )
    return scanner.run()


class _Scanner:
    """Single-pass character scanner behind :func:`strip_comments_preserving_quotes`.

    ``run`` advances ``i`` one construct at a time via whichever
    ``_advance_*``/``_try_*`` method matches the current state; each of
    those only ever touches ``i``, ``result`` and its own flag(s), which is
    what keeps each one's complexity low despite the scanner overall having
    several kinds of span to track.
    """

    def __init__(
        self,
        sql: str,
        *,
        line_prefixes: List[str],
        has_block_comments: bool,
        nested_block_comments: bool,
        supports_dollar_quoting: bool,
    ) -> None:
        self.sql = sql
        self.line_prefixes = line_prefixes
        self.has_block_comments = has_block_comments
        self.nested_block_comments = nested_block_comments
        self.supports_dollar_quoting = supports_dollar_quoting

        self.result: List[str] = []
        self.i = 0
        self.in_single = False
        self.in_double = False
        self.in_backtick = False
        self.in_bracket = False
        self.block_comment_depth = 0
        self.in_line_comment = False
        self.dollar_tag: Optional[str] = None

    def run(self) -> str:
        length = len(self.sql)
        while self.i < length:
            if self.in_line_comment:
                self._advance_line_comment()
            elif self.block_comment_depth > 0:
                self._advance_block_comment()
            elif self.dollar_tag is not None:
                self._advance_dollar_body()
            else:
                self._advance_default()
        return "".join(self.result).strip()

    def _advance_line_comment(self) -> None:
        char = self.sql[self.i]
        if char in ("\n", "\r"):
            self.in_line_comment = False
            self.result.append(char)
        self.i += 1

    def _advance_block_comment(self) -> None:
        char = self.sql[self.i]
        opens_nested = (
            self.nested_block_comments and char == "/" and self.sql[self.i + 1 : self.i + 2] == "*"
        )
        closes = char == "*" and self.sql[self.i + 1 : self.i + 2] == "/"
        if opens_nested:
            self.block_comment_depth += 1
            self.i += 2
        elif closes:
            self.block_comment_depth -= 1
            self.i += 2
        else:
            self.i += 1

    def _advance_dollar_body(self) -> None:
        tag = self.dollar_tag
        assert tag is not None  # guarded by the caller
        if self.sql.startswith(tag, self.i):
            self.result.append(tag)
            self.i += len(tag)
            self.dollar_tag = None
        else:
            self.result.append(self.sql[self.i])
            self.i += 1

    def _in_quote(self) -> bool:
        return self.in_single or self.in_double or self.in_backtick or self.in_bracket

    def _advance_default(self) -> None:
        char = self.sql[self.i]
        in_quote = self._in_quote()

        consumed = (
            (not in_quote and self._try_dollar_quote_start(char))
            or self._try_single_quote(char)
            or self._try_double_quote(char)
            or self._try_backtick(char)
            or self._try_bracket(char)
            or (not in_quote and self._try_comment_start(char))
        )
        if not consumed:
            self.result.append(char)
            self.i += 1

    def _try_dollar_quote_start(self, char: str) -> bool:
        """``$tag$`` opening a dollar-quoted body (PostgreSQL)."""
        if not self.supports_dollar_quoting or char != "$":
            return False
        match = re.match(r"\$([a-zA-Z_][a-zA-Z0-9_]*)?\$", self.sql[self.i :])
        if not match:
            return False
        tag = match.group(0)
        self.dollar_tag = tag
        self.result.append(tag)
        self.i += len(tag)
        return True

    def _try_quote(self, char: str, marker: str, other_quotes_open: bool, flag: str) -> bool:
        """Toggle a same-open/close-character quote span (``'``, ``"``, `` ` ``).

        Doubling the marker (``''``, ``""``, `` `` ``) is the escape for a
        literal marker inside the span and does not end it.
        """
        if other_quotes_open or char != marker:
            return False
        was_open = getattr(self, flag)
        self.result.append(char)
        self.i += 1
        if was_open and self.sql[self.i : self.i + 1] == marker:
            self.result.append(marker)
            self.i += 1
        else:
            setattr(self, flag, not was_open)
        return True

    def _try_single_quote(self, char: str) -> bool:
        return self._try_quote(
            char, "'", self.in_double or self.in_backtick or self.in_bracket, "in_single"
        )

    def _try_double_quote(self, char: str) -> bool:
        return self._try_quote(
            char, '"', self.in_single or self.in_backtick or self.in_bracket, "in_double"
        )

    def _try_backtick(self, char: str) -> bool:
        return self._try_quote(
            char, "`", self.in_single or self.in_double or self.in_bracket, "in_backtick"
        )

    def _try_bracket(self, char: str) -> bool:
        """``[...]`` bracket-quoted identifier (SQL Server), not a matched pair."""
        if self.in_single or self.in_double or self.in_backtick:
            return False
        if not self.in_bracket and char == "[":
            self.in_bracket = True
            self.result.append(char)
            self.i += 1
            return True
        if self.in_bracket and char == "]":
            self.result.append(char)
            self.i += 1
            if self.sql[self.i : self.i + 1] == "]":
                self.result.append("]")
                self.i += 1
            else:
                self.in_bracket = False
            return True
        return False

    def _try_comment_start(self, char: str) -> bool:
        if self.has_block_comments and char == "/" and self.sql[self.i + 1 : self.i + 2] == "*":
            self.block_comment_depth = 1
            self.i += 2
            return True
        matched_prefix = next(
            (p for p in self.line_prefixes if self.sql.startswith(p, self.i)), None
        )
        if matched_prefix is None:
            return False
        self.in_line_comment = True
        self.i += len(matched_prefix)
        return True
