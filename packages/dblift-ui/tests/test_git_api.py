import json
import subprocess
import threading
from pathlib import Path

import pytest
from dblift_ui import gitops
from dblift_ui.server import RepositoryGuard, repository_of
from fastapi import HTTPException

SCRIPT = "migrations/V1_0_0__create_accounts.sql"
NOT_A_REPOSITORY = "This project is not in a git repository."
VERBS = ["switch", "create", "fetch", "pull", "push", "commit"]
CHANGING_VERBS = ["switch", "create", "pull", "commit"]


def _add(client, auth, config, name="shop"):
    response = client.post(
        "/api/projects", headers=auth, json={"name": name, "config_path": str(config)}
    )
    assert response.status_code == 201
    return response.json()["id"]


def _head(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"], check=True, capture_output=True, text=True
    ).stdout


def _local_branches(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "for-each-ref", "--format=%(refname:short)", "refs/heads"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()


def _body(verb):
    """A request that would succeed on the fixture repository, by verb."""
    return {
        "switch": {"name": "origin/feature/remote-only"},
        "create": {"name": "feature/new"},
        "commit": {"paths": [SCRIPT], "message": "Change the script"},
    }.get(verb, {})


@pytest.fixture
def project_id(client, auth, repo):
    return _add(client, auth, repo / "dblift.yaml")


@pytest.fixture
def outside_id(client, auth, sqlite_project):
    return _add(client, auth, sqlite_project)


def test_status_of_a_project_in_a_repository(client, auth, repo, project_id):
    response = client.get(f"/api/projects/{project_id}/git", headers=auth)

    assert response.status_code == 200
    assert response.json() == {
        "repository": True,
        "root": str(repo.resolve()),
        "branch": "main",
        "detached": False,
        "upstream": "origin/main",
        "ahead": 0,
        "behind": 0,
        "files": [],
        "truncated": False,
    }


def test_status_of_a_project_outside_a_repository(client, auth, outside_id):
    response = client.get(f"/api/projects/{outside_id}/git", headers=auth)

    assert response.status_code == 200
    assert response.json() == {"repository": False}


def test_status_lists_changed_files(client, auth, repo, project_id):
    (repo / SCRIPT).write_text("-- changed\n")

    files = client.get(f"/api/projects/{project_id}/git", headers=auth).json()["files"]

    assert files == [{"path": SCRIPT, "state": "modified"}]


def test_status_of_an_unknown_project_is_a_404(client, auth):
    assert client.get("/api/projects/nope/git", headers=auth).status_code == 404


def test_branches(client, auth, project_id):
    response = client.get(f"/api/projects/{project_id}/git/branches", headers=auth)

    assert response.status_code == 200
    assert response.json() == [
        {"name": "main", "current": True, "remote": False, "upstream": "origin/main"},
        {"name": "origin/feature/remote-only", "current": False, "remote": True, "upstream": ""},
        {"name": "origin/main", "current": False, "remote": True, "upstream": ""},
    ]


def test_create_a_branch_answers_the_new_status(client, auth, repo, project_id):
    response = client.post(
        f"/api/projects/{project_id}/git/create", headers=auth, json={"name": "feature/x"}
    )

    assert response.status_code == 200
    assert (response.json()["branch"], response.json()["upstream"]) == ("feature/x", "")
    assert "feature/x" in _local_branches(repo)


def test_switch_back_answers_the_new_status(client, auth, repo, project_id):
    client.post(f"/api/projects/{project_id}/git/create", headers=auth, json={"name": "feature/x"})

    response = client.post(
        f"/api/projects/{project_id}/git/switch", headers=auth, json={"name": "main"}
    )

    assert response.status_code == 200
    assert (response.json()["branch"], response.json()["upstream"]) == ("main", "origin/main")


def test_switch_to_a_remote_branch(client, auth, repo, project_id):
    response = client.post(
        f"/api/projects/{project_id}/git/switch",
        headers=auth,
        json={"name": "origin/feature/remote-only"},
    )

    assert response.status_code == 200
    assert response.json()["branch"] == "feature/remote-only"
    assert (repo / "migrations" / "V1_1_0__add_emails.sql").is_file()


def test_create_an_existing_branch_is_a_400_with_gits_reason(client, auth, project_id):
    response = client.post(
        f"/api/projects/{project_id}/git/create", headers=auth, json={"name": "main"}
    )

    assert response.status_code == 400
    assert "already exists" in response.json()["detail"]


@pytest.mark.parametrize("verb", ["switch", "create"])
@pytest.mark.parametrize("name", ["", "-f", "--orphan=x", "a..b", "@{-1}", "origin/main\n"])
def test_a_bad_branch_name_is_a_400_and_the_branch_is_unchanged(
    client, auth, repo, project_id, verb, name
):
    response = client.post(
        f"/api/projects/{project_id}/git/{verb}", headers=auth, json={"name": name}
    )

    assert response.status_code == 400
    assert client.get(f"/api/projects/{project_id}/git", headers=auth).json()["branch"] == "main"
    assert _local_branches(repo) == ["main"]


def test_commit_one_changed_script(client, auth, repo, project_id):
    (repo / SCRIPT).write_text("-- changed\n")
    (repo / "notes.txt").write_text("x")

    response = client.post(
        f"/api/projects/{project_id}/git/commit",
        headers=auth,
        json={"paths": [SCRIPT], "message": "Change the script"},
    )

    assert response.status_code == 200
    assert response.json()["files"] == [{"path": "notes.txt", "state": "untracked"}]
    assert response.json()["ahead"] == 1


def test_a_refused_commit_is_a_400_with_the_reason(client, auth, repo, project_id):
    head = _head(repo)

    response = client.post(
        f"/api/projects/{project_id}/git/commit",
        headers=auth,
        json={"paths": [SCRIPT], "message": "Nothing changed"},
    )

    assert response.status_code == 400
    assert response.json()["detail"] == f"{SCRIPT} has no change to commit"
    assert _head(repo) == head


def test_a_commit_without_a_message_is_a_400(client, auth, repo, project_id):
    (repo / SCRIPT).write_text("-- changed\n")

    response = client.post(
        f"/api/projects/{project_id}/git/commit",
        headers=auth,
        json={"paths": [SCRIPT], "message": "  "},
    )

    assert response.status_code == 400
    assert client.get(f"/api/projects/{project_id}/git", headers=auth).json()["files"] == [
        {"path": SCRIPT, "state": "modified"}
    ]


def test_fetch(client, auth, project_id, colleague_pushes):
    colleague_pushes()

    response = client.post(f"/api/projects/{project_id}/git/fetch", headers=auth)

    assert response.status_code == 200
    assert response.json()["behind"] == 1


def test_pull(client, auth, repo, project_id, colleague_pushes):
    colleague_pushes("from-a-colleague.txt")

    response = client.post(f"/api/projects/{project_id}/git/pull", headers=auth)

    assert response.status_code == 200
    assert response.json()["behind"] == 0
    assert (repo / "from-a-colleague.txt").is_file()


def test_a_pull_that_cannot_fast_forward_is_a_400(client, auth, repo, project_id, colleague_pushes):
    colleague_pushes()
    (repo / "mine.txt").write_text("x")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "mine")
    head = _head(repo)

    response = client.post(f"/api/projects/{project_id}/git/pull", headers=auth)

    assert response.status_code == 400
    assert "both moved" in response.json()["detail"]
    assert _head(repo) == head


