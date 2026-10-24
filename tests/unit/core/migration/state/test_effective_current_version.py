"""The current version follows the effective migration history."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine, text

from dblift.api import DBLiftClient

pytestmark = [pytest.mark.unit, pytest.mark.sqlite]


@pytest.fixture
def client_and_scripts(tmp_path: Path):
    scripts = tmp_path / "migrations"
    scripts.mkdir()
    engine = create_engine(f"sqlite:///{tmp_path / 'app.db'}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=str(scripts))
    try:
        yield client, scripts, engine
    finally:
        client.close()
        engine.dispose()


def _write(scripts: Path, **files: str) -> None:
    for name, sql in files.items():
        (scripts / name).write_text(sql)


def _assert_current(client: DBLiftClient, scripts: Path, expected: str | None) -> None:
    state_manager = client.executor.state_manager
    state = state_manager.build_state(scripts)
    assert state.current_version == expected
    assert state.to_dict()["current_version"] == expected
    assert state_manager.get_current_version(state.all_applied_objects) == expected
    assert state_manager.resolve_current_schema_version() == expected
    info = client.info()
    assert info.success, info.error_message
    assert info.current_schema_version == expected
    plan = state_manager.plan_migrate(
        scripts,
        recursive=False,
        additional_dirs=None,
        dir_recursive_map=None,
        target_version=None,
        tags=None,
        exclude_tags=None,
        versions=None,
        exclude_versions=None,
        strict_mode=False,
    )
    assert plan.current_version == expected
    assert plan.state.current_version == expected
    undo_plan = state_manager.plan_undo(
        scripts,
        recursive=False,
        additional_dirs=None,
        dir_recursive_map=None,
        target_version=None,
        tags=None,
        exclude_tags=None,
        versions=None,
        exclude_versions=None,
        migration_rules=state_manager.migration_rules,
    )
    assert undo_plan.current_version == expected
    assert undo_plan.state.current_version == expected


def test_state_current_version_after_undo(client_and_scripts) -> None:
    client, scripts, _ = client_and_scripts
    _write(
        scripts,
        **{
            "V1__create_t.sql": "CREATE TABLE t (id INTEGER);",
            "V2__create_u.sql": "CREATE TABLE u (id INTEGER);",
            "U2__drop_u.sql": "DROP TABLE u;",
        },
    )
    assert client.migrate().success
    assert client.undo(target_version="1").success
    _assert_current(client, scripts, "1")


def test_state_current_version_from_baseline(client_and_scripts) -> None:
    client, scripts, _ = client_and_scripts
    assert client.baseline(version="5").success
    _assert_current(client, scripts, "5")


def test_undo_to_empty_history_has_no_current_version(client_and_scripts) -> None:
    client, scripts, _ = client_and_scripts
    _write(
        scripts,
        **{
            "V1__create_t.sql": "CREATE TABLE t (id INTEGER);",
            "U1__drop_t.sql": "DROP TABLE t;",
        },
    )
    assert client.migrate().success
    result = client.undo(target_version="0")
    assert result.success, result.error_message
    assert result.current_schema_version is None
    _assert_current(client, scripts, None)


@pytest.mark.parametrize(
    "scenario,expected",
    [
        ("reapply", "2"),
        ("failed_v3", "2"),
        ("out_of_order", "3"),
        ("failed_undo", "2"),
        ("failed_reapply", "1"),
    ],
)
def test_current_version_obeys_latest_successful_action(
    client_and_scripts, scenario: str, expected: str
) -> None:
    client, scripts, engine = client_and_scripts
    _write(scripts, **{"V1__create_t.sql": "CREATE TABLE t (id INTEGER);"})
    assert client.migrate().success

    if scenario == "out_of_order":
        _write(scripts, **{"V3__create_v.sql": "CREATE TABLE v (id INTEGER);"})
        assert client.migrate().success
        _write(scripts, **{"V2__create_u.sql": "CREATE TABLE u (id INTEGER);"})
        assert client.migrate().success
    else:
        _write(scripts, **{"V2__create_u.sql": "CREATE TABLE u (id INTEGER);"})
        if scenario == "failed_undo":
            _write(scripts, **{"U2__drop_u.sql": "DROP TABLE absent;"})
        else:
            _write(scripts, **{"U2__drop_u.sql": "DROP TABLE u;"})
        assert client.migrate().success

        if scenario == "failed_v3":
            _write(scripts, **{"V3__invalid.sql": "INSERT INTO absent VALUES (1);"})
            assert not client.migrate().success
        elif scenario == "failed_undo":
            assert not client.undo(target_version="1").success
        elif scenario in {"reapply", "failed_reapply"}:
            assert client.undo(target_version="1").success
            if scenario == "failed_reapply":
                with engine.begin() as connection:
                    connection.execute(text("CREATE TABLE u (id INTEGER)"))
                assert not client.migrate().success
            else:
                assert client.migrate().success

    _assert_current(client, scripts, expected)
