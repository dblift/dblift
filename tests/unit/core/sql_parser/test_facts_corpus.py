"""The statement facts snapshot corpus: schema, stability, growth, and reserved-word lists."""

from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, List

import pytest
import sqlglot

from tests.support.facts_corpus import (
    CORPUS_DIR,
    FAMILIES,
    INPUTS_FILE,
    REPO_ROOT,
    family_file,
    read_rows,
    read_versions,
    statement_id,
)
from tests.support.facts_corpus.record import is_frozen, record_statement
from tests.support.facts_corpus.seed import split

NO_OLD = ("sqlite", "duckdb")  # their text extraction already is the facts reader
RESERVED_FAMILIES = (
    "postgresql",
    "mysql",
    "oracle",
    "sqlserver",
    "duckdb",
    "redshift",
    "snowflake",
)
ROW_KEYS = {"sql", "inputs", "facts", "old", "facts_newest", "old_newest"}

# (family, word, page wording) -- one reserved word and one word the page does not reserve.
SPOT_CHECKS: Dict[str, Dict[str, Any]] = {
    "postgresql": {
        "in": [("SELECT", "SELECT | reserved | reserved | reserved | reserved")],
        "out": ("COMMENT", "COMMENT | non-reserved"),
    },
    "mysql": {
        "in": [
            ("SELECT", "SELECT (R)"),
            ("PERCENT_RANK", "PERCENT_RANK (R); added in 8.0.2 (reserved)"),
        ],
        "out": ("COMMENT", "COMMENT"),
    },
    "oracle": {
        "in": [("SELECT", "SELECT *")],
        "out": ("TYPE", 'TYPE: not on the reserved list; "Oracle SQL keywords are not reserved"'),
    },
    "sqlserver": {
        "in": [("SELECT", "SELECT")],
        "out": ("ABSOLUTE", "ABSOLUTE under Future Keywords: could be reserved in future releases"),
    },
    "redshift": {
        "in": [("SELECT", "SELECT")],
        "out": ("START", "While START and CONNECT are not reserved words"),
    },
    "snowflake": {
        "in": [("SELECT", "SELECT Reserved by ANSI.")],
        "out": ("LEFT", "LEFT Cannot be used as table name or alias in a FROM clause."),
    },
    "duckdb": {
        "in": [
            ("SELECT", "They must not be a reserved keyword ... SELECT 123 AS SELECT will fail")
        ],
        "out": ("COMMENT", "COMMENT: duckdb_keywords() category 'unreserved'"),
    },
}


def _on_this_arm(row: Dict[str, Any]) -> Dict[str, Any]:
    """The row's ``facts`` and ``old`` as recorded for the installed sqlglot."""
    versions = read_versions()
    newest = sqlglot.__version__ == versions["newest"] != versions["floor"]
    if not newest:
        return {"facts": row["facts"], "old": row["old"]}
    return {
        "facts": row.get("facts_newest", row["facts"]),
        "old": row.get("old_newest", row["old"]),
    }


@pytest.fixture(scope="module")
def corpus() -> Dict[str, List[Dict[str, Any]]]:
    return {family: read_rows(family_file(family)) for family in FAMILIES}


@pytest.fixture(scope="module")
def inputs() -> List[Dict[str, Any]]:
    return read_rows(INPUTS_FILE)


def test_inputs_are_identified_by_their_text_and_unique(inputs: List[Dict[str, Any]]) -> None:
    ids = [row["id"] for row in inputs]
    assert ids == sorted(set(ids))
    assert all(row["id"] == statement_id(row["sql"]) for row in inputs)
    for row in inputs:
        assert set(row) == {"id", "sql", "origins"}
        assert all(set(o) == {"file", "dialects"} for o in row["origins"])


def test_inputs_are_only_ever_added(inputs: List[Dict[str, Any]]) -> None:
    base = (CORPUS_DIR / "input_ids.txt").read_text(encoding="utf-8").split()
    assert base == sorted(set(base)) and len(base) == read_versions()["inputs"]
    assert set(base) <= {row["id"] for row in inputs}


@pytest.mark.parametrize("family", FAMILIES)
def test_rows_follow_the_schema(
    family: str, corpus: Dict[str, List[Dict[str, Any]]], inputs: List[Dict[str, Any]]
) -> None:
    known = {row["id"] for row in inputs}
    assert corpus[family], "no rows recorded"
    for row in corpus[family]:
        assert set(row) <= ROW_KEYS and {"sql", "inputs", "facts", "old"} <= set(row), row["sql"]
        assert isinstance(row["sql"], str) and row["sql"].strip()
        assert row["inputs"] == sorted(set(row["inputs"])) and set(row["inputs"]) <= known
        if not is_frozen(family):  # a frozen family's new statement has no recorded extraction
            assert (row["old"] is None) == (family in NO_OLD)
        assert row["facts"] is not None
        if row["old"] is not None:
            assert {"hybrid", "analyzer"} <= set(row["old"]) <= {"hybrid", "analyzer", "dml"}


@pytest.mark.parametrize("family", FAMILIES)
def test_rows_are_deduplicated_and_sorted_by_statement_text(
    family: str, corpus: Dict[str, List[Dict[str, Any]]]
) -> None:
    texts = [row["sql"] for row in corpus[family]]
    assert texts == sorted(set(texts))


