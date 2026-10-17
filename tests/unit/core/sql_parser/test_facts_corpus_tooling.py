"""Tooling behind the statement facts corpus: encoding, harvesting, seeding, recording."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import NamedObject, StatementFacts
from tests.support.facts_corpus import statement_id
from tests.support.facts_corpus.canonical import compact_facts, dumps
from tests.support.facts_corpus.measure import update_versions
from tests.support.facts_corpus.record import check_arm, record_family, record_statement
from tests.support.facts_corpus.seed import (
    assert_only_added,
    harvest,
    merge_inputs,
    seed,
    source_files,
    split,
)

SELECT_FILE = """
def test_a():
    parse_sql("CREATE TABLE t (id int)")
    parse_sql("-- lead\\n/* block */ DROP TABLE t")
    parse_sql(f"CREATE TABLE {name} (id int)")
    parse_sql("not sql at all")
    parse_sql(name + "x")
"""


def _tree(tmp_path: Path, body: str = SELECT_FILE) -> Path:
    tests = tmp_path / "tests" / "unit"
    tests.mkdir(parents=True)
    (tests / "test_one.py").write_text(body, encoding="utf-8")
    (tests / "test_unrelated.py").write_text('X = "CREATE TABLE z (a int)"\n', encoding="utf-8")
    return tmp_path


def test_canonical_encoding_is_stable_and_order_independent() -> None:
    assert dumps({"b": 1, "a": [1, 2]}) == dumps({"a": [1, 2], "b": 1})
    assert dumps({"a": "é"}) == '{"a":"\\u00e9"}'


def test_compact_facts_drops_empty_sorts_events_and_uses_enum_values() -> None:
    facts = StatementFacts(
        operation="UPDATE",
        kind="DML",
        objects=(NamedObject("t", SqlObjectType.TABLE, "altered", "s"),),
        target="t",
        events=frozenset({"UPDATE", "INSERT"}),
    )
    assert compact_facts(facts) == {
        "operation": "UPDATE",
        "kind": "DML",
        "objects": [["t", "TABLE", "altered", "s"]],
        "target": "t",
        "events": ["INSERT", "UPDATE"],
    }


def test_source_files_are_the_files_calling_the_two_entry_points(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    assert source_files(root) == ["tests/unit/test_one.py"]


def test_harvest_keeps_sql_constants_only(tmp_path: Path) -> None:
    found = {row["sql"] for row in harvest(_tree(tmp_path))}
    assert found == {"CREATE TABLE t (id int)", "-- lead\n/* block */ DROP TABLE t"}


def test_harvest_skips_constants_over_4000_characters(tmp_path: Path) -> None:
    big = "SELECT '" + "a" * 4000 + "'"
    root = _tree(tmp_path, f"def test_a():\n    parse_sql({big!r})\n    parse_sql('SELECT 1')\n")
    assert [row["sql"] for row in harvest(root)] == ["SELECT 1"]


def test_harvest_merges_origins_of_a_repeated_script(tmp_path: Path) -> None:
    root = _tree(tmp_path, "def test_a():\n    parse_sql('SELECT 1')\n    parse_sql('SELECT 1')\n")
    (row,) = harvest(root)
    assert row["id"] == statement_id("SELECT 1")
    assert row["origins"] == [{"file": "tests/unit/test_one.py", "dialects": []}]


def test_merge_never_drops_an_input_and_guard_rejects_a_removal() -> None:
    old = [{"id": "a", "sql": "SELECT 1", "origins": []}]
    assert [r["id"] for r in merge_inputs(old, [])] == ["a"]
    with pytest.raises(ValueError, match="removed"):
        assert_only_added(old, [])


def test_seed_is_deterministic_and_keeps_inputs_of_a_removed_test(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    inputs, sources = tmp_path / "inputs.jsonl", tmp_path / "SOURCES.md"
    assert seed(root, inputs, sources) == 2
    first = inputs.read_bytes()
    assert seed(root, inputs, sources) == 2
    assert inputs.read_bytes() == first
    (root / "tests/unit/test_one.py").unlink()
    assert seed(root, inputs, sources) == 2
    assert inputs.read_bytes() == first
    assert "tests/unit/test_one.py" not in sources.read_text(encoding="utf-8")


def test_split_uses_the_family_analysis_splitter() -> None:
    assert split("postgresql", "SELECT 1;\nSELECT 2;") == ["SELECT 1", "SELECT 2"]


def test_record_statement_freezes_both_old_paths_and_dml() -> None:
    row = record_statement("postgresql", "UPDATE s.t SET a = 1 WHERE b = 2")
    assert row["facts"]["objects"] == [["t", "TABLE", "altered", "s"]]
    assert set(row["old"]) == {"hybrid", "analyzer", "dml"}
    assert row["old"]["dml"] == {
        "table": "s.t",
        "events": ["UPDATE"],
        "updated_columns": ["a"],
        "predicate": "b = 2",
        "full_table": False,
    }
    assert isinstance(row["old"]["hybrid"], list) and isinstance(row["old"]["analyzer"], list)


def test_record_statement_for_families_without_old_or_without_reader() -> None:
    assert record_statement("sqlite", "CREATE TABLE t (a int)")["old"] is None
    assert record_statement("db2", "CREATE TABLE t (a int)")["facts"] is None


def test_inactive_family_reads_facts_through_the_sqlglot_reader() -> None:
    row = record_statement("mysql", "CREATE TABLE t (a int)")
    assert row["facts"]["objects"] == [["t", "TABLE", "created", None]]


def test_record_family_dedups_by_statement_text_sorted_with_input_ids() -> None:
    inputs = [
        {"id": "i1", "sql": "SELECT 1;\nSELECT 2;", "origins": []},
        {"id": "i2", "sql": "SELECT 2;", "origins": []},
    ]
    rows = record_family("postgresql", "floor", inputs, [])
    assert [(r["sql"], r["inputs"]) for r in rows] == [
        ("SELECT 1", ["i1"]),
        ("SELECT 2", ["i1", "i2"]),
    ]


def test_newest_arm_adds_only_differences_and_needs_the_floor_rows() -> None:
    inputs = [{"id": "i1", "sql": "SELECT 1", "origins": []}]
    floor = record_family("postgresql", "floor", inputs, [])
    again = record_family("postgresql", "newest", inputs, floor)
    assert [r for r in again if "facts_newest" in r or "old_newest" in r] == [
        r for r in floor if "facts_newest" in r or "old_newest" in r
    ]
    assert [r["sql"] for r in again] == [r["sql"] for r in floor]
    with pytest.raises(ValueError, match="floor"):
        record_family("postgresql", "newest", inputs, [])


def test_recorder_refuses_a_sqlglot_that_is_neither_floor_nor_newest() -> None:
    versions = {"floor": "30.18.0", "newest": "30.23.0"}
    check_arm("floor", "30.18.0", versions)
    check_arm("newest", "30.23.0", versions)
    with pytest.raises(RuntimeError, match="30.20.0"):
        check_arm("floor", "30.20.0", versions)
    with pytest.raises(RuntimeError):
        check_arm("newest", "30.18.0", versions)
    assert json.loads(dumps(versions)) == versions


CALLS_FILE = '''"""DROP TABLE in a module docstring."""
X = "CREATE TABLE z (a int)"
SQL = "ALTER TABLE a ADD b int"
SCRIPT = "import sys; DROP TABLE not_sql"


def test_a():
    """CREATE INDEX in a function docstring."""
    parse_sql("CREATE TABLE t (id int)")
    analyzer.extract_objects("DROP TABLE t")
    parse_sql(SQL)
    log("SELECT 9")
    assert "INSERT INTO" in out
    assert out and "DELETE FROM x" not in out
    assert ok, "UPDATE t failed"
    raise ValueError("lock timeout exceeded")
'''


def test_harvest_skips_docstrings_messages_and_foreign_scripts(tmp_path: Path) -> None:
    found = {row["sql"] for row in harvest(_tree(tmp_path, CALLS_FILE))}
    assert found == {
        "CREATE TABLE z (a int)",
        "ALTER TABLE a ADD b int",
        "CREATE TABLE t (id int)",
        "DROP TABLE t",
    }


def test_source_files_exclude_the_corpus_package_itself(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    own = root / "tests" / "support" / "facts_corpus"
    own.mkdir(parents=True)
    (own / "seed.py").write_text('extract_objects("SELECT 1")\n', encoding="utf-8")
    assert source_files(root) == ["tests/unit/test_one.py"]


def test_seed_output_does_not_depend_on_line_numbers(tmp_path: Path) -> None:
    root = _tree(tmp_path)
    inputs, sources = tmp_path / "inputs.jsonl", tmp_path / "SOURCES.md"
    seed(root, inputs, sources)
    first = inputs.read_bytes()
    path = root / "tests/unit/test_one.py"
    path.write_text("\n\n\n" + path.read_text(encoding="utf-8"), encoding="utf-8")
    inputs.unlink()
    seed(root, inputs, sources)
    assert inputs.read_bytes() == first


def test_versions_first_measurement_is_taken_as_is() -> None:
    measured = {"size_bytes": 100, "inputs": 10, "newest_differing_rows": {"a": 1}}
    assert update_versions({"floor": "1", "newest": "2"}, measured, [], ["a"]) == {
        "floor": "1",
        "newest": "2",
        **measured,
    }


def test_versions_keep_the_first_size_and_never_lower_the_inputs() -> None:
    existing = {
        "floor": "1",
        "newest": "2",
        "size_bytes": 100,
        "inputs": 10,
        "newest_differing_rows": {},
    }
    ids = [str(i) for i in range(12)]
    measured = {"size_bytes": 900, "inputs": 12, "newest_differing_rows": {"a": 3}}
    result = update_versions(existing, measured, ids[:10], ids)
    assert result["size_bytes"] == 100
    assert result["inputs"] == 12
    assert result["newest_differing_rows"] == {"a": 3}
    with pytest.raises(ValueError, match="inputs"):
        update_versions(existing, {**measured, "inputs": 9}, ids[:10], ids[:9])


def test_versions_refuse_a_swapped_input() -> None:
    existing = {"size_bytes": 100, "inputs": 3, "newest_differing_rows": {}}
    measured = {"size_bytes": 100, "inputs": 3, "newest_differing_rows": {}}
    with pytest.raises(ValueError, match="removed"):
        update_versions(existing, measured, ["a", "b", "c"], ["a", "b", "z"])
