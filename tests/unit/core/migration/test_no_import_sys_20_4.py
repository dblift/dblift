"""Structural tests: verify import sys absent from 9 files (story 20-4)."""

import inspect
from pathlib import Path

import pytest

# fmt: off
_FILES_UNDER_TEST = [
    "dblift/core/migration/rules/migration_rules.py",
    "dblift/core/migration/state/migration_state_manager.py",
    "dblift/core/migration/state/migration_data_service.py",
    "dblift/core/migration/ui/migration_ui.py",
    "dblift/core/migration/executor/migration_helpers.py",
    "dblift/core/migration/executor/placeholder_manager.py",
]
# fmt: on

_ROOT = Path(__file__).parents[4]

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize("rel_path", _FILES_UNDER_TEST)
def test_no_import_sys(rel_path: str) -> None:
    """import sys must be absent from all 8 files cleaned up in story 20-4."""
    source = (_ROOT / rel_path).read_text(encoding="utf-8")
    import_sys_lines = [line for line in source.splitlines() if line.strip() == "import sys"]
    assert import_sys_lines == [], f"{rel_path} still contains 'import sys' (story 20-4 regression)"