@pytest.mark.parametrize("family", FAMILIES)
def test_every_statement_splits_back_to_itself_except_the_recorded_ones(
    family: str, corpus: Dict[str, List[Dict[str, Any]]]
) -> None:
    unstable = []
    for row in corpus[family]:
        try:
            again = split(family, row["sql"])
        except Exception:
            again = None  # the splitter refuses the lone statement
        if again != [row["sql"]]:
            unstable.append(statement_id(row["sql"]))
    expected = json.loads((CORPUS_DIR / "not_idempotent.json").read_text(encoding="utf-8"))
    assert unstable == expected[family]


def test_corpus_size_stays_within_a_fifth_of_the_first_recording() -> None:
    versions = read_versions()
    size = sum(path.stat().st_size for path in CORPUS_DIR.glob("*.jsonl"))
    assert 0 < versions["size_bytes"] and size <= 1.2 * versions["size_bytes"]


def test_both_sqlglot_arms_are_recorded(corpus: Dict[str, List[Dict[str, Any]]]) -> None:
    versions = read_versions()
    pyproject = (REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8")
    assert f'"sqlglot>={versions["floor"]},<' in pyproject
    assert versions["floor"] != versions["newest"]
    counts = {
        family: sum(1 for r in rows if "facts_newest" in r or "old_newest" in r)
        for family, rows in corpus.items()
    }
    assert counts == versions["newest_differing_rows"]
    assert sum(counts.values()) > 0


@pytest.mark.parametrize("family", FAMILIES)
def test_rows_match_what_the_installed_sqlglot_reads_now(
    family: str, corpus: Dict[str, List[Dict[str, Any]]]
) -> None:
    versions = read_versions()
    installed = sqlglot.__version__
    if installed not in (versions["floor"], versions["newest"]):
        pytest.skip(f"sqlglot {installed} is neither recorded arm")
    newest = installed == versions["newest"] and installed != versions["floor"]
    for row in corpus[family]:
        now = record_statement(family, row["sql"])
        want_facts = row.get("facts_newest", row["facts"]) if newest else row["facts"]
        want_old = row.get("old_newest", row["old"]) if newest else row["old"]
        assert now["facts"] == want_facts, row["sql"]
        if not is_frozen(family):  # its extraction is carried, never recomputed
            assert now["old"] == want_old, row["sql"]


def _reserved(family: str) -> Dict[str, Any]:
    lines = (CORPUS_DIR / "reserved" / f"{family}.txt").read_text(encoding="utf-8").splitlines()
    header = {
        k: v
        for k, v in (m.groups() for m in map(re.compile(r"# (\w+): (.*)").fullmatch, lines) if m)
    }
    words = [line for line in lines if line and not line.startswith("#")]
    return {"header": header, "words": words}


@pytest.mark.parametrize("family", RESERVED_FAMILIES)
def test_reserved_list_carries_its_provenance_and_only_words(family: str) -> None:
    listing = _reserved(family)
    header = listing["header"]
    assert re.fullmatch(r"https://\S+", header["source"])
    assert re.fullmatch(r"\d{4}-\d{2}-\d{2}", header["retrieved"])
    assert header["engine"] and header["category"]
    words = listing["words"]
    assert words == sorted(set(words)) and len(words) > 50
    assert all(re.fullmatch(r"[A-Z_][A-Z_0-9]*( GROUP)?", word) for word in words)


@pytest.mark.parametrize("family", RESERVED_FAMILIES)
def test_reserved_list_agrees_with_the_vendor_page_on_two_words(family: str) -> None:
    words = set(_reserved(family)["words"])
    checks = SPOT_CHECKS[family]
    for word, wording in checks["in"]:
        assert word in words
        assert word.lower() in wording.lower()
    word, wording = checks["out"]
    assert word not in words
    assert word.lower() in wording.lower()


@pytest.mark.parametrize("family", ("sqlite", "db2"))
def test_families_without_a_vendor_reserved_list_have_none(family: str) -> None:
    assert not (CORPUS_DIR / "reserved" / f"{family}.txt").exists()


POSTGRESQL_DERIVATIVES = (
    "alloydb",
    "aurora-postgresql",
    "citus",
    "cockroachdb",
    "neon",
    "supabase",
    "timescaledb",
    "yugabytedb",
)


def test_postgresql_derivatives_record_exactly_what_postgresql_does(
    corpus: Dict[str, List[Dict[str, Any]]],
) -> None:
    for derivative in POSTGRESQL_DERIVATIVES:
        for row in corpus["postgresql"]:
            now = record_statement(derivative, row["sql"])
            assert now == _on_this_arm(row), (derivative, row["sql"])


def test_mariadb_differs_from_mysql_only_in_the_client_command_error_text(
    corpus: Dict[str, List[Dict[str, Any]]],
) -> None:
    differing = {}
    for row in corpus["mysql"]:
        now = record_statement("mariadb", row["sql"])
        want = _on_this_arm(row)
        if now != want:
            differing[row["sql"]] = (want["old"]["hybrid"], now["old"]["hybrid"])
            assert now["facts"] == want["facts"]
            assert now["old"]["analyzer"] == want["old"]["analyzer"]
    assert list(differing) == ["GO"]
    mysql_error, mariadb_error = (v["raised"] for v in differing["GO"])
    assert mysql_error.replace("mysql", "mariadb") == mariadb_error
