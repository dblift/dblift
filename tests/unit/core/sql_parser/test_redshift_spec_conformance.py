"""Every §10 row of docs/sql-parsing/redshift.md, run through StatementReader.split_statements.

Each row was sent to Redshift Serverless 1.0.485645 (psycopg 3.3.5, 2026-10-20); the rows are the
splitter's claim about what that engine does with the same text.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dblift.db.plugins.redshift.parser.lexical_spec import REDSHIFT_SPEC
from tests.support.splitter_spec.spec_tables import ConformanceRow, load_conformance_rows
from tests.support.splitter_spec.splitting import split_script

SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ROWS = [row for row in load_conformance_rows(SPEC_DIR) if row.dialect == "redshift"]


def test_spec_compiles_to_the_rows_measured_on_2026_10_20() -> None:
    assert len(ROWS) == 30
    assert len({row.row_id for row in ROWS}) == len(ROWS)


@pytest.mark.parametrize("row", ROWS, ids=lambda row: row.row_id)
def test_spec_row(row: ConformanceRow) -> None:
    outcome = split_script("redshift", row.script)
    assert outcome.matches(row.expectation), (
        f"row {row.row_id}\nscript: {row.script!r}\n"
        f"expected: {row.expectation}\nactual: {outcome!r}"
    )


def test_spec_claims_only_what_the_engine_accepts() -> None:
    assert REDSHIFT_SPEC.nested_comments
    assert REDSHIFT_SPEC.plain_string_escapes
    assert not REDSHIFT_SPEC.copy_from_stdin
    assert REDSHIFT_SPEC.block_opener == ("", "")
    assert REDSHIFT_SPEC.escape_prefixes == ()
