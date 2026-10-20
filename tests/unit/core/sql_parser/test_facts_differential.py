"""The comparison of the recorded object extraction with the statement facts, and its gate.

A family listed in ``gated.json`` fails here on any difference that is neither one of the
mechanical classes nor explained in its review file; other families are only counted. A review
entry that names no row, or a class the row does not have, fails in every family.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

from tests.support.facts_corpus import FAMILIES
from tests.support.facts_corpus import __main__ as cli
from tests.support.facts_corpus import differential, family_file, read_rows
from tests.support.facts_corpus.classes import (
    DEFAULT_SCHEMA,
    DIALECTS,
    NO_OLD_FAMILIES,
    ORDER,
    REVIEW,
)
from tests.support.facts_corpus.differential import (
    arm_row,
    check_review,
    classify_family,
    counts,
    current_arm,
    gated_families,
    reserved_words,
    skeleton,
)
from tests.support.facts_corpus.record import is_frozen

Results = List[Tuple[str, Dict[str, Any], Dict[str, str]]]


def _row(sql: str, facts: Any, old: Any) -> Dict[str, Any]:
    return {"sql": sql, "facts": facts, "old": old}


def _results() -> Results:
    """One agreeing row, one the reader names fewer objects for (on the analyzer path only)."""
    same = _row("CREATE TABLE a (i int)", {"objects": [["a", "TABLE", "created", None]]}, None)
    fewer = _row(
        "CREATE TABLE b (i int)",
        {"operation": "CREATE", "kind": "DDL", "objects": [["b", "TABLE", "created", None]]},
        {
            "hybrid": [["TABLE", "b", None]],
            "analyzer": [["TABLE", "default_schema.b"], ["INDEX", "default_schema.i"]],
        },
    )
    return [
        ("r1", same, {"hybrid": "same", "analyzer": "same"}),
        ("r2", fewer, {"hybrid": "same", "analyzer": "facts-fewer"}),
    ]


# which families are gated ------------------------------------------------------------------------


def test_only_families_whose_differences_are_explained_are_gated() -> None:
    assert gated_families() == ["db2", "mysql", "postgresql"]


def test_gated_families_are_known_families_with_a_reader() -> None:
    gated = gated_families()
    assert gated == sorted(gated) and set(gated) <= set(FAMILIES)
    assert not set(gated) & set(NO_OLD_FAMILIES), "a family with nothing to compare is not gated"


def test_every_family_has_a_review_file_of_entries_that_say_why() -> None:
    for family in FAMILIES:
        entries = json.loads(differential.review_file(family).read_text(encoding="utf-8"))
        for key, entry in entries.items():
            assert key.partition("/")[0] and {"sql", "path", "class", "reason"} <= set(entry), key
            assert entry["path"] in ("hybrid", "analyzer", "both")
            if isinstance(entry["class"], dict):
                assert set(entry["class"]) <= {"floor", "newest"}, key
                assert all(c in REVIEW + ("same",) for c in entry["class"].values()), key
                assert set(entry["class"].values()) != {"same"}, key
            else:
                assert entry["class"] in REVIEW, key


@pytest.mark.parametrize("family", FAMILIES)
def test_no_ledger_entry_is_stale_whether_or_not_its_family_is_gated(family: str) -> None:
    """Each entry names an existing row and the class that row has on this arm."""
    assert differential.report_family(family, current_arm())["stale"] == []


def _plant(monkeypatch: pytest.MonkeyPatch, tmp_path: Path, family: str, extra: Dict) -> None:
    """A copy of the family's ledger with ``extra`` added; the tracked file is not touched."""
    copy = tmp_path / f"{family}.review.json"
    copy.write_text(json.dumps({**differential.load_review(family), **extra}), encoding="utf-8")
    monkeypatch.setattr(differential, "review_file", lambda name: copy)


def _some_row(family: str) -> Tuple[str, str]:
    row_id, _, classes = classify_family(family, current_arm())[0]
    return row_id, classes["hybrid"]


