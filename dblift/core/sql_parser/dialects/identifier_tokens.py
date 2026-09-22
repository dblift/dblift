r"""Escape-aware quoted-identifier delimiters, shared across dialect configs.

A closing delimiter inside a quoted identifier is escaped by doubling it:
``[a]]b]`` is the identifier ``a]b``; ``"a""b"`` is ``a"b``; the same
convention covers MySQL/SQLite backtick quoting, `` `a``b` `` is `` a`b ``.
Each fragment below consumes a doubled pair as part of the token instead of
stopping at the first occurrence.

This is the single definition of "what a quoted SQL identifier looks like"
for every consumer that needs it, dialect config or otherwise -- a second,
independent copy of this is how an identifier-parsing fix lands in one
place and not another (#375, #380).

The repeated group in each pattern below is deliberately left unbounded.
Reading a doubled delimiter as part of the token makes an unterminated one
cost O(n^2) to fail: each of the n candidate start positions ``re.search``
tries backtracks through the rest of the string looking for a closing
delimiter that was never opened, one position that never matches costing
O(n) instead of O(1). Measured on 5000 unterminated ``[`` (no closing ``]``
anywhere): 233ms for this pattern, against 9.6ms for the pattern it
replaced, which stopped at the first ``]`` instead of reading a doubled one
(#375/#380). Two ways to bound that cost were tried and both rejected, for
the same reason: they cannot tell a legitimately short match from one that
silently gave up partway through the real identifier, and this module's
callers rely on that distinction to refuse rather than guess wrong --

- An atomic/possessive quantifier stops backtracking once the greedy path
  fails, which is exactly what breaks a caller's ambiguity check: for
  ``[dbo].[t]](col)`` the plain pattern below backtracks to the shorter,
  correct match ``[t]``, leaving a trailing ``]`` that
  ``_extract_table_ref_from_create_index``
  (dblift/core/migration/scripting/undo_script_generator/_extractors.py)
  reads as "this looked truncated" and refuses on. An atomic group instead
  fails the alternative outright and the search moves on, silently
  collapsing the match to ``[dbo]`` alone with no signal that anything was
  left over.
- A length cap on the repeated group (``{1,256}``, matching every engine's
  real identifier limit -- SQL Server/Oracle/DB2 128, MySQL 64, PostgreSQL
  63) produces the identical hazard by a different route, and the premise
  behind picking 256 does not hold for every engine this module serves:
  SQLite and DuckDB accept and round-trip a quoted identifier far past
  that (verified directly against both, 300 and 1000 characters). Capped,
  ``CREATE INDEX [idx] ON [dbo].[`` + 300 ``x`` s + ``](col)`` matches
  ``[dbo]`` as a complete ``_QUALIFIED_NAME`` on its own -- the second
  identifier fails to match at all once its content exceeds the cap, so
  the ``(?:\.\s*_IDENTIFIER)*`` tail simply never extends, rather than
  extending short. The character right after the match is ``.``, not the
  closing delimiter the truncation guard watches for, so it does not fire:
  ``_extract_table_ref_from_create_index`` returns ``(None, "dbo")`` --
  the schema silently reported as the table, the real (very long) table
  name silently dropped -- instead of refusing.

So the O(n^2) cost on a malformed, unterminated delimiter is an accepted
trade-off, not a bug to keep chasing: dblift's regex-fallback path and
SQL Server's structured-parser id_token both run against migration SQL the
person deploying it wrote (or a schema-diff tool generated, itself reading
a real schema), not input from an untrusted, adversarial network caller --
the "adversarial" input this cost describes is malformed SQL, which is
invisible in cost at any length a real identifier reaches, and a project
that can commit an unterminated multi-KB bracket run into a migration file
already controls what that migration runs. Silently returning a wrong
object reference for a legitimate long identifier is the worse failure by
far, and every bounding technique tried produces exactly that.
"""

DOUBLE_QUOTED_IDENTIFIER = r'"(?:[^"]|"")+"'
BRACKET_IDENTIFIER = r"\[(?:[^\]]|\]\])+\]"
BACKTICK_IDENTIFIER = r"`(?:[^`]|``)+`"

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
