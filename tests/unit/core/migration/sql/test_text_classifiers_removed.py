"""The text classifiers the splitter's records replaced stay deleted."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest


pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[5] / "dblift"
GONE = {"empty_statement_blanks", "hash_line_comments"}
CLASSIFIERS = {
    "is_comment_only_statement",
    "_is_comment_only_statement",
    "_comment_only",
    "is_batch_separator",
}
def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return getattr(node, "id", "")


def _rel(path: Path, root: Path) -> str:
    return path.relative_to(root).as_posix()


def removed_names_used(root: Path) -> list:
    """Every definition, reference or keyword that brings a deleted name back."""
    found = []
    for path in root.rglob("*.py"):
        rel = _rel(path, root)
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and node.name in GONE:
                found.append((rel, node.name))
            elif isinstance(node, (ast.Attribute, ast.Name)) and _name(node) in GONE:
                found.append((rel, _name(node)))
            elif isinstance(node, ast.Call) and _name(node.func) in CLASSIFIERS:
                found += [
                    (rel, kw.arg) for kw in node.keywords if kw.arg in {"blanks", "hash_comments"}
                ]
    return found


def classifier_calls(root: Path) -> set:
    """``(path under root, enclosing function, classifier)`` of every call of a classifier.

    Every node is visited, so a call in a class body or at module level counts too; those are
    reported under ``<module>``.
    """
    found = set()

    def visit(node: ast.AST, rel: str, scope: str) -> None:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            scope = node.name
        if isinstance(node, ast.Call) and _name(node.func) in CLASSIFIERS:
            found.add((rel, scope, _name(node.func)))
        for child in ast.iter_child_nodes(node):
            visit(child, rel, scope)

    for path in root.rglob("*.py"):
        visit(ast.parse(path.read_text()), _rel(path, root), "<module>")
    return found


def test_the_two_hooks_and_the_keywords_are_gone():
    assert removed_names_used(SRC) == []


def test_no_text_classifier_calls_remain():
    assert classifier_calls(SRC) == set()


def test_the_scans_see_a_planted_defect(tmp_path):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "bad.py").write_text(
        "class Q:\n"
        "    def empty_statement_blanks(self):\n        return None\n"
        "def run(s, q):\n"
        "    return q.is_batch_separator(s) or is_comment_only_statement(s, blanks=' ')\n"
    )
    (tmp_path / "pkg" / "cls.py").write_text('class _Z:\n    w = is_comment_only_statement("x")\n')
    assert ("pkg/bad.py", "empty_statement_blanks") in removed_names_used(tmp_path)
    assert ("pkg/bad.py", "blanks") in removed_names_used(tmp_path)
    assert classifier_calls(tmp_path) == {
        ("pkg/bad.py", "run", "is_batch_separator"),
        ("pkg/bad.py", "run", "is_comment_only_statement"),
        ("pkg/cls.py", "<module>", "is_comment_only_statement"),
    }


def test_an_allowed_call_is_allowed_only_at_its_own_path(tmp_path):
    other = tmp_path / "elsewhere"
    other.mkdir()
    (other / "statement_splitter.py").write_text(
        "def _records_of_strings(t):\n    return _comment_only(t)\n"
    )
    assert classifier_calls(tmp_path) != set()