@pytest.mark.parametrize("kind", ["wrong class", "no such row"])
def test_a_wrong_or_orphaned_ledger_entry_fails_a_family_that_is_not_gated(
    kind: str, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    row_id, actual = _some_row("snowflake")
    wrong = "disagree" if actual != "disagree" else "facts-fewer"
    key, entry_class = (
        (f"{row_id}/hybrid", wrong)
        if kind == "wrong class"
        else (
            "nosuchrow0000000/hybrid",
            "disagree",
        )
    )
    entry = {"sql": "s", "path": "hybrid", "class": entry_class, "reason": "ok"}
    _plant(monkeypatch, tmp_path, "snowflake", {key: entry})
    assert "snowflake" not in gated_families()
    assert differential.report_family("snowflake", current_arm())["stale"] == [key]
    assert differential.run(["snowflake"]) == 1
    assert differential.run(["snowflake"], report_only=True) == 0


def test_the_listed_families_have_no_unexplained_difference() -> None:
    for family in gated_families():
        report = differential.report_family(family, current_arm())
        assert report["unclassified"] == [] and report["stale"] == [], family


def test_a_family_planted_in_the_gate_fails_on_its_real_unexplained_rows(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setattr(differential, "gated_families", lambda: ["snowflake"])
    report = differential.report_family("snowflake", current_arm())
    assert report["gated"] and report["unclassified"], "the corpus has rows no entry explains"
    assert differential.run(["snowflake"]) == 1
    assert differential.run(["snowflake"], report_only=True) == 0


@pytest.mark.parametrize("family", FAMILIES)
def test_every_row_of_every_family_is_classified_on_this_arm(family: str) -> None:
    results = classify_family(family, current_arm())
    assert len(results) == len(read_rows(family_file(family)))
    assert {c for _, _, classes in results for c in classes.values()} <= set(ORDER)


def test_a_family_whose_extraction_is_the_reader_has_nothing_to_compare() -> None:
    for family in NO_OLD_FAMILIES:
        seen = {c for _, _, cl in classify_family(family, current_arm()) for c in cl.values()}
        assert seen == {"no-old-side"}


def test_default_schemas_are_the_ones_the_extraction_assigns() -> None:
    from tests.support.facts_corpus.record import is_frozen, record_statement

    for family in FAMILIES:
        if family in NO_OLD_FAMILIES or DIALECTS[family] is None or is_frozen(family):
            continue
        old = record_statement(family, "CREATE TABLE zz (a int)")["old"]
        assert old["hybrid"][0][2] == DEFAULT_SCHEMA.get(family), family
        assert old["analyzer"] == [["TABLE", "default_schema.zz"]], family


def test_reserved_words_are_the_recorded_vendor_lists() -> None:
    assert "IF" in reserved_words("mysql") and "IF" in reserved_words("sqlserver")
    assert "IF" not in reserved_words("postgresql")
    assert "COMMENT" not in reserved_words("postgresql")
    assert reserved_words("sqlite") == frozenset() == reserved_words("db2")


# the two arms --------------------------------------------------------------------------------


def test_the_newest_arm_reads_the_newest_fields_where_the_row_has_them() -> None:
    row = {"sql": "s", "facts": {"a": 1}, "old": {"b": 1}, "facts_newest": {"a": 2}}
    assert arm_row(row, "floor") == {"sql": "s", "facts": {"a": 1}, "old": {"b": 1}}
    assert arm_row(row, "newest") == {"sql": "s", "facts": {"a": 2}, "old": {"b": 1}}
    both = {**row, "old_newest": None}
    assert arm_row(both, "newest")["old"] is None


# review files -----------------------------------------------------------------------------------


def test_a_row_that_needs_a_reason_is_unclassified_until_the_file_gives_one() -> None:
    results = _results()
    assert check_review(results, {}, "newest")["unclassified"] == ["r2/analyzer"]
    empty = {"r2/analyzer": {"path": "analyzer", "class": "facts-fewer", "reason": ""}}
    assert check_review(results, empty, "newest")["unclassified"] == ["r2/analyzer"]
    given = {"r2/analyzer": {"path": "analyzer", "class": "facts-fewer", "reason": "ok"}}
    assert check_review(results, given, "newest") == {"unclassified": [], "stale": []}


def test_an_entry_for_the_other_path_does_not_cover_the_path_that_differs() -> None:
    wrong = {"r2/hybrid": {"path": "hybrid", "class": "facts-fewer", "reason": "ok"}}
    problems = check_review(_results(), wrong, "newest")
    assert problems == {"unclassified": ["r2/analyzer"], "stale": ["r2/hybrid"]}


def test_an_entry_for_a_row_that_is_gone_or_now_agrees_is_stale() -> None:
    entries = {
        "gone/analyzer": {"path": "analyzer", "class": "facts-fewer", "reason": "ok"},
        "r1/analyzer": {"path": "analyzer", "class": "facts-fewer", "reason": "ok"},
        "r2/analyzer": {"path": "analyzer", "class": "disagree", "reason": "ok"},
    }
    problems = check_review(_results(), entries, "newest")
    assert problems["stale"] == ["gone/analyzer", "r1/analyzer", "r2/analyzer"]
    assert problems["unclassified"] == ["r2/analyzer"]


def test_an_entry_for_both_paths_needs_the_same_class_on_both() -> None:
    results: Results = [("r", _row("s", {}, {}), {"hybrid": "disagree", "analyzer": "disagree"})]
    both = {"r": {"path": "both", "class": "disagree", "reason": "ok"}}
    assert check_review(results, both, "newest") == {"unclassified": [], "stale": []}
    results = [("r", _row("s", {}, {}), {"hybrid": "disagree", "analyzer": "facts-fewer"})]
    assert check_review(results, both, "newest")["stale"] == ["r"]


ARM_ROW: Results = [("r", _row("s", {}, {}), {"hybrid": "same", "analyzer": "same"})]


def _per_arm_entry(floor: str, newest: str) -> Dict[str, Any]:
    return {
        "r/hybrid": {
            "path": "hybrid",
            "class": {"floor": floor, "newest": newest},
            "reason": "differs by release",
            "issue": "#1",
        }
    }


def test_an_entry_can_hold_the_class_each_sqlglot_arm_gives() -> None:
    """A row that is ``same`` on one release and a reader gap on the other."""
    entry = _per_arm_entry("same", "opaque-reader-gap")
    floor: Results = [("r", _row("s", {}, {}), {"hybrid": "same", "analyzer": "same"})]
    newest: Results = [
        ("r", _row("s", {}, {}), {"hybrid": "opaque-reader-gap", "analyzer": "same"})
    ]
    assert check_review(floor, entry, "floor") == {"unclassified": [], "stale": []}
    assert check_review(newest, entry, "newest") == {"unclassified": [], "stale": []}


def test_an_entry_whose_class_for_the_running_arm_does_not_match_is_stale_on_that_arm() -> None:
    entry = _per_arm_entry("same", "opaque-reader-gap")
    newest: Results = [("r", _row("s", {}, {}), {"hybrid": "disagree", "analyzer": "same"})]
    floor: Results = [("r", _row("s", {}, {}), {"hybrid": "opaque-reader-gap", "analyzer": "same"})]
    assert check_review(newest, entry, "newest") == {
        "unclassified": ["r/hybrid"],
        "stale": ["r/hybrid"],
    }
    assert check_review(floor, entry, "floor")["stale"] == ["r/hybrid"]


def test_a_per_arm_reader_gap_names_an_issue_on_the_arm_that_has_the_gap() -> None:
    entry = _per_arm_entry("same", "opaque-reader-gap")
    newest: Results = [
        ("r", _row("s", {}, {}), {"hybrid": "opaque-reader-gap", "analyzer": "same"})
    ]
    del entry["r/hybrid"]["issue"]
    assert check_review(newest, entry, "newest")["unclassified"] == ["r/hybrid"]
    floor: Results = [("r", _row("s", {}, {}), {"hybrid": "same", "analyzer": "same"})]
    assert check_review(floor, entry, "floor") == {"unclassified": [], "stale": []}


def test_a_reader_gap_names_an_issue() -> None:
    results: Results = [
        ("r", _row("s", {}, {}), {"hybrid": "opaque-reader-gap", "analyzer": "same"})
    ]
    entry = {"path": "hybrid", "class": "opaque-reader-gap", "reason": "opaque is safer"}
    assert check_review(results, {"r/hybrid": entry}, "newest")["unclassified"] == ["r/hybrid"]
    assert (
        check_review(results, {"r/hybrid": {**entry, "issue": "#1"}}, "newest")["unclassified"]
        == []
    )


GOOD_REJECTION = {"postgresql 16.14": "42601", "mysql 8.4": "1064"}


def _gap_unclassified(entry: dict, cls: str = "opaque-reader-gap") -> list:
    results: Results = [("r", _row("s", {}, {}), {"hybrid": cls, "analyzer": "same"})]
    base = {"path": "hybrid", "class": cls, "reason": "the engine rejects it"}
    return check_review(results, {"r/hybrid": {**base, **entry}}, "newest")["unclassified"]


def test_a_reader_gap_the_engines_reject_is_explained_by_rejected_by() -> None:
    assert _gap_unclassified({"rejected_by": GOOD_REJECTION}) == []


@pytest.mark.parametrize(
    "rejected_by",
    [
        {},
        "42601",
        ["42601"],
        None,
        {"postgresql 16.14": ""},
        {"": "42601"},
        {"postgresql 16.14": 42601},
        {"postgresql 16.14": "42601", "mysql 8.4": " "},
    ],
)
def test_a_malformed_rejected_by_does_not_explain_a_reader_gap(rejected_by: object) -> None:
    assert _gap_unclassified({"rejected_by": rejected_by}) == ["r/hybrid"]


def test_an_issue_still_explains_a_reader_gap_alone() -> None:
    assert _gap_unclassified({"issue": "#1"}) == []
    assert _gap_unclassified({"issue": "#1", "rejected_by": {}}) == []


def test_rejected_by_is_ignored_for_a_class_that_is_not_a_reader_gap() -> None:
    assert _gap_unclassified({"rejected_by": {}}, "disagree") == []
    assert _gap_unclassified({"reason": " ", "rejected_by": GOOD_REJECTION}) == ["r/hybrid"]


def test_an_entry_that_lacks_the_running_arm_is_stale_on_that_arm() -> None:
    entry = {"r/hybrid": {**_per_arm_entry("same", "disagree")["r/hybrid"]}}
    entry["r/hybrid"]["class"] = {"floor": "disagree"}
    row: Results = [("r", _row("s", {}, {}), {"hybrid": "disagree", "analyzer": "same"})]
    assert check_review(row, entry, "floor") == {"unclassified": [], "stale": []}
    assert check_review(row, entry, "newest") == {
        "unclassified": ["r/hybrid"],
        "stale": ["r/hybrid"],
    }


def test_an_entry_whose_class_is_same_explains_nothing_and_is_stale() -> None:
    results: Results = [("r", _row("s", {}, {}), {"hybrid": "same", "analyzer": "same"})]
    for value in ("same", {"floor": "same", "newest": "same"}):
        entry = {"r/hybrid": {"path": "hybrid", "class": value, "reason": "ok"}}
        assert check_review(results, entry, "newest")["stale"] == ["r/hybrid"], value
    mixed = _per_arm_entry("same", "disagree")
    assert check_review(results, mixed, "floor") == {"unclassified": [], "stale": []}


def test_the_skeleton_fills_only_the_running_arm_of_an_entry_and_keeps_the_other() -> None:
    results: Results = [("r", _row("s", {}, {}), {"hybrid": "facts-fewer", "analyzer": "same"})]
    kept = _per_arm_entry("opaque-reader-gap", "opaque-reader-gap")
    kept["r/hybrid"]["class"] = {"floor": "opaque-reader-gap"}
    out = skeleton(results, kept, "newest")
    assert out["r/hybrid"]["class"] == {"floor": "opaque-reader-gap", "newest": "facts-fewer"}
    assert out["r/hybrid"]["reason"] == "differs by release" and out["r/hybrid"]["issue"] == "#1"
    assert out["r/hybrid"]["unreviewed"] == ["newest"]
    assert set(out) == {"r/hybrid"}
    assert check_review(results, out, "floor")["stale"] == ["r/hybrid"]  # the floor is rechecked


def test_the_skeleton_keeps_the_other_arm_of_a_class_that_no_longer_holds_here() -> None:
    results: Results = [("r", _row("s", {}, {}), {"hybrid": "facts-fewer", "analyzer": "same"})]
    wrong = {"r/hybrid": {"path": "hybrid", "class": "disagree", "reason": "why", "issue": ""}}
    out = skeleton(results, wrong, "newest")
    assert out["r/hybrid"]["class"] == {"floor": "disagree", "newest": "facts-fewer"}
    assert out["r/hybrid"]["reason"] == "why" and out["r/hybrid"]["unreviewed"] == ["newest"]
    assert check_review(results, out, "newest")["unclassified"] == ["r/hybrid"]


def test_a_reason_written_for_another_class_does_not_explain_the_class_the_skeleton_set(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    results: Results = [
        ("r", _row("s", {}, {}), {"hybrid": "facts-adds-acted", "analyzer": "same"})
    ]
    monkeypatch.setattr(differential, "classify_family", lambda family, arm: results)
    monkeypatch.setattr(differential, "review_file", lambda family: tmp_path / "f.json")
    monkeypatch.setattr(differential, "current_arm", lambda: "floor")
    monkeypatch.setattr(differential, "gated_families", lambda: [])
    ledger = tmp_path / "f.json"
    entry = {"path": "hybrid", "class": "disagree", "reason": "R", "issue": ""}
    ledger.write_text(json.dumps({"r/hybrid": entry}), encoding="utf-8")
    assert differential.run(["f"], write=True) == 1  # the entry was stale
    assert differential.run(["f"]) == 0  # not gated
    after = differential.report_family("f", "floor")
    assert after["stale"] == [] and after["unclassified"] == ["r/hybrid"]
    written = json.loads(ledger.read_text(encoding="utf-8"))["r/hybrid"]
    assert written["class"] == {"floor": "facts-adds-acted", "newest": "disagree"}
    assert written["reason"] == "R" and written["unreviewed"] == ["floor"]
    del written["unreviewed"]  # a person read the row and kept the reason
    ledger.write_text(json.dumps({"r/hybrid": written}), encoding="utf-8")
    assert differential.report_family("f", "floor")["unclassified"] == []


def test_the_skeleton_drops_an_entry_whose_row_is_gone_or_whose_class_explains_nothing() -> None:
    results: Results = [("r", _row("s", {}, {}), {"hybrid": "same", "analyzer": "same"})]
    gone = {"x/hybrid": {"path": "hybrid", "class": "disagree", "reason": "why"}}
    pointless = {"r/hybrid": {"path": "hybrid", "class": "same", "reason": "why"}}
    assert skeleton(results, {**gone, **pointless}, "newest") == {}


def test_the_skeleton_adds_an_empty_entry_for_each_unexplained_row_and_keeps_the_rest() -> None:
    kept = {"r2/analyzer": {"path": "analyzer", "class": "facts-fewer", "reason": "ok"}}
    assert skeleton(_results(), kept, "newest") == kept
    out = skeleton(_results(), {}, "newest")
    assert set(out) == {"r2/analyzer"}
    assert out["r2/analyzer"]["reason"] == "" and out["r2/analyzer"]["class"] == "facts-fewer"
    both: Results = [
        (
            "r",
            _row("s", {"objects": []}, {"hybrid": [], "analyzer": []}),
            {"hybrid": "disagree", "analyzer": "disagree"},
        )
    ]
    assert (
        set(skeleton(both, {}, "newest")) == {"r"}
        and skeleton(both, {}, "newest")["r"]["path"] == "both"
    )


def test_counts_are_per_path_in_rule_order() -> None:
    assert counts(_results()) == {
        "hybrid": {"same": 2},
        "analyzer": {"same": 1, "facts-fewer": 1},
    }


# the gate --------------------------------------------------------------------------------------


@pytest.fixture
def fabricated(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(differential, "classify_family", lambda family, arm: _results())
    monkeypatch.setattr(differential, "load_review", lambda family: {})


def test_the_gate_fails_a_listed_family_with_an_unexplained_row(
    fabricated: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(differential, "gated_families", lambda: ["postgresql"])
    assert differential.run(["postgresql"]) == 1
    assert "postgresql" in capsys.readouterr().out
    assert differential.report_family("postgresql", "floor")["unclassified"] == ["r2/analyzer"]


def test_the_gate_passes_a_family_that_is_not_listed(
    fabricated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(differential, "gated_families", lambda: ["sqlite"])
    assert differential.run(["postgresql"]) == 0


def test_report_only_prints_and_never_fails(
    fabricated: None, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(differential, "gated_families", lambda: ["postgresql"])
    assert differential.run(["postgresql"], report_only=True) == 0


def test_a_stale_entry_fails_a_family_that_is_not_listed(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(differential, "classify_family", lambda family, arm: _results())
    stale = {"r1/hybrid": {"path": "hybrid", "class": "disagree", "reason": "ok"}}
    monkeypatch.setattr(differential, "load_review", lambda family: stale)
    monkeypatch.setattr(differential, "gated_families", lambda: [])
    assert differential.run(["postgresql"]) == 1
    assert differential.run(["postgresql"], report_only=True) == 0


def test_a_stale_entry_fails_a_listed_family(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(differential, "classify_family", lambda family, arm: _results())
    stale = {"r1/hybrid": {"path": "hybrid", "class": "disagree", "reason": "ok"}}
    monkeypatch.setattr(differential, "load_review", lambda family: stale)
    monkeypatch.setattr(differential, "gated_families", lambda: ["postgresql"])
    assert differential.report_family("postgresql", "floor")["stale"] == ["r1/hybrid"]
    assert differential.run(["postgresql"]) == 1


def test_the_command_applies_the_same_rule(
    fabricated: None, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture
) -> None:
    monkeypatch.setattr(differential, "gated_families", lambda: ["postgresql"])
    assert cli.main(["diff", "postgresql"]) == 1
    assert cli.main(["diff", "postgresql", "--report"]) == 0
    capsys.readouterr()
    assert cli.main(["diff", "postgresql", "--report", "--json"]) == 0
    printed = json.loads(capsys.readouterr().out)
    assert printed["families"]["postgresql"]["counts"]["analyzer"] == {"same": 1, "facts-fewer": 1}


def test_the_command_rejects_an_unknown_family() -> None:
    assert cli.main(["diff", "nosuch"]) == 2


def test_skeleton_flag_writes_the_empty_entries(
    fabricated: None, monkeypatch: pytest.MonkeyPatch, tmp_path
) -> None:
    monkeypatch.setattr(differential, "review_file", lambda family: tmp_path / f"{family}.json")
    monkeypatch.setattr(differential, "gated_families", lambda: [])
    assert cli.main(["diff", "postgresql", "--skeleton"]) == 0
    written = json.loads((tmp_path / "postgresql.json").read_text(encoding="utf-8"))
    assert list(written) == ["r2/analyzer"] and written["r2/analyzer"]["reason"] == ""


@pytest.mark.parametrize("unreviewed", ["newset", "floor", ["newset"], ["floor", 1], None])
def test_unreviewed_must_be_a_list_of_known_arms(
    monkeypatch: pytest.MonkeyPatch, unreviewed: Any
) -> None:
    """A misspelt arm would leave the arm explained; a string would match by substring."""
    results: Results = [("r", _row("s", {}, {}), {"hybrid": "disagree", "analyzer": "same"})]
    entry = {"path": "hybrid", "class": "disagree", "reason": "ok", "unreviewed": unreviewed}
    assert check_review(results, {"r/hybrid": entry}, "floor")["stale"] == ["r/hybrid"]
    monkeypatch.setattr(differential, "classify_family", lambda family, arm: results)
    monkeypatch.setattr(differential, "load_review", lambda family: {"r/hybrid": entry})
    monkeypatch.setattr(differential, "gated_families", lambda: [])
    assert differential.run(["f"]) == 1


@pytest.mark.parametrize("unreviewed", [[], ["floor"], ["floor", "newest"]])
def test_unreviewed_lists_known_arms(unreviewed: List[str]) -> None:
    results: Results = [("r", _row("s", {}, {}), {"hybrid": "disagree", "analyzer": "same"})]
    entry = {"path": "hybrid", "class": "disagree", "reason": "ok", "unreviewed": unreviewed}
    assert check_review(results, {"r/hybrid": entry}, "floor")["stale"] == []
