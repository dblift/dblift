"""The container strategy of the scratch test.

Most tests use a fake runtime and a fake engine whose "container" is a SQLite file, so the
whole cycle runs for real without a database server. The tests at the end start real
containers; they run only with DBLIFT_UI_CONTAINER_TESTS set to a runtime name
(docker, podman or container), and download a missing image only with
DBLIFT_UI_CONTAINER_PULL=1.
"""

import dataclasses
import json
import os
import secrets
import sqlite3
import threading
import time

import pytest
from dblift_ui import containers, jobs, scratch
from dblift_ui.registry import ProjectRegistry

from dblift.api import DBLiftClient

PG_ROOT = "database:\n  url: postgresql://app:hunter2@db.invalid:5432/shop\n"
GOOD = {
    "V1_0_0__create_accounts.sql": "CREATE TABLE accounts (id INTEGER PRIMARY KEY);\n",
    "V1_1_0__create_invoices.sql": "CREATE TABLE invoices (id INTEGER PRIMARY KEY);\n",
    "U1_1_0__create_invoices.sql": "DROP TABLE invoices;\n",
}
BROKEN_UNDO = {**GOOD, "U1_1_0__create_invoices.sql": "DROP TABLE nope;\n"}
NEW = "V1_1_0__create_invoices.sql"
IMAGE = "example/postgres:1"
SUMMARY = (
    "A throwaway PostgreSQL database is started in a container (Fake, image example/postgres:1), "
    "used for the test and removed. Your databases are not touched."
)


def _project(tmp_path, root=PG_ROOT, environments="", scripts=None, folder="shop"):
    project = tmp_path / folder
    (project / "migrations").mkdir(parents=True)
    for name, text in (GOOD if scripts is None else scripts).items():
        (project / "migrations" / name).write_text(text)
    config = project / "dblift.yaml"
    body = root + "migrations:\n  directory: ./migrations\n"
    if environments:
        body += "environments:\n" + environments
    config.write_text(body)
    return config


class Recorder:
    def __init__(self):
        self.calls = []
        self.events = []

    def phase(self, phase, status):
        self.calls.append((phase.name, status, phase.detail))

    def event(self, event):
        self.events.append(event)


def _run(config, tmp_path, recorder=None, **options):
    recorder = recorder or Recorder()
    work = tmp_path / "runs" / "job"
    work.mkdir(parents=True, exist_ok=True)
    options.setdefault("container_name", "dblift-ui-test-job")
    return scratch.run_test(str(config), NEW, work, work, recorder.phase, recorder.event, **options)


def _phases(outcome):
    return [(p["name"], p["ok"]) for p in outcome["phases"]]


def _detail(outcome, name):
    return next(p["detail"] for p in outcome["phases"] if p["name"] == name)


@pytest.fixture
def engine(tmp_path, monkeypatch, fake_runtime):
    """A fake PostgreSQL engine whose container is a SQLite file; returns the fake runtime."""
    runtime = fake_runtime()
    database = tmp_path / "container" / "scratch.db"
    database.parent.mkdir()
    spec = containers.EngineSpec(
        engine="PostgreSQL",
        image=IMAGE,
        size_mb=123,
        port=5432,
        memory="",
        architecture="",
        environment=lambda password: {"POSTGRES_PASSWORD": password},
        ready=lambda password: ["ready"],
        prepare=lambda schema, password: ["prepare", schema] if schema else None,
        url=lambda host, port: f"sqlite:///{database}",
        username="postgres",
        driver="sqlite3",
        deadline_seconds=5,
    )
    monkeypatch.delenv(containers.RUNTIME_VARIABLE, raising=False)
    monkeypatch.setattr(containers, "CATALOGUE", {"postgresql": spec})
    monkeypatch.setattr(containers, "detect", lambda: runtime)
    runtime.spec = spec
    runtime.database = database
    return runtime


@pytest.fixture
def spy(monkeypatch):
    """Every client built, by its keyword arguments."""
    built = []
    real_build = DBLiftClient.from_config_file.__func__

    def build(cls, *args, **kwargs):
        built.append(kwargs)
        return real_build(cls, *args, **kwargs)

    monkeypatch.setattr(DBLiftClient, "from_config_file", classmethod(build))
    return built


