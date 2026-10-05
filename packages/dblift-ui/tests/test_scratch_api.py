import json
import threading

import pytest
from dblift_ui import scratch

from dblift.api import DBLiftClient

NEW = "V1_0_1__create_orders.sql"


def _add(client, auth, config):
    return client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(config)}
    ).json()["id"]


def _start(client, auth, project_id, command="scratch_test", params=None, environment=""):
    return client.post(
        f"/api/projects/{project_id}/jobs",
        headers=auth,
        json={
            "command": command,
            "environment": environment,
            "params": {"script": NEW} if params is None else params,
        },
    )


def _events(client, auth, job_id):
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        return [json.loads(l[6:]) for l in response.iter_lines() if l.startswith("data: ")]


def _within(seconds, read):
    """Run *read* in a thread so a stream that never ends fails instead of hanging."""
    outcome = []
    reader = threading.Thread(target=lambda: outcome.append(read()), daemon=True)
    reader.start()
    reader.join(seconds)
    assert outcome, f"reading the job's events did not finish within {seconds}s"
    return outcome[0]


def _phase_events(events):
    return [(e["phase"], e["status"]) for e in events if e["event"] == "scratch.phase"]


def test_the_scratch_plan_of_a_project(client, auth, sqlite_project):
    project_id = _add(client, auth, sqlite_project)

    response = client.get(f"/api/projects/{project_id}/scratch", headers=auth)

    assert response.status_code == 200
    assert response.json() == {
        "strategy": "file",
        "engine": "sqlite",
        "summary": "A temporary SQLite database is created, used and deleted. "
        "Your databases are not touched.",
        "warning": "",
    }


def test_the_scratch_plan_of_an_unknown_project_is_404(client, auth):
    assert client.get("/api/projects/nope/scratch", headers=auth).status_code == 404


