"""Escape-aware quoted-identifier delimiters, shared across dialect configs.

A closing delimiter inside a quoted identifier is escaped by doubling it:
``[a]]b]`` is the identifier ``a]b``; ``"a""b"`` is ``a"b``; the same
convention covers MySQL/SQLite backtick quoting, `` `a``b` `` is `` a`b ``.
Each fragment below consumes a doubled pair as part of the token instead of
stopping at the first occurrence.

This is the single definition of "what a quoted SQL identifier looks like"
for every consumer that needs it, dialect config or otherwise -- a second,
independent copy of this is how an identifier-parsing fix lands in one
place and not another (#375, #380).

The repeated group in each pattern is capped at ``_MAX_IDENTIFIER_LENGTH``
rather than left unbounded. Every engine this repo targets caps a real
identifier well under that (SQL Server/Oracle/DB2 128, MySQL 64,
PostgreSQL 63), so the cap never truncates a legitimate name. Without it, an
unquoted delimiter run costs O(n^2): each of the n candidate start positions
that ``re.search`` tries backtracks through the rest of the string looking
for a closing delimiter that was never opened, one position that never
matches costing O(n) instead of O(1). Measured on 5000 unterminated ``[``
(no closing ``]`` anywhere): the doubling-aware pattern this shared module
replaced two copies of took 233ms uncapped, against 9.6ms for the
pre-doubling-fix pattern it replaced -- a ~24x regression from the added
alternation on adversarial input, invisible at realistic identifier lengths
but scaling quadratically with attacker-controlled input size since this
token is now on SQL Server's structured-parser scan for every statement,
not just the regex-fallback path's rare use. Capping the group bounds a
single position's worst case to O(cap) instead of O(n): the same 5000-``[``
input drops to ~21ms capped, and stays near-linear as input grows (~87ms at
20000, not the ~965ms quadratic scaling would predict) -- verified to match
the uncapped pattern's output on every case in this repo's identifier test
matrix, including the genuinely-ambiguous one an atomic/possessive
quantifier was tried against first and rejected for: it stopped the
regex from backtracking into the shorter, correct match that a downstream
truncation guard relies on seeing.
"""

_MAX_IDENTIFIER_LENGTH = 256

DOUBLE_QUOTED_IDENTIFIER = rf'"(?:[^"]|""){{1,{_MAX_IDENTIFIER_LENGTH}}}"'
BRACKET_IDENTIFIER = rf"\[(?:[^\]]|\]\]){{1,{_MAX_IDENTIFIER_LENGTH}}}\]"
BACKTICK_IDENTIFIER = rf"`(?:[^`]|``){{1,{_MAX_IDENTIFIER_LENGTH}}}`"

# The closing delimiter for each quoting style above, keyed by its opener.
CLOSING_DELIMITER = {"[": "]", '"': '"', "`": "`"}


def strip_identifier_quotes(token: str) -> str:
    """Undo one layer of quoting from a matched identifier token.

    Removes the delimiters and collapses a doubled closing delimiter back
    to one. A bare (unquoted) token is returned unchanged.
    """
    if len(token) < 2:
        return token
    closing = CLOSING_DELIMITER.get(token[0])
    if closing is None or token[-1] != closing:
        return token
    return token[1:-1].replace(closing * 2, closing)
