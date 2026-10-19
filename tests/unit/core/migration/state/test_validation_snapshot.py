"""StateManager owns validation inputs and read-phase freshness."""

from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest
from sqlalchemy import create_engine

from dblift.api import DBLiftClient


@pytest.fixture
def client(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(tmp_path))
    client.executor.history_manager.create_schema_and_history_table(create_schema=False)
    try:
        yield client
    finally:
        client.close()
        engine.dispose()


def test_snapshot_collects_and_scopes_once(client, tmp_path):
    for version in (1, 2):
        (tmp_path / f"V{version}__init.sql").write_text("SELECT 1;")
    assert client.migrate().success
    manager = client.executor.state_manager
    phase = manager.new_read_snapshot()
    with (
        patch.object(
            manager.script_manager,
            "load_migration_scripts",
            wraps=manager.script_manager.load_migration_scripts,
        ) as scripts,
        patch.object(
            manager.history_manager,
            "get_applied_migrations",
            wraps=manager.history_manager.get_applied_migrations,
        ) as history,
    ):
        snapshot = manager.build_validation_snapshot(
            tmp_path, "validate", versions=["2"], strict_mode=True, read_snapshot=phase
        )
        assert scripts.call_count == history.call_count == 1
        reused = manager.build_validation_snapshot(
            tmp_path,
            "migrate",
            resolved_migrations=list(snapshot.resolved_migrations),
            applied_migrations=list(snapshot.all_applied_migrations),
            read_snapshot=phase,
        )
        assert scripts.call_count == history.call_count == 1
    assert [m.version for m in snapshot.resolved_migrations] == ["1", "2"]
    assert [m.version for m in snapshot.selected_migrations] == ["2"]
    assert [m.version for m in snapshot.all_applied_migrations] == ["1", "2"]
    assert [m.version for m in snapshot.scoped_applied_migrations] == ["2"]
    assert (
        snapshot.history_table_exists and snapshot.scripts_directory_exists and snapshot.strict_mode
    )
    assert not reused.strict_mode
    with pytest.raises(FrozenInstanceError):
        snapshot.strict_mode = False


def test_new_snapshot_sees_file_and_history_writes(client, tmp_path):
    manager = client.executor.state_manager
    before = manager.build_validation_snapshot(tmp_path, "validate")
    (tmp_path / "V1__init.sql").write_text("SELECT 1;")
    assert client.migrate().success
    after = manager.build_validation_snapshot(tmp_path, "validate")
    assert before.resolved_migrations == before.all_applied_migrations == ()
    assert len(after.resolved_migrations) == len(after.all_applied_migrations) == 1
    assert not manager.build_validation_snapshot(
        tmp_path / "missing", "validate"
    ).scripts_directory_exists


def test_sequence_and_string_filters_normalize_identically(client, tmp_path):
    (tmp_path / "V1__init.sql").write_text("SELECT 1;")
    manager = client.executor.state_manager
    scripts = manager.get_resolved_migrations(tmp_path)
    scripts[0].tags = ["alpha"]
    assert manager.apply_filters_to_migrations(
        scripts, versions=" 1 "
    ) == manager.apply_filters_to_migrations(scripts, versions=[" 1 "])
    from dblift.core.migration.state.migration_selector import select_migrations

    assert select_migrations(scripts, tags=" alpha, beta ") == select_migrations(
        scripts, tags=[" alpha", "beta "]
    )


def test_snapshot_validation_never_collects(client, tmp_path):
    (tmp_path / "V1__init.sql").write_text("SELECT 1;")
    assert client.migrate().success
    manager = client.executor.state_manager
    snapshot = manager.build_validation_snapshot(tmp_path, "validate", strict_mode=True)
    (tmp_path / "V1__init.sql").unlink()
    with (
        patch.object(
            manager, "build_validation_snapshot", side_effect=AssertionError("collection")
        ),
        patch.object(
            manager.history_manager, "get_applied_migrations", side_effect=AssertionError("history")
        ),
        patch.object(
            manager.script_manager, "get_migration_scripts", side_effect=AssertionError("scripts")
        ),
    ):
        assert client.executor.validator.validate_snapshot(snapshot, "validate").success


