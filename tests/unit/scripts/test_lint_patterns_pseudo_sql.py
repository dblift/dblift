"""Unit tests for the ``pseudo-sql-translator`` lint rule.

The rule is the standing guard behind the 3.0.0 removal: a SQL-shaped
front-end over a document-store SDK is exactly what CosmosDB shipped and what
this release deleted. It exists so the second document store (MongoDB) cannot
arrive with a second copy of it.

The rule function inspects an AST and the raw source lines only, so the
synthetic paths below need not exist on disk.
"""

from __future__ import annotations

import ast
from pathlib import Path
from typing import List

import pytest

import scripts.lint_patterns as lp

pytestmark = [pytest.mark.unit]


def run_rule(src: str, rel_path: str = "db/plugins/cosmosdb/query_executor.py") -> List:
    return list(lp._check_pseudo_sql_translator(Path(rel_path), ast.parse(src), src.splitlines()))


class TestTranslatorNames:
    @pytest.mark.parametrize("name", sorted(lp.PSEUDO_SQL_TRANSLATOR_NAMES))
    def test_every_banned_name_is_flagged_as_a_function(self, name: str) -> None:
        violations = run_rule(f"def {name}(self):\n    pass\n")
        assert len(violations) == 1
        assert violations[0].rule == "pseudo-sql-translator"

    def test_a_class_of_the_same_name_is_flagged(self) -> None:
        assert len(run_rule("class SDK_PATTERNS:\n    pass\n")) == 1

    def test_an_assignment_is_flagged(self) -> None:
        assert len(run_rule('SDK_PATTERNS = {"drop": "..."}\n')) == 1

    def test_a_private_alias_does_not_escape_the_rule(self) -> None:
        """``_generate_sdk_script`` is the same thing wearing an underscore."""
        assert len(run_rule("def _generate_sdk_script(self):\n    pass\n")) == 1

    def test_an_unrelated_name_is_not_flagged(self) -> None:
        assert run_rule("def generate_ddl(self):\n    pass\n") == []


class TestPseudoDdlLiterals:
    @pytest.mark.parametrize("prefix", sorted(lp.PSEUDO_SQL_STATEMENT_PREFIXES))
    def test_every_banned_verb_is_flagged(self, prefix: str) -> None:
        violations = run_rule(f'SQL = "{prefix} orders"\n')
        assert len(violations) == 1
        assert violations[0].rule == "pseudo-sql-translator"

    def test_matching_is_case_insensitive_and_ignores_leading_space(self) -> None:
        assert len(run_rule('SQL = "  drop container orders"\n')) == 1

    def test_a_real_cosmos_select_is_left_alone(self) -> None:
        """Native ``SELECT`` is the one statement kind CosmosDB still runs."""
        assert run_rule('SQL = "SELECT * FROM c WHERE c.id = @id"\n') == []

    def test_relational_ddl_is_left_alone(self) -> None:
        assert run_rule('SQL = "DROP TABLE orders"\n') == []


class TestAllowMarker:
    def test_the_marker_on_the_same_line_suppresses(self) -> None:
        src = 'SQL = "DROP CONTAINER orders"  # lint: allow-pseudo-sql: rejection test\n'
        assert run_rule(src) == []

    def test_the_marker_on_the_line_above_suppresses(self) -> None:
        src = '# lint: allow-pseudo-sql: rejection test\nSQL = "DROP CONTAINER orders"\n'
        assert run_rule(src) == []

    def test_the_marker_suppresses_a_banned_name_too(self) -> None:
        src = "# lint: allow-pseudo-sql: historical\ndef generate_sdk_script(self):\n    pass\n"
        assert run_rule(src) == []


def test_the_rule_is_wired_into_the_runner(tmp_path: Path) -> None:
    """A rule nobody calls is not a gate. This is the regression that matters."""
    target = tmp_path / "offender.py"
    target.write_text('SQL = "DROP CONTAINER orders"\n', encoding="utf-8")

    violations = lp._lint_file(target)

    assert [v.rule for v in violations] == ["pseudo-sql-translator"]


def test_default_roots_point_at_packages_that_exist() -> None:
    """A root that does not resolve makes the gate pass vacuously.

    ``Path.rglob`` on a missing directory yields nothing rather than raising,
    so a stale root is silent. The monorepo copy of this script shipped with
    exactly that defect after its packages moved; this asserts the OSS roots
    still resolve.
    """
    repo_root = Path(lp.__file__).resolve().parent.parent

    for root in lp.DEFAULT_ROOTS:
        assert (repo_root / root).is_dir(), f"lint root {root!r} does not exist"

    scanned = list(lp._iter_py_files([repo_root / r for r in lp.DEFAULT_ROOTS]))
    assert scanned, "the default roots scan no Python files at all"
