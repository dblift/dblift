import json

import pytest
from dblift_ui.jobs import check_params


def _add(client, auth, config):
    return client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(config)}
    ).json()["id"]


def _run(client, auth, project_id, command, params=None):
    started = client.post(
        f"/api/projects/{project_id}/jobs",
        headers=auth,
        json={"command": command, "params": params or {}},
    )
    assert started.status_code == 202, started.text
    with client.stream(
        "GET", f"/api/jobs/{started.json()['job_id']}/events", headers=auth
    ) as response:
        events = [json.loads(l[6:]) for l in response.iter_lines() if l.startswith("data: ")]
    return events, events[-1]["result"]


def _states(result):
    return [(m["version"], m["status"]) for m in result["migrations"]]


def test_preview_lists_statements_and_applies_nothing(
    client, auth, sqlite_project, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    _, preview = _run(client, auth, project_id, "preview")

    assert preview["success"] is True
    assert [s["script"] for s in preview["sql"]] == [
        "V1_0_0__create_customers.sql",
        "V1_0_1__create_orders.sql",
    ]
    assert preview["sql"][0]["statements"] == ["CREATE TABLE customers (id INTEGER PRIMARY KEY);"]
    _, status = _run(client, auth, project_id, "info")
    assert _states(status) == [("1.0.0", "PENDING"), ("1.0.1", "PENDING")]


def test_migrate_streams_one_event_pair_per_script(
    client, auth, sqlite_project, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    events, result = _run(client, auth, project_id, "migrate")

    names = [e["event"] for e in events]
    assert names[0] == "migration.started"
    assert names.count("migration.script.started") == 2
    assert names.count("migration.script.completed") == 2
    completed = [e["script"] for e in events if e["event"] == "migration.script.completed"]
    assert completed == ["V1_0_0__create_customers.sql", "V1_0_1__create_orders.sql"]
    assert result["success"] is True
    assert result["current_version"] == "1.0.1"


def test_undo_reverts_the_last_migration(client, auth, sqlite_project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)
    _run(client, auth, project_id, "migrate")

    events, result = _run(client, auth, project_id, "undo")

    assert result["success"] is True
    assert "undo.script.rolled_back" in [e["event"] for e in events]
    _, status = _run(client, auth, project_id, "info")
    assert dict(_states(status))["1.0.0"] == "SUCCESS"
    assert dict(_states(status))["1.0.1"] == "PENDING"


def test_failed_script_then_repair(client, auth, sqlite_project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    (sqlite_project.parent / "migrations" / "V1_0_2__broken.sql").write_text("SELEC nonsense;\n")
    project_id = _add(client, auth, sqlite_project)

    events, result = _run(client, auth, project_id, "migrate")

    assert result["success"] is False
    assert "V1_0_2__broken.sql" in result["error"]
    failed = [e for e in events if e["event"] == "migration.script.failed"]
    assert failed and failed[0]["script"] == "V1_0_2__broken.sql"
    _, status = _run(client, auth, project_id, "info")
    assert dict(_states(status))["1.0.2"] == "FAILED"

    _, repaired = _run(client, auth, project_id, "repair")

    assert repaired["success"] is True
    assert repaired["repaired"] == 1
    _, status = _run(client, auth, project_id, "info")
    assert dict(_states(status))["1.0.2"] == "PENDING"


def test_validate_reports_an_edited_applied_script(
    client, auth, sqlite_project, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)
    _run(client, auth, project_id, "migrate")
    script = sqlite_project.parent / "migrations" / "V1_0_0__create_customers.sql"
    script.write_text(script.read_text() + "-- edited\n")

    _, result = _run(client, auth, project_id, "validate")

    assert result["success"] is False
    assert "V1_0_0__create_customers.sql" in result["error"]


def test_baseline_marks_the_starting_point(client, auth, sqlite_project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    _, result = _run(
        client, auth, project_id, "baseline", {"version": "1.0.0", "description": "existing schema"}
    )

    assert result["success"] is True
    assert result["baseline_version"] == "1.0.0"
    _, status = _run(client, auth, project_id, "info")
    assert "BASELINE" in [m["status"] for m in status["migrations"]]


def test_baseline_without_a_version_is_refused_before_starting(client, auth, sqlite_project):
    project_id = _add(client, auth, sqlite_project)

    response = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "baseline", "params": {}}
    )

    assert response.status_code == 400
    assert "version" in response.json()["detail"]


@pytest.mark.parametrize("version", ["", "  ", "one", "1..2", "1.0.0; DROP", "-1"])
def test_baseline_version_must_be_dotted_numbers(version):
    with pytest.raises(ValueError):
        check_params("baseline", {"version": version})


def test_params_are_ignored_by_commands_that_take_none():
    check_params("migrate", {"version": "x"})
    check_params("info", {})