def test_missing_directory_and_empty_strict_catalog_preserve_public_results(client, tmp_path):
    missing = tmp_path / "missing"
    result = client.executor.validator.validate_migrations(missing)
    assert not result.success
    assert result.error_message == f"Migration scripts directory not found: {missing}"
    assert result.issues == []
    (tmp_path / "V1__init.sql").write_text("SELECT 1;")
    assert client.migrate().success
    snapshot = client.executor.state_manager.build_validation_snapshot(
        tmp_path, strict_mode=True, resolved_migrations=[]
    )
    result = client.executor.validator.validate_snapshot(snapshot)
    assert not result.success
    assert result.error_message == ""
    assert result.issues == []


@pytest.mark.parametrize("probe", ["directory", "history", "both"])
@pytest.mark.parametrize("populated", [False, True])
def test_preloaded_inputs_skip_existence_and_collection_probes(client, tmp_path, probe, populated):
    from unittest.mock import PropertyMock

    from dblift.core.migration.history.migration_history_manager import MigrationHistoryManager

    manager = client.executor.state_manager
    if populated:
        (tmp_path / "V1__init.sql").write_text("SELECT 1;")
        assert client.migrate().success
    prepared = manager.build_validation_snapshot(tmp_path)
    with (
        patch.object(
            manager.script_manager,
            "migration_directory_exists",
            side_effect=(
                AssertionError("directory probe") if probe in ("directory", "both") else None
            ),
            return_value=True,
        ) as directory,
        patch.object(
            MigrationHistoryManager,
            "has_history_table",
            new_callable=PropertyMock,
            side_effect=AssertionError("history probe") if probe in ("history", "both") else None,
            return_value=True,
        ) as table,
        patch.object(
            manager.script_manager,
            "get_migration_scripts",
            side_effect=AssertionError("catalog read"),
        ) as scripts,
        patch.object(
            manager.history_manager,
            "get_applied_migrations",
            side_effect=AssertionError("history read"),
        ) as history,
        patch.object(
            client.provider, "table_exists", side_effect=AssertionError("provider probe")
        ) as provider,
    ):
        snapshot = manager.build_validation_snapshot(
            tmp_path / "no-longer-present",
            resolved_migrations=list(prepared.resolved_migrations),
            applied_migrations=list(prepared.all_applied_migrations),
        )
    assert snapshot.scripts_directory_exists and snapshot.history_table_exists
    assert snapshot.resolved_migrations == prepared.resolved_migrations
    assert snapshot.all_applied_migrations == prepared.all_applied_migrations
    for read in (directory, table, scripts, history, provider):
        read.assert_not_called()


@pytest.mark.parametrize(
    "collection_method", ["get_migration_scripts", "migration_directory_exists"]
)
def test_catalog_collection_failure_is_immutable_snapshot_input(
    client, tmp_path, collection_method
):
    manager = client.executor.state_manager
    with patch.object(
        manager.script_manager,
        collection_method,
        side_effect=PermissionError("catalog unavailable"),
    ):
        snapshot = manager.build_validation_snapshot(tmp_path)
    assert snapshot.catalog_read_error == "catalog unavailable"
    assert snapshot.resolved_migrations == snapshot.selected_migrations == ()
    with pytest.raises(FrozenInstanceError):
        snapshot.catalog_read_error = "changed"


def _break_history_table(tmp_path):
    import sqlite3

    connection = sqlite3.connect(tmp_path / "app.db")
    try:
        connection.execute("ALTER TABLE dblift_schema_history RENAME COLUMN checksum TO renamed")
        connection.commit()
    finally:
        connection.close()


def test_history_read_failure_is_immutable_snapshot_input(client, tmp_path):
    manager = client.executor.state_manager
    with patch.object(
        manager.history_manager,
        "get_applied_migrations",
        side_effect=RuntimeError("history unavailable"),
    ):
        snapshot = manager.build_validation_snapshot(tmp_path)
    assert snapshot.history_read_error == "history unavailable"
    assert snapshot.all_applied_migrations == ()
    with pytest.raises(FrozenInstanceError):
        snapshot.history_read_error = "changed"


@pytest.mark.parametrize("strict", [False, True])
@pytest.mark.parametrize("with_scripts", [False, True])
def test_unreadable_history_fails_validation(client, tmp_path, strict, with_scripts):
    (tmp_path / "V1__init.sql").write_text("SELECT 1;")
    assert client.migrate().success
    if not with_scripts:
        (tmp_path / "V1__init.sql").unlink()
    _break_history_table(tmp_path)
    manager = client.executor.state_manager
    snapshot = manager.build_validation_snapshot(tmp_path, "validate", strict_mode=strict)
    result = client.executor.validator.validate_snapshot(snapshot, "validate")
    assert not result.success
    assert result.error_message.startswith("Validation failed: could not read migration history:")
    assert "checksum" in result.error_message


