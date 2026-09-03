"""Line-length (flake8 E501) ratchet.

Enforces a count-based cap on lines > 100 characters in the project's
source roots (``dblift/api/``, ``dblift/cli/``, ``dblift/config/``,
``dblift/core/``, ``dblift/db/``). The
mechanism mirrors ``scripts/check_api_docstrings.py``: a per-root cap
loaded from ``--ratchet PATH`` (default ``.flake8-e501-ratchet.json``)
records the maximum tolerated count. PRs at-or-below their cap pass;
PRs that grow a count fail with a "Net +N" message; PRs that lower a
count get a nudge to commit a tighter cap.

Why a separate gate
===================

``.flake8`` ignores ``E501`` globally because there is too much
legacy debt to make every flake8 run fail. This script reintroduces
the rule under a ratchet: it runs ``flake8 --isolated --select=E501
--max-line-length=100`` on the configured roots and ignores the
project's flake8 ignore list, so the cap is the only thing keeping
the count honest. Black is configured at 100, but black does not
split string literals, comment-heavy lines, function signatures
with long defaults, or many other shapes — so a count > 0 is
expected and shrinks PR-by-PR.

Running
=======

::

    python scripts/check_line_length.py                                       # default roots + ratchet
    python scripts/check_line_length.py --paths dblift/api dblift/cli          # subset
    python scripts/check_line_length.py --paths dblift/core --ratchet path/to/r.json

Exit code is ``0`` when every configured root is at-or-below its cap
(loose roots emit a "consider tightening" nudge), ``1`` when any root
exceeds its cap.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from collections import Counter
from typing import Dict, List, Optional, Sequence

DEFAULT_PATHS: Sequence[str] = (
    "dblift/api",
    "dblift/cli",
    "dblift/config",
    "dblift/core",
    "dblift/db",
)
DEFAULT_RATCHET = ".flake8-e501-ratchet.json"
MAX_LINE_LENGTH = 100


def _count_e501(root: str) -> List[str]:
    """Return the list of `path:line:col: E501 ...` strings produced by flake8 for *root*.

    Runs flake8 in ``--isolated`` mode so the project's ``.flake8`` ignore
    list (which silences E501 for the main lint job) does not apply to this
    targeted check. The script's only responsibility is counting; flake8
    itself produces the diagnostics if a maintainer wants to see them.
    """
    result = subprocess.run(
        [
            sys.executable,
            "-m",
            "flake8",
            "--isolated",
            "--select=E501",
            f"--max-line-length={MAX_LINE_LENGTH}",
            root,
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode not in (0, 1):
        # 0 = clean, 1 = violations found (expected). Anything else
        # (e.g. ``--isolated`` invalid in the installed flake8) is a hard
        # failure of the tool itself, propagate it.
        sys.stderr.write(result.stderr)
        raise RuntimeError(f"flake8 exited with unexpected code {result.returncode}")
    return [line for line in result.stdout.splitlines() if line.strip()]


def _load_ratchet(path: str) -> Dict[str, int]:
    """Read per-root caps from a JSON object. Underscore-prefixed keys are comments.

    Keep in sync with ``scripts/check_api_docstrings.py::_load_ratchet`` —
    these two are duplicated on purpose (project convention is one
    standalone script per lint rule, with no shared scripts/ package).
    A third ratchet would justify extracting into ``scripts/_ratchet_utils.py``.
    """
    with open(path, encoding="utf-8") as fh:
        data = json.load(fh)
    if not isinstance(data, dict):
        raise ValueError(f"{path}: expected a top-level JSON object, got {type(data).__name__}")
    out: Dict[str, int] = {}
    for key, value in data.items():
        if key.startswith("_"):
            continue
        # ``bool`` subclasses ``int`` in Python — reject explicitly so a JSON
        # ``true`` typo doesn't silently become cap=1 (see PR #340).
        if isinstance(value, bool) or not isinstance(value, int) or value < 0:
            raise ValueError(f"{path}: ratchet key '{key}' must map to a non-negative integer")
        out[key] = value
    return out


def _normalize(path: str) -> str:
    return path.replace(os.sep, "/").rstrip("/")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=list(DEFAULT_PATHS),
        help=f"Source roots to scan (default: {' '.join(DEFAULT_PATHS)})",
    )
    parser.add_argument(
        "--ratchet",
        metavar="PATH",
        default=DEFAULT_RATCHET,
        help=f"Path to the per-root cap JSON file (default: {DEFAULT_RATCHET})",
    )
    args = parser.parse_args(argv)

    caps = _load_ratchet(args.ratchet)

    counts: Counter[str] = Counter()
    violations_by_root: Dict[str, List[str]] = {}
    for root in args.paths:
        rnorm = _normalize(root)
        lines = _count_e501(root)
        counts[rnorm] = len(lines)
        violations_by_root[rnorm] = lines

    failing: List[str] = []
    failing_roots: List[str] = []
    suggest_tighten: List[str] = []
    for root in args.paths:
        rnorm = _normalize(root)
        current = counts.get(rnorm, 0)
        cap = caps.get(rnorm)
        if cap is None:
            if current > 0:
                failing.append(
                    f"  {rnorm}: {current} violation(s) — root not declared in ratchet "
                    f"{args.ratchet}. Add a cap for it or drop it from --paths."
                )
                failing_roots.append(rnorm)
            continue
        if current > cap:
            failing.append(
                f"  {rnorm}: {current} violation(s), cap is {cap}. Net +{current - cap} "
                "since the last ratchet update — shorten lines or wrap them."
            )
            failing_roots.append(rnorm)
        elif current < cap:
            suggest_tighten.append(
                f"  {rnorm}: {current} violation(s), cap is {cap} — you can lower "
                f"the cap by {cap - current} in {args.ratchet}."
            )

    if failing:
        print("FAIL: line-length ratchet exceeded:")
        for line in failing:
            print(line)
        first_root = failing_roots[0]
        print(f"\nE501 violations in '{first_root}':")
        for line in violations_by_root.get(first_root, []):
            print(f"  {line}")
        print(
            "\nFix by wrapping the line, or — for one-off cases where wrapping "
            "would actively hurt readability — annotate with `  # noqa: E501`."
        )
        return 1

    summary = ", ".join(
        f"{_normalize(r)}={counts.get(_normalize(r), 0)}/{caps.get(_normalize(r), 'n/a')}"
        for r in args.paths
    )
    print(f"OK: line-length ratchet respected ({summary})")
    if suggest_tighten:
        print("\nThe ratchet is loose on these roots — consider committing tighter caps:")
        for line in suggest_tighten:
            print(line)
    return 0


if __name__ == "__main__":
    sys.exit(main())
