import subprocess

import pytest
from dblift_ui import gitops
from dblift_ui.gitops import (
    GitError,
    branches,
    check_branch,
    commit,
    create,
    fetch,
    pull,
    push,
    status,
    switch,
)


def _log(repo, *args):
    return subprocess.run(
        ["git", "-C", str(repo), "log", *args], check=True, capture_output=True, text=True
    ).stdout


def test_switch_to_a_local_branch(repo):
    repo.git("branch", "feature/x")

    switch(repo, "feature/x")

    assert status(repo).branch == "feature/x"


def test_switch_to_a_remote_branch_creates_the_tracking_branch(repo):
    switch(repo, "origin/feature/remote-only")

    found = status(repo)
    assert (found.branch, found.upstream) == ("feature/remote-only", "origin/feature/remote-only")
    assert (repo / "migrations" / "V1_1_0__add_emails.sql").is_file()


def test_switch_carries_uncommitted_changes_or_says_why_not(repo):
    (repo / "untracked.txt").write_text("x")
    repo.git("branch", "feature/x")
    switch(repo, "feature/x")
    assert (repo / "untracked.txt").is_file()

    switch(repo, "main")
    (repo / "migrations" / "V1_1_0__add_emails.sql").write_text("-- would be overwritten\n")
    with pytest.raises(GitError):
        switch(repo, "origin/feature/remote-only")
    assert status(repo).branch == "main"
    assert (
        repo / "migrations" / "V1_1_0__add_emails.sql"
    ).read_text() == "-- would be overwritten\n"


def test_create_a_branch_and_land_on_it(repo):
    create(repo, "feature/add-invoices")

    assert status(repo).branch == "feature/add-invoices"
    with pytest.raises(GitError):
        create(repo, "feature/add-invoices")


@pytest.mark.parametrize(
    "name",
    [
        "",
        "-b",
        "--orphan",
        "-",
        "a b",
        "a..b",
        "a~1",
        "a^",
        "a:b",
        "x.lock",
        "/a",
        "a/",
        "@{-1}",
        "HEAD~1",
        "a\nb",
        "a\x00b",
    ],
)
def test_names_that_are_not_branch_names_are_refused(repo, name):
    for verb in (check_branch, switch, create):
        with pytest.raises(GitError):
            verb(repo, name)
    assert status(repo).branch == "main"
    assert [b.name for b in branches(repo) if not b.remote] == ["main"]


def test_commit_only_the_selected_files(repo):
    (repo / "migrations" / "V1_2_0__new.sql").write_text("SELECT 1;\n")
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("-- changed\n")
    (repo / "unrelated.txt").write_text("x")
    (repo / "staged-by-hand.txt").write_text("x")
    repo.git("add", "staged-by-hand.txt")

    commit(
        repo,
        ["migrations/V1_2_0__new.sql", "migrations/V1_0_0__create_accounts.sql"],
        "Add the new migration\n\nWith a body.",
    )

    assert _log(repo, "-1", "--format=%B").startswith("Add the new migration\n\nWith a body.")
    assert _log(repo, "-1", "--name-only", "--format=").split() == [
        "migrations/V1_0_0__create_accounts.sql",
        "migrations/V1_2_0__new.sql",
    ]
    assert [(f.path, f.state) for f in status(repo).files] == [
        ("staged-by-hand.txt", "added"),
        ("unrelated.txt", "untracked"),
    ]


def test_commit_a_deletion(repo):
    (repo / "dblift.yaml").unlink()

    commit(repo, ["dblift.yaml"], "Remove the config")

    assert status(repo).files == []


def test_a_message_that_looks_like_an_option_is_only_a_message(repo):
    (repo / "a.txt").write_text("a")

    commit(repo, ["a.txt"], "--amend")

    assert _log(repo, "-1", "--format=%s").strip() == "--amend"
    assert len(_log(repo, "--format=%H").split()) == 2


@pytest.mark.parametrize(
    "paths, message",
    [
        ([], "x"),
        (["a.txt"], ""),
        (["a.txt"], "   \n"),
        (["-a"], "x"),
        (["../x"], "x"),
        (["not-changed.txt"], "x"),
        (["migrations"], "x"),
    ],
)
def test_commit_refusals(repo, paths, message):
    (repo / "a.txt").write_text("a")
    before = _log(repo, "--format=%H")

    with pytest.raises(GitError):
        commit(repo, paths, message)

    assert _log(repo, "--format=%H") == before


def test_fetch_then_pull_fast_forwards(repo, tmp_path):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    (other / "from-a-colleague.txt").write_text("x")
    for args in (
        ["add", "."],
        ["-c", "user.email=c@e.x", "-c", "user.name=Col", "commit", "-q", "-m", "colleague"],
        ["push", "-q"],
    ):
        subprocess.run(["git", "-C", str(other), *args], check=True)

    fetch(repo)
    assert status(repo).behind == 1
    pull(repo)

    assert status(repo).behind == 0 and (repo / "from-a-colleague.txt").is_file()


