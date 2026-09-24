"""Product-identity strings are defined once, in ``dblift.core.constants``."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from dblift.core.constants import DEFAULT_HISTORY_TABLE, ENV_PREFIX, MIGRATION_LOCK_TABLE

pytestmark = [pytest.mark.unit]

PACKAGE = Path(__file__).resolve().parents[3] / "dblift"
CONSTANTS = PACKAGE / "core" / "constants.py"

# Literals that stay by design: a public integration contract and a
# dialect-specific derived name that cannot be computed from the constant.
ALLOWED_ENV_PREFIX_SITES = {
    PACKAGE / "integrations" / "django" / "_client.py",
    PACKAGE / "db" / "plugins" / "oracle" / "provider.py",
}


def _code_lines(path: Path):
    """Yield (line_number, text) for lines that are not comments or docstrings."""
    in_docstring = False
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        stripped = line.strip()
        if stripped.count('"""') == 1:
            in_docstring = not in_docstring
            continue
        if in_docstring or stripped.startswith("#"):
            continue
        yield number, line


def _offenders(pattern: str, allowed: set[Path] = frozenset()) -> list[str]:
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


def test_history_table_literal_appears_only_in_constants() -> None:
    assert _offenders(r'"dblift_schema_history"|"DBLIFT_SCHEMA_HISTORY"') == []


def test_lock_table_literal_appears_only_in_constants() -> None:
    assert _offenders(r'"dblift_migration_lock|"DBLIFT_MIGRATION_LOCK"') == []


def test_env_prefix_literal_appears_only_in_constants() -> None:
    assert _offenders(r'"DBLIFT_', ALLOWED_ENV_PREFIX_SITES) == []
