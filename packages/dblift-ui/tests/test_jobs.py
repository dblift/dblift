import json
import threading
import time
from types import SimpleNamespace

from dblift_ui.jobs import EVENT_FIELDS, FINISHED, JobRunner, redact, serialize_event

SECRET_URL = "postgresql+psycopg://app:s3cret@db.local:5432/shop"


def _events(client, auth, job_id):
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        assert response.status_code == 200
        assert response.headers["content-type"].startswith("text/event-stream")
        return [json.loads(line[6:]) for line in response.iter_lines() if line.startswith("data: ")]


def _within(seconds, read):
    """Run *read* in a thread so a stream that never ends fails instead of hanging."""
    outcome = []
    reader = threading.Thread(target=lambda: outcome.append(read()), daemon=True)
    reader.start()
    reader.join(seconds)
    assert outcome, f"reading the job's events did not finish within {seconds}s"
    return outcome[0]


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


def test_events_can_be_read_twice(client, auth, sqlite_project, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)
    job_id = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "info"}
    ).json()["job_id"]

    first = _within(10, lambda: _events(client, auth, job_id))
    second = _within(5, lambda: _events(client, auth, job_id))

    assert first[-1]["event"] == "job.finished"
    assert second == first


def test_reading_a_finished_job_returns_its_full_log(
    registry, sqlite_project, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    project = registry.add("shop", str(sqlite_project))
    runner = JobRunner(registry)
    job = runner.start(project.id, "info")
    deadline = time.monotonic() + 10
    while not (job.events and job.events[-1]["event"] == FINISHED):
        assert time.monotonic() < deadline, "job did not finish"
        time.sleep(0.01)

    events = _within(2, lambda: list(runner.stream(job.id)))

    assert [e["event"] for e in events] == [e["event"] for e in job.events]
    assert events[0]["event"] == "info.started"
    assert events[-1]["event"] == FINISHED


def test_redact_masks_the_password_of_a_url():
    masked = redact(f"could not connect to {SECRET_URL}")

    assert "app:***@db.local" in masked
    assert "s3cret" not in masked


def test_redact_masks_password_parameters():
    assert "s3cret" not in redact("postgresql://db.local/shop?password=s3cret&x=1")
    assert "s3cret" not in redact("Server=db;UID=app;PWD=s3cret;")


def test_redact_leaves_text_without_credentials_unchanged():
    text = 'connection to server at "127.0.0.1", port 1 failed: Connection refused'
    assert redact(text) == text


def test_event_errors_are_redacted():
    event = SimpleNamespace(
        event_type=SimpleNamespace(value="info.failed"),
        timestamp=1.0,
        error=f"cannot reach {SECRET_URL}",
    )

    assert "s3cret" not in json.dumps(serialize_event(event))


def test_failed_job_does_not_leak_the_password(client, auth, sqlite_project, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    def unreachable(*args, **kwargs):
        raise ConnectionError(f"cannot connect to {SECRET_URL}")

    monkeypatch.setattr("dblift_ui.jobs.DBLiftClient.from_config_file", unreachable)
    project_id = _add(client, auth, sqlite_project)
    job_id = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "info"}
    ).json()["job_id"]
    events = _within(10, lambda: _events(client, auth, job_id))

    assert events[-1]["result"]["success"] is False
    assert "app:***@db.local" in events[-1]["result"]["error"]
    assert "s3cret" not in json.dumps(events)
