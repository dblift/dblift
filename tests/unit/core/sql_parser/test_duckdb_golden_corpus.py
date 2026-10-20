"""A corpus of DuckDB scripts with the exact outputs of the scanner the shared engine replaced.

Each entry records what the public views returned for a script: the records (all nine fields,
offsets included), the execution strings, the extraction statements, the analysis statements the analyzer
reads, the script with its comments blanked, the masked and described text of every record, or the
refusal (class and message). The recording was made from the scanner that preceded the shared
lexical engine. The scripts are the shapes that found or guard a defect while the engine was
written (see ``name``), plus the few scripts that reach every branch of the segment path.
"""

import dataclasses
import json
from functools import lru_cache
from pathlib import Path
from typing import Any, Dict, List

import pytest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser.lexical_engine import LexicalEngine
from dblift.core.sql_parser.redaction import describe_statement, mask_string_literals
from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks


def recorded(record):
    """The fields the corpus records; ``execution_text`` is pinned by the string comparison."""
    return {k: v for k, v in dataclasses.asdict(record).items() if k != "execution_text"}


CORPUS = Path(__file__).with_name("duckdb_golden_corpus.json")
CHUNK = 50


@lru_cache(maxsize=None)
def entries() -> List[Dict[str, Any]]:
    loaded: List[Dict[str, Any]] = json.loads(CORPUS.read_text(encoding="utf-8"))
    return loaded


def evaluate(script: str) -> Dict[str, Any]:
    """The recorded views of one script, or its refusal."""
    parser = DuckDBRegexParser()
    try:
        records = parser.split(script)
        views = {
            "records": [recorded(r) for r in records],
            "strings": parser.split_statements(script),
            "extraction": parser.split_for_extraction(script),
            "analysis": SqlAnalyzer("duckdb").split_statements_for_analysis(script),
            "blanked": DuckDBQuirks().blank_comments(script),
            "masking": [
                [mask_string_literals(r.text, "duckdb"), describe_statement(r.text, "duckdb")]
                for r in records
            ],
        }
    except Exception as error:  # noqa: BLE001 - the class and text are what is recorded
        return {"error": [type(error).__name__, str(error)]}
    loaded: Dict[str, Any] = json.loads(json.dumps(views))
    return loaded


HISTORICAL_GAP_ROWS = {"74", "75"}


def describe(entry: Dict[str, Any]) -> str:
    """The entry's name, and for a historical gap why its snapshot may differ."""
    gap = entry.get("known_gap")
    if gap is None:
        return str(entry["name"])
    return (
        f"{entry['name']} records a historical gap (row {gap} of docs/sql-parsing/duckdb.md): "
        "the preserved scanner snapshot predates its fix"
    )


def test_the_corpus_is_small_and_named() -> None:
    assert 50 <= len(entries()) <= 500, len(entries())
    assert all(e["name"] for e in entries())
    assert len({e["name"] for e in entries()}) == len(entries())
    assert len({e["script"] for e in entries()}) == len(entries())
    assert CORPUS.read_bytes().isascii()


@pytest.mark.parametrize("chunk", range(0, len(entries()), CHUNK))
def test_the_engine_gives_the_recorded_views(chunk: int) -> None:
    for entry in entries()[chunk : chunk + CHUNK]:
        if entry.get("known_gap") in HISTORICAL_GAP_ROWS:
            continue  # the original scanner output is preserved; conformance rows cover the fix
        assert evaluate(entry["script"]) == entry["views"], describe(entry)


def test_the_engine_s_analysis_view_is_the_recorded_extraction() -> None:
    from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC

    engine = LexicalEngine(DUCKDB_SPEC)
    for entry in entries():
        if "error" not in entry["views"] and entry.get("known_gap") not in HISTORICAL_GAP_ROWS:
            assert (
                engine.split_for_analysis(entry["script"]) == entry["views"]["extraction"]
            ), entry["name"]


def test_historical_gap_entries_name_a_listed_row() -> None:
    marked = [e for e in entries() if "known_gap" in e]
    assert marked
    assert {e["known_gap"] for e in marked} <= HISTORICAL_GAP_ROWS
    assert {e["known_gap"] for e in marked} == HISTORICAL_GAP_ROWS


@pytest.mark.parametrize(
    "name,expected",
    [
        (
            "escape_mode_carried_across_blanks_on_one_line",
            [["SELECT E'?' '?'", "SELECT E"], ["SELECT 1", "SELECT 1"], ["SELECT '?'", "SELECT"]],
        ),
        (
            "escape_mode_survives_a_plain_string_between",
            [
                ["SELECT E'?' '?' '?'", "SELECT E"],
                ["SELECT 2", "SELECT 2"],
                ["SELECT '?'", "SELECT"],
            ],
        ),
        (
            "superscript_two_before_e",
            [["SELECT ²E'?'", "SELECT ²E"], ["c'?'", "c"]],
        ),
        (
            "arabic_digit_before_e",
            [["SELECT ٣E'?'", "SELECT ٣E"], ["c'?'", "c"]],
        ),
    ],
)
def test_current_masking_of_historical_boundary_cases(name, expected):
    script = next(entry["script"] for entry in entries() if entry["name"] == name)
    assert evaluate(script)["masking"] == expected


def test_the_entries_duckdb_accepts_have_matching_cuts() -> None:
    """Every entry DuckDB's own parser accepts has matching statement cuts."""
    import re

    import duckdb

    from dblift.db.plugins.duckdb.parser.lexical_spec import DUCKDB_SPEC

    tail = re.compile(r"^(?:[\s;]|--[^\r\n]*|/\*.*?\*/)*$", re.S)

    def agrees(cut: List[str], theirs: List[str]) -> bool:
        cut = [t.strip() for t in cut if not tail.match(t)]
        theirs = [t.strip() for t in theirs if not tail.match(t)]

        def same(a: str, b: str) -> bool:
            short, long_ = (a, b) if len(a) <= len(b) else (b, a)
            return long_.startswith(short) and bool(tail.match(long_[len(short) :]))

        return len(cut) == len(theirs) and all(same(a, b) for a, b in zip(cut, theirs))

    engine = LexicalEngine(DUCKDB_SPEC)
    blanks = {ord(c): " " for c in "\xa0\u202f\u205f\u2060\u3000\ufeff"}
    blanks.update({c: " " for c in range(0x2000, 0x200C)})
    for entry in entries():
        if "error" in entry["views"]:
            continue
        script = entry["script"]
        try:
            theirs = [q.query.translate(blanks) for q in duckdb.extract_statements(script)]
        except duckdb.Error:
            continue
        ours = [t.translate(blanks) for t in engine.split_statements(script)]
        assert agrees(ours, theirs), entry["name"]
