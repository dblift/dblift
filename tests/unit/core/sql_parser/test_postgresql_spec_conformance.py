"""Every §10 row of docs/sql-parsing/postgresql.md, run through SqlAnalyzer.split_statements.

Rows the splitter gets wrong today are listed in KNOWN_GAPS and fail strictly:
an id that starts to pass must be removed, an id that fails differently is a
regression. Rows the spec marks *to verify* are skipped: not a claim yet.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from dblift.db.plugins.postgresql.parser.postgresql_regex_parser import PostgreSqlRegexParser
from dblift.db.plugins.postgresql.provider import _split_copy_from_stdin
from tests.support.splitter_spec.spec_tables import ConformanceRow, load_conformance_rows
from tests.support.splitter_spec.splitting import SplitOutcome, split_script

SPEC_DIR = Path(__file__).resolve().parents[4] / "docs" / "sql-parsing"
ROWS = [row for row in load_conformance_rows(SPEC_DIR) if row.dialect == "postgresql"]

KNOWN_GAPS: frozenset[str] = frozenset()


@pytest.mark.parametrize("row_id", ["11", "11a", "11b", "15b"])
def test_copy_conformance_row_preserves_trailing_payload_newlines(row_id: str) -> None:
    row = next(row for row in ROWS if row.row_id == row_id)
    outcome = split_script("postgresql", row.script)
    assert outcome.matches(row.expectation)
    assert not SplitOutcome((outcome.statements[0].rstrip("\n"), *outcome.statements[1:])).matches(
        row.expectation
    )


def test_copy_header_conformance_row_excludes_comment_from_data() -> None:
    row = next(row for row in ROWS if row.row_id == "11b")
    statement = split_script("postgresql", row.script).statements[0]
    assert _split_copy_from_stdin(statement) == ("COPY t (a) FROM STDIN", "1\n\n")
    assert PostgreSqlRegexParser().split(row.script)[0].analysis_statements == (
        "COPY t (a) FROM STDIN",
    )


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
