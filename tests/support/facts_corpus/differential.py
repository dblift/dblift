"""Compare the frozen object extraction with the statement facts, per family and per path."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any, Dict, FrozenSet, List, Optional, Tuple

import sqlglot

from tests.support.facts_corpus import (
    CORPUS_DIR,
    FAMILIES,
    family_file,
    read_rows,
    read_versions,
    statement_id,
)
from tests.support.facts_corpus.canonical import dumps
from tests.support.facts_corpus.classes import (
    OPAQUE_READER_GAP,
    ORDER,
    PATHS,
    REVIEW,
    classify_row,
)

GATED_FILE = CORPUS_DIR / "gated.json"
SQL_EXCERPT = 120
Entry = Dict[str, Any]


def review_file(family: str) -> Path:
    """The file holding the reasons a family's differing rows are accepted."""
    return CORPUS_DIR / f"{family}.review.json"


def gated_families() -> List[str]:
    """The families whose differences must all be classified or explained."""
    return json.loads(GATED_FILE.read_text(encoding="utf-8"))


def reserved_words(family: str) -> FrozenSet[str]:
    """The vendor's reserved words recorded for a family (none when the family has no list)."""
    path = CORPUS_DIR / "reserved" / f"{family}.txt"
    if not path.exists():
        return frozenset()
    lines = path.read_text(encoding="utf-8").splitlines()
    return frozenset(line.strip().upper() for line in lines if line.strip() and line[0] != "#")


def current_arm() -> str:
    """``floor`` when the installed sqlglot is the recorded floor, otherwise ``newest``."""
    return "floor" if sqlglot.__version__ == read_versions()["floor"] else "newest"


def arm_row(row: Dict[str, Any], arm: str) -> Dict[str, Any]:
    """A corpus row reduced to the facts and extraction recorded for one sqlglot arm."""
    if arm == "floor":
        return {"sql": row["sql"], "facts": row["facts"], "old": row["old"]}
    return {
        "sql": row["sql"],
        "facts": row.get("facts_newest", row["facts"]),
        "old": row.get("old_newest", row["old"]),
    }


def classify_family(family: str, arm: str) -> List[Tuple[str, Dict[str, Any], Dict[str, str]]]:
    """``(row id, arm row, class per path)`` for every row of a family."""
    reserved = reserved_words(family)
    out = []
    for row in read_rows(family_file(family)):
        view = arm_row(row, arm)
        out.append((statement_id(row["sql"]), view, classify_row(view, family, reserved)))
    return out


def load_review(family: str) -> Dict[str, Entry]:
    """The review entries of a family (an absent file has none)."""
    path = review_file(family)
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}


def _needed(classes: Dict[str, str]) -> Dict[str, str]:
    return {path: cls for path, cls in classes.items() if cls in REVIEW}


def _entry_paths(key: str, entry: Entry) -> Tuple[str, ...]:
    return PATHS if entry.get("path") == "both" else (entry.get("path", key.rpartition("/")[2]),)


def entry_class(entry: Entry, arm: str) -> Optional[str]:
    """The class an entry expects on an arm: ``class`` is one string, or ``{floor, newest}``."""
    value = entry.get("class")
    return value.get(arm) if isinstance(value, dict) else value


def _explained(entry: Entry, arm: str) -> bool:
    if not str(entry.get("reason", "")).strip():
        return False
    return entry_class(entry, arm) != OPAQUE_READER_GAP or bool(str(entry.get("issue", "")).strip())


def check_review(
    results: List[Tuple[str, Dict[str, Any], Dict[str, str]]], review: Dict[str, Entry], arm: str
) -> Dict[str, List[str]]:
    """Rows needing an entry that has none, and entries that no longer match a row on ``arm``.

    ``unclassified`` and ``stale`` hold ``"<id>/<path>"`` and entry keys respectively.
    """
    by_id = {row_id: classes for row_id, _, classes in results}
    covered = set()
    stale = []
    for key, entry in review.items():
        row_id = key.partition("/")[0]
        classes = by_id.get(row_id)
        paths = _entry_paths(key, entry)
        if classes is None or any(classes.get(p) != entry_class(entry, arm) for p in paths):
            stale.append(key)
        elif _explained(entry, arm):
            covered.update(f"{row_id}/{p}" for p in paths)
    unclassified = [
        f"{row_id}/{path}"
        for row_id, _, classes in results
        for path in _needed(classes)
        if f"{row_id}/{path}" not in covered
    ]
    return {"unclassified": unclassified, "stale": sorted(stale)}