# --- plan ---------------------------------------------------------------------------


def test_a_server_engine_without_scratch_environment_uses_a_container(tmp_path, engine):
    found = scratch.plan(str(_project(tmp_path)))

    assert found == scratch.Plan(
        strategy="container",
        engine="postgresql",
        summary=SUMMARY,
        warning="",
        runtime="Fake",
        image=IMAGE,
        image_present=True,
        image_size_mb=123,
    )


def test_the_plan_says_when_the_image_is_absent(tmp_path, engine):
    engine.present = False

    found = scratch.plan(str(_project(tmp_path)))

    assert found.strategy == "container" and found.image_present is False
    assert engine.pulled == [] and engine.started == []


def test_other_strategies_carry_no_container_fields(tmp_path, engine):
    sqlite = scratch.plan(str(_project(tmp_path, "database:\n  type: sqlite\n  path: ./a.db\n")))
    environment = scratch.plan(
        str(
            _project(
                tmp_path,
                environments="  scratch:\n    database:\n      url: sqlite:///./s.db\n",
                folder="other",
            )
        )
    )

    for found in (sqlite, environment):
        assert (found.runtime, found.image, found.image_present, found.image_size_mb) == (
            "",
            "",
            None,
            None,
        )
    assert (sqlite.strategy, environment.strategy) == ("file", "environment")


def test_no_runtime_is_a_skip_saying_so(tmp_path, engine, monkeypatch):
    monkeypatch.setattr(containers, "detect", lambda: None)

    found = scratch.plan(str(_project(tmp_path)))

    assert found == scratch.Plan(
        "skip",
        "postgresql",
        "No container runtime was found (Docker, Podman or Apple container).",
        "",
    )


def test_a_missing_driver_is_a_skip_saying_so(tmp_path, engine, monkeypatch):
    spec = containers.CATALOGUE["postgresql"]
    monkeypatch.setitem(
        containers.CATALOGUE,
        "postgresql",
        dataclasses.replace(spec, driver="no_such_driver_for_dblift_ui"),
    )

    found = scratch.plan(str(_project(tmp_path)))

    assert found.strategy == "skip"
    assert found.summary == "The PostgreSQL driver is not installed where this interface runs."


@pytest.mark.parametrize(
    "schema", ["sales; DROP", "'a b'", "'x\"y'", "x" * 100, "${UNSET_SCHEMA_X}"]
)
def test_a_schema_that_is_not_an_identifier_is_a_skip_saying_so(tmp_path, engine, schema):
    config = _project(tmp_path, PG_ROOT + f"  schema: {schema}\n")

    found = scratch.plan(str(config))

    assert found.strategy == "skip"
    assert found.summary == "The schema name cannot be used in a scratch container."


def test_an_engine_without_an_image_is_a_skip_saying_so(tmp_path, engine):
    config = _project(tmp_path, "database:\n  url: db2://app:pw@db.invalid:50000/shop\n")

    found = scratch.plan(str(config))

    assert found.strategy == "skip"
    assert found.summary == "No scratch image is known for db2 yet."


def test_containers_turned_off_keep_the_former_answer(tmp_path, engine, monkeypatch):
    monkeypatch.setenv(containers.RUNTIME_VARIABLE, "none")

    found = scratch.plan(str(_project(tmp_path)))

    assert found.strategy == "skip"
    assert found.summary.startswith("No scratch database is available for this engine yet.")


def test_a_scratch_environment_comes_before_a_container(tmp_path, engine):
    config = _project(
        tmp_path, environments="  scratch:\n    database:\n      url: sqlite:///./s.db\n"
    )

    assert scratch.plan(str(config)).strategy == "environment"


# --- run ----------------------------------------------------------------------------


