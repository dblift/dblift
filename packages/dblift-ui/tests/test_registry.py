import json

import pytest
from dblift_ui.registry import SCHEMA_VERSION, ProjectRegistry, RegistryError


def test_empty_when_file_is_missing(tmp_path):
    assert ProjectRegistry(tmp_path / "projects.json").list() == []


def test_add_persists_and_reloads(tmp_path, sqlite_project):
    path = tmp_path / "state" / "projects.json"
    added = ProjectRegistry(path).add("shop", str(sqlite_project))

    reloaded = ProjectRegistry(path).list()

    assert [p.id for p in reloaded] == [added.id]
    assert reloaded[0].name == "shop"
    assert reloaded[0].config_path == str(sqlite_project.resolve())
    assert json.loads(path.read_text())["schema_version"] == SCHEMA_VERSION


def test_add_rejects_missing_file(tmp_path):
    with pytest.raises(RegistryError, match="not found"):
        ProjectRegistry(tmp_path / "projects.json").add("x", str(tmp_path / "nope.yaml"))


def test_add_rejects_non_yaml(tmp_path):
    other = tmp_path / "notes.txt"
    other.write_text("hello")
    with pytest.raises(RegistryError, match="yaml"):
        ProjectRegistry(tmp_path / "projects.json").add("x", str(other))


def test_add_rejects_duplicate_config(tmp_path, sqlite_project):
    registry = ProjectRegistry(tmp_path / "projects.json")
    registry.add("shop", str(sqlite_project))
    with pytest.raises(RegistryError, match="already"):
        registry.add("shop again", str(sqlite_project))


def test_remove(tmp_path, sqlite_project):
    registry = ProjectRegistry(tmp_path / "projects.json")
    project = registry.add("shop", str(sqlite_project))
    registry.remove(project.id)
    assert registry.list() == []
    with pytest.raises(KeyError):
        registry.remove(project.id)


def test_set_environment(tmp_path, sqlite_project):
    registry = ProjectRegistry(tmp_path / "projects.json")
    project = registry.add("shop", str(sqlite_project))
    registry.set_environment(project.id, "staging")
    assert registry.get(project.id).last_environment == "staging"


def test_file_from_a_newer_version_is_refused(tmp_path):
    path = tmp_path / "projects.json"
    path.write_text(json.dumps({"schema_version": SCHEMA_VERSION + 1, "projects": []}))
    with pytest.raises(RegistryError, match="newer"):
        ProjectRegistry(path).list()


def test_default_location_honours_override(tmp_path, monkeypatch):
    monkeypatch.setenv("DBLIFT_UI_HOME", str(tmp_path))
    assert ProjectRegistry.default().path == tmp_path / "projects.json"
