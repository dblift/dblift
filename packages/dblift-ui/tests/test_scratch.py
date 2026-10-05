import sqlite3
from pathlib import Path

import pytest
from dblift_ui import scratch

from dblift.api import DBLiftClient

PG_ROOT = "database:\n  url: postgresql://app:hunter2@db.invalid:5432/shop\n"
SQLITE_ROOT = "database:\n  type: sqlite\n  path: ./dev.db\n"
GOOD = {
    "V1_0_0__create_accounts.sql": "CREATE TABLE accounts (id INTEGER PRIMARY KEY);\n",
    "V1_1_0__create_invoices.sql": "CREATE TABLE invoices (id INTEGER PRIMARY KEY);\n",
    "U1_1_0__create_invoices.sql": "DROP TABLE invoices;\n",
}
NEW = "V1_1_0__create_invoices.sql"


def _project(tmp_path, root=SQLITE_ROOT, environments="", scripts=None):
    folder = tmp_path / "shop"
    (folder / "migrations").mkdir(parents=True)
    for name, text in (GOOD if scripts is None else scripts).items():
        (folder / "migrations" / name).write_text(text)
    config = folder / "dblift.yaml"
    body = root + "migrations:\n  directory: ./migrations\n"
    if environments:
        body += "environments:\n" + environments
    config.write_text(body)
    return config


def _scratch_env(url="sqlite:///./scratch.db"):
    return f"  scratch:\n    database:\n      url: {url}\n"


class Recorder:
    def __init__(self):
        self.calls = []
        self.events = []

    def phase(self, phase, status):
        self.calls.append((phase.name, status))

    def event(self, event):
        self.events.append(event)


def _run(config, tmp_path, script=NEW, recorder=None):
    recorder = recorder or Recorder()
    work = tmp_path / "runs" / "job"
    work.mkdir(parents=True, exist_ok=True)
    return scratch.run_test(str(config), script, work, work, recorder.phase, recorder.event)


def _phases(outcome):
    return [(p["name"], p["ok"]) for p in outcome["phases"]]


def _detail(outcome, name):
    return next(p["detail"] for p in outcome["phases"] if p["name"] == name)


@pytest.fixture
def spy(monkeypatch):
    """Record every client built (its keyword arguments) and every clean (its environment)."""
    built, cleaned, environments = [], [], {}
    real_build = DBLiftClient.from_config_file.__func__
    real_clean = DBLiftClient.clean

    def build(cls, *args, **kwargs):
        built.append(kwargs)
        client = real_build(cls, *args, **kwargs)
        environments[id(client)] = kwargs.get("environment")
        return client

    def clean(self, *args, **kwargs):
        cleaned.append(environments.get(id(self), "<unknown client>"))
        return real_clean(self, *args, **kwargs)

    monkeypatch.setattr(DBLiftClient, "from_config_file", classmethod(build))
    monkeypatch.setattr(DBLiftClient, "clean", clean)
    return built, cleaned


# --- plan ---------------------------------------------------------------------------


def test_a_sqlite_project_is_tested_on_a_temporary_file(tmp_path):
    found = scratch.plan(str(_project(tmp_path)))

    assert found == scratch.Plan(
        strategy="file",
        engine="sqlite",
        summary="A temporary SQLite database is created, used and deleted. "
        "Your databases are not touched.",
        warning="",
    )


def test_a_server_engine_with_a_scratch_environment_uses_it(tmp_path):
    found = scratch.plan(str(_project(tmp_path, PG_ROOT, _scratch_env())))

    assert found.strategy == "environment"
    assert found.engine == "postgresql"
    assert found.summary == "The environment named scratch is emptied, then used for the test."
    assert found.warning == "Everything in the scratch environment's database is deleted first."


def test_a_server_engine_without_a_scratch_environment_is_skipped(tmp_path):
    found = scratch.plan(str(_project(tmp_path, PG_ROOT)))

    assert found.strategy == "skip"
    assert found.engine == "postgresql"
    assert found.summary == (
        "No scratch database is available for this engine yet. Add an environment named "
        "scratch to the config, or continue without the test."
    )
    assert found.warning == ""


@pytest.mark.parametrize("name", ["Scratch", "scratch2", "my_scratch"])
def test_only_an_environment_named_exactly_scratch_counts(tmp_path, name):
    environments = f"  {name}:\n    database:\n      url: sqlite:///./scratch.db\n"

    assert scratch.plan(str(_project(tmp_path, PG_ROOT, environments))).strategy == "skip"


def test_a_config_that_is_not_yaml_is_skipped_with_the_reason(tmp_path):
    config = _project(tmp_path)
    config.write_text("database: [unclosed\n")

    found = scratch.plan(str(config))

    assert found.strategy == "skip"
    assert "line" in found.summary and "hunter2" not in found.summary


