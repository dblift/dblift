import os
import subprocess

import pytest
from dblift_ui import gitops
from dblift_ui.gitops import (
    Branch,
    ChangedFile,
    GitError,
    branches,
    check_path,
    diff,
    is_repository,
    run,
    status,
)


def test_is_repository(repo, tmp_path):
    assert is_repository(repo) is True
    assert is_repository(tmp_path) is False


def test_a_clean_status(repo):
    assert status(repo) == gitops.RepoStatus(
        branch="main",
        detached=False,
        upstream="origin/main",
        ahead=0,
        behind=0,
        files=[],
        truncated=False,
    )


def test_status_lists_every_kind_of_change(repo):
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("-- changed\n")
    (repo / "migrations" / "V1_2_0__new.sql").write_text("SELECT 1;\n")
    (repo / "dblift.yaml").unlink()
    (repo / "notes with space.txt").write_text("x")
    (repo / "staged.sql").write_text("x")
    repo.git("add", "staged.sql")

    files = status(repo).files

    assert files == [
        ChangedFile("dblift.yaml", "deleted"),
        ChangedFile("migrations/V1_0_0__create_accounts.sql", "modified"),
        ChangedFile("migrations/V1_2_0__new.sql", "untracked"),
        ChangedFile("notes with space.txt", "untracked"),
        ChangedFile("staged.sql", "added"),
    ]


def test_status_reports_a_rename_under_its_new_name(repo):
    repo.git("mv", "dblift.yaml", "dblift-main.yaml")

    assert status(repo).files == [ChangedFile("dblift-main.yaml", "renamed")]


def test_status_counts_ahead_and_behind(repo):
    (repo / "a.txt").write_text("a")
    repo.git("add", ".")
    repo.git("commit", "-q", "-m", "local")

    assert (status(repo).ahead, status(repo).behind) == (1, 0)

    repo.git("reset", "-q", "--hard", "HEAD~1")
    repo.git("update-ref", "refs/remotes/origin/main", "refs/remotes/origin/feature/remote-only")
    assert (status(repo).ahead, status(repo).behind) == (0, 1)


def test_status_on_a_branch_without_upstream_and_detached(repo):
    repo.git("switch", "-q", "-c", "local-only")
    found = status(repo)
    assert (found.branch, found.upstream, found.ahead, found.behind) == ("local-only", "", 0, 0)

    repo.git("switch", "-q", "--detach", "HEAD")
    found = status(repo)
    assert found.detached is True and found.branch == ""


def test_status_is_cut_short_on_a_huge_change(repo, monkeypatch):
    monkeypatch.setattr(gitops, "MAX_FILES", 3)
    for index in range(10):
        (repo / f"file{index}.txt").write_text("x")

    found = status(repo)

    assert len(found.files) == 3 and found.truncated is True


def test_branches_local_then_remote(repo):
    repo.git("switch", "-q", "-c", "feature/local")
    repo.git("switch", "-q", "main")

    assert branches(repo) == [
        Branch("feature/local", current=False, remote=False, upstream=""),
        Branch("main", current=True, remote=False, upstream="origin/main"),
        Branch("origin/feature/remote-only", current=False, remote=True, upstream=""),
        Branch("origin/main", current=False, remote=True, upstream=""),
    ]


def test_diff_of_a_modified_file(repo):
    path = "migrations/V1_0_0__create_accounts.sql"
    (repo / path).write_text("CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT);\n")

    text = diff(repo, path)

    assert "-CREATE TABLE accounts (id INTEGER PRIMARY KEY);" in text
    assert "+CREATE TABLE accounts (id INTEGER PRIMARY KEY, name TEXT);" in text


def test_diff_of_an_unchanged_file_is_empty(repo):
    assert diff(repo, "migrations/V1_0_0__create_accounts.sql") == ""


def test_diff_of_an_untracked_file_is_all_additions(repo):
    (repo / "migrations" / "V1_2_0__new.sql").write_text("SELECT 1;\nSELECT 2;\n")

    text = diff(repo, "migrations/V1_2_0__new.sql")

    assert "+SELECT 1;" in text and "+SELECT 2;" in text
    assert not any(
        line.startswith("-") and not line.startswith("---") for line in text.splitlines()
    )


