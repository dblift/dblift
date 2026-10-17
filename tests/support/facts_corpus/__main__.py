"""Command line: ``python -m tests.support.facts_corpus seed|record <arm>|measure``."""

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
from tests.support.facts_corpus.record import check_arm, record_family
from tests.support.facts_corpus.seed import seed, split


def _record(arm: str) -> None:
    check_arm(arm, sqlglot.__version__, read_versions())
    inputs = read_rows(INPUTS_FILE)
    for family in FAMILIES:
        path = family_file(family)
        rows = record_family(family, arm, inputs, read_rows(path))
        path.write_text("".join(dumps(row) + "\n" for row in rows), encoding="utf-8")
        print(f"{family}: {len(rows)} statements")


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
    """Store the sizes of the first complete recording; the corpus test caps growth on it."""
    versions = read_versions()
    versions["size_bytes"] = sum(f.stat().st_size for f in CORPUS_DIR.glob("*.jsonl"))
    versions["inputs"] = len(read_rows(INPUTS_FILE))
    versions["newest_differing_rows"] = {
        family: sum(
            1 for r in read_rows(family_file(family)) if "facts_newest" in r or "old_newest" in r
        )
        for family in FAMILIES
    }
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
    elif command == "record" and len(argv) == 2:
        _record(argv[1])
    elif command == "measure":
        _measure()
    else:
        print(__doc__)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
