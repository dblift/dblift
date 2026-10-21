"""Every §10 row of docs/sql-parsing/snowflake.md through the public split path."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.splitter_spec.spec_tables import ConformanceRow, load_conformance_rows
from tests.support.splitter_spec.splitting import split_script

SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ROWS = [row for row in load_conformance_rows(SPEC_DIR) if row.dialect == "snowflake"]


def test_spec_compiles_all_22_rows() -> None:
    assert len(ROWS) == 22
    assert len({row.row_id for row in ROWS}) == 22


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_id)
def test_spec_row(row: ConformanceRow) -> None:
    outcome = split_script("snowflake", row.script)
    assert outcome.matches(row.expectation), (
        f"row {row.row_id}\nscript: {row.script!r}\n"
        f"expected: {row.expectation}\nactual: {outcome!r}"
    )
