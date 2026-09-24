"""Product-identity strings are defined once, in ``dblift.core.constants``."""

from __future__ import annotations

import ast
import io
import re
import tokenize
from pathlib import Path
from typing import Collection, Iterator

import pytest

from dblift.core.constants import (
    DBLIFT_DATA_AUDIT_TABLE,
    DBLIFT_DATA_CHANGE_SET_TABLE,
    DBLIFT_SCHEMA_SNAPSHOTS_TABLE,
    DEFAULT_HISTORY_TABLE,
    ENV_PREFIX,
    MIGRATION_LOCK_TABLE,
)

pytestmark = [pytest.mark.unit]

PACKAGE = Path(__file__).resolve().parents[3] / "dblift"
CONSTANTS = PACKAGE / "core" / "constants.py"

# Literals that stay by design: a public integration contract and a
# dialect-specific derived name that cannot be computed from the constant.
ALLOWED_ENV_PREFIX_SITES = frozenset(
    {
        PACKAGE / "integrations" / "django" / "_client.py",
        PACKAGE / "db" / "plugins" / "oracle" / "provider.py",
    }
)


def _docstring_lines(tree: ast.AST) -> set[int]:
    """Line numbers covered by module, class and function docstrings."""
    lines: set[int] = set()
    for node in ast.walk(tree):
        if not isinstance(node, (ast.Module, ast.ClassDef, ast.FunctionDef, ast.AsyncFunctionDef)):
            continue
        body = node.body
        if body and isinstance(body[0], ast.Expr) and isinstance(body[0].value, ast.Constant):
            if isinstance(body[0].value.value, str):
                first = body[0]
                lines.update(range(first.lineno, (first.end_lineno or first.lineno) + 1))
    return lines


# A trailing comment on a code line (e.g. `x = 1  # see "dblift_schema_history"`) is still
# counted as code below: the COMMENT filter only drops lines that are wholly a comment.
def _code_lines(path: Path) -> Iterator[tuple[int, str]]:
    """Yield (line_number, text) with comments and docstrings removed."""
    source = path.read_text(encoding="utf-8")
    skip = _docstring_lines(ast.parse(source))
    comment_lines = {
        tok.start[0]
        for tok in tokenize.generate_tokens(io.StringIO(source).readline)
        if tok.type == tokenize.COMMENT and tok.line.lstrip().startswith("#")
    }
    for number, line in enumerate(source.splitlines(), start=1):
        if number in skip or number in comment_lines:
            continue
        yield number, line


def _offenders(pattern: str, allowed: Collection[Path] = ()) -> list[str]:
    regex = re.compile(pattern)
    hits = []
    for path in sorted(PACKAGE.rglob("*.py")):
        if path == CONSTANTS or path in allowed:
            continue
        for number, line in _code_lines(path):
            if regex.search(line):
                hits.append(f"{path.relative_to(PACKAGE.parent)}:{number}: {line.strip()}")
    return hits


def test_values_are_the_historical_defaults() -> None:
    assert DEFAULT_HISTORY_TABLE == "dblift_schema_history"
    assert MIGRATION_LOCK_TABLE == "dblift_migration_lock"
    assert ENV_PREFIX == "DBLIFT_"
    assert DBLIFT_SCHEMA_SNAPSHOTS_TABLE == "dblift_schema_snapshots"
    assert DBLIFT_DATA_CHANGE_SET_TABLE == "dblift_data_change_set"
    assert DBLIFT_DATA_AUDIT_TABLE == "dblift_data_audit"


def test_history_table_literal_appears_only_in_constants() -> None:
    assert _offenders(r'["\']dblift_schema_history["\']|["\']DBLIFT_SCHEMA_HISTORY["\']') == []


def test_lock_table_literal_appears_only_in_constants() -> None:
    assert _offenders(r'["\']dblift_migration_lock|["\']DBLIFT_MIGRATION_LOCK["\']') == []


def test_env_prefix_literal_appears_only_in_constants() -> None:
    assert _offenders(r'["\']DBLIFT_', ALLOWED_ENV_PREFIX_SITES) == []


def test_snapshot_table_literal_appears_only_in_constants() -> None:
    assert _offenders(r'["\']dblift_schema_snapshots["\']') == []


def test_data_change_set_table_literal_appears_only_in_constants() -> None:
    assert _offenders(r'["\']dblift_data_change_set["\']') == []


def test_data_audit_table_literal_appears_only_in_constants() -> None:
    assert _offenders(r'["\']dblift_data_audit["\']') == []
