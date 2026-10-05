import json

from dblift_ui.jobs import LOG_LIMIT, JobRunner


def _add(client, auth, config):
    return client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(config)}
    ).json()["id"]


def _run(client, auth, project_id, command):
    job_id = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": command}
    ).json()["job_id"]
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        events = [json.loads(l[6:]) for l in response.iter_lines() if l.startswith("data: ")]
    return job_id, events[-1]["result"]


def test_jobs_leave_no_log_in_the_project(
    client, auth, sqlite_project, registry, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    _run(client, auth, project_id, "info")
    _run(client, auth, project_id, "migrate")

    project = sqlite_project.parent
    assert sorted(p.name for p in project.iterdir()) == ["dblift.yaml", "dev.db", "migrations"]
    runs = registry.path.parent / "runs"
    assert not runs.exists() or list(runs.iterdir()) == []


def test_result_names_its_job_and_says_a_log_exists(
    client, auth, sqlite_project, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)

    job_id, result = _run(client, auth, project_id, "migrate")

    assert result["job_id"] == job_id
    assert result["has_log"] is True


def test_full_log_is_served_as_plain_text(client, auth, sqlite_project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    project_id = _add(client, auth, sqlite_project)
    job_id, _ = _run(client, auth, project_id, "migrate")

    response = client.get(f"/api/jobs/{job_id}/log", headers=auth)

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/plain")
    assert "V1_0_0__create_customers.sql" in response.text
    assert "V1_0_1__create_orders.sql" in response.text


def test_log_of_an_unknown_job_is_a_404(client, auth):
    assert client.get("/api/jobs/nope/log", headers=auth).status_code == 404


def test_log_needs_the_token(client, auth, sqlite_project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    job_id, _ = _run(client, auth, _add(client, auth, sqlite_project), "info")

    assert client.get(f"/api/jobs/{job_id}/log").status_code == 401


def test_log_text_is_redacted_and_capped(registry, sqlite_project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    project = registry.add("shop", str(sqlite_project))
    runner = JobRunner(registry)
    filler = "x" * (LOG_LIMIT + 5000)

    def noisy(client, params):
        result = JobRunner.COMMANDS["info"](client, params)
        folder = next((registry.path.parent / "runs").iterdir())
        log_file = next(folder.glob("*.log"))
        with log_file.open("a") as handle:
            handle.write(filler + "\nconnect postgresql://app:s3cret@db.local/shop\n")
        return result

    monkeypatch.setitem(JobRunner.COMMANDS, "validate", noisy)
    job = runner.start(project.id, "validate")
    assert job.done.wait(timeout=10)

    assert len(job.log_text) <= LOG_LIMIT
    assert "s3cret" not in job.log_text
    assert "app:***@db.local" in job.log_text


def test_runs_folder_can_be_chosen(registry, sqlite_project, monkeypatch, tmp_path):
    monkeypatch.chdir(tmp_path)
    project = registry.add("shop", str(sqlite_project))
    seen = []
    elsewhere = tmp_path / "elsewhere"

    def spy(client, params):
        seen.append(sorted(p.name for p in elsewhere.iterdir()))
        return JobRunner.COMMANDS["info"](client, params)

    monkeypatch.setitem(JobRunner.COMMANDS, "validate", spy)
    job = JobRunner(registry, runs_dir=elsewhere).start(project.id, "validate")
    assert job.done.wait(timeout=10)

    assert seen == [[job.id]]
    assert list(elsewhere.iterdir()) == []