def test_a_config_the_loader_refuses_is_skipped_with_the_reason(tmp_path):
    config = _project(tmp_path, "database:\n  url: postgresql://app@db.invalid/shop\n")

    found = scratch.plan(str(config))

    assert found.strategy == "skip"
    assert "password" in found.summary.lower()


def test_a_missing_config_is_skipped(tmp_path):
    found = scratch.plan(str(tmp_path / "nowhere" / "dblift.yaml"))

    assert found.strategy == "skip" and found.summary


# --- the file strategy --------------------------------------------------------------


def test_a_good_migration_and_its_undo_pass(tmp_path):
    recorder = Recorder()

    outcome = _run(_project(tmp_path), tmp_path, recorder=recorder)

    assert outcome["strategy"] == "file"
    assert outcome["passed"] is True and outcome["skipped"] is False
    assert outcome["script"] == NEW
    assert _phases(outcome) == [("build", True), ("undo", True), ("reapply", True)]


def test_each_phase_is_announced_then_reported(tmp_path):
    recorder = Recorder()

    _run(_project(tmp_path), tmp_path, recorder=recorder)

    assert recorder.calls == [
        ("build", "started"),
        ("build", "passed"),
        ("undo", "started"),
        ("undo", "passed"),
        ("reapply", "started"),
        ("reapply", "passed"),
    ]


def test_engine_events_reach_the_caller(tmp_path):
    recorder = Recorder()

    _run(_project(tmp_path), tmp_path, recorder=recorder)

    scripts = {getattr(event, "script", None) for event in recorder.events}
    assert {"V1_0_0__create_accounts.sql", NEW} <= scripts


def test_the_projects_database_is_never_created(tmp_path):
    config = _project(tmp_path)

    _run(config, tmp_path)

    assert not (config.parent / "dev.db").exists()


def test_an_existing_project_database_is_left_byte_identical(tmp_path):
    config = _project(tmp_path)
    database = sqlite3.connect(config.parent / "dev.db")
    database.execute("CREATE TABLE precious (id INTEGER PRIMARY KEY)")
    database.commit()
    database.close()
    before = (config.parent / "dev.db").read_bytes()

    assert _run(config, tmp_path)["passed"] is True

    assert (config.parent / "dev.db").read_bytes() == before


def test_the_temporary_database_lives_in_the_work_folder(tmp_path, spy):
    built, _ = spy

    _run(_project(tmp_path), tmp_path)

    urls = [kwargs["database_url"] for kwargs in built if "database_url" in kwargs]
    assert urls == [f"sqlite:///{(tmp_path / 'runs' / 'job' / 'scratch.db').resolve()}"]


def test_a_client_that_ignores_the_temporary_database_is_never_used(tmp_path, monkeypatch):
    real_build = DBLiftClient.from_config_file.__func__

    def ignoring(cls, *args, **kwargs):
        kwargs.pop("database_url", None)
        return real_build(cls, *args, **kwargs)

    monkeypatch.setattr(DBLiftClient, "from_config_file", classmethod(ignoring))
    config = _project(tmp_path)

    outcome = _run(config, tmp_path)

    assert outcome["passed"] is False
    assert _phases(outcome) == [("build", False), ("undo", None), ("reapply", None)]
    assert _detail(outcome, "build") == (
        "The temporary database could not be selected. Nothing was done."
    )
    assert not (config.parent / "dev.db").exists()


def test_a_broken_undo_fails_the_undo_phase_with_the_database_error(tmp_path):
    scripts = {**GOOD, "U1_1_0__create_invoices.sql": "DROP TABLE nope;\n"}

    outcome = _run(_project(tmp_path, scripts=scripts), tmp_path)

    assert outcome["passed"] is False
    assert _phases(outcome) == [("build", True), ("undo", False), ("reapply", None)]
    assert "U1_1_0__create_invoices.sql" in _detail(outcome, "undo")
    assert "no such table: nope" in _detail(outcome, "undo")
    assert _detail(outcome, "reapply") == "Not run."


def test_a_phase_after_a_failure_is_reported_skipped(tmp_path):
    scripts = {**GOOD, "U1_1_0__create_invoices.sql": "DROP TABLE nope;\n"}
    recorder = Recorder()

    _run(_project(tmp_path, scripts=scripts), tmp_path, recorder=recorder)

    assert recorder.calls[-2:] == [("undo", "failed"), ("reapply", "skipped")]
    assert ("reapply", "started") not in recorder.calls


def test_a_broken_migration_fails_the_build_with_the_database_error(tmp_path):
    scripts = {**GOOD, NEW: "CREATE TABLE invoices (;\n"}

    outcome = _run(_project(tmp_path, scripts=scripts), tmp_path)

    assert outcome["passed"] is False
    assert _phases(outcome) == [("build", False), ("undo", None), ("reapply", None)]
    assert NEW in _detail(outcome, "build")
    assert "syntax error" in _detail(outcome, "build")


