"""Every section 10 row of docs/sql-parsing/mysql.md and mariadb.md, run through SqlAnalyzer.split_statements.

The mysql.md rows run for both engines (MariaDB reads a script the way MySQL does, except where
mariadb.md says otherwise); the mariadb.md rows run for MariaDB only. Rows the splitter gets wrong
today are listed in KNOWN_GAPS and fail strictly: an id that starts to pass must be removed, an id
that fails differently is a regression. Rows the spec marks *to verify* are skipped: not a claim yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.support.splitter_spec.spec_tables import (
    ConformanceRow,
    load_conformance_rows,
)
from tests.support.splitter_spec.splitting import split_script

SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ALL_ROWS = load_conformance_rows(SPEC_DIR)
MYSQL_ROWS = [row for row in ALL_ROWS if row.dialect == "mysql"]
MARIADB_ROWS = [row for row in ALL_ROWS if row.dialect == "mariadb"]

#: mysql.md rows whose expected statements are MySQL's reading and not MariaDB's.
MYSQL_ONLY_ROWS = frozenset({"16", "39a"})

KNOWN_GAPS: frozenset[str] = frozenset()

RUNS = (
    [pytest.param("mysql", row, id=f"mysql-{row.row_id}") for row in MYSQL_ROWS]
    + [
        pytest.param("mariadb", row, id=f"mariadb-on-mysql-{row.row_id}")
        for row in MYSQL_ROWS
        if row.row_id not in MYSQL_ONLY_ROWS
    ]
    + [pytest.param("mariadb", row, id=f"mariadb-{row.row_id}") for row in MARIADB_ROWS]
)


def test_specs_compile_to_at_least_the_rows_they_had_on_2026_10_11() -> None:
    assert len(MYSQL_ROWS) >= 85
    assert len(MARIADB_ROWS) >= 6
    for rows in (MYSQL_ROWS, MARIADB_ROWS):
        assert len({row.row_id for row in rows}) == len(rows)
    assert MYSQL_ONLY_ROWS <= {row.row_id for row in MYSQL_ROWS}


@pytest.mark.parametrize("dialect,row", RUNS)
def test_spec_row(dialect: str, row: ConformanceRow, request: pytest.FixtureRequest) -> None:
    if row.status == "to_verify":
        pytest.skip("spec marks this row 'to verify': not a claim yet")
    if row.row_id in KNOWN_GAPS:
        request.applymarker(pytest.mark.xfail(strict=True, reason="listed in KNOWN_GAPS"))
    outcome = split_script(dialect, row.script)
    assert outcome.matches(row.expectation), (
        f"{dialect} row {row.row_id}\nscript: {row.script!r}\n"
        f"expected: {row.expectation}\nactual: {outcome!r}"
    )
