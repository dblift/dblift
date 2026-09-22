"""Structural-debt ratchet.

Counts five debt signals across ``dblift/`` and compares each with the cap in
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
    "any_annotations": re.compile(r": Any\b|-> Any\b|Dict\[str, Any\]"),
    "dynamic_attribute_access": re.compile(r"\b(hasattr|getattr)\("),
    "broad_excepts": re.compile(r"^\s*except Exception\b"),
}


def measure(root: Path) -> Dict[str, int]:
    """Return the current count of every debt signal under *root*."""
    counts = {name: 0 for name in _LINE_PATTERNS}
    counts["large_files"] = 0
    for path in sorted(root.rglob("*.py")):
        lines = path.read_text(encoding="utf-8").splitlines()
        if len(lines) > LARGE_FILE_LINES:
            counts["large_files"] += 1
        for line in lines:
            for name, pattern in _LINE_PATTERNS.items():
                if pattern.search(line):
                    counts[name] += 1
    return counts


def _load_ratchet(path: str) -> Dict[str, int]:
    """Read caps from a JSON object. Underscore-prefixed keys are comments."""
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
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
    counts = measure(Path(args.root))

    failing: List[str] = []
    loose: List[str] = []
    for name, current in counts.items():
        cap = caps.get(name)
        if cap is None:
            failing.append(f"  {name}: {current}, no cap declared in {args.ratchet}")
        elif current > cap:
            failing.append(f"  {name}: {current}, cap is {cap}. Net +{current - cap}.")
        elif current < cap:
            loose.append(f"  {name}: {current}, cap is {cap} - lower the cap by {cap - current}.")

    if failing:
        print("FAIL: structural-debt ratchet exceeded:")
        print("\n".join(failing))
        return 1
    summary = ", ".join(f"{name}={counts[name]}/{caps[name]}" for name in counts)
    print(f"OK: structural-debt ratchet respected ({summary})")
    if loose:
        print("\nThe ratchet is loose - consider committing tighter caps:")
        print("\n".join(loose))
    return 0


if __name__ == "__main__":
    sys.exit(main())
