"""Per-function cyclomatic-complexity ceiling.

Measures every function and method under ``dblift/`` with radon, wherever it is defined: at
module level, in a class, in a nested class, in a class built inside a function, or as a
closure. Each function is scored on its own, as radon scores it, and compared with
``.complexity-ceiling.json``. A function may not exceed the ceiling unless it is listed as an
exception, and a listed exception may only shrink:

* an unlisted function above the ceiling fails: split it;
* a listed function above its recorded value fails: it grew;
* a listed function below its recorded value but still above the ceiling fails until its entry
  is lowered to the exact current value, so freed headroom cannot be reused;
* a listed function at or under the ceiling, or no longer present, fails until its entry is
  removed; a renamed or moved function's entry moves to its new key at the same value;
* an entry recorded at or under the ceiling is invalid.

Keys are ``<path relative to the root>::<qualified name>``, for example
``core/sql_parser/sqlglot_statement_facts.py::read_statement_facts``. The qualified name joins
the enclosing class and function names with dots: ``Class.method``, ``outer.inner``,
``Outer.Inner.method``, ``factory.Local.method``. Exit 0 when every function respects its limit,
1 on any violation, 2 when the root or the baseline cannot be read.

Running
=======

::

    python scripts/check_complexity_ceiling.py
    python scripts/check_complexity_ceiling.py --baseline .complexity-ceiling.json dblift
"""

from __future__ import annotations

import argparse
import ast
import json
import sys
from pathlib import Path
from typing import Dict, Iterable, Iterator, List, Optional, Tuple, Union

from radon.complexity import cc_visit_ast

DEFAULT_ROOT = "dblift"
DEFAULT_BASELINE = ".complexity-ceiling.json"
RENAME_HINT = (
    "If a listed function was renamed or moved, its entry moves to its new key at the same value."
)

Measured = Dict[str, Tuple[int, int]]
FunctionNode = Union[ast.FunctionDef, ast.AsyncFunctionDef]


def _functions(nodes: Iterable[ast.AST], prefix: str = "") -> Iterator[Tuple[str, FunctionNode]]:
    """Yield ``(qualified name, node)`` for every function definition below *nodes*.

    Class and function names extend the prefix; other statements (``if``, ``try``, ...) are
    searched without adding to it.
    """
    for node in nodes:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            name = f"{prefix}{node.name}"
            if not isinstance(node, ast.ClassDef):
                yield name, node
            yield from _functions(node.body, f"{name}.")
        else:
            yield from _functions(ast.iter_child_nodes(node), prefix)


def _complexity(node: FunctionNode) -> int:
    """Return radon's score for *node* alone: nested functions and classes are not counted."""
    blocks = cc_visit_ast(ast.Module(body=[node], type_ignores=[]))
    return int(blocks[0].complexity)


def measure(root: Path) -> Measured:
    """Return ``{key: (complexity, line)}`` for every function under *root*.

    A name defined more than once in a module (a property setter, a conditional
    redefinition) is held to its most complex definition.
    """
    measured: Measured = {}
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        tree = ast.parse(path.read_text(encoding="utf-8-sig"), filename=str(path))
        for name, node in _functions(tree.body):
            key = f"{relative}::{name}"
            complexity = _complexity(node)
            if key not in measured or complexity > measured[key][0]:
                measured[key] = (complexity, node.lineno)
    return measured


def _load_baseline(path: str) -> Tuple[int, Dict[str, int]]:
    """Read the ceiling and the recorded exceptions from *path*.

    Raises ``ValueError`` naming *path* when the file is missing or malformed.
    """
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        ceiling = int(data["ceiling"])
        exceptions = {str(key): int(value) for key, value in data["exceptions"].items()}
    except (OSError, ValueError, KeyError, TypeError, AttributeError) as error:
        raise ValueError(f"cannot read baseline {path}: {error!r}") from error
    return ceiling, exceptions


def _check_listed(key: str, recorded: int, measured: Measured, ceiling: int) -> Optional[str]:
    """Return the problem with a listed exception, or ``None`` when it matches the code."""
    if recorded <= ceiling:
        return f"{key}: recorded {recorded}, not above the ceiling of {ceiling}. Remove its entry."
    if key not in measured:
        return f"{key}: no longer present. Remove its entry."
    current, line = measured[key]
    where = f"{key} (line {line}): complexity {current}"
    if current <= ceiling:
        return f"{where}, within the ceiling of {ceiling}. Remove its entry."
    if current > recorded:
        return f"{where}, recorded {recorded}. It grew: bring it back to {recorded} or below."
    if current < recorded:
        return f"{where}, recorded {recorded}. Lower its entry to {current}."
    return None


def check(measured: Measured, ceiling: int, exceptions: Dict[str, int]) -> List[str]:
    """Return one line per function that breaks the ceiling or its recorded exception."""
    unlisted = [
        f"{key} (line {line}): complexity {current} exceeds the ceiling of {ceiling}. "
        "Split it into smaller functions."
        for key, (current, line) in sorted(measured.items())
        if current > ceiling and key not in exceptions
    ]
    listed = [
        problem
        for key, recorded in sorted(exceptions.items())
        if (problem := _check_listed(key, recorded, measured, ceiling)) is not None
    ]
    if unlisted and any(key not in measured for key in exceptions):
        listed.append(RENAME_HINT)
    return unlisted + listed


def main(argv: Optional[List[str]] = None) -> int:
    """Run the gate and return the process exit code."""
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--baseline", default=DEFAULT_BASELINE)
    parser.add_argument("root", nargs="?", default=DEFAULT_ROOT)
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.is_dir():
        print(f"FAIL: root not found: {root}")
        return 2
    try:
        ceiling, exceptions = _load_baseline(args.baseline)
    except ValueError as error:
        print(f"FAIL: {error}")
        return 2
    measured = measure(root)
    problems = check(measured, ceiling, exceptions)
    if problems:
        print(f"FAIL: complexity ceiling ({ceiling}) broken:")
        print("\n".join(f"  {problem}" for problem in problems))
        print(
            f"\nSplit new hotspots rather than listing them in {args.baseline}. A listed "
            "exception may only shrink: record its exact current value, and remove it once it "
            "is at or under the ceiling."
        )
        return 1
    print(
        f"OK: complexity ceiling respected ({len(measured)} functions, ceiling {ceiling}, "
        f"{len(exceptions)} recorded exceptions)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
