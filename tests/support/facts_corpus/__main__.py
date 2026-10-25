"""Command line.

``python -m tests.support.facts_corpus seed | record <arm> [family] [--frozen] | measure``

``python -m tests.support.facts_corpus diff <family|all> [--report] [--json] [--skeleton]``
compares the frozen object extraction with the statement facts. In a family listed in
``gated.json`` a difference that is neither classified mechanically nor explained in the family's
review file fails (exit 1), and a review entry that matches no row fails in every family;
``--report`` only prints. ``--skeleton`` adds an empty entry to the
review file for each row that needs one.
"""

from __future__ import annotations

import json
import sys

import sqlglot

from tests.support.facts_corpus import (
    CORPUS_DIR,
    FAMILIES,
    INPUTS_FILE,
    REPO_ROOT,
    VERSIONS_FILE,
    family_file,
    read_rows,
    read_versions,
    statement_id,
)
from tests.support.facts_corpus.canonical import dumps
from tests.support.facts_corpus.differential import families, run
from tests.support.facts_corpus.measure import update_versions
from tests.support.facts_corpus.record import check_arm, is_frozen, record_family
from tests.support.facts_corpus.seed import seed, split


def _record(arm: str, frozen: bool, selected: str | None = None) -> int:
    check_arm(arm, sqlglot.__version__, read_versions())
    inputs = read_rows(INPUTS_FILE)
    selected_families = (selected,) if selected else FAMILIES
    frozen_families = [family for family in selected_families if is_frozen(family)]
    if frozen_families and not frozen:
        print(
            "the recorded extraction is frozen for: " + ", ".join(frozen_families) + "; "
            "record them with --frozen, the others without"
        )
        return 1
    families_to_record = selected_families if selected or not frozen else frozen_families
    for family in families_to_record:
        path = family_file(family)
        rows = record_family(family, arm, inputs, read_rows(path), frozen)
        path.write_text("".join(dumps(row) + "\n" for row in rows), encoding="utf-8")
        print(f"{family}: {len(rows)} statements")
    return 0


def _resplit_unstable(family: str) -> list:
    """Statement ids whose text does not split back to itself (splitter refusals included)."""
    unstable = []
    for row in read_rows(family_file(family)):
        try:
            again = split(family, row["sql"])
        except Exception:
            again = None
        if again != [row["sql"]]:
            unstable.append(statement_id(row["sql"]))
    return unstable


def _measure() -> None:
    """Record sizes and counts; the first measurement of inputs and size is never rewritten."""
    ids = [row["id"] for row in read_rows(INPUTS_FILE)]
    base_file = CORPUS_DIR / "input_ids.txt"
    if not base_file.exists():
        base_file.write_text("".join(i + "\n" for i in sorted(ids)), encoding="utf-8")
    measured = {
        "size_bytes": sum(f.stat().st_size for f in CORPUS_DIR.glob("*.jsonl")),
        "inputs": len(ids),
        "newest_differing_rows": {
            family: sum(
                1
                for r in read_rows(family_file(family))
                if "facts_newest" in r or "old_newest" in r
            )
            for family in FAMILIES
        },
    }
    versions = update_versions(
        read_versions(), measured, base_file.read_text(encoding="utf-8").split(), ids
    )
    unstable = {family: _resplit_unstable(family) for family in FAMILIES}
    (CORPUS_DIR / "not_idempotent.json").write_text(
        json.dumps(unstable, indent=1, sort_keys=True) + "\n", encoding="utf-8"
    )
    VERSIONS_FILE.write_text(
        json.dumps(versions, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(versions)


def main(argv: list) -> int:
    """Run one sub-command."""
    command = argv[0] if argv else ""
    if command == "seed":
        print(seed(REPO_ROOT, INPUTS_FILE, CORPUS_DIR / "SOURCES.md"), "inputs")
    elif command == "record" and len(argv) in (2, 3, 4):
        args = argv[2:]
        if any(arg != "--frozen" and arg not in FAMILIES for arg in args):
            print(__doc__)
            return 2
        selected = [arg for arg in args if arg != "--frozen"]
        if len(selected) > 1 or args.count("--frozen") > 1:
            print(__doc__)
            return 2
        return _record(argv[1], "--frozen" in args, selected[0] if selected else None)
    elif command == "measure":
        _measure()
    elif command == "diff" and len(argv) >= 2 and families(argv[1]):
        flags = set(argv[2:])
        return run(
            families(argv[1]) or [],
            report_only="--report" in flags,
            as_json="--json" in flags,
            write="--skeleton" in flags,
        )
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