def test_push(client, auth, repo, project_id):
    (repo / "a.txt").write_text("a")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "a")

    response = client.post(f"/api/projects/{project_id}/git/push", headers=auth)

    assert response.status_code == 200
    assert response.json()["ahead"] == 0


def test_push_publishes_a_new_branch(client, auth, project_id):
    client.post(f"/api/projects/{project_id}/git/create", headers=auth, json={"name": "feature/x"})

    response = client.post(f"/api/projects/{project_id}/git/push", headers=auth)

    assert response.status_code == 200
    assert response.json()["upstream"] == "origin/feature/x"


@pytest.mark.parametrize("verb", VERBS)
def test_every_verb_outside_a_repository_is_a_400(client, auth, outside_id, verb):
    response = client.post(f"/api/projects/{outside_id}/git/{verb}", headers=auth, json=_body(verb))

    assert response.status_code == 400
    assert response.json()["detail"] == NOT_A_REPOSITORY


def test_branches_outside_a_repository_is_a_400(client, auth, outside_id):
    response = client.get(f"/api/projects/{outside_id}/git/branches", headers=auth)

    assert response.status_code == 400
    assert response.json()["detail"] == NOT_A_REPOSITORY


@pytest.mark.parametrize("verb", VERBS)
def test_every_verb_on_an_unknown_project_is_a_404(client, auth, verb):
    response = client.post(f"/api/projects/nope/git/{verb}", headers=auth, json=_body(verb))

    assert response.status_code == 404


