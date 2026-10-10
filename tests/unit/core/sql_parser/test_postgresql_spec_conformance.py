"""Every §10 row of docs/sql-parsing/postgresql.md, run through SqlAnalyzer.split_statements.

Rows the splitter gets wrong today are listed in KNOWN_GAPS and fail strictly:
an id that starts to pass must be removed, an id that fails differently is a
regression. Rows the spec marks *to verify* are skipped: not a claim yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.splitter_spec.spec_tables import ConformanceRow, load_conformance_rows
from tests.support.splitter_spec.splitting import split_script

SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ROWS = [row for row in load_conformance_rows(SPEC_DIR) if row.dialect == "postgresql"]

KNOWN_GAPS: frozenset[str] = frozenset({"6", "8", "11", "15", "15a", "15b", "16", "19"})


def test_spec_compiles_to_at_least_the_rows_it_had_on_2026_10_10() -> None:
    assert len(ROWS) >= 22
    assert len({row.row_id for row in ROWS}) == len(ROWS)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_id)
def test_spec_row(row: ConformanceRow, request: pytest.FixtureRequest) -> None:
    if row.status == "to_verify":
        pytest.skip("spec marks this row 'to verify': not a claim yet")
    if row.row_id in KNOWN_GAPS:
        request.applymarker(pytest.mark.xfail(strict=True, reason="listed in KNOWN_GAPS"))
    outcome = split_script("postgresql", row.script)
    assert outcome.matches(row.expectation), (
        f"row {row.row_id}\nscript: {row.script!r}\n"
        f"expected: {row.expectation}\nactual: {outcome!r}"
    )
