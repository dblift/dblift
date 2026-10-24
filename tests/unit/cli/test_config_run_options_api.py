"""Run options set in the YAML config or the environment are honoured by the Python API.

Precedence is the CLI's: explicit argument > environment variable > YAML.
"""

import os
import sqlite3

import pytest
import yaml

from dblift.api import DBLiftClient

pytestmark = pytest.mark.unit

_TAGS = {1: "a", 2: "b", 3: "a,b"}


@pytest.fixture(autouse=True)
def _clean_environment(monkeypatch):
    for key in list(os.environ):
        if key.startswith("DBLIFT_"):
            monkeypatch.delenv(key)


def _project(tmp_path, **options):
    for number in (1, 2, 3):
        for name, sql in (
            (f"V{number}__t{number}[{_TAGS[number]}].sql", f"CREATE TABLE t{number}(id INTEGER);"),
            (f"U{number}__t{number}.sql", f"DROP TABLE t{number};"),
        ):
            if not (tmp_path / name).exists():
                (tmp_path / name).write_text(sql)
    config = tmp_path / "dblift.yaml"
    config.write_text(
        yaml.safe_dump(
            {
                "database": {"type": "sqlite", "path": str(tmp_path / "db.sqlite")},
                "migrations": {"directory": str(tmp_path)},
                **options,
            }
        )
    )
    return str(config)


def _tables(tmp_path):
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        return {
            row[0]
            for row in db.execute("SELECT name FROM sqlite_master WHERE type='table'")
            if row[0] in ("t1", "t2", "t3")
        }


def _history_rows(tmp_path):
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        table = next(n for n in names if "history" in n.lower())
        return db.execute(f"SELECT COUNT(*) FROM {table} WHERE version IS NOT NULL").fetchone()[0]


def _migrate(tmp_path, options, **arguments):
    with DBLiftClient.from_config_file(_project(tmp_path, **options)) as client:
        result = client.migrate(**arguments)
        assert result.success, result.error_message
    return result


@pytest.mark.parametrize(
    "options, expected",
    [
        ({"versions": "1,3"}, {"t1", "t3"}),
        ({"exclude_versions": "2"}, {"t1", "t3"}),
        ({"tags": "b"}, {"t2", "t3"}),
        ({"exclude_tags": "b"}, {"t1"}),
    ],
)
def test_migrate_honours_selection_from_yaml(tmp_path, options, expected):
    _migrate(tmp_path, options)
    assert _tables(tmp_path) == expected


def test_migrate_honours_dry_run_from_yaml(tmp_path):
    _migrate(tmp_path, {"dry_run": True})
    assert _tables(tmp_path) == set()


def test_migrate_honours_mark_as_executed_from_yaml(tmp_path):
    _migrate(tmp_path, {"mark_as_executed": True})
    assert _tables(tmp_path) == set()
    assert _history_rows(tmp_path) == 3


