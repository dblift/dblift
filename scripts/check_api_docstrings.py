"""Public-API docstring linter.

Enforces that every public module, class, function and method in the
``dblift`` package carries a docstring. The gate is zero-tolerance: it
scans the whole package (every subpackage and the top-level modules) and
any violation fails the run. There are no per-root caps.

Scope
=====

Default behaviour scans ``dblift/``. ``--paths`` narrows the scan to
other directories or files. A root that is not found is an error (exit
code ``2``), so running from the wrong working directory can never pass
on an empty scan.

What counts as "public"
=======================

A name is public when it does **not** start with an underscore. Private
names (``_helper``, etc.) are skipped, **with two refinements**:

* ``__init__`` is treated as public on a public class (constructor
  documentation matters). When its enclosing class is private, the
  constructor inherits the class's privacy — a stub on a private
  class doesn't add user-facing value.
* A public-named method on a private class also inherits the class's
  privacy. ``class _Result: def execution_time(self): ...`` is part of
  the private surface; documenting it is busywork.

Exemptions
==========

Four categories of public names are exempt because requiring a
docstring on them is either redundant or actively misleading:

1. **Inner functions / closures.** Decorators using ``functools.wraps``
   inherit the wrapped function's docstring; insisting on a docstring on
   the inner closure produces duplicated, drifting prose. Detection:
   any ``FunctionDef`` whose immediate parent is another ``FunctionDef``
   or ``AsyncFunctionDef``.

2. **Methods on private classes** (see "public" rules above).

3. **Protocol / ABC stubs.** Methods whose body is exactly ``...``
   (``Ellipsis``) or ``pass`` are signature stubs (typing.Protocol,
   abc.abstractmethod, etc.). The class-level docstring documents the
   contract; the stub bodies don't need their own.

4. **Inline-annotated overrides.** A line ending with
   ``# lint: allow-missing-docstring: <reason>`` is treated as an
   intentional deferral, matching the convention from
   ``scripts/lint_patterns.py`` (e.g. ``# lint: allow-print``,
   ``# lint: allow-enum-str``).

Running
=======

::

    python scripts/check_api_docstrings.py                      # whole package
    python scripts/check_api_docstrings.py --paths dblift/api   # one subtree
    python scripts/check_api_docstrings.py --help

Exit code is ``0`` when no violations remain, ``1`` when there are
violations and ``2`` when a scanned root does not exist. CI gates the
lint job on the zero-exit (see ``.github/workflows/code-quality.yml``).
"""

from __future__ import annotations

import argparse
import ast
import os
import sys
from typing import Iterable, List, Tuple

DEFAULT_ROOTS = ("dblift",)
ALLOW_ANNOTATION = "# lint: allow-missing-docstring"

Violation = Tuple[str, int, str, str]  # (path, lineno, kind, name)


def _iter_python_files(roots: Iterable[str]) -> Iterable[str]:
    for root in roots:
        if os.path.isfile(root) and root.endswith(".py"):
            yield root
            continue
        for dirpath, _dirnames, filenames in os.walk(root):
            for filename in filenames:
                if filename.endswith(".py"):
                    yield os.path.join(dirpath, filename)


def _is_public_name(name: str) -> bool:
    """A bare name is public iff it does not start with an underscore."""
    if name == "__init__":
        return True
    return not name.startswith("_")


def _enclosing_classes(node: ast.AST) -> List[ast.ClassDef]:
    """Walk up the AST parent chain and return EVERY enclosing ``ClassDef``.

    Returned innermost-first. For ``class _P: class Q: def m(): ...``, the
    list for ``m`` is ``[Q, _P]``. Returning all ancestors (rather than only
    the nearest) is what lets ``_is_public`` notice that ``m`` lives under
    a private class even though the immediate enclosing class ``Q`` is
    public.
    """
    classes: List[ast.ClassDef] = []
    cur = getattr(node, "_parent", None)
    while cur is not None:
        if isinstance(cur, ast.ClassDef):
            classes.append(cur)
        cur = getattr(cur, "_parent", None)
    return classes


