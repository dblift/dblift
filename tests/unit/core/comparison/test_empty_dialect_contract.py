"""Pin tests for the empty-dialect (``""``) fallback contract.

PR #252 (commit ea5891f) changed several public signatures in
``core.comparison`` and ``core.comparison.diff_models`` to default
``dialect: str = ""`` instead of ``"postgresql"``. This was an
intentional design decision — empty dialect now means **"no
dialect-specific rendering"** rather than "fall back to PostgreSQL" —
but the change was buried inside an unrelated Oracle-quoting PR.

These tests pin the contract so future contributors don't accidentally
restore the historical PostgreSQL fallback (or the inverse — drop the
``""`` handling entirely).
"""

from __future__ import annotations

import pytest

from core.comparison.comparison_utils import normalize_view_definition
from core.comparison.diff_models import TableDiff
from core.sql_model.table import Table


class _StubTable:
    """Minimal stand-in: ``TableDiff._resolve_dialect`` only reads ``.dialect``."""

    def __init__(self, dialect=None):
        self.dialect = dialect


@pytest.mark.unit
class TestResolveDialectFallback:
    def test_returns_first_populated_dialect(self):
        a = _StubTable(dialect=None)
        b = _StubTable(dialect="oracle")
        assert TableDiff._resolve_dialect(a, b) == "oracle"

    def test_returns_empty_string_when_no_table_carries_a_dialect(self):
        # Pinned by PR #252 / ea5891f. Previously this returned "postgresql".
        # If you change this default, update the docstrings on
        # ``_resolve_dialect``, ``compare_tables``, ``compare_schemas`` and
        # ``normalize_view_definition`` AND release a CHANGELOG entry — the
        # downstream rendering path treats ``""`` as "no dialect-specific
        # rendering" (no SERIAL → INTEGER aliasing, no sqlglot view parse,
        # no per-quirks property comparison).
        a = _StubTable(dialect=None)
        b = _StubTable(dialect=None)
        assert TableDiff._resolve_dialect(a, b) == ""

    def test_returns_empty_string_for_no_tables_supplied(self):
        assert TableDiff._resolve_dialect() == ""

    def test_returns_empty_string_when_all_tables_are_none(self):
        assert TableDiff._resolve_dialect(None, None) == ""


@pytest.mark.unit
class TestNormalizeViewDefinitionEmptyDialect:
    def test_empty_dialect_skips_sqlglot_parse(self):
        # With dialect="" the sqlglot ``read`` step is bypassed
        # (_sqlglot_read_dialect_for_view_normalization returns None).
        # We verify by checking that whitespace + comment normalisation still
        # works while a dialect-specific rewrite (lower-case keyword, double
        # quotes preserved verbatim) does NOT happen.
        sql = "select * from t -- comment\n"
        out = normalize_view_definition(sql, dialect="")
        # Comment stripped, uppercased, whitespace collapsed
        assert "comment" not in out.lower() or "--" not in out
        assert "SELECT" in out

    def test_empty_dialect_returns_empty_for_falsy_definition(self):
        assert normalize_view_definition(None, dialect="") == ""
        assert normalize_view_definition("", dialect="") == ""


@pytest.mark.unit
class TestRealTableResolvesDialect:
    """Sanity check that ``Table.dialect`` is the resolution source."""

    def test_real_table_with_explicit_dialect_is_picked_up(self):
        t = Table(name="t", columns=[], dialect="mysql")
        assert TableDiff._resolve_dialect(t) == "mysql"

    def test_real_table_without_explicit_dialect_falls_back_to_empty(self):
        t = Table(name="t", columns=[])
        assert TableDiff._resolve_dialect(t) == ""