def test_pull_stops_when_both_sides_moved_and_changes_nothing(repo, tmp_path):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    (other / "theirs.txt").write_text("x")
    for args in (
        ["add", "."],
        ["-c", "user.email=c@e.x", "-c", "user.name=Col", "commit", "-q", "-m", "theirs"],
        ["push", "-q"],
    ):
        subprocess.run(["git", "-C", str(other), *args], check=True)
    (repo / "mine.txt").write_text("x")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "mine")
    head = _log(repo, "-1", "--format=%H")

    with pytest.raises(GitError, match="both moved"):
        pull(repo)

    assert _log(repo, "-1", "--format=%H") == head
    assert not (repo / ".git" / "MERGE_HEAD").exists()


def test_pull_without_an_upstream_is_explained(repo):
    repo.git("switch", "-q", "-c", "local-only")

    with pytest.raises(GitError, match="no remote branch"):
        pull(repo)


def test_push_and_first_push_of_a_new_branch(repo):
    (repo / "a.txt").write_text("a")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "a")
    push(repo)
    assert status(repo).ahead == 0

    create(repo, "feature/new")
    (repo / "b.txt").write_text("b")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "b")
    push(repo)

    found = status(repo)
    assert (found.upstream, found.ahead) == ("origin/feature/new", 0)


def test_push_is_never_forced(repo, tmp_path):
    other = tmp_path / "other"
    subprocess.run(["git", "clone", "-q", str(tmp_path / "origin.git"), str(other)], check=True)
    (other / "theirs.txt").write_text("x")
    for args in (
        ["add", "."],
        ["-c", "user.email=c@e.x", "-c", "user.name=Col", "commit", "-q", "-m", "theirs"],
        ["push", "-q"],
    ):
        subprocess.run(["git", "-C", str(other), *args], check=True)
    (repo / "mine.txt").write_text("x")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "mine")

    with pytest.raises(GitError):
        push(repo)


def test_push_without_origin_and_detached(repo):
    repo.git("switch", "-q", "--detach", "HEAD")
    with pytest.raises(GitError):
        push(repo)
    repo.git("switch", "-q", "main")
    repo.git("remote", "remove", "origin")
    with pytest.raises(GitError, match="no remote named origin"):
        push(repo)


def _remote_head(tmp_path):
    return subprocess.run(
        ["git", "-C", str(tmp_path / "origin.git"), "rev-parse", "main"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout


@pytest.mark.parametrize("name", ["@", "refs/heads/x", "origin/new", "origin/main"])
def test_names_that_would_be_read_as_another_reference_are_refused(repo, name):
    with pytest.raises(GitError):
        create(repo, name)

    assert status(repo).branch == "main"
    assert [b.name for b in branches(repo) if not b.remote] == ["main"]


def test_a_file_name_is_never_read_as_a_pattern(repo):
    (repo / "x*").write_text("star")
    (repo / "xa").write_text("a")

    commit(repo, ["x*"], "Only the star")

    assert _log(repo, "-1", "--name-only", "--format=").split() == ["x*"]
    assert [(f.path, f.state) for f in status(repo).files] == [("xa", "untracked")]
    for pattern in (":(glob)**", ":(top)xa", "x?"):
        with pytest.raises(GitError):
            commit(repo, [pattern], "x")


def test_push_is_never_forced_even_by_the_repositorys_config(repo, tmp_path, colleague_pushes):
    colleague_pushes()
    before = _remote_head(tmp_path)
    repo.git("config", "remote.origin.push", "+refs/heads/main:refs/heads/main")
    (repo / "mine.txt").write_text("x")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "mine")

    with pytest.raises(GitError):
        push(repo)

    assert _remote_head(tmp_path) == before


def test_pull_never_rebases_even_by_the_repositorys_config(repo, colleague_pushes):
    colleague_pushes()
    repo.git("config", "pull.rebase", "true")
    (repo / "mine.txt").write_text("x")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "mine")
    head = _log(repo, "-1", "--format=%H")

    with pytest.raises(GitError, match="both moved"):
        pull(repo)

    assert _log(repo, "-1", "--format=%H") == head
    assert not (repo / ".git" / "rebase-merge").exists()
    assert not (repo / ".git" / "rebase-apply").exists()


def test_push_of_a_branch_that_follows_a_local_branch_is_refused(repo):
    repo.git("switch", "-q", "-c", "follower", "--track", "main")
    (repo / "a.txt").write_text("a")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "a")

    with pytest.raises(GitError):
        push(repo)

    assert len(_log(repo, "main", "--format=%H").split()) == 1