def test_a_full_pass_reports_start_build_undo_reapply(tmp_path, engine):
    recorder = Recorder()

    outcome = _run(_project(tmp_path), tmp_path, recorder)

    assert outcome["strategy"] == "container"
    assert outcome["passed"] is True
    assert _phases(outcome) == [("start", True), ("build", True), ("undo", True), ("reapply", True)]
    assert recorder.calls[:2] == [
        ("start", "started", f"{IMAGE} via Fake"),
        ("start", "passed", "Ready in 0 s."),
    ]
    assert "cleanup" not in outcome
    tables = {
        row[0]
        for row in sqlite3.connect(engine.database).execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert {"accounts", "invoices"} <= tables


def test_the_container_is_named_started_and_removed_once(tmp_path, engine):
    _run(_project(tmp_path), tmp_path, container_name="dblift-ui-abc-123")

    assert [name for name, _, _ in engine.started] == ["dblift-ui-abc-123"]
    assert engine.removed == ["dblift-ui-abc-123"]
    assert engine.existing == []


def test_the_configs_schema_is_prepared(tmp_path, engine):
    _run(_project(tmp_path, PG_ROOT + "  schema: main\n"), tmp_path)

    assert ["prepare", "main"] in [argv for argv, _, _ in engine.executed]


def test_an_absent_image_without_pull_fails_the_start_and_downloads_nothing(tmp_path, engine):
    engine.present = False
    recorder = Recorder()

    outcome = _run(_project(tmp_path), tmp_path, recorder)

    assert _phases(outcome) == [
        ("start", False),
        ("build", None),
        ("undo", None),
        ("reapply", None),
    ]
    assert _detail(outcome, "start") == f"The image {IMAGE} is not on this machine."
    assert engine.pulled == [] and engine.started == [] and recorder.events == []


def test_an_absent_image_with_pull_is_downloaded_once_then_used(tmp_path, engine):
    engine.present = False
    recorder = Recorder()

    outcome = _run(_project(tmp_path), tmp_path, recorder, pull=True)

    assert engine.pulled == [IMAGE]
    assert recorder.calls[0] == ("start", "started", f"Downloading {IMAGE}…")
    assert outcome["passed"] is True


def test_pull_is_not_used_when_the_image_is_present(tmp_path, engine):
    _run(_project(tmp_path), tmp_path, pull=True)

    assert engine.pulled == []


def test_a_failing_build_still_removes_the_container(tmp_path, engine):
    scripts = {**GOOD, NEW: "CREATE TABLE invoices (;\n"}

    outcome = _run(_project(tmp_path, scripts=scripts), tmp_path)

    assert _phases(outcome) == [
        ("start", True),
        ("build", False),
        ("undo", None),
        ("reapply", None),
    ]
    assert "syntax error" in _detail(outcome, "build")
    assert engine.removed == ["dblift-ui-test-job"]


def test_a_broken_undo_fails_the_undo_phase(tmp_path, engine):
    outcome = _run(_project(tmp_path, scripts=BROKEN_UNDO), tmp_path)

    assert _phases(outcome) == [
        ("start", True),
        ("build", True),
        ("undo", False),
        ("reapply", None),
    ]
    assert "no such table: nope" in _detail(outcome, "undo")
    assert engine.removed == ["dblift-ui-test-job"]


def test_a_crash_inside_a_phase_still_removes_the_container(tmp_path, engine, monkeypatch):
    def crash(self, *args, **kwargs):
        raise KeyboardInterrupt

    monkeypatch.setattr(DBLiftClient, "undo", crash)

    with pytest.raises(KeyboardInterrupt):
        _run(_project(tmp_path), tmp_path)

    assert engine.removed == ["dblift-ui-test-job"]


def test_a_start_that_fails_reports_why_and_runs_nothing(tmp_path, engine, spy):
    engine.replies["prepare"] = (1, "ERROR: permission denied")

    outcome = _run(_project(tmp_path, PG_ROOT + "  schema: main\n"), tmp_path)

    assert _phases(outcome)[0] == ("start", False)
    assert "permission denied" in _detail(outcome, "start")
    assert spy == [] and engine.removed == ["dblift-ui-test-job"]


def test_a_container_left_behind_is_reported_in_cleanup(tmp_path, engine):
    engine.keeps_containers = True

    outcome = _run(_project(tmp_path), tmp_path, container_name="dblift-ui-abc-9")

    assert outcome["passed"] is True
    assert outcome["cleanup"] == (
        "The container dblift-ui-abc-9 could not be removed. Remove it with Fake."
    )


def test_a_removal_that_cannot_be_checked_is_reported_in_cleanup(tmp_path, engine):
    def broken(prefix):
        raise containers.ContainerError("the runtime stopped answering")

    engine.names = broken

    outcome = _run(_project(tmp_path), tmp_path, container_name="dblift-ui-abc-9")

    assert outcome["cleanup"] == (
        "Whether the container dblift-ui-abc-9 was removed could not be checked: "
        "the runtime stopped answering"
    )


def test_every_client_is_built_on_the_container(tmp_path, engine, spy):
    config = _project(tmp_path, environments="  prod:\n    database:\n      url: sqlite:///p.db\n")

    assert _run(config, tmp_path)["passed"] is True

    assert spy
    for kwargs in spy:
        assert kwargs["database_url"] == f"sqlite:///{engine.database}"
        assert kwargs["database_username"] == "postgres"
        assert kwargs["database_password"] == engine.started[0][2]["POSTGRES_PASSWORD"]
        assert "environment" not in kwargs
    assert not (config.parent / "p.db").exists()


def test_a_client_that_ignores_the_container_is_never_used(tmp_path, engine, monkeypatch):
    real_build = DBLiftClient.from_config_file.__func__
    ran = []

    def ignoring(cls, *args, **kwargs):
        kwargs.pop("database_url", None)
        return real_build(cls, *args, **kwargs)

    monkeypatch.setattr(DBLiftClient, "from_config_file", classmethod(ignoring))
    monkeypatch.setattr(DBLiftClient, "migrate", lambda self, *a, **k: ran.append(self))

    outcome = _run(_project(tmp_path), tmp_path)

    assert _phases(outcome)[:2] == [("start", True), ("build", False)]
    assert _detail(outcome, "build") == (
        "The scratch database could not be selected. Nothing was done."
    )
    assert ran == [] and engine.removed == ["dblift-ui-test-job"]


# --- the job ------------------------------------------------------------------------


def _job(runner, project_id, params):
    job = runner.start(project_id, "scratch_test", "", params)
    assert job.done.wait(30)
    return job


@pytest.fixture
def runner(tmp_path):
    registry = ProjectRegistry(tmp_path / "state" / "projects.json")
    return jobs.JobRunner(registry), registry


def test_the_job_names_its_container_after_the_launch_and_the_job(tmp_path, engine, runner):
    job_runner, registry = runner
    project = registry.add("shop", str(_project(tmp_path)))

    job = _job(job_runner, project.id, {"script": NEW})

    assert job_runner.prefix.startswith("dblift-ui-") and job_runner.prefix.endswith("-")
    assert engine.started[0][0] == f"{job_runner.prefix}{job.id}"
    assert jobs.JobRunner(registry).prefix != job_runner.prefix
    assert job.events[-1]["result"]["scratch"]["passed"] is True


@pytest.mark.parametrize("pull", ["yes", 1, None, "true"])
def test_pull_must_be_true_or_false(tmp_path, engine, runner, pull):
    job_runner, registry = runner
    project = registry.add("shop", str(_project(tmp_path)))

    with pytest.raises(ValueError, match="pull"):
        job_runner.start(project.id, "scratch_test", "", {"script": NEW, "pull": pull})


def test_the_job_passes_pull_through(tmp_path, engine, runner):
    job_runner, registry = runner
    engine.present = False
    project = registry.add("shop", str(_project(tmp_path)))

    refused = _job(job_runner, project.id, {"script": NEW, "pull": False})
    pulled = _job(job_runner, project.id, {"script": NEW, "pull": True})

    assert (
        refused.events[-1]["result"]["error"] == f"start: The image {IMAGE} is not on this machine."
    )
    assert pulled.events[-1]["result"]["success"] is True
    assert engine.pulled == [IMAGE]


def test_the_password_never_appears_in_events_results_or_the_log(tmp_path, engine, runner):
    job_runner, registry = runner
    project = registry.add("shop", str(_project(tmp_path, PG_ROOT + "  schema: main\n")))
    job = _job(job_runner, project.id, {"script": NEW})
    password = engine.started[0][2]["POSTGRES_PASSWORD"]
    assert job.events[-1]["result"]["success"] is True

    # A start that fails while echoing the password.
    def leaking(name, argv, timeout, stdin=""):
        secret = engine.started[-1][2]["POSTGRES_PASSWORD"]
        if argv[0] == "prepare":
            return 1, f"FATAL: password {secret} rejected for postgresql://postgres:{secret}@h/x"
        return 0, ""

    engine.execute = leaking
    failed = _job(job_runner, project.id, {"script": NEW})
    second = engine.started[-1][2]["POSTGRES_PASSWORD"]

    assert failed.events[-1]["result"]["error"].startswith("start: ")
    assert "rejected" in failed.events[-1]["result"]["error"]
    text = json.dumps(job.events + failed.events) + job.log_text + failed.log_text
    assert job.log_text
    assert password not in text and second not in text


def test_shutdown_removes_this_launchs_containers_only(tmp_path, engine, runner):
    job_runner, registry = runner
    project = registry.add("shop", str(_project(tmp_path)))
    left = f"{job_runner.prefix}left-behind"
    foreign = ["dblift-ui-0000aaaa-other-launch", "pr320_pg16", f"x{job_runner.prefix}y"]
    engine.existing.extend([left, *foreign])
    _job(job_runner, project.id, {"script": NEW})

    job_runner.drain()

    assert left in engine.removed
    assert not set(foreign) & set(engine.removed)
    assert engine.existing == foreign


def test_shutdown_without_a_scratch_test_asks_no_runtime(tmp_path, runner, monkeypatch):
    job_runner, _ = runner
    asked = []
    monkeypatch.setattr(containers, "detect", lambda: asked.append(1))

    job_runner.drain()

    assert asked == []


def test_shutdown_waits_for_a_running_test_then_its_container_is_gone(
    tmp_path, engine, runner, monkeypatch
):
    job_runner, registry = runner
    project = registry.add("shop", str(_project(tmp_path)))
    entered, release = threading.Event(), threading.Event()
    real = DBLiftClient.undo

    def slow(self, *args, **kwargs):
        entered.set()
        assert release.wait(10)
        return real(self, *args, **kwargs)

    monkeypatch.setattr(DBLiftClient, "undo", slow)
    job_runner.start(project.id, "scratch_test", "", {"script": NEW})
    assert entered.wait(10)
    threading.Timer(0.2, release.set).start()

    job_runner.drain()

    assert engine.existing == []


def test_the_plan_route_returns_the_container_fields(tmp_path, engine, client, auth):
    config = _project(tmp_path)
    project_id = client.post(
        "/api/projects", headers=auth, json={"name": "shop", "config_path": str(config)}
    ).json()["id"]

    response = client.get(f"/api/projects/{project_id}/scratch", headers=auth)

    assert response.json() == {
        "strategy": "container",
        "engine": "postgresql",
        "summary": SUMMARY,
        "warning": "",
        "runtime": "Fake",
        "image": IMAGE,
        "image_present": True,
        "image_size_mb": 123,
    }


# --- real containers (opt-in) -------------------------------------------------------

REAL = os.environ.get("DBLIFT_UI_CONTAINER_TESTS", "")
PULL = os.environ.get("DBLIFT_UI_CONTAINER_PULL", "") == "1"
REAL_ENGINES = {
    "postgresql": "url: postgresql://app:hunter2@db.invalid:5432/shop",
    "mysql": "url: mysql://app:hunter2@db.invalid:3306/shop",
    "mariadb": "url: mariadb://app:hunter2@db.invalid:3306/shop",
    "sqlserver": "url: mssql://app:hunter2@db.invalid:1433/shop",
    "oracle": "url: oracle://app:hunter2@db.invalid:1521/?service_name=PROD",
}
# The database's own words for a missing table.
MISSING_TABLE = {
    "postgresql": 'table "nope" does not exist',
    "mysql": "Unknown table",
    "mariadb": "Unknown table",
    "sqlserver": "Cannot drop the table 'nope'",
    "oracle": "ORA-00942",
}


@pytest.fixture
def passwords(monkeypatch):
    """Every password the real runs make."""
    made = []
    real = containers.new_password

    def recorded():
        made.append(real())
        return made[-1]

    monkeypatch.setattr(containers, "new_password", recorded)
    return made


@pytest.fixture
def real_runtime(monkeypatch):
    if not REAL:
        pytest.skip("set DBLIFT_UI_CONTAINER_TESTS to a runtime name to start real containers")
    monkeypatch.setenv(containers.RUNTIME_VARIABLE, REAL)
    runtime = containers.detect()
    assert runtime is not None, f"the runtime {REAL} does not answer"
    return runtime


def test_every_catalogue_engine_has_a_real_run():
    assert {key for key in REAL_ENGINES} == {
        key for key, spec in containers.CATALOGUE.items() if key == _key(spec)
    }


def _key(spec):
    return next(key for key, known in containers.CATALOGUE.items() if known is spec)


@pytest.mark.parametrize("key", sorted(REAL_ENGINES))
def test_a_real_container_runs_the_whole_cycle(tmp_path, real_runtime, passwords, key, capsys):
    spec = containers.CATALOGUE[key]
    pytest.importorskip(spec.driver)
    if not PULL and not real_runtime.has_image(spec.image):
        pytest.skip(f"{spec.image} is not on this machine")
    prefix = f"dblift-ui-{secrets.token_hex(4)}-"
    root = f"database:\n  {REAL_ENGINES[key]}\n  schema: sales\n"
    assert scratch.plan(str(_project(tmp_path, root, folder="plan"))).strategy == "container"

    timings = []
    outcomes = []
    texts = []
    for folder, scripts in (("good", GOOD), ("broken", BROKEN_UNDO)):
        config = _project(tmp_path, root, scripts=scripts, folder=folder)
        work = tmp_path / "runs" / folder
        work.mkdir(parents=True)
        recorder = Recorder()
        began = time.monotonic()
        outcomes.append(
            scratch.run_test(
                str(config),
                NEW,
                work,
                work,
                recorder.phase,
                recorder.event,
                pull=PULL,
                container_name=f"{prefix}{folder}",
            )
        )
        timings.append(time.monotonic() - began)
        # Everything a viewer of the job could see, and the engine's raw log files.
        texts.append(json.dumps(outcomes[-1]))
        texts.append(json.dumps([jobs.serialize_event(event) for event in recorder.events]))
        texts.append(json.dumps(recorder.calls))
        texts += [path.read_text(errors="replace") for path in work.glob("*.log")]

    assert len(passwords) == 2 and all(texts)
    assert not [password for password in passwords if password in "".join(texts)]
    good, broken = outcomes
    assert good["passed"] is True, good
    assert _phases(good) == [("start", True), ("build", True), ("undo", True), ("reapply", True)]
    assert _phases(broken) == [("start", True), ("build", True), ("undo", False), ("reapply", None)]
    assert MISSING_TABLE[key] in _detail(broken, "undo")
    assert "cleanup" not in good and "cleanup" not in broken
    assert real_runtime.names(prefix) == []
    with capsys.disabled():
        print(
            f"\n{key}: {_detail(good, 'start')} cycle {timings[0]:.1f} s, "
            f"broken undo {timings[1]:.1f} s"
        )


def test_a_container_name_already_taken_is_neither_used_nor_reported(tmp_path, engine):
    engine.existing.append("dblift-ui-test-job")

    outcome = _run(_project(tmp_path), tmp_path)

    assert _phases(outcome)[0] == ("start", False)
    assert "already exists" in _detail(outcome, "start")
    assert "cleanup" not in outcome
    assert engine.started == [] and engine.removed == []