def test_migrate_honours_dry_run_from_environment_and_the_argument_adds_it(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_DRY_RUN", "true")
    _migrate(tmp_path, {})
    assert _tables(tmp_path) == set()
    monkeypatch.delenv("DBLIFT_DRY_RUN")
    _migrate(tmp_path, {}, dry_run=True)
    assert _tables(tmp_path) == set()


def test_environment_dry_run_beats_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_DRY_RUN", "false")
    _migrate(tmp_path, {"dry_run": True})
    assert _tables(tmp_path) == {"t1", "t2", "t3"}


def test_migrate_environment_beats_yaml(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_VERSIONS", "2")
    _migrate(tmp_path, {"versions": "1,3"})
    assert _tables(tmp_path) == {"t2"}


def test_explicit_selection_argument_beats_yaml(tmp_path):
    _migrate(tmp_path, {"versions": "1,3"}, versions="2")
    assert _tables(tmp_path) == {"t2"}


def _applied(tmp_path, **options):
    _migrate(tmp_path, {})
    return DBLiftClient.from_config_file(_project(tmp_path, **options))


def test_undo_honours_dry_run_and_selection_from_yaml(tmp_path):
    with _applied(tmp_path, dry_run=True) as client:
        assert client.undo(target_version="1").success
    assert _tables(tmp_path) == {"t1", "t2", "t3"}
    with _applied(tmp_path, versions="3") as client:
        assert client.undo(target_version="1").success
    assert _tables(tmp_path) == {"t1", "t2"}


def test_validate_and_info_honour_selection_from_yaml(tmp_path):
    with _applied(tmp_path, exclude_versions="3") as client:
        (tmp_path / "V3__t3[a,b].sql").write_text("CREATE TABLE t3(id INTEGER, extra TEXT);")
        assert client.validate().success is True
        assert client.validate(exclude_versions="").success is False
        listed = {str(m.version) for m in client.info().migrations}
        assert "3" not in listed


def test_clean_honours_dry_run_from_yaml(tmp_path):
    _migrate(tmp_path, {})
    config = _project(tmp_path, dry_run=True, clean_disabled=False)
    with DBLiftClient.from_config_file(config) as client:
        client.clean()
    assert _tables(tmp_path) == {"t1", "t2", "t3"}


@pytest.mark.parametrize(
    "options, left",
    [
        ({"tags": "b"}, {"t1"}),
        ({"exclude_tags": "b"}, {"t2", "t3"}),
        ({"versions": "2"}, {"t1", "t3"}),
        ({"exclude_versions": "3"}, {"t3"}),
    ],
)
def test_undo_honours_selection_from_yaml(tmp_path, options, left):
    with _applied(tmp_path, **options) as client:
        assert client.undo(target_version="0").success
    assert _tables(tmp_path) == left


@pytest.mark.parametrize(
    "options, listed",
    [
        ({"tags": "b"}, {"2", "3"}),
        ({"exclude_tags": "b"}, {"1"}),
        ({"versions": "2"}, {"2"}),
        ({"exclude_versions": "2,3"}, {"1"}),
    ],
)
def test_info_honours_selection_from_yaml(tmp_path, options, listed):
    with DBLiftClient.from_config_file(_project(tmp_path, **options)) as client:
        assert {str(m.version) for m in client.info().migrations} == listed


@pytest.mark.parametrize(
    "options",
    [{"tags": "b"}, {"exclude_tags": "a"}, {"versions": "2"}, {"exclude_versions": "1"}],
)
def test_validate_honours_selection_from_yaml(tmp_path, options):
    _migrate(tmp_path, {})
    (tmp_path / "V1__t1[a].sql").write_text("CREATE TABLE t1(id INTEGER, extra TEXT);")
    with DBLiftClient.from_config_file(_project(tmp_path, **options)) as client:
        assert client.validate().success is True
    with DBLiftClient.from_config_file(_project(tmp_path)) as client:
        assert client.validate().success is False


def _stored_checksum(tmp_path):
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        table = next(n for n in names if "history" in n.lower() and "flyway" not in n.lower())
        return db.execute(f"SELECT checksum FROM {table} WHERE version = '1'").fetchone()[0]


def test_repair_honours_dry_run_from_yaml(tmp_path):
    _migrate(tmp_path, {})
    before = _stored_checksum(tmp_path)
    (tmp_path / "V1__t1[a].sql").write_text("CREATE TABLE t1(id INTEGER, extra TEXT);")
    with DBLiftClient.from_config_file(_project(tmp_path, dry_run=True)) as client:
        assert client.repair().success
    assert _stored_checksum(tmp_path) == before
    with DBLiftClient.from_config_file(_project(tmp_path)) as client:
        assert client.repair().success
    assert _stored_checksum(tmp_path) != before


def test_import_flyway_honours_dry_run_from_yaml(tmp_path):
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        db.execute(
            "CREATE TABLE flyway_schema_history (installed_rank INTEGER, version TEXT, "
            "description TEXT, type TEXT, script TEXT, installed_by TEXT, installed_on TEXT, "
            "checksum INTEGER, execution_time INTEGER, success INTEGER)"
        )
        db.execute(
            "INSERT INTO flyway_schema_history VALUES "
            "(1, '1', 't1', 'SQL', 'V1__t1.sql', 'me', '2026-01-01 00:00:00', 1, 0, 1)"
        )
    with DBLiftClient.from_config_file(_project(tmp_path, dry_run=True)) as client:
        assert client.import_flyway().success
    with sqlite3.connect(tmp_path / "db.sqlite") as db:
        names = [r[0] for r in db.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        history = [n for n in names if "history" in n.lower() and "flyway" not in n.lower()]
        assert not history or db.execute(f"SELECT COUNT(*) FROM {history[0]}").fetchone()[0] == 0


@pytest.mark.parametrize("configured", [True, False])
def test_results_report_whether_the_run_was_a_dry_run(tmp_path, configured):
    options = {"dry_run": True} if configured else {}
    with DBLiftClient.from_config_file(_project(tmp_path, **options)) as client:
        assert client.migrate().dry_run is configured
    _migrate(tmp_path, {}) if configured else None
    with DBLiftClient.from_config_file(_project(tmp_path, clean_disabled=False, **options)) as c:
        assert c.undo(target_version="1").dry_run is configured
        assert c.repair().dry_run is configured
        assert c.clean().dry_run is configured