def test_a_migration_without_undo_skips_undo_and_reapply(tmp_path):
    scripts = {k: v for k, v in GOOD.items() if not k.startswith("U")}

    outcome = _run(_project(tmp_path, scripts=scripts), tmp_path)

    assert outcome["passed"] is True
    assert _phases(outcome) == [("build", True), ("undo", None), ("reapply", None)]
    assert _detail(outcome, "undo") == "This migration has no undo script."


def test_an_undo_with_another_description_still_counts(tmp_path):
    scripts = {k: v for k, v in GOOD.items() if not k.startswith("U")}
    scripts["U1_1_0__drop_invoices.sql"] = "DROP TABLE invoices;\n"

    outcome = _run(_project(tmp_path, scripts=scripts), tmp_path)

    assert _phases(outcome) == [("build", True), ("undo", True), ("reapply", True)]


def test_an_undo_that_reverts_a_later_migration_fails(tmp_path):
    scripts = {
        **GOOD,
        "V1_2_0__create_payments.sql": "CREATE TABLE payments (id INTEGER PRIMARY KEY);\n",
        "U1_2_0__create_payments.sql": "DROP TABLE payments;\n",
    }

    outcome = _run(_project(tmp_path, scripts=scripts), tmp_path)

    assert outcome["passed"] is False
    assert _phases(outcome) == [("build", True), ("undo", False), ("reapply", None)]
    assert "did not target the new migration" in _detail(outcome, "undo")
    assert "U1_2_0__create_payments.sql" in _detail(outcome, "undo")


@pytest.mark.parametrize(
    "name",
    ["U1_1_0__create_invoices.sql", "R__views.sql", "../x", "", "V1__a.sql\n", None],
)
def test_a_name_that_is_not_a_versioned_migration_is_refused_before_anything(tmp_path, spy, name):
    built, _ = spy
    config = _project(tmp_path)

    with pytest.raises(ValueError):
        _run(config, tmp_path, script=name)

    assert built == []


def test_a_migration_the_project_does_not_hold_is_refused(tmp_path):
    with pytest.raises(ValueError, match="V9_0_0__ghost.sql"):
        _run(_project(tmp_path), tmp_path, script="V9_0_0__ghost.sql")


def test_a_skipped_plan_opens_nothing(tmp_path, spy):
    _, cleaned = spy
    recorder = Recorder()

    outcome = _run(_project(tmp_path, PG_ROOT), tmp_path, recorder=recorder)

    assert outcome == {
        "strategy": "skip",
        "passed": False,
        "skipped": True,
        "phases": [],
        "script": NEW,
    }
    assert recorder.calls == [] and recorder.events == [] and cleaned == []
    assert list((tmp_path / "runs" / "job").iterdir()) == []


# --- the environment strategy -------------------------------------------------------


def _fill(path):
    """A database holding a stray table and a DBLift history, as a used scratch one would."""
    database = sqlite3.connect(path)
    database.execute("CREATE TABLE leftover (id INTEGER PRIMARY KEY)")
    database.commit()
    database.close()


