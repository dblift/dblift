"""Structural-debt ratchet.

Counts six debt signals across ``dblift/`` and compares each with the cap in
``.debt-ratchet.json``. A count may stay flat or shrink, never grow. Mirrors
``scripts/check_line_length.py``: exit 0 at or below every cap (with a nudge
to tighten loose caps), exit 1 when any cap is exceeded.

Running
=======

::

    python scripts/check_debt_ratchet.py
    python scripts/check_debt_ratchet.py --root dblift --ratchet .debt-ratchet.json
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Dict, List, Optional

DEFAULT_ROOT = "dblift"
DEFAULT_RATCHET = ".debt-ratchet.json"
LARGE_FILE_LINES = 800

_LINE_PATTERNS: Dict[str, "re.Pattern[str]"] = {
    # An import of this package below module level usually hides an import cycle.
    "function_level_imports": re.compile(r"^\s{4,}(from dblift[.\s]|import dblift[.\s])"),
    # ``Any`` used as a type: preceded by ``:``, ``[``, ``,`` or ``->`` (``x: Any``,
    # ``Mapping[str, Any]``, ``Callable[[Any], bool]``). Prose that starts a sentence with
    # "Any", and a bare ``Any,`` continuation line of a wrapped import, do not count.
    "any_annotations": re.compile(r"^(?!\s*(?:from|import)\s).*(?:[:\[,]\s*|->\s*)Any\b"),
    "dynamic_attribute_access": re.compile(r"\b(hasattr|getattr)\("),
    "broad_excepts": re.compile(r"^\s*except Exception\b"),
    # Internal tracking identifiers mean nothing to a reader of the public tree:
    # epic/story numbers and ticket ids such as SIMP-37, DEDUP-30 or B10-BUG-01.
    "process_references": re.compile(
        r"\b(?:Epic|epic|Story|story)\s+\d"
        r"|\b(?:SIMP|DIP|DEDUP|SMELL|DEAD|DEAD-NEW|NEW-BUG|B\d+-BUG|BUG|NOTE)-\d+"
    ),
}

# Signals for which a comment-only line counts: a comment that names a tracking
# identifier is precisely the debt, whereas a comment describing getattr() is not a call.
_COUNT_IN_COMMENTS = frozenset({"process_references"})


def measure(root: Path) -> Dict[str, int]:
    """Return the current count of every debt signal under *root*."""
    return {name: len(hits) for name, hits in locate(root).items()}


def locate(root: Path) -> Dict[str, List[str]]:
    """Return every offending ``path:line: text`` under *root*, keyed by signal."""
    hits: Dict[str, List[str]] = {name: [] for name in _LINE_PATTERNS}
    hits["large_files"] = []
    for path in sorted(root.rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > LARGE_FILE_LINES:
            hits["large_files"].append(f"{path}: {len(lines)} lines")
        for number, line in enumerate(lines, start=1):
            is_comment = line.lstrip().startswith("#")
            for name, pattern in _LINE_PATTERNS.items():
                if is_comment and name not in _COUNT_IN_COMMENTS:
                    continue  # a comment describing getattr() is not a call
                if pattern.search(line):
                    hits[name].append(f"{path}:{number}: {line.strip()}")
    return hits


def _load_ratchet(path: str) -> Dict[str, int]:
    """Read caps from a JSON object. Underscore-prefixed keys are comments."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a top-level JSON object, got {type(data).__name__}")
    caps: Dict[str, int] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{path}: ratchet key '{key}' must map to a non-negative integer")
        caps[key] = value
    return caps


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--root", default=DEFAULT_ROOT)
    parser.add_argument("--ratchet", default=DEFAULT_RATCHET)
    args = parser.parse_args(argv)

    caps = _load_ratchet(args.ratchet)
    hits = locate(Path(args.root))
    counts = {name: len(lines) for name, lines in hits.items()}

    failing: List[str] = []
    failing_signals: List[str] = []
    loose: List[str] = []
    for name, current in counts.items():
        cap = caps.get(name)
        if cap is None:
            failing.append(f"  {name}: {current}, no cap declared in {args.ratchet}")
            failing_signals.append(name)
        elif current > cap:
            failing.append(f"  {name}: {current}, cap is {cap}. Net +{current - cap}.")
            failing_signals.append(name)
        elif current < cap:
            loose.append(f"  {name}: {current}, cap is {cap} - lower the cap by {cap - current}.")

    if failing:
        print("FAIL: structural-debt ratchet exceeded:")
        print("\n".join(failing))
        first = failing_signals[0]
        print(f"\nOffending lines for '{first}':")
        print("\n".join(f"  {line}" for line in hits[first]))
        print(
            "\nRemove the new occurrence rather than raising the cap; when your change lowers a "
            "count, lower the cap in the same pull request."
        )
        return 1
    summary = ", ".join(f"{name}={counts[name]}/{caps[name]}" for name in counts)
    print(f"OK: structural-debt ratchet respected ({summary})")
    if loose:
        print("\nThe ratchet is loose - consider committing tighter caps:")
        print("\n".join(loose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
