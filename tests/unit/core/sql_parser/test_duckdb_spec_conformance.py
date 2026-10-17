"""Every §10 row of docs/sql-parsing/duckdb.md, run through SqlAnalyzer.split_statements.

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
ROWS = [row for row in load_conformance_rows(SPEC_DIR) if row.dialect == "duckdb"]

KNOWN_GAPS: frozenset[str] = frozenset({"74", "75", "85", "86", "87", "88", "89"})


def test_spec_compiles_to_at_least_the_rows_it_had_on_2026_10_12() -> None:
    assert len(ROWS) >= 73
    assert len({row.row_id for row in ROWS}) == len(ROWS)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_id)
def test_spec_row(row: ConformanceRow, request: pytest.FixtureRequest) -> None:
    if row.status == "to_verify":
        pytest.skip("spec marks this row 'to verify': not a claim yet")
    if row.row_id in KNOWN_GAPS:
        request.applymarker(pytest.mark.xfail(strict=True, reason="listed in KNOWN_GAPS"))
    outcome = split_script("duckdb", row.script)
    assert outcome.matches(row.expectation), (
        f"row {row.row_id}\nscript: {row.script!r}\n"
        f"expected: {row.expectation}\nactual: {outcome!r}"
    )


def test_rows_74_to_77_compile_to_the_engine_cut() -> None:
    rows = {row.row_id: row for row in ROWS}
    assert rows["74"].script == "SELECT E'a' 'b\\'; SELECT 1; SELECT 'z';"
    assert rows["74"].expectation.statements == ("SELECT E'a' 'b\\'", "SELECT 1", "SELECT 'z'")
    assert rows["75"].script == "SELECT " + chr(0xB2) + "E'b\\';c'; SELECT 2;"
    assert rows["75"].expectation.statements == ("SELECT " + chr(0xB2) + "E'b\\'", "c'; SELECT 2")
    assert rows["76"].script == "PREPARE p AS SELECT $1a$$x; SELECT 2; SELECT 3 AS y$$;"
    assert rows["76"].expectation.statements == (
        "PREPARE p AS SELECT $1a$$x",
        "SELECT 2",
        "SELECT 3 AS y$$",
    )
    assert rows["77"].script == "SELECT 1a$$x; DROP TABLE t; SELECT 3 AS y$$;"
    assert rows["77"].expectation.statements == ("SELECT 1a$$x", "DROP TABLE t", "SELECT 3 AS y$$")


def test_new_rows_have_no_code_span_in_prose() -> None:
    text = (SPEC_DIR / "duckdb.md").read_text(encoding="utf-8")
    cells = {
        line.split(" | ")[0]: line
        for line in text.splitlines()
        if line.startswith(("| 74 |", "| 75 |", "| 76 |", "| 77 |"))
    }
    assert sorted(cells) == ["| 74", "| 75", "| 76", "| 77"]
    for line in cells.values():
        assert "(measured" in line, line[:40]
        assert "`" not in line[line.index("(measured") :]