def test_the_scratch_environment_is_emptied_then_used(tmp_path):
    config = _project(tmp_path, PG_ROOT, _scratch_env())
    used = DBLiftClient.from_config_file(
        str(config), environment="scratch", relative_to_config=True, log_dir=str(tmp_path / "l")
    )
    with used:
        assert used.migrate().success
    _fill(config.parent / "scratch.db")
    recorder = Recorder()

    outcome = _run(config, tmp_path, recorder=recorder)

    assert outcome["strategy"] == "environment"
    assert outcome["passed"] is True
    assert _phases(outcome) == [
        ("clean", True),
        ("build", True),
        ("undo", True),
        ("reapply", True),
    ]
    assert recorder.calls[:2] == [("clean", "started"), ("clean", "passed")]
    tables = {
        row[0]
        for row in sqlite3.connect(config.parent / "scratch.db").execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    assert "leftover" not in tables and {"accounts", "invoices"} <= tables


def test_only_the_scratch_environment_is_ever_cleaned(tmp_path, spy):
    built, cleaned = spy
    environments = "  staging:\n    database:\n      url: sqlite:///./staging.db\n"
    config = _project(tmp_path, PG_ROOT, environments + _scratch_env())

    assert _run(config, tmp_path)["passed"] is True

    assert cleaned == ["scratch"]
    assert all("database_path" not in kwargs for kwargs in built)
    assert not (config.parent / "staging.db").exists()


def test_the_file_strategy_never_cleans_and_never_passes_a_database_path(tmp_path, spy):
    built, cleaned = spy

    _run(_project(tmp_path), tmp_path)

    assert cleaned == []
    assert built and all("database_path" not in kwargs for kwargs in built)


def test_scratch_on_the_default_database_is_refused_before_connecting(tmp_path, spy):
    _, cleaned = spy
    same = _scratch_env("postgresql://other:pw@DB.invalid:5432/shop")
    recorder = Recorder()

    outcome = _run(_project(tmp_path, PG_ROOT, same), tmp_path, recorder=recorder)

    assert outcome["passed"] is False
    assert _phases(outcome) == [
        ("clean", False),
        ("build", None),
        ("undo", None),
        ("reapply", None),
    ]
    assert _detail(outcome, "clean") == (
        "The scratch environment points at the same database as default. Nothing was done."
    )
    assert cleaned == []
    assert recorder.events == []


def test_scratch_on_the_database_of_another_environment_is_refused(tmp_path, spy):
    _, cleaned = spy
    environments = "  qa:\n    database:\n      url: sqlite:///./shared.db\n" + _scratch_env(
        "sqlite:///./sub/../shared.db"
    )
    config = _project(tmp_path, PG_ROOT, environments)
    (config.parent / "sub").mkdir()
    _fill(config.parent / "shared.db")
    before = (config.parent / "shared.db").read_bytes()

    outcome = _run(config, tmp_path)

    assert outcome["passed"] is False
    assert _detail(outcome, "clean") == (
        "The scratch environment points at the same database as qa. Nothing was done."
    )
    assert (config.parent / "shared.db").read_bytes() == before
    assert cleaned == []


def test_an_environment_that_cannot_be_resolved_refuses_the_test(tmp_path, spy):
    _, cleaned = spy
    environments = "  prod:\n    database:\n      url: postgresql://app@prod.invalid/shop\n"
    config = _project(tmp_path, PG_ROOT, environments + _scratch_env())

    outcome = _run(config, tmp_path)

    assert outcome["passed"] is False
    assert _phases(outcome)[0] == ("clean", False)
    assert "the environment prod could not be checked" in _detail(outcome, "clean")
    assert cleaned == []
    assert not (config.parent / "scratch.db").exists()


def test_same_database_names_the_default_for_a_sqlite_alias(tmp_path):
    config = _project(tmp_path, SQLITE_ROOT, _scratch_env("sqlite:///./dev.db"))

    assert scratch.same_database(str(config)) == "default"


def test_same_database_is_none_for_a_separate_database(tmp_path):
    config = _project(tmp_path, PG_ROOT, _scratch_env())

    assert scratch.same_database(str(config)) is None


@pytest.mark.parametrize(
    "url",
    [
        "postgresql://app:hunter2@db.invalid:5432/shop",
        "postgresql://someone:else@DB.INVALID/shop",
    ],
)
def test_same_database_ignores_credentials_case_and_a_missing_port(tmp_path, url):
    config = _project(tmp_path, PG_ROOT, _scratch_env(url))

    assert scratch.same_database(str(config)) == "default"


def test_same_database_tells_another_database_on_the_same_server_apart(tmp_path):
    config = _project(
        tmp_path, PG_ROOT, _scratch_env("postgresql://app:hunter2@db.invalid:5432/scratch")
    )

    assert scratch.same_database(str(config)) is None


def test_same_database_cannot_be_decided_without_a_scratch_environment(tmp_path):
    with pytest.raises(scratch.NotChecked):
        scratch.same_database(str(_project(tmp_path, PG_ROOT)))


def test_same_database_cannot_be_decided_on_an_unreadable_config(tmp_path):
    config = _project(tmp_path, PG_ROOT, _scratch_env())
    config.write_text("environments: [\n")

    with pytest.raises(scratch.NotChecked):
        scratch.same_database(str(config))


def test_a_password_in_a_failing_detail_is_redacted(tmp_path, monkeypatch):
    def broken(self, *args, **kwargs):
        raise RuntimeError("could not reach postgresql://app:hunter2@db.invalid/shop")

    monkeypatch.setattr(DBLiftClient, "migrate", broken)

    outcome = _run(_project(tmp_path), tmp_path)

    assert _phases(outcome)[0] == ("build", False)
    assert "hunter2" not in _detail(outcome, "build")
    assert "postgresql://app:***@db.invalid/shop" in _detail(outcome, "build")


def test_the_scratch_name_is_scratch():
    assert scratch.SCRATCH == "scratch"


def test_the_work_folder_is_the_only_place_written(tmp_path):
    config = _project(tmp_path)
    before = sorted(p.name for p in config.parent.iterdir())

    _run(config, tmp_path)

    assert sorted(p.name for p in config.parent.iterdir()) == before
    assert Path(tmp_path / "runs" / "job" / "scratch.db").exists()