def test_scripts_carry_their_change_in_git(client, auth, repo, project_id):
    (repo / "migrations" / "V1_1_0__add_emails.sql").write_text("SELECT 1;\n")
    (repo / SCRIPT).write_text("-- changed\n")
    (repo / "migrations" / "V1_2_0__unchanged_later.sql").write_text("SELECT 2;\n")
    repo.git("add", "migrations/V1_2_0__unchanged_later.sql")
    repo.git("commit", "-q", "-m", "later")

    scripts = client.get(f"/api/projects/{project_id}/scripts", headers=auth).json()

    assert {s["name"]: s["change"] for s in scripts} == {
        "V1_0_0__create_accounts.sql": "modified",
        "V1_1_0__add_emails.sql": "untracked",
        "V1_2_0__unchanged_later.sql": "",
    }


def test_scripts_outside_a_repository_have_no_change(client, auth, outside_id):
    scripts = client.get(f"/api/projects/{outside_id}/scripts", headers=auth).json()

    assert scripts and all(s["change"] == "" for s in scripts)
    assert all(s["path"] == "" and s["undo_path"] == "" and s["undo_change"] == "" for s in scripts)


def test_scripts_carry_their_paths_in_the_repository(client, auth, repo, project_id):
    (repo / "migrations" / "U1_0_0__create_accounts.sql").write_text("DROP TABLE accounts;\n")

    (script,) = client.get(f"/api/projects/{project_id}/scripts", headers=auth).json()

    assert script["path"] == SCRIPT
    assert script["undo_path"] == "migrations/U1_0_0__create_accounts.sql"


def test_a_new_undo_script_is_untracked(client, auth, repo, project_id):
    (repo / "migrations" / "U1_0_0__create_accounts.sql").write_text("DROP TABLE accounts;\n")

    (script,) = client.get(f"/api/projects/{project_id}/scripts", headers=auth).json()

    assert script["change"] == ""
    assert script["undo_change"] == "untracked"


def test_a_script_without_an_undo_script_has_no_undo_change(client, auth, repo, project_id):
    (repo / SCRIPT).write_text("-- changed\n")

    (script,) = client.get(f"/api/projects/{project_id}/scripts", headers=auth).json()

    assert (script["change"], script["undo_path"], script["undo_change"]) == ("modified", "", "")