def test_verbs_that_may_run_hooks_get_two_minutes(repo, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(command, *args, **kwargs):
        seen.append((command, kwargs.get("timeout")))
        return real(command, *args, **kwargs)

    monkeypatch.setattr(gitops.subprocess, "run", spy)
    (repo / "a.txt").write_text("a")
    commit(repo, ["a.txt"], "a")
    create(repo, "feature/x")
    switch(repo, "main")

    for verb in ("commit", "switch", "add"):
        timeouts = [timeout for command, timeout in seen if verb in command]
        assert timeouts and set(timeouts) == {120}, verb


def test_a_conflicted_file_is_not_committed(repo):
    path = repo / "migrations" / "V1_0_0__create_accounts.sql"
    repo.git("switch", "-q", "-c", "theirs")
    path.write_text("-- theirs\n")
    repo.git("commit", "-q", "-am", "theirs")
    repo.git("switch", "-q", "main")
    path.write_text("-- ours\n")
    repo.git("commit", "-q", "-am", "ours")
    subprocess.run(["git", "-C", str(repo), "merge", "-q", "theirs"], capture_output=True)

    with pytest.raises(GitError, match="conflict"):
        commit(repo, ["migrations/V1_0_0__create_accounts.sql"], "x")

    assert [f.state for f in status(repo).files] == ["conflicted"]


def _porcelain(repo):
    return subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain=v2", "--branch", "-z"],
        check=True,
        capture_output=True,
    ).stdout


def test_a_mixed_commit_takes_exactly_the_selected_files(repo):
    (repo / "migrations" / "V1_2_0__new.sql").write_text("SELECT 1;\n")
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("-- changed\n")
    (repo / "dblift.yaml").unlink()
    (repo / "left-alone.txt").write_text("x")

    commit(
        repo,
        ["migrations/V1_2_0__new.sql", "migrations/V1_0_0__create_accounts.sql", "dblift.yaml"],
        "Mixed",
    )

    assert _log(repo, "-1", "--name-status", "--format=").split("\n")[:3] == [
        "D\tdblift.yaml",
        "M\tmigrations/V1_0_0__create_accounts.sql",
        "A\tmigrations/V1_2_0__new.sql",
    ]
    assert [(f.path, f.state) for f in status(repo).files] == [("left-alone.txt", "untracked")]


def test_a_commit_refused_by_git_leaves_the_index_as_it_was(repo, tmp_path, monkeypatch):
    # No identity anywhere: git refuses to commit ("Please tell me who you are").
    home = tmp_path / "home"
    home.mkdir()
    for name in ("GIT_AUTHOR_NAME", "GIT_AUTHOR_EMAIL", "GIT_COMMITTER_NAME", "EMAIL"):
        monkeypatch.delenv(name, raising=False)
    monkeypatch.delenv("GIT_COMMITTER_EMAIL", raising=False)
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("XDG_CONFIG_HOME", str(home))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(home / "none"))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    repo.git("config", "--unset", "user.email")
    repo.git("config", "--unset", "user.name")
    repo.git("config", "user.useConfigOnly", "true")
    (repo / "migrations" / "V1_2_0__new.sql").write_text("SELECT 1;\n")
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("-- changed\n")
    (repo / "dblift.yaml").unlink()
    (repo / "staged-by-hand.txt").write_text("x")
    repo.git("add", "staged-by-hand.txt")
    before = _porcelain(repo)
    head = _log(repo, "-1", "--format=%H")

    with pytest.raises(GitError, match="email"):
        commit(
            repo,
            ["migrations/V1_2_0__new.sql", "migrations/V1_0_0__create_accounts.sql", "dblift.yaml"],
            "Refused",
        )

    assert _porcelain(repo) == before
    assert _log(repo, "-1", "--format=%H") == head


def test_a_file_staged_by_hand_and_not_selected_stays_staged_and_uncommitted(repo):
    (repo / "staged-by-hand.txt").write_text("by hand")
    repo.git("add", "staged-by-hand.txt")
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("-- changed\n")
    (repo / "migrations" / "V1_2_0__new.sql").write_text("SELECT 1;\n")

    commit(repo, ["migrations/V1_0_0__create_accounts.sql", "migrations/V1_2_0__new.sql"], "x")

    assert "staged-by-hand.txt" not in _log(repo, "-1", "--name-only", "--format=")
    assert [(f.path, f.state) for f in status(repo).files] == [("staged-by-hand.txt", "added")]
    staged = subprocess.run(
        ["git", "-C", str(repo), "diff", "--cached", "--name-only"],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.split()
    assert staged == ["staged-by-hand.txt"]
