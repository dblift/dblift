"""The text classifiers the splitter's records replaced stay deleted."""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

from dblift.core.migration import sql as migration_sql

pytestmark = pytest.mark.unit

SRC = Path(__file__).resolve().parents[5] / "dblift"
GONE = {"empty_statement_blanks", "hash_line_comments"}
CLASSIFIERS = {
    "is_comment_only_statement",
    "_is_comment_only_statement",
    "_comment_only",
    "is_batch_separator",
}
# (file, enclosing function, classifier): the only calls left, all of them for a parser that
# returns strings and not records, plus the deprecated public helper's own body.
ADAPTER = {
    ("statement_splitter.py", "_records_of_strings", "_comment_only"),
    ("statement_splitter.py", "_records_of_strings", "is_batch_separator"),
    ("execution_statement.py", "is_comment_only_statement", "_comment_only"),
}


def _name(node: ast.AST) -> str:
    if isinstance(node, ast.Attribute):
        return node.attr
    return getattr(node, "id", "")


def removed_names_used(root: Path) -> list:
    """Every definition, reference or keyword that brings a deleted name back."""
    found = []
    for path in root.rglob("*.py"):
        for node in ast.walk(ast.parse(path.read_text())):
            if isinstance(node, ast.FunctionDef) and node.name in GONE:
                found.append((path.name, node.name))
            elif isinstance(node, (ast.Attribute, ast.Name)) and _name(node) in GONE:
                found.append((path.name, _name(node)))
            elif isinstance(node, ast.Call) and _name(node.func) in CLASSIFIERS:
                found += [
                    (path.name, kw.arg)
                    for kw in node.keywords
                    if kw.arg in {"blanks", "hash_comments"}
                ]
    return found


def classifier_calls(root: Path) -> set:
    """``(file, enclosing function, classifier)`` of every call of a classifier under *root*."""
    found = set()
    for path in root.rglob("*.py"):
        tree = ast.parse(path.read_text())
        for func in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)] + [tree]:
            body = ast.walk(func) if func is not tree else _module_level(tree)
            for call in body:
                if isinstance(call, ast.Call) and _name(call.func) in CLASSIFIERS:
                    found.add((path.name, getattr(func, "name", "<module>"), _name(call.func)))
    return found


def _module_level(tree: ast.Module):
    stack = [n for n in tree.body if not isinstance(n, (ast.FunctionDef, ast.ClassDef))]
    while stack:
        node = stack.pop()
        yield node
        stack.extend(ast.iter_child_nodes(node))


def test_the_two_hooks_and_the_keywords_are_gone():
    assert removed_names_used(SRC) == []


def test_only_the_adapter_calls_a_text_classifier():
    outside = {c for c in classifier_calls(SRC) if c not in ADAPTER}
    # A function nested in the adapter is reported under its own name; the set is the claim.
    assert outside == set()


def test_the_scans_see_a_planted_defect(tmp_path):
    (tmp_path / "bad.py").write_text(
        "class Q:\n"
        "    def empty_statement_blanks(self):\n        return None\n"
        "def run(s, q):\n"
        "    return q.is_batch_separator(s) or is_comment_only_statement(s, blanks=' ')\n"
    )
    assert ("bad.py", "empty_statement_blanks") in removed_names_used(tmp_path)
    assert ("bad.py", "blanks") in removed_names_used(tmp_path)
    assert classifier_calls(tmp_path) == {
        ("bad.py", "run", "is_batch_separator"),
        ("bad.py", "run", "is_comment_only_statement"),
    }


def test_the_helper_is_deprecated_and_still_answers():
    with pytest.warns(DeprecationWarning, match="StatementSplitter"):
        assert migration_sql.is_comment_only_statement("-- x") is True
    with pytest.warns(DeprecationWarning):
        assert migration_sql.is_comment_only_statement("SELECT 1") is False


def test_the_helper_takes_no_blanks_or_hash_keyword():
    with pytest.raises(TypeError):
        migration_sql.is_comment_only_statement("-- x", blanks=" ")  # type: ignore[call-arg]
    with pytest.raises(TypeError):
        migration_sql.is_comment_only_statement("# x", hash_comments=True)  # type: ignore[call-arg]