def test_undo_scripts_of_the_same_name_in_two_projects_are_told_apart(client, auth, repo):
    config = "database:\n  type: sqlite\n  path: ./dev.db\nmigrations:\n  directory: ./migrations\n"
    for folder in ("billing", "shop"):
        (repo / folder / "migrations").mkdir(parents=True)
        (repo / folder / "dblift.yaml").write_text(config)
        (repo / folder / "migrations" / "V1_0_0__init.sql").write_text("SELECT 1;\n")
        (repo / folder / "migrations" / "U1_0_0__init.sql").write_text("SELECT 0;\n")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "two projects")
    (repo / "shop" / "migrations" / "U1_0_0__init.sql").write_text("SELECT 2;\n")
    billing = _add(client, auth, repo / "billing" / "dblift.yaml", name="billing")
    shop = _add(client, auth, repo / "shop" / "dblift.yaml", name="shop")

    (billing_script,) = client.get(f"/api/projects/{billing}/scripts", headers=auth).json()
    (shop_script,) = client.get(f"/api/projects/{shop}/scripts", headers=auth).json()

    assert billing_script["undo_path"] == "billing/migrations/U1_0_0__init.sql"
    assert billing_script["undo_change"] == ""
    assert shop_script["undo_path"] == "shop/migrations/U1_0_0__init.sql"
    assert shop_script["undo_change"] == "modified"


def test_the_diff_of_a_script(client, auth, repo, project_id):
    (repo / SCRIPT).write_text("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT);\n")

    response = client.get(
        f"/api/projects/{project_id}/scripts/V1_0_0__create_accounts.sql/diff", headers=auth
    )

    assert response.status_code == 200
    text = response.json()["diff"]
    assert "-CREATE TABLE accounts (id INTEGER PRIMARY KEY);" in text
    assert "+CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT);" in text


def test_the_diff_of_an_unchanged_script_is_empty(client, auth, project_id):
    response = client.get(
        f"/api/projects/{project_id}/scripts/V1_0_0__create_accounts.sql/diff", headers=auth
    )

    assert response.status_code == 200
    assert response.json() == {"diff": ""}


@pytest.mark.parametrize("name", ["V9_9_9__missing.sql", "dblift.yaml", "-x"])
def test_the_diff_of_an_unknown_or_unsafe_name_is_refused_like_a_read(
    client, auth, project_id, name
):
    read = client.get(f"/api/projects/{project_id}/scripts/{name}", headers=auth)

    response = client.get(f"/api/projects/{project_id}/scripts/{name}/diff", headers=auth)

    assert read.status_code in (400, 404)
    assert (response.status_code, response.json()) == (read.status_code, read.json())


@pytest.mark.parametrize(
    "method, path",
    [
        ("GET", "/git"),
        ("GET", "/git/branches"),
        ("GET", "/scripts/V1_0_0__create_accounts.sql/diff"),
        *[("POST", f"/git/{verb}") for verb in VERBS],
    ],
)
def test_every_git_route_needs_the_token(client, project_id, method, path):
    response = client.request(method, f"/api/projects/{project_id}{path}", json={})

    assert response.status_code == 401


def _hold_a_migrate(client, auth, project_id, held_migrate):
    entered, _ = held_migrate
    started = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "migrate"}
    )
    assert started.status_code == 202
    assert entered.wait(timeout=10)
    return started.json()["job_id"]


def _finish(client, auth, held_migrate, job_id):
    held_migrate[1].set()
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        return [json.loads(l[6:]) for l in response.iter_lines() if l.startswith("data: ")][-1]


@pytest.mark.parametrize("verb", CHANGING_VERBS)
def test_a_running_change_refuses_the_verbs_that_rewrite_files(
    client, auth, repo, project_id, held_migrate, monkeypatch, tmp_path, colleague_pushes, verb
):
    monkeypatch.chdir(tmp_path)
    colleague_pushes()
    repo.git("fetch", "-q")
    (repo / SCRIPT).write_text("-- changed\n")
    head = _head(repo)
    job_id = _hold_a_migrate(client, auth, project_id, held_migrate)

    try:
        response = client.post(
            f"/api/projects/{project_id}/git/{verb}", headers=auth, json=_body(verb)
        )

        assert response.status_code == 409
        assert "A change is running" in response.json()["detail"]
        assert _head(repo) == head
        assert _local_branches(repo) == ["main"]
        assert (repo / SCRIPT).read_text() == "-- changed\n"
    finally:
        _finish(client, auth, held_migrate, job_id)