def test_diff_refuses_a_huge_change(repo, monkeypatch):
    monkeypatch.setattr(gitops, "MAX_DIFF", 50)
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("x\n" * 200)

    with pytest.raises(GitError, match="too large"):
        diff(repo, "migrations/V1_0_0__create_accounts.sql")


def test_diff_never_asks_for_an_external_program(repo, monkeypatch):
    seen = []
    real = subprocess.run

    def spy(command, *args, **kwargs):
        seen.append(command)
        return real(command, *args, **kwargs)

    monkeypatch.setattr(gitops.subprocess, "run", spy)
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("-- changed\n")
    diff(repo, "migrations/V1_0_0__create_accounts.sql")
    status(repo)

    diffs = [command for command in seen if "diff" in command]
    assert diffs and all(
        "--no-ext-diff" in command and "--no-textconv" in command for command in diffs
    )
    for command in seen:
        assert (
            command[:1] == ["git"]
            and "core.fsmonitor=false" in command
            and "protocol.ext.allow=never" in command
        )


@pytest.mark.parametrize(
    "path", ["", "-x", "--output=/tmp/x", "../outside.txt", "/etc/passwd", "a/../../b", "a\x00b"]
)
def test_paths_that_could_be_options_or_escape_are_refused(repo, path):
    with pytest.raises(GitError):
        check_path(repo, path)
    with pytest.raises(GitError):
        diff(repo, path)


def test_a_link_out_of_the_repository_is_refused(repo, tmp_path):
    outside = tmp_path / "secret.txt"
    outside.write_text("secret")
    os.symlink(outside, repo / "link.sql")

    with pytest.raises(GitError):
        check_path(repo, "link.sql")


def test_check_path_accepts_a_deleted_file(repo):
    (repo / "dblift.yaml").unlink()

    assert check_path(repo, "dblift.yaml") == "dblift.yaml"


def test_run_reports_gits_reason_without_credentials(repo):
    with pytest.raises(GitError) as raised:
        run(repo, "fetch", "https://user:hunter2@localhost:1/x.git")

    assert "hunter2" not in str(raised.value)


def test_run_gives_up_after_its_timeout(repo, monkeypatch):
    def slow(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd="git", timeout=1)

    monkeypatch.setattr(gitops.subprocess, "run", slow)

    with pytest.raises(GitError, match="too long"):
        run(repo, "status")


def test_run_refuses_unbounded_output(repo):
    with pytest.raises(GitError, match="too much"):
        run(repo, "log", "--format=%H", limit=10)


def test_git_missing_is_explained(repo, monkeypatch):
    monkeypatch.setattr(gitops.shutil, "which", lambda name: None)

    with pytest.raises(GitError, match="not installed"):
        status(repo)


def test_status_reports_a_conflicted_file(repo):
    path = repo / "migrations" / "V1_0_0__create_accounts.sql"
    repo.git("switch", "-q", "-c", "theirs")
    path.write_text("-- theirs\n")
    repo.git("commit", "-q", "-am", "theirs")
    repo.git("switch", "-q", "main")
    path.write_text("-- ours\n")
    repo.git("commit", "-q", "-am", "ours")
    merged = subprocess.run(["git", "-C", str(repo), "merge", "-q", "theirs"], capture_output=True)
    assert merged.returncode != 0

    assert status(repo).files == [
        ChangedFile("migrations/V1_0_0__create_accounts.sql", "conflicted")
    ]


@pytest.mark.parametrize("pattern", ["*", "migrations/*", ":(glob)**/*.sql", ":(top)dblift.yaml"])
def test_a_path_is_never_read_as_a_pattern(repo, pattern):
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("-- changed\n")
    (repo / "dblift.yaml").write_text("-- changed\n")

    with pytest.raises(GitError):
        diff(repo, pattern)


def test_diff_of_a_folder_or_of_gits_own_files_is_refused(repo):
    (repo / "migrations" / "V1_0_0__create_accounts.sql").write_text("-- changed\n")

    for path in ("migrations", ".git/config", "migrations/../.git/HEAD", ".GIT/config"):
        with pytest.raises(GitError):
            diff(repo, path)
