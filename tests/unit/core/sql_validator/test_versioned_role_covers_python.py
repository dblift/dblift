"""Versioned-migration gates must treat ``.py`` scripts like ``.sql`` scripts.

``MigrationType.SQL`` names a *role* (versioned, run-once), not a format:
``parse_filename`` assigns it to every supported extension and the constructor
then relabels non-SQL formats as ``MigrationType.PYTHON``. A check written
``type == MigrationType.SQL`` therefore silently skips every Python migration.

Each test below parametrises over the file extension and asserts the *same*
outcome for both, so a future third format that is added without touching the
predicate fails here rather than in production.
"""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from core.migration.migration import AppliedMigration, Migration
from core.sql_validator._migration_filter import handle_baseline_filtering
from core.sql_validator._strict_mode_validator import validate_strict_mode_rules
from core.sql_validator.migration_validator import MigrationValidator, ValidationResult

VERSIONED_EXTENSIONS = (".sql", ".py")

_CONTENT = {".sql": "SELECT 1;\n", ".py": "def migrate(context):\n    pass\n"}


def _script(tmp_path: Path, name: str) -> Migration:
    """Build a real ``Migration`` from a file so ``type`` is derived, not asserted."""
    path = tmp_path / name
    path.write_text(_CONTENT[path.suffix])
    return Migration(script_path=path)


def _applied(script_name: str, version: str) -> Migration:
    """Build a history-row-derived ``Migration``, as ``get_applied_migrations`` returns."""
    migration_type = "PYTHON" if script_name.endswith(".py") else "SQL"
    return AppliedMigration.from_history_row(
        {
            "script": script_name,
            "version": version,
            "description": "applied",
            "type": migration_type,
            "checksum": 1,
            "success": True,
        }
    ).to_migration()


def _validator() -> MigrationValidator:
    validator = MigrationValidator.__new__(MigrationValidator)
    validator.log = MagicMock()
    validator.script_manager = SimpleNamespace(
        compare_versions=lambda left, right: int(left) - int(right)
    )
    return validator


@pytest.mark.unit
@pytest.mark.parametrize("extension", VERSIONED_EXTENSIONS)
def test_baseline_filtering_drops_pre_baseline_versioned_script(tmp_path: Path, extension: str):
    """A versioned script at or below the baseline version must never survive the filter.

    A surviving script is re-executed against a schema that was baselined
    precisely to declare it already applied.
    """
    baseline = Migration.create_baseline_migration("-- baseline", "2", "baselined")
    old = _script(tmp_path, f"V1__old{extension}")
    new = _script(tmp_path, f"V3__new{extension}")

    kept = [s.script_name for s in handle_baseline_filtering(_validator(), [baseline, old, new])]

    assert old.script_name not in kept
    assert new.script_name in kept


@pytest.mark.unit
@pytest.mark.parametrize("pending_extension", VERSIONED_EXTENSIONS)
@pytest.mark.parametrize("applied_extension", VERSIONED_EXTENSIONS)
def test_strict_mode_detects_out_of_order_pending_script(
    tmp_path: Path, pending_extension: str, applied_extension: str
):
    """Out-of-order detection must hold for every combination of pending/applied format.

    ``pending_extension`` exercises the pending-versioned collection and
    ``applied_extension`` the applied-versions collection; either one skipping
    Python short-circuits the whole check to a pass.
    """
    pending = _script(tmp_path, f"V1__old{pending_extension}")
    later = _script(tmp_path, f"V2__new{applied_extension}")
    applied = _applied(later.script_name, "2")

    result = ValidationResult()
    issues: list[str] = []

    passed = validate_strict_mode_rules(_validator(), [pending, later], [applied], result, issues)

    assert passed is False
    assert result.success is False
    assert any(pending.script_name in issue for issue in issues)