def skeleton(
    results: List[Tuple[str, Dict[str, Any], Dict[str, str]]], review: Dict[str, Entry], arm: str
) -> Dict[str, Entry]:
    """``review`` plus an entry with an empty reason for every row that still needs one.

    A new entry holds the class of this arm only; a row whose class depends on the sqlglot release
    is completed by hand with ``{"floor": ..., "newest": ...}``.
    """
    problems = check_review(results, review, arm)
    missing = set(problems["unclassified"])
    out = {key: entry for key, entry in review.items() if key not in problems["stale"]}
    for row_id, row, classes in results:
        need = {p: c for p, c in _needed(classes).items() if f"{row_id}/{p}" in missing}
        if not need:
            continue
        shared = len(need) == len(PATHS) and len(set(need.values())) == 1
        for path in ("both",) if shared else need:
            cls = next(iter(need.values())) if shared else need[path]
            sides = PATHS if shared else (path,)
            out[row_id if shared else f"{row_id}/{path}"] = {
                "sql": row["sql"][:SQL_EXCERPT],
                "path": path,
                "class": cls,
                "reason": "",
                "issue": "",
                "old": {p: (row["old"] or {}).get(p) for p in sides},
                "facts": row["facts"],
            }
    return out


def counts(results: List[Tuple[str, Dict[str, Any], Dict[str, str]]]) -> Dict[str, Dict[str, int]]:
    """Rows per class for each path, classes in rule order."""
    out: Dict[str, Dict[str, int]] = {}
    for path in PATHS:
        tally = Counter(classes[path] for _, _, classes in results)
        out[path] = {cls: tally[cls] for cls in ORDER if tally[cls]}
    return out


def report_family(family: str, arm: str) -> Dict[str, Any]:
    """Counts and unresolved rows of one family on one arm."""
    results = classify_family(family, arm)
    problems = check_review(results, load_review(family), arm)
    return {
        "gated": family in gated_families(),
        "rows": len(results),
        "counts": counts(results),
        **problems,
    }


def format_report(family: str, report: Dict[str, Any]) -> str:
    """A few readable lines for one family."""
    head = f"{family}: {report['rows']} rows" + (" (gated)" if report["gated"] else "")
    lines = [head]
    for path, tally in report["counts"].items():
        lines.append(f"  {path}: " + ", ".join(f"{k}={v}" for k, v in tally.items()))
    if report["unclassified"] or report["stale"]:
        lines.append(f"  unclassified={len(report['unclassified'])} stale={len(report['stale'])}")
    return "\n".join(lines)


def run(
    targets: List[str], *, report_only: bool = False, as_json: bool = False, write: bool = False
) -> int:
    """Compare the families; return 1 when a gated family has unexplained or stale rows."""
    arm = current_arm()
    reports = {family: report_family(family, arm) for family in targets}
    if write:
        for family in targets:
            skeleton_entries = skeleton(classify_family(family, arm), load_review(family), arm)
            review_file(family).write_text(
                json.dumps(skeleton_entries, indent=1, sort_keys=True) + "\n", encoding="utf-8"
            )
    if as_json:
        print(dumps({"arm": arm, "sqlglot": sqlglot.__version__, "families": reports}))
    else:
        print(f"sqlglot {sqlglot.__version__} ({arm} arm)")
        print("\n".join(format_report(f, r) for f, r in reports.items()))
    failed = [
        family
        for family, report in reports.items()
        if report["gated"] and (report["unclassified"] or report["stale"])
    ]
    if failed and not report_only:
        print("unexplained differences in gated families: " + ", ".join(failed), flush=True)
        return 1
    return 0


def families(name: str) -> Optional[List[str]]:
    """``all`` or one family name; ``None`` when unknown."""
    if name == "all":
        return list(FAMILIES)
    return [name] if name in FAMILIES else None