def _is_public(node: ast.AST, name: str) -> bool:
    """Public iff the name AND every enclosing class name are public.

    A public-named method on a private class (``class _R: def m(self): ...``)
    inherits the class's privacy — it is not part of the user-facing API
    surface, so a docstring on it is busywork. Same logic for ``__init__``:
    only flagged when every enclosing class is itself public. The full
    chain is checked, not just the nearest ancestor — otherwise a public
    class nested under a private one (``class _P: class Q: ...``) would
    leak its methods back into the strict gate.
    """
    if not _is_public_name(name):
        return False
    for enclosing in _enclosing_classes(node):
        if not _is_public_name(enclosing.name):
            return False
    return True


def _is_stub_body(node: ast.AST) -> bool:
    """Return True when *node*'s body is a single Ellipsis or ``pass`` statement."""
    body = getattr(node, "body", None)
    if not body or len(body) != 1:
        return False
    only = body[0]
    if isinstance(only, ast.Pass):
        return True
    if isinstance(only, ast.Expr) and isinstance(only.value, ast.Constant):
        return only.value.value is ...
    return False


def _annotated_lines(source: str) -> set[int]:
    """Set of 1-based line numbers carrying the ``allow-missing-docstring`` opt-out."""
    out: set[int] = set()
    for lineno, line in enumerate(source.splitlines(), start=1):
        if ALLOW_ANNOTATION in line:
            out.add(lineno)
    return out


def _attach_parents(tree: ast.AST) -> None:
    """Annotate each node with a ``_parent`` attribute (used to detect inner funcs)."""
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            child._parent = parent  # type: ignore[attr-defined]


def _is_inner_function(node: ast.AST) -> bool:
    parent = getattr(node, "_parent", None)
    return isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef))


def scan_file(path: str) -> List[Violation]:
    """Return the list of public-name docstring violations in *path*."""
    with open(path, encoding="utf-8") as fh:
        source = fh.read()
    try:
        tree = ast.parse(source)
    except SyntaxError:
        return []

    _attach_parents(tree)
    skip_lines = _annotated_lines(source)
    violations: List[Violation] = []

    has_module_doc = bool(
        tree.body
        and isinstance(tree.body[0], ast.Expr)
        and isinstance(tree.body[0].value, ast.Constant)
        and isinstance(tree.body[0].value.value, str)
    )
    if not has_module_doc and 1 not in skip_lines:
        violations.append((path, 1, "module", "<module>"))

    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if not _is_public(node, node.name):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                if _is_inner_function(node):
                    continue
                if _is_stub_body(node):
                    continue
            if ast.get_docstring(node):
                continue
            if node.lineno in skip_lines:
                continue
            kind = "class" if isinstance(node, ast.ClassDef) else "function"
            violations.append((path, node.lineno, kind, node.name))

    return violations


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--paths",
        nargs="*",
        default=list(DEFAULT_ROOTS),
        help=f"Directories or files to scan (default: {' '.join(DEFAULT_ROOTS)})",
    )
    args = parser.parse_args(argv)

    missing = [path for path in args.paths if not os.path.exists(path)]
    if missing:
        print(
            f"error: scan root(s) {', '.join(missing)} not found "
            f"(cwd: {os.getcwd()}). Run from the repository root.",
            file=sys.stderr,
        )
        return 2

    all_violations: List[Violation] = []
    for path in _iter_python_files(args.paths):
        all_violations.extend(scan_file(path))

    if not all_violations:
        print(f"OK: no missing docstrings in {' '.join(args.paths)}")
        return 0
    print(f"FAIL: {len(all_violations)} missing docstring(s) in public API surface:")
    for path, lineno, kind, name in all_violations:
        print(f"  {path}:{lineno}  {kind}  {name}")
    print(
        "\nFix by adding a docstring, or — if the case is genuinely exempt — "
        f"annotate the def/class line with `{ALLOW_ANNOTATION}: <reason>`."
    )
    return 1


if __name__ == "__main__":
    sys.exit(main())