def test_a_scratch_test_streams_its_phases_then_its_result(
    client, auth, sqlite_project, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    started = _start(client, auth, project_id)
    assert started.status_code == 202
    events = _within(30, lambda: _events(client, auth, started.json()["job_id"]))

    assert _phase_events(events) == [
        ("build", "started"),
        ("build", "passed"),
        ("undo", "started"),
        ("undo", "passed"),
        ("reapply", "started"),
        ("reapply", "passed"),
    ]
    phase = next(e for e in events if e["event"] == "scratch.phase")
    assert set(phase) == {"event", "phase", "status", "detail"}
    assert any(e.get("script") == NEW for e in events if e["event"] != "scratch.phase")
    result = events[-1]["result"]
    assert result["success"] is True and result["error"] is None
    assert result["scratch"] == {
        "strategy": "file",
        "passed": True,
        "skipped": False,
        "script": NEW,
        "phases": [
            {"name": "build", "ok": True, "detail": result["scratch"]["phases"][0]["detail"]},
            {"name": "undo", "ok": True, "detail": result["scratch"]["phases"][1]["detail"]},
            {"name": "reapply", "ok": True, "detail": result["scratch"]["phases"][2]["detail"]},
        ],
    }


def test_nothing_is_left_behind_and_the_project_database_is_untouched(
    client, auth, sqlite_project, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)
    runs = tmp_path / "state" / "runs"

    job_id = _start(client, auth, project_id, environment="staging").json()["job_id"]
    result = _within(30, lambda: _events(client, auth, job_id))[-1]["result"]

    assert result["scratch"]["passed"] is True
    assert not runs.exists() or list(runs.iterdir()) == []
    assert not (sqlite_project.parent / "dev.db").exists()
    assert not (sqlite_project.parent / "staging.db").exists()


def test_a_failing_test_is_a_failed_job_naming_the_phase(
    client, auth, sqlite_project, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    (sqlite_project.parent / "migrations" / "U1_0_1__create_orders.sql").write_text(
        "DROP TABLE nope;\n"
    )
    project_id = _add(client, auth, sqlite_project)

    job_id = _start(client, auth, project_id).json()["job_id"]
    events = _within(30, lambda: _events(client, auth, job_id))

    result = events[-1]["result"]
    assert result["success"] is False
    assert result["error"].startswith("undo: ")
    assert "no such table: nope" in result["error"]
    assert result["scratch"]["passed"] is False
    assert _phase_events(events)[-2:] == [("undo", "failed"), ("reapply", "skipped")]
    assert not (tmp_path / "state" / "runs").exists() or not any(
        (tmp_path / "state" / "runs").iterdir()
    )


def test_a_skipped_test_is_a_successful_job_that_says_so(client, auth, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    folder = tmp_path / "pg"
    (folder / "migrations").mkdir(parents=True)
    (folder / "migrations" / NEW).write_text("SELECT 1;\n")
    config = folder / "dblift.yaml"
    config.write_text(
        "database:\n  url: postgresql://app:hunter2@db.invalid:5432/shop\n"
        "migrations:\n  directory: ./migrations\n"
    )
    project_id = _add(client, auth, config)

    events = _within(
        30, lambda: _events(client, auth, _start(client, auth, project_id).json()["job_id"])
    )

    result = events[-1]["result"]
    assert result["success"] is True
    assert result["scratch"]["skipped"] is True and result["scratch"]["passed"] is False
    assert _phase_events(events) == []


def test_a_password_in_a_failure_is_redacted_everywhere(
    client, auth, sqlite_project, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    def broken(self, *args, **kwargs):
        raise RuntimeError("could not reach postgresql://app:hunter2@db.invalid/shop\nmore")

    monkeypatch.setattr(DBLiftClient, "migrate", broken)
    project_id = _add(client, auth, sqlite_project)

    job_id = _start(client, auth, project_id).json()["job_id"]
    events = _within(30, lambda: _events(client, auth, job_id))

    assert "hunter2" not in json.dumps(events)
    result = events[-1]["result"]
    assert result["error"] == "build: could not reach postgresql://app:***@db.invalid/shop"


@pytest.mark.parametrize(
    "params",
    [
        {"script": "U1_0_1__create_orders.sql"},
        {"script": "R__views.sql"},
        {"script": "../x"},
        {"script": ""},
        {},
    ],
)
def test_a_name_that_is_not_a_versioned_migration_is_a_400(
    client, auth, sqlite_project, tmp_path, monkeypatch, params
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    response = _start(client, auth, project_id, params=params)

    assert response.status_code == 400
    assert _start(client, auth, project_id, "info", params={}).status_code == 202


def test_a_running_scratch_test_holds_the_project(
    client, auth, sqlite_project, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)
    entered, release = threading.Event(), threading.Event()
    real = DBLiftClient.undo

    def slow(self, *args, **kwargs):
        entered.set()
        assert release.wait(timeout=10), "test never released the held undo"
        return real(self, *args, **kwargs)

    monkeypatch.setattr(DBLiftClient, "undo", slow)
    project_id = _add(client, auth, sqlite_project)
    first = _start(client, auth, project_id)
    assert first.status_code == 202
    assert entered.wait(timeout=10)

    try:
        for command in ("migrate", "scratch_test"):
            refused = _start(client, auth, project_id, command)
            assert refused.status_code == 409, command
        assert _start(client, auth, project_id, "info", params={}).status_code == 202
    finally:
        release.set()
    assert _within(30, lambda: _events(client, auth, first.json()["job_id"]))[-1]["result"][
        "success"
    ]
    assert _start(client, auth, project_id, "migrate", params={}).status_code == 202


def test_a_crashing_scratch_test_still_cleans_up(
    client, auth, sqlite_project, tmp_path, monkeypatch
):
    monkeypatch.chdir(tmp_path)

    def crash(config_path, script, workdir, log_dir, on_phase, on_event):
        (workdir / "scratch.db").write_bytes(b"half")
        raise RuntimeError("the test crashed")

    monkeypatch.setattr(scratch, "run_test", crash)
    project_id = _add(client, auth, sqlite_project)

    job_id = _start(client, auth, project_id).json()["job_id"]
    result = _within(30, lambda: _events(client, auth, job_id))[-1]["result"]

    assert result["success"] is False and result["error"] == "the test crashed"
    assert result["scratch"] is None
    runs = tmp_path / "state" / "runs"
    assert not runs.exists() or list(runs.iterdir()) == []
    assert _start(client, auth, project_id, "migrate", params={}).status_code == 202


def test_other_jobs_have_no_scratch_result(client, auth, sqlite_project, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    job_id = _start(client, auth, project_id, "info", params={}).json()["job_id"]
    result = _within(30, lambda: _events(client, auth, job_id))[-1]["result"]

    assert result["success"] is True and result["scratch"] is None


def test_a_failed_job_has_no_scratch_result(client, auth, sqlite_project, tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)
    sqlite_project.write_text("database:\n  type: no-such-engine\n")

    job_id = _start(client, auth, project_id, "info", params={}).json()["job_id"]
    result = _within(30, lambda: _events(client, auth, job_id))[-1]["result"]

    assert result["success"] is False and result["scratch"] is None