def test_client_validate_returns_failed_result_for_unreadable_history(client, tmp_path):
    import warnings

    (tmp_path / "V1__init.sql").write_text("SELECT 1;")
    assert client.migrate().success
    _break_history_table(tmp_path)
    with warnings.catch_warnings():
        warnings.simplefilter("error", DeprecationWarning)
        result = client.validate()
    assert not result.success
    assert "could not read migration history" in result.error_message


def test_snapshot_and_state_carry_repeatable_runs(client, tmp_path):
    (tmp_path / "R__view.sql").write_text("SELECT 1;")
    manager = client.executor.state_manager

    before = manager.build_validation_snapshot(tmp_path, "validate")
    assert before.repeatable_runs["R__view.sql"].status.value == "NEW"
    assert manager.build_state(tmp_path).repeatable_runs["R__view.sql"].status.value == "NEW"

    assert client.migrate().success
    after = manager.build_validation_snapshot(tmp_path, "validate")
    assert after.repeatable_runs["R__view.sql"].status.value == "UNCHANGED"
    assert manager.build_state(tmp_path).repeatable_runs["R__view.sql"].status.value == "UNCHANGED"


def _edited_v1(tmp_path):
    (tmp_path / "V1__init.sql").write_text("SELECT 1;")
    (tmp_path / "V2__more.sql").write_text("SELECT 2;")


def test_build_state_reports_drift(client, tmp_path):
    _edited_v1(tmp_path)
    assert client.migrate().success
    manager = client.executor.state_manager
    assert manager.build_state(tmp_path).checksum_drift == ()
    (tmp_path / "V1__init.sql").write_text("SELECT 1; -- edited")
    state = manager.build_state(tmp_path)
    assert [d.script_name for d in state.checksum_drift] == ["V1__init.sql"]
    assert not state.checksum_drift[0].repeatable
    assert state.copy().checksum_drift == state.checksum_drift
    assert manager.build_state(None).checksum_drift == ()


def test_snapshot_reports_drift(client, tmp_path):
    _edited_v1(tmp_path)
    assert client.migrate().success
    manager = client.executor.state_manager
    assert manager.build_validation_snapshot(tmp_path, "validate").checksum_drift == ()
    (tmp_path / "V1__init.sql").write_text("SELECT 1; -- edited")
    snapshot = manager.build_validation_snapshot(tmp_path, "validate")
    assert [d.script_name for d in snapshot.checksum_drift] == ["V1__init.sql"]
    # A script outside the version scope is not reported.
    scoped = manager.build_validation_snapshot(tmp_path, "validate", versions=["2"])
    assert scoped.checksum_drift == ()


def _plan_refuses(manager, tmp_path):
    from dblift.core.migration.state.migrate_plan import StrictModeError

    try:
        manager.plan_migrate(
            tmp_path,
            recursive=True,
            additional_dirs=None,
            dir_recursive_map=None,
            target_version=None,
            tags=None,
            exclude_tags=None,
            versions=None,
            exclude_versions=None,
            strict_mode=True,
        )
    except StrictModeError:
        return True
    return False


def _applied_v1_v3(tmp_path):
    (tmp_path / "V1__a.sql").write_text("SELECT 1;")
    (tmp_path / "V3__c.sql").write_text("SELECT 3;")
    (tmp_path / "U3__c.sql").write_text("SELECT -3;")


def test_snapshot_out_of_order_is_measured_against_current_version(client, tmp_path):
    _applied_v1_v3(tmp_path)
    assert client.migrate().success
    (tmp_path / "V2__b.sql").write_text("SELECT 2;")
    manager = client.executor.state_manager

    snapshot = manager.build_validation_snapshot(tmp_path, "validate", strict_mode=True)

    assert [(o.migration.script_name, o.current_version) for o in snapshot.out_of_order] == [
        ("V2__b.sql", "3")
    ]
    assert _plan_refuses(manager, tmp_path)


def test_snapshot_out_of_order_ignores_undone_versions(client, tmp_path):
    _applied_v1_v3(tmp_path)
    assert client.migrate().success
    assert client.undo().success
    (tmp_path / "V2__b.sql").write_text("SELECT 2;")
    manager = client.executor.state_manager

    snapshot = manager.build_validation_snapshot(tmp_path, "validate", strict_mode=True)

    assert snapshot.out_of_order == ()
    assert not _plan_refuses(manager, tmp_path)


