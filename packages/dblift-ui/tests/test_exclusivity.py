import json
import threading

import pytest
from dblift_ui.jobs import JobRunner


def _add(client, auth, config):
    return client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(config)}
    ).json()["id"]


def _start(client, auth, project_id, command):
    return client.post(f"/api/projects/{project_id}/jobs", headers=auth, json={"command": command})


def _finish(client, auth, job_id):
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        return [json.loads(l[6:]) for l in response.iter_lines() if l.startswith("data: ")][-1]


@pytest.fixture
def held_migrate(monkeypatch):
    """Make `migrate` block until released, so a job can be caught mid-run."""
    entered, release = threading.Event(), threading.Event()
    real = JobRunner.COMMANDS["migrate"]

    def slow(client, params):
        entered.set()
        assert release.wait(timeout=10), "test never released the held migrate"
        return real(client, params)

    monkeypatch.setitem(JobRunner.COMMANDS, "migrate", slow)
    yield entered, release
    release.set()


def test_second_change_on_the_same_project_is_refused(
    client, auth, sqlite_project, held_migrate, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    entered, release = held_migrate
    project_id = _add(client, auth, sqlite_project)

    first = _start(client, auth, project_id, "migrate")
    assert first.status_code == 202
    assert entered.wait(timeout=10)

    for command in ("migrate", "undo", "repair"):
        refused = _start(client, auth, project_id, command)
        assert refused.status_code == 409
        assert "Another change is running" in refused.json()["detail"]

    release.set()
    assert _finish(client, auth, first.json()["job_id"])["result"]["success"] is True
    assert _start(client, auth, project_id, "undo").status_code == 202


def test_reading_is_allowed_while_a_change_runs(
    client, auth, sqlite_project, held_migrate, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    entered, release = held_migrate
    project_id = _add(client, auth, sqlite_project)
    first = _start(client, auth, project_id, "migrate")
    assert entered.wait(timeout=10)

    assert _start(client, auth, project_id, "validate").status_code == 202

    release.set()
    _finish(client, auth, first.json()["job_id"])


def test_a_refused_job_does_not_block_the_project_afterwards(
    client, auth, sqlite_project, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    refused = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "baseline", "params": {}}
    )
    assert refused.status_code == 400

    assert _start(client, auth, project_id, "migrate").status_code == 202


def test_a_crashing_change_frees_the_project(client, auth, sqlite_project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)

    def boom(client, params):
        raise RuntimeError("driver exploded")

    monkeypatch.setitem(JobRunner.COMMANDS, "migrate", boom)
    project_id = _add(client, auth, sqlite_project)

    first = _start(client, auth, project_id, "migrate")
    assert _finish(client, auth, first.json()["job_id"])["result"]["success"] is False

    assert _start(client, auth, project_id, "repair").status_code == 202


# The job's thread re-raises the SystemExit after its final event, by design.
@pytest.mark.filterwarnings("ignore::pytest.PytestUnhandledThreadExceptionWarning")
def test_a_change_that_exits_still_ends_with_its_final_event(
    client, auth, sqlite_project, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)

    def bail(client, params):
        raise SystemExit("driver bailed out")

    monkeypatch.setitem(JobRunner.COMMANDS, "migrate", bail)
    project_id = _add(client, auth, sqlite_project)
    job_id = _start(client, auth, project_id, "migrate").json()["job_id"]

    # Read in a thread so a job that never ends fails the test instead of hanging it.
    outcome = []
    reader = threading.Thread(
        target=lambda: outcome.append(_finish(client, auth, job_id)), daemon=True
    )
    reader.start()
    reader.join(5)
    assert outcome, "the job's events never ended"

    last = outcome[0]
    assert last["event"] == "job.finished"
    assert last["result"]["success"] is False
    assert "driver bailed out" in last["result"]["error"]
    assert _start(client, auth, project_id, "repair").status_code == 202


def test_shutdown_waits_for_a_running_change(
    make_client, auth, sqlite_project, held_migrate, monkeypatch, tmp_path, port
):
    monkeypatch.chdir(tmp_path)
    entered, release = held_migrate
    client = make_client(f"http://127.0.0.1:{port}")
    runner = None

    with client:  # entering and leaving runs the application's startup and shutdown
        project_id = _add(client, auth, sqlite_project)
        job_id = _start(client, auth, project_id, "migrate").json()["job_id"]
        assert entered.wait(timeout=10)
        runner = client.app.state.runner
        threading.Timer(0.3, release.set).start()

    job = runner.get(job_id)
    assert job.done.is_set()
    assert job.events[-1]["result"]["success"] is True


def test_unfinished_jobs_survive_the_job_cap(
    registry, sqlite_project, held_migrate, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    entered, release = held_migrate
    project = registry.add("shop", str(sqlite_project))
    runner = JobRunner(registry)

    held = runner.start(project.id, "migrate")
    assert entered.wait(timeout=10)
    for _ in range(60):
        runner.start(project.id, "info").done.wait(timeout=10)

    assert runner.get(held.id) is held
    release.set()
    assert held.done.wait(timeout=10)