def test_a_running_change_still_lets_the_status_and_fetch_answer(
    client, auth, project_id, held_migrate, monkeypatch, tmp_path, colleague_pushes
):
    monkeypatch.chdir(tmp_path)
    colleague_pushes()
    job_id = _hold_a_migrate(client, auth, project_id, held_migrate)

    try:
        assert client.get(f"/api/projects/{project_id}/git", headers=auth).status_code == 200
        fetched = client.post(f"/api/projects/{project_id}/git/fetch", headers=auth)
        assert fetched.status_code == 200 and fetched.json()["behind"] == 1
    finally:
        _finish(client, auth, held_migrate, job_id)


def test_a_change_on_one_project_refuses_a_switch_through_another_of_the_same_repository(
    client, auth, repo, project_id, held_migrate, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    (repo / "dblift-other.yaml").write_text((repo / "dblift.yaml").read_text())
    other_id = _add(client, auth, repo / "dblift-other.yaml", name="other")
    job_id = _hold_a_migrate(client, auth, project_id, held_migrate)

    try:
        response = client.post(
            f"/api/projects/{other_id}/git/switch",
            headers=auth,
            json={"name": "origin/feature/remote-only"},
        )

        assert response.status_code == 409
        assert client.get(f"/api/projects/{other_id}/git", headers=auth).json()["branch"] == "main"
    finally:
        _finish(client, auth, held_migrate, job_id)


def test_the_change_is_allowed_again_once_the_migrate_has_finished(
    client, auth, project_id, held_migrate, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    job_id = _hold_a_migrate(client, auth, project_id, held_migrate)
    _finish(client, auth, held_migrate, job_id)

    response = client.post(
        f"/api/projects/{project_id}/git/create", headers=auth, json={"name": "feature/x"}
    )

    assert response.status_code == 200


def test_a_second_git_change_on_the_same_repository_waits_for_the_first(
    client, auth, project_id, monkeypatch
):
    entered, release, order = threading.Event(), threading.Event(), []
    real_fetch, real_create = gitops.fetch, gitops.create

    def slow_fetch(root):
        entered.set()
        assert release.wait(timeout=10), "test never released the held fetch"
        order.append("fetch")
        real_fetch(root)

    def create(root, name):
        order.append("create")
        real_create(root, name)

    monkeypatch.setattr(gitops, "fetch", slow_fetch)
    monkeypatch.setattr(gitops, "create", create)
    answers = []
    first = threading.Thread(
        target=lambda: answers.append(
            client.post(f"/api/projects/{project_id}/git/fetch", headers=auth).status_code
        )
    )
    second = threading.Thread(
        target=lambda: answers.append(
            client.post(
                f"/api/projects/{project_id}/git/create", headers=auth, json={"name": "x"}
            ).status_code
        )
    )
    first.start()
    assert entered.wait(timeout=10)
    second.start()
    second.join(0.5)

    assert second.is_alive() and order == []
    release.set()
    first.join(10)
    second.join(10)
    assert order == ["fetch", "create"] and answers == [200, 200]


def _job_result(client, auth, job_id):
    with client.stream("GET", f"/api/jobs/{job_id}/events", headers=auth) as response:
        return [json.loads(l[6:]) for l in response.iter_lines() if l.startswith("data: ")][-1]


@pytest.fixture
def held_git_verb(client, auth, project_id, monkeypatch):
    """Start the git verb named by the caller and keep it inside git until released."""
    held = []

    def hold(verb, body=None):
        entered, release, answers = threading.Event(), threading.Event(), []
        real = getattr(gitops, verb)

        def slow(*args):
            entered.set()
            assert release.wait(timeout=10), "test never released the held git verb"
            return real(*args)

        monkeypatch.setattr(gitops, verb, slow)
        thread = threading.Thread(
            target=lambda: answers.append(
                client.post(
                    f"/api/projects/{project_id}/git/{verb}", headers=auth, json=body or {}
                ).status_code
            )
        )
        thread.start()
        assert entered.wait(timeout=10)
        held.append((release, thread))
        return release, thread, answers

    yield hold
    for release, thread in held:
        release.set()
        thread.join(10)


@pytest.mark.parametrize("command", ["migrate", "preview"])
def test_a_running_git_verb_refuses_a_database_change_or_an_sql_preview(
    client, auth, project_id, held_git_verb, monkeypatch, tmp_path, command
):
    monkeypatch.chdir(tmp_path)
    held_git_verb("switch", {"name": "origin/feature/remote-only"})

    response = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": command}
    )

    assert response.status_code == 409
    assert response.json()["detail"] == (
        "A git operation is running on this repository. Wait for it to finish."
    )


@pytest.mark.parametrize("command", ["info", "validate"])
def test_a_running_git_verb_lets_a_read_only_job_start(
    client, auth, project_id, held_git_verb, monkeypatch, tmp_path, command
):
    monkeypatch.chdir(tmp_path)
    held_git_verb("commit", {"paths": [SCRIPT], "message": "x"})

    response = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": command}
    )

    assert response.status_code == 202
    _job_result(client, auth, response.json()["job_id"])


