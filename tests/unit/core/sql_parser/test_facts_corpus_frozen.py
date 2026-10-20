"""Once a family reads its statements through the reader, its recorded extraction is frozen."""

from __future__ import annotations

from typing import Any, Dict, List

import pytest

from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.plugins.oracle.quirks import OracleQuirks
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks
from tests.support.facts_corpus import FAMILIES
from tests.support.facts_corpus import __main__ as cli
from tests.support.facts_corpus import family_file, record
from tests.support.facts_corpus.differential import current_arm
from tests.support.facts_corpus.record import normalise, record_family

OLD_A = {"hybrid": [["TABLE", "a", "public"]], "analyzer": [["TABLE", "default_schema.a"]]}
ROW_A = {"sql": "CREATE TABLE a (i int);", "inputs": ["i1"], "facts": {"stale": True}, "old": OLD_A}


@pytest.fixture
def activated(monkeypatch: pytest.MonkeyPatch) -> None:
    """PostgreSQL reads its statements through the reader, as an activated family does."""
    monkeypatch.setattr(PostgresqlQuirks, "statement_facts_class", SqlglotStatementFactsReader)


def _inputs(*sql: str) -> List[Dict[str, Any]]:
    return [{"id": f"i{n}", "sql": text, "origins": []} for n, text in enumerate(sql, 1)]


def test_record_floor_refuses_to_rewrite_the_extraction_of_an_activated_family(
    activated: None,
) -> None:
    with pytest.raises(RuntimeError, match="frozen"):
        record_family("postgresql", "floor", _inputs("SELECT 1"), [])


def test_is_frozen_reflects_the_plugin_hook(monkeypatch: pytest.MonkeyPatch) -> None:
    assert OracleQuirks.statement_facts_class is None
    assert not record.is_frozen("oracle")
    assert not record.is_frozen("sqlite")
    monkeypatch.setattr(PostgresqlQuirks, "statement_facts_class", SqlglotStatementFactsReader)
    assert record.is_frozen("postgresql")


def test_the_command_refuses_before_writing_any_file(
    activated: None, capsys: pytest.CaptureFixture
) -> None:
    before = {f: family_file(f).read_bytes() for f in FAMILIES}
    assert cli.main(["record", current_arm()]) == 1
    assert "postgresql" in capsys.readouterr().out
    assert {f: family_file(f).read_bytes() for f in FAMILIES} == before


def test_a_family_that_is_not_activated_cannot_be_recorded_as_frozen() -> None:
    with pytest.raises(RuntimeError, match="not activated"):
        record_family("oracle", "floor", _inputs("SELECT 1"), [], frozen=True)


def test_frozen_recording_keeps_old_and_refreshes_facts(monkeypatch, activated: None) -> None:
    monkeypatch.setattr(record, "split", lambda family, sql: [sql])
    rows = record_family("postgresql", "floor", _inputs(ROW_A["sql"]), [ROW_A], frozen=True)
    (row,) = rows
    assert row["old"] == OLD_A
    assert row["facts"]["objects"] == [["a", "TABLE", "created", None]]
    assert row["inputs"] == ["i1"]


def test_old_carries_over_when_only_whitespace_or_the_terminator_changed(
    monkeypatch, activated: None
) -> None:
    """The splitter now yields the statement without its terminator: same statement, same old."""
    monkeypatch.setattr(record, "split", lambda family, sql: ["CREATE TABLE a (i int)"])
    (row,) = record_family("postgresql", "floor", _inputs("x"), [ROW_A], frozen=True)
    assert row["sql"] == "CREATE TABLE a (i int)"
    assert row["old"] == OLD_A


def test_a_changed_statement_has_no_old_and_is_not_inherited(monkeypatch, activated: None) -> None:
    monkeypatch.setattr(record, "split", lambda family, sql: ["CREATE TABLE b (i int)"])
    (row,) = record_family("postgresql", "floor", _inputs("x"), [ROW_A], frozen=True)
    assert row["old"] is None


def test_a_row_the_split_still_produces_keeps_its_old_even_when_a_new_row_resembles_it(
    monkeypatch, activated: None
) -> None:
    pieces = ["CREATE TABLE a (i int);", "CREATE TABLE a (i int)"]
    monkeypatch.setattr(record, "split", lambda family, sql: pieces)
    rows = record_family("postgresql", "floor", _inputs("x"), [ROW_A], frozen=True)
    by_sql = {r["sql"]: r["old"] for r in rows}
    assert by_sql == {"CREATE TABLE a (i int);": OLD_A, "CREATE TABLE a (i int)": None}


def test_frozen_newest_arm_refreshes_facts_only(monkeypatch, activated: None) -> None:
    monkeypatch.setattr(record, "split", lambda family, sql: [sql])
    inputs = _inputs(ROW_A["sql"])
    floor = record_family("postgresql", "floor", inputs, [ROW_A], frozen=True)
    marked = [{**floor[0], "old_newest": {"hybrid": [], "analyzer": []}}]
    (row,) = record_family("postgresql", "newest", inputs, marked, frozen=True)
    assert row["old"] == OLD_A and row["old_newest"] == {"hybrid": [], "analyzer": []}


def test_normalised_text_drops_outer_blanks_and_one_terminator() -> None:
    assert normalise("  SELECT 1 ;\n") == "SELECT 1"
    assert normalise("SELECT 1;;") == "SELECT 1;"
    assert normalise("SELECT  1") == "SELECT  1"


def test_families_without_an_old_side_are_not_frozen(monkeypatch) -> None:
    monkeypatch.setattr(record, "split", lambda family, sql: [sql])
    (row,) = record_family("sqlite", "floor", _inputs("SELECT 1"), [])
    assert row["old"] is None
