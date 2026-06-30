"""Unit tests for ``scripts/lint_patterns`` (AST lint rules).

These pin the ``dialect-string-literal`` rule's scope contract: ``db/`` is
now scanned for hardcoded dialect-name literals, *except* plugin code under
``db/plugins/<X>/**`` (plugins own their dialect) and ``core/introspection/``
(capability matrices). The rule function only inspects ``path.parts`` /
``path.as_posix()``, so the synthetic paths below need not exist on disk.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

import pytest

import scripts.lint_patterns as lp

pytestmark = [pytest.mark.unit]


def run_rule(rel_path: str, src: str) -> List[lp.Violation]:
    """Run only the dialect-string-literal rule against synthetic source."""
    return list(_check(rel_path, src))


def _check(rel_path: str, src: str):
    return lp._check_dialect_string_literal(Path(rel_path), ast.parse(src), src.splitlines())


def test_db_shared_file_is_flagged() -> None:
    violations = run_rule("db/foo.py", 'X = "oracle"')
    assert len(violations) == 1
    assert violations[0].rule == "dialect-string-literal"


def test_db_plugins_per_dialect_package_is_exempt() -> None:
    assert run_rule("db/plugins/mysql/bar.py", 'X = "mysql"') == []


def test_db_plugins_nested_per_dialect_package_is_exempt() -> None:
    assert run_rule("db/plugins/oracle/oracle/foo.py", 'X = "oracle"') == []


def test_db_plugins_shared_base_module_is_flagged() -> None:
    violations = run_rule("db/plugins/base_snapshot_manager.py", 'X = "mysql"')
    assert len(violations) == 1
    assert violations[0].rule == "dialect-string-literal"


def test_db_plugins_shared_base_foo_module_is_flagged() -> None:
    violations = run_rule("db/plugins/base_foo.py", 'X = "oracle"')
    assert len(violations) == 1
    assert violations[0].rule == "dialect-string-literal"


def test_same_line_annotation_skips() -> None:
    src = 'X = "oracle"  # lint: allow-dialect-string: registry key'
    assert run_rule("db/foo.py", src) == []


def test_previous_line_annotation_skips() -> None:
    src = '# lint: allow-dialect-string: registry key\nX = "oracle"'
    assert run_rule("db/foo.py", src) == []


def test_core_introspection_now_scanned() -> None:
    # ADR-26 B2: core/introspection is no longer exempt — its dialect-specific
    # filters moved to plugin quirks, so it is scanned like the rest of core/.
    violations = run_rule("core/introspection/x.py", 'X = "oracle"')
    assert len(violations) == 1
    assert violations[0].rule == "dialect-string-literal"


def test_existing_core_root_still_flagged() -> None:
    violations = run_rule("core/foo.py", 'X = "postgresql"')
    assert len(violations) == 1
    assert violations[0].rule == "dialect-string-literal"


def test_non_dialect_string_in_db_not_flagged() -> None:
    assert run_rule("db/foo.py", 'X = "hello"') == []
