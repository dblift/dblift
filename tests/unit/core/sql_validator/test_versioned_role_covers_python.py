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

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.logger import NullLog
from dblift.core.migration.migration import AppliedMigration, Migration
from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager
from dblift.core.migration.state.migration_selector import prune_baseline_migrations
from tests.unit._migration_factory import make_migration

VERSIONED_EXTENSIONS = (".sql", ".py")

_CONTENT = {".sql": "SELECT 1;\n", ".py": "def migrate(context):\n    pass\n"}


def _script(tmp_path: Path, name: str) -> Migration:
    """Build a real ``Migration`` from a file so ``type`` is derived, not asserted."""
    path = tmp_path / name
    path.write_text(_CONTENT[path.suffix])
    return make_migration(script_path=path)


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


@pytest.mark.unit
@pytest.mark.parametrize("extension", VERSIONED_EXTENSIONS)
def test_baseline_filtering_drops_pre_baseline_versioned_script(tmp_path: Path, extension: str):
    """A versioned script at or below the baseline version must never survive the filter.

    A surviving script is re-executed against a schema that was baselined
    precisely to declare it already applied.
    """
    baseline = MigrationScriptManager(NullLog()).baseline_marker("2", "baselined")
    old = _script(tmp_path, f"V1__old{extension}")
    new = _script(tmp_path, f"V3__new{extension}")

    kept = [s.script_name for s in prune_baseline_migrations([baseline, old, new])]

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

    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(tmp_path))
    try:
        snapshot = client.executor.state_manager.build_validation_snapshot(
            None,
            "validate",
            strict_mode=True,
            resolved_migrations=[pending, later],
            applied_migrations=[applied],
        )
        result = client.executor.validator.validate_snapshot(snapshot, "validate")
    finally:
        client.close()
        engine.dispose()

    assert result.success is False
    assert any(pending.script_name in issue for issue in result.issues)