def test_a_running_git_verb_refuses_a_change_through_another_project_of_the_repository(
    client, auth, repo, project_id, held_git_verb, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    (repo / "dblift-other.yaml").write_text((repo / "dblift.yaml").read_text())
    other_id = _add(client, auth, repo / "dblift-other.yaml", name="other")
    held_git_verb("pull")

    response = client.post(
        f"/api/projects/{other_id}/jobs", headers=auth, json={"command": "migrate"}
    )

    assert response.status_code == 409


def test_once_the_git_verb_has_finished_the_migrate_starts(
    client, auth, project_id, held_git_verb, monkeypatch, tmp_path
):
    monkeypatch.chdir(tmp_path)
    release, thread, answers = held_git_verb("create", {"name": "feature/x"})
    refused = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "migrate"}
    )
    assert refused.status_code == 409

    release.set()
    thread.join(10)
    started = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "migrate"}
    )

    assert answers == [200]
    assert started.status_code == 202
    assert _job_result(client, auth, started.json()["job_id"])["result"]["success"] is True


@pytest.mark.parametrize("verb", ["fetch", "push"])
def test_a_running_fetch_or_push_does_not_refuse_a_migrate(
    client, auth, project_id, held_git_verb, monkeypatch, tmp_path, verb
):
    monkeypatch.chdir(tmp_path)
    held_git_verb(verb)

    started = client.post(
        f"/api/projects/{project_id}/jobs", headers=auth, json={"command": "migrate"}
    )

    assert started.status_code == 202
    _job_result(client, auth, started.json()["job_id"])


def test_a_job_and_a_git_verb_starting_together_never_both_pass(registry, repo):
    project = registry.add("shop", str(repo / "dblift.yaml"))
    changing = set()

    class Runner:
        def is_changing(self, project_id):
            return project_id in changing

    repositories = RepositoryGuard(Runner(), registry)
    deciding, decided = threading.Event(), threading.Event()

    def start():
        deciding.set()
        assert decided.wait(timeout=10)
        changing.add(project.id)
        return "job"

    job = threading.Thread(target=lambda: repositories.start_job(project, "migrate", start))
    job.start()
    assert deciding.wait(timeout=10)
    outcome = []

    def verb():
        try:
            with repositories.git_verb(repository_of(Path(project.config_path)), True):
                outcome.append("ran")
        except HTTPException as exc:
            outcome.append(exc.status_code)

    git = threading.Thread(target=verb)
    git.start()
    git.join(0.3)

    assert outcome == []  # the git verb waits for the job's decision
    decided.set()
    job.join(10)
    git.join(10)
    assert outcome == [409]
