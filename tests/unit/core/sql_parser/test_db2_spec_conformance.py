"""Every §10 row of docs/sql-parsing/db2.md, run through SqlAnalyzer.split_statements.

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
ROWS = [row for row in load_conformance_rows(SPEC_DIR) if row.dialect == "db2"]

KNOWN_GAPS: frozenset[str] = frozenset({"51", "52", "53", "54"})

#: Rows that fail today for the reason given: they fail strictly, and the change that fixes a row
#: removes its id (a row that starts to pass under a strict xfail fails loudly).
RED_ROWS: dict[str, str] = {}


def test_spec_compiles_to_at_least_the_rows_it_had_on_2026_10_11() -> None:
    assert len(ROWS) >= 60
    assert len({row.row_id for row in ROWS}) == len(ROWS)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_id)
def test_spec_row(row: ConformanceRow, request: pytest.FixtureRequest) -> None:
    if row.status == "to_verify":
        pytest.skip("spec marks this row 'to verify': not a claim yet")
    if row.row_id in KNOWN_GAPS:
        request.applymarker(pytest.mark.xfail(strict=True, reason="listed in KNOWN_GAPS"))
    if row.row_id in RED_ROWS:
        request.applymarker(pytest.mark.xfail(strict=True, reason=RED_ROWS[row.row_id]))
    outcome = split_script("db2", row.script)
    assert outcome.matches(row.expectation), (
        f"row {row.row_id}\nscript: {row.script!r}\n"
        f"expected: {row.expectation}\nactual: {outcome!r}"
    )


@pytest.mark.parametrize("row_id", sorted(KNOWN_GAPS))
def test_rows_51_to_54_are_known_gaps(row_id: str) -> None:
    row = next(r for r in ROWS if r.row_id == row_id)
    outcome = split_script("db2", row.script)
    assert not outcome.matches(row.expectation)
    actual = {
        "51": (None, ("VALUES 'x\n-- y;\nz'", "VALUES 2")),
        "52": ("UnsupportedMetaCommandError", ()),
        "53": ("UnsafeStatementSplitError", ()),
        "54": (None, ("VALUES 1", "VALUES 2;")),
    }[row_id]
    assert (outcome.error, outcome.statements) == actual


def test_row_53_script_holds_a_carriage_return_run() -> None:
    assert "\r\r\n" in next(r for r in ROWS if r.row_id == "53").script


def test_new_rows_have_no_code_span_in_prose() -> None:
    by_id = {r.row_id: r for r in ROWS}
    assert by_id["51"].script == "VALUES 'x\n-- y;\nz';\nVALUES 2;"
    assert by_id["52"].expectation.statements == ("VALUES 'p\n(= q\n'", "VALUES 2")
    assert by_id["53"].expectation.statements == ("VALUES 1", "VALUES 2")
    assert (
        by_id["54"].script
        == "--#SET TERMINATOR " + chr(0xE9) * 2 + "\nVALUES 1" + chr(0xE9) * 2 + "\nVALUES 2;"
    )
