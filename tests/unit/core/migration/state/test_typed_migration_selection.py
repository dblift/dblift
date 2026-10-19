"""Executable migration selection is independent of display rows."""

from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient
from dblift.core.migration.state import migration_state
from dblift.core.migration.state.migration_display_state import MigrationDisplayState

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


@pytest.fixture
def catalog(tmp_path: Path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    for name, sql in {
        "V1__first.sql": "SELECT 1;",
        "V3__third.sql": "SELECT 3;",
        "V4__fourth.sql": "SELECT 4;",
        "U3__third.sql": "SELECT -3;",
    }.items():
        (scripts / name).write_text(sql)
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(scripts))
    try:
        assert client.baseline(version="2").success
        yield client, scripts
    finally:
        client.close()
        engine.dispose()


def _state(catalog):
    client, scripts = catalog
    return client.executor.state_manager.build_state(scripts, target_version="3")


def _plan(catalog):
    client, scripts = catalog
    return client.executor.state_manager.plan_migrate(
        scripts,
        recursive=False,
        additional_dirs=None,
        dir_recursive_map=None,
        target_version="3",
        tags=None,
        exclude_tags=None,
        versions=None,
        exclude_versions=None,
        strict_mode=False,
    )


def test_display_cannot_change_execute_list(catalog) -> None:
    """Changing a rendered label must not deselect an eligible migration."""
    state = _state(catalog)
    selected = state.executable_pending_objects()
    assert [migration.script_name for migration in selected] == ["V3__third.sql"]
    original_checksum = selected[0].checksum

    rendered = state.to_dict()
    assert [row["script"] for row in rendered["pending"]] == [
        "V1__first.sql",
        "V3__third.sql",
        "V4__fourth.sql",
        "U3__third.sql",
    ]
    for entry in state.pending:
        if entry.script == "V3__third.sql":
            entry.status = "Ready to run"

    actual = state.executable_pending_objects()
    assert [migration.script_name for migration in actual] == ["V3__third.sql"]
    assert actual[0] is selected[0]
    assert actual[0].checksum == original_checksum


def test_display_list_mutation_cannot_change_execute_list(catalog) -> None:
    """Reordering or clearing rendered rows must not reorder or erase selection."""
    state = _state(catalog)
    selected = state.executable_pending_objects()
    assert [migration.script_name for migration in selected] == ["V3__third.sql"]
    state.to_dict()
    state.pending.reverse()
    assert state.executable_pending_objects() == selected
    state.pending.clear()

    actual = state.executable_pending_objects()
    assert actual == selected
    assert actual[0] is selected[0]


def test_has_pending_ignores_display_mutation(catalog) -> None:
    """The executable flag follows eligibility even when display rows change."""
    state = _state(catalog)
    assert state.has_pending

    for entry in state.pending:
        if entry.script == "V3__third.sql":
            entry.status = "Ready to run"
    assert state.has_pending

    state.pending.clear()
    assert state.has_pending


def test_catalog_is_immutable_and_owns_selected_objects(catalog) -> None:
    """Catalog records retain selection identity independently of display rows."""
    assert hasattr(migration_state, "MigrationEligibility")
    assert hasattr(migration_state, "CatalogMigration")
    state = _state(catalog)
    assert hasattr(state, "catalog")

    eligibility = migration_state.MigrationEligibility
    assert isinstance(state.catalog, tuple)
    assert [(record.migration.script_name, record.eligibility) for record in state.catalog] == [
        ("V1__first.sql", eligibility.BELOW_BASELINE),
        ("V3__third.sql", eligibility.PENDING),
        ("V4__fourth.sql", eligibility.ABOVE_TARGET),
        ("U3__third.sql", eligibility.UNDO_AVAILABLE),
    ]
    selected = state.executable_pending_objects()
    assert selected[0] is state.catalog[1].migration
    with pytest.raises(FrozenInstanceError):
        state.catalog[1].eligibility = eligibility.ABOVE_TARGET


def test_copy_preserves_catalog_identity_and_missing_applied(catalog) -> None:
    """Copy keeps canonical selection and unrelated missing-script evidence."""
    state = _state(catalog)
    selected = state.executable_pending_objects()
    state.missing_applied = (selected[0],)
    copied = state.copy()

    assert copied.catalog == state.catalog
    assert copied.catalog is state.catalog
    assert copied.executable_pending_objects()[0] is selected[0]
    assert copied.pending is not state.pending
    assert copied.pending_objects is not state.pending_objects
    assert copied.missing_applied == state.missing_applied


def test_target_and_baseline_are_eligibility(catalog) -> None:
    """Baseline, target and undo categories retain their current behavior."""
    state = _state(catalog)
    assert [(entry.script, entry.status) for entry in state.pending] == [
        ("V1__first.sql", MigrationDisplayState.BELOW_BASELINE.value),
        ("V3__third.sql", MigrationDisplayState.PENDING.value),
        ("V4__fourth.sql", MigrationDisplayState.ABOVE_TARGET.value),
        ("U3__third.sql", MigrationDisplayState.AVAILABLE.value),
    ]
    assert [migration.script_name for migration in state.executable_pending_objects()] == [
        "V3__third.sql"
    ]


def test_plan_preserves_selected_object_and_checksum(catalog) -> None:
    """The plan selects the exact catalog object in the same order."""
    plan = _plan(catalog)
    selected = plan.state.executable_pending_objects()
    assert [migration.script_name for migration in plan.pending] == ["V3__third.sql"]
    assert tuple(selected) == plan.pending
    assert plan.pending[0] is selected[0]
    assert plan.pending[0].checksum == selected[0].checksum


def test_display_cannot_hide_available_undo_script(catalog) -> None:
    """An available undo script stays selectable after its display label changes."""
    client, scripts = catalog
    assert client.migrate(target_version="3").success
    manager = client.executor.state_manager
    state = manager.build_state(scripts)
    undo_script = next(
        migration for migration in state.pending_objects if migration.script_name == "U3__third.sql"
    )
    checksum = undo_script.checksum
    state.to_dict()
    for entry in state.pending:
        if entry.script == "U3__third.sql":
            entry.status = "Ready to undo"

    with patch.object(manager, "build_state", return_value=state):
        plan = manager.plan_undo(
            scripts,
            recursive=False,
            additional_dirs=None,
            dir_recursive_map=None,
            target_version=None,
            tags=None,
            exclude_tags=None,
            versions=None,
            exclude_versions=None,
            migration_rules=manager.migration_rules,
        )

    assert plan.refusal is None
    assert len(plan.steps) == 1
    assert plan.steps[0].migration.script_name == "V3__third.sql"
    assert plan.steps[0].undo_script is undo_script
    assert plan.steps[0].undo_script.checksum == checksum


def test_two_eligible_scripts_keep_order_and_identity_after_display_reorder(catalog) -> None:
    """Display order cannot add or remove an executable catalog object."""
    client, scripts = catalog
    (scripts / "V5__fifth.sql").write_text("SELECT 5;")
    state = client.executor.state_manager.build_state(scripts, target_version="4")
    selected = state.executable_pending_objects()
    assert [migration.script_name for migration in selected] == [
        "V3__third.sql",
        "V4__fourth.sql",
    ]
    checksums = [migration.checksum for migration in selected]
    state.to_dict()
    state.pending.reverse()

    actual = state.executable_pending_objects()
    assert [migration.script_name for migration in actual] == [
        "V3__third.sql",
        "V4__fourth.sql",
    ]
    assert all(found is original for found, original in zip(actual, selected))
    assert [migration.checksum for migration in actual] == checksums
