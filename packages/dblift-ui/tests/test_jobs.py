import json
from types import SimpleNamespace

from dblift_ui.jobs import EVENT_FIELDS, serialize_event


def _events(client, auth, job_id):
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]


def _add(client, auth, config):
    return client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(config)}
    ).json()["id"]


def test_info_job_streams_events_then_result(client, auth, sqlite_project, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    started = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "info"}
    )
    assert started.status_code == 202
    events = _events(client, auth, started.json()["job_id"])

    assert events[0]["event"] == "info.started"
    assert events[-1]["event"] == "job.finished"
    result = events[-1]["result"]
    assert result["success"] is True
    assert [(m["version"], m["status"]) for m in result["migrations"]] == [
        ("1.0.0", "PENDING"),
        ("1.0.1", "PENDING"),
    ]


def test_job_never_writes_to_the_working_directory(
    client, auth, sqlite_project, tmp_path, monkeypatch
):
    elsewhere = tmp_path / "elsewhere"
    elsewhere.mkdir()
    monkeypatch.chdir(elsewhere)
    project_id = _add(client, auth, sqlite_project)

    job_id = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "info"}
    ).json()["job_id"]
    _events(client, auth, job_id)

    assert list(elsewhere.iterdir()) == []


def test_environment_is_applied(client, auth, sqlite_project, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    job_id = client.post(
        f"/api/projects/{project_id}/jobs",
        headers=auth,
        json={"command": "info", "environment": "staging"},
    ).json()["job_id"]
    result = _events(client, auth, job_id)[-1]["result"]

    assert result["success"] is True
    assert (sqlite_project.parent / "staging.db").exists()
    assert not (sqlite_project.parent / "dev.db").exists()


def test_broken_config_finishes_with_an_error(client, auth, sqlite_project, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)
    sqlite_project.write_text("database:\n  type: no-such-engine\n")

    job_id = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "info"}
    ).json()["job_id"]
    last = _events(client, auth, job_id)[-1]

    assert last["event"] == "job.finished"
    assert last["result"]["success"] is False
    assert last["result"]["error"]


def test_unknown_command_is_a_400(client, auth, sqlite_project):
    project_id = _add(client, auth, sqlite_project)
    response = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "drop-everything"}
    )
    assert response.status_code == 400


def test_unknown_project_and_job_are_404(client, auth):
    assert (
        client.post("/api/projects/nope/jobs", headers=auth, json={"command": "info"}).status_code
        == 404
    )
    assert client.get("/api/jobs/nope/events", headers=auth).status_code == 404


def test_events_carry_only_whitelisted_fields():
    event = SimpleNamespace(
        event_type=SimpleNamespace(value="migration.script.completed"),
        timestamp=12.5,
        script="V1_0_0__a.sql",
        version="1.0.0",
        execution_time=3,
        error=None,
        config=SimpleNamespace(database=SimpleNamespace(password="hunter2")),
        provider=object(),
        result=object(),
    )

    payload = serialize_event(event)

    assert payload == {
        "event": "migration.script.completed",
        "timestamp": 12.5,
        "script": "V1_0_0__a.sql",
        "version": "1.0.0",
        "execution_time": 3,
    }
    assert set(payload) <= {"event", "timestamp", *EVENT_FIELDS}
    assert "hunter2" not in json.dumps(payload)