def test_snapshot_out_of_order_follows_the_selection(client, tmp_path):
    _applied_v1_v3(tmp_path)
    assert client.migrate().success
    (tmp_path / "V2__b.sql").write_text("SELECT 2;")
    manager = client.executor.state_manager

    excluded = manager.build_validation_snapshot(
        tmp_path, "validate", strict_mode=True, exclude_versions=["2"]
    )

    assert excluded.out_of_order == ()


def test_snapshot_out_of_order_is_only_computed_for_strict_validation(client, tmp_path):
    _applied_v1_v3(tmp_path)
    assert client.migrate().success
    (tmp_path / "V2__b.sql").write_text("SELECT 2;")
    manager = client.executor.state_manager

    with patch.object(manager, "_analyse_history", wraps=manager._analyse_history) as analyse:
        loose = manager.build_validation_snapshot(tmp_path, "validate", strict_mode=False)

    assert loose.out_of_order == ()
    analyse.assert_not_called()


def test_snapshot_missing_applied_ignores_tag_and_version_filters(client, tmp_path):
    (tmp_path / "V1__a.sql").write_text("SELECT 1;")
    (tmp_path / "V2__b.sql").write_text("SELECT 2;")
    assert client.migrate().success
    (tmp_path / "V2__b.sql").unlink()
    manager = client.executor.state_manager

    everything = manager.build_validation_snapshot(tmp_path, "validate")
    filtered = manager.build_validation_snapshot(tmp_path, "validate", versions=["1"])

    assert [m.script_name for m in everything.missing_applied] == ["V2__b.sql"]
    # Version 2 is outside the filter, so its row is out of scope, not missing.
    assert filtered.missing_applied == ()
    (tmp_path / "V2__b.sql").write_text("SELECT 2;")
    present = manager.build_validation_snapshot(tmp_path, "validate", versions=["1"])
    assert present.missing_applied == ()


def test_snapshot_missing_applied_is_filled_without_strict_mode(client, tmp_path):
    (tmp_path / "V1__a.sql").write_text("SELECT 1;")
    assert client.migrate().success
    (tmp_path / "V1__a.sql").unlink()
    manager = client.executor.state_manager

    with patch.object(manager, "_analyse_history", wraps=manager._analyse_history) as analyse:
        loose = manager.build_validation_snapshot(tmp_path, "validate", strict_mode=False)

    assert [m.script_name for m in loose.missing_applied] == ["V1__a.sql"]
    analyse.assert_not_called()


def test_state_missing_applied_follows_the_catalog(client, tmp_path):
    (tmp_path / "V1__a.sql").write_text("SELECT 1;")
    (tmp_path / "V2__b.sql").write_text("SELECT 2;")
    assert client.migrate().success
    (tmp_path / "V2__b.sql").unlink()
    manager = client.executor.state_manager

    state = manager.build_state(tmp_path)
    without_catalog = manager.build_state(None)

    assert [m.script_name for m in state.missing_applied] == ["V2__b.sql"]
    assert state.copy().missing_applied == state.missing_applied
    assert without_catalog.missing_applied == ()


def _applied_v1_v2_with_undo(client, tmp_path):
    (tmp_path / "V1__a.sql").write_text("SELECT 1;")
    (tmp_path / "V2__b.sql").write_text("SELECT 2;")
    (tmp_path / "U2__b.sql").write_text("SELECT -2;")
    assert client.migrate().success


def test_undone_version_with_deleted_script_is_not_missing(client, tmp_path):
    _applied_v1_v2_with_undo(client, tmp_path)
    assert client.undo().success
    (tmp_path / "V2__b.sql").unlink()
    manager = client.executor.state_manager

    snapshot = manager.build_validation_snapshot(tmp_path, "validate")
    state = manager.build_state(tmp_path)

    assert snapshot.missing_applied == ()
    assert state.missing_applied == ()


def test_reapplied_version_with_deleted_script_is_missing(client, tmp_path):
    _applied_v1_v2_with_undo(client, tmp_path)
    assert client.undo().success
    assert client.migrate().success
    (tmp_path / "V2__b.sql").unlink()
    manager = client.executor.state_manager

    snapshot = manager.build_validation_snapshot(tmp_path, "validate")
    state = manager.build_state(tmp_path)

    assert [m.script_name for m in snapshot.missing_applied] == ["V2__b.sql"]
    assert [m.script_name for m in state.missing_applied] == ["V2__b.sql"]
