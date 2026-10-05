"""A narrow set of git verbs for the interface. Never a shell, never a prompt, never a forced change."""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Sequence, Tuple
from urllib.parse import quote, urlsplit

from dblift_ui.masking import redact

MAX_FILES = 2_000
MAX_DIFF = 400_000
MAX_PULL_REQUEST_BODY = 4_000
_HOST = re.compile(r"^[A-Za-z0-9.-]+$")
_SEGMENT = re.compile(r"^[A-Za-z0-9._-]+$")
# ``[user@]host:path``, git's short form of an ssh address: no slash before the colon.
_SCP = re.compile(r"^(?:[^@/:]+@)?(?P<host>[^@/:]+):(?P<path>.+)$")

ENVIRONMENT: Dict[str, str] = {
    "GIT_TERMINAL_PROMPT": "0",
    "GIT_OPTIONAL_LOCKS": "0",
    "GIT_EDITOR": "true",
    "GIT_SSH_COMMAND": "ssh -oBatchMode=yes",
    "GIT_ALLOW_PROTOCOL": "https:ssh:file",
}
# A repository's own config must not make git run a program of its choosing while we only read.
SAFE: Tuple[str, ...] = (
    "-c",
    "core.fsmonitor=false",
    "-c",
    "core.untrackedCache=false",
    "-c",
    "protocol.ext.allow=never",
)
# Every path from the browser is a file name, never a pattern: no wildcard, no ``:(magic)``.
_LITERAL = "--literal-pathspecs"
_NO_PROGRAMS = ("--no-ext-diff", "--no-textconv", "--no-color")


class GitError(Exception):
    """Git refused or failed; the message is for the user."""


@dataclass(frozen=True)
class ChangedFile:
    path: str
    state: str


@dataclass(frozen=True)
class RepoStatus:
    branch: str
    detached: bool
    upstream: str
    ahead: int
    behind: int
    files: List[ChangedFile]
    truncated: bool


@dataclass(frozen=True)
class Branch:
    name: str
    current: bool
    remote: bool
    upstream: str


def run(
    root: Path,
    *args: str,
    timeout: int = 30,
    stdin: Optional[str] = None,
    limit: int = 2_000_000,
    ok: Tuple[int, ...] = (0,),
) -> str:
    """Stdout of ``git -C root <args>``; *ok* lists the exit codes that are not a failure."""
    if shutil.which("git") is None:
        raise GitError("git is not installed on this machine")
    try:
        done = subprocess.run(
            ["git", "-C", str(root), *SAFE, *args],
            capture_output=True,
            timeout=timeout,
            input=stdin.encode("utf-8") if stdin is not None else None,
            env={**os.environ, **ENVIRONMENT},
        )
    except subprocess.TimeoutExpired as exc:
        raise GitError("git took too long and was stopped") from exc
    except OSError as exc:
        raise GitError(f"git could not be started: {exc.strerror or exc}") from exc
    except ValueError as exc:  # an argument holding a NUL byte
        raise GitError("git cannot be given that value") from exc
    if done.returncode not in ok:
        lines = redact(done.stderr.decode("utf-8", errors="replace")).strip().splitlines()
        raise GitError(lines[-1] if lines else "git failed")
    if len(done.stdout) > limit:
        raise GitError("git answered with too much to show")
    return done.stdout.decode("utf-8", errors="replace")


def is_repository(root: Path) -> bool:
    return (root / ".git").exists()


def _state(xy: str) -> str:
    if "D" in xy:
        return "deleted"
    if xy[:1] == "A":
        return "added"
    return "modified"


def status(root: Path) -> RepoStatus:
    records = run(
        root, "status", "--porcelain=v2", "--branch", "-z", "--untracked-files=all"
    ).split("\0")
    branch, detached, upstream, ahead, behind = "", False, "", 0, 0
    files: List[ChangedFile] = []
    index = 0
    while index < len(records):
        record = records[index]
        index += 1
        if record.startswith("# branch.head "):
            head = record[len("# branch.head ") :]
            detached = head == "(detached)"
            branch = "" if detached else head
        elif record.startswith("# branch.upstream "):
            upstream = record[len("# branch.upstream ") :]
        elif record.startswith("# branch.ab "):
            counts = record[len("# branch.ab ") :].split()
            ahead, behind = abs(int(counts[0])), abs(int(counts[1]))
        elif record.startswith("1 "):
            fields = record.split(" ", 8)
            files.append(ChangedFile(fields[8], _state(fields[1])))
        elif record.startswith("2 "):
            fields = record.split(" ", 9)
            files.append(ChangedFile(fields[9], "deleted" if "D" in fields[1] else "renamed"))
            index += 1  # the original path follows as its own record
        elif record.startswith("u "):
            files.append(ChangedFile(record.split(" ", 10)[10], "conflicted"))
        elif record.startswith("? "):
            files.append(ChangedFile(record[2:], "untracked"))
    files.sort(key=lambda changed: changed.path)
    return RepoStatus(
        branch=branch,
        detached=detached,
        upstream=upstream,
        ahead=ahead,
        behind=behind,
        files=files[:MAX_FILES],
        truncated=len(files) > MAX_FILES,
    )


def branches(root: Path) -> List[Branch]:
    listed = run(
        root,
        "for-each-ref",
        "--format=%(refname)%00%(HEAD)%00%(upstream:short)",
        "refs/heads",
        "refs/remotes",
    )
    local: List[Branch] = []
    remote: List[Branch] = []
    for line in listed.splitlines():
        refname, head, upstream = (line.split("\0") + ["", ""])[:3]
        if refname.startswith("refs/heads/"):
            local.append(Branch(refname[len("refs/heads/") :], head == "*", False, upstream))
        elif refname.startswith("refs/remotes/") and not refname.endswith("/HEAD"):
            remote.append(Branch(refname[len("refs/remotes/") :], False, True, ""))
    return sorted(local, key=lambda b: b.name) + sorted(remote, key=lambda b: b.name)


def check_path(root: Path, path: str) -> str:
    """*path* when it names a place inside *root* and cannot be read as an option."""
    if not isinstance(path, str) or not path or "\0" in path or path.startswith("-"):
        raise GitError("that is not a file of this repository")
    relative = Path(path)
    if relative.is_absolute() or ".." in relative.parts:
        raise GitError("that is not a file of this repository")
    # The repository's own store is not a file of the project.
    if any(part.lower() == ".git" for part in relative.parts):
        raise GitError("that is not a file of this repository")
    top = root.resolve()
    try:
        resolved = (top / relative).resolve()
    except (OSError, RuntimeError) as exc:
        raise GitError("that is not a file of this repository") from exc
    if top not in resolved.parents:
        raise GitError("that is not a file of this repository")
    return path


def diff(root: Path, path: str) -> str:
    """The changes of one file against ``HEAD``; an untracked file shows whole as additions."""
    check_path(root, path)
    if (root / path).is_dir():
        raise GitError("that is a folder, not a file")
    try:
        run(root, _LITERAL, "ls-files", "--error-unmatch", "--", path)
        tracked = True
    except GitError:
        tracked = False
    if tracked:
        text = run(root, _LITERAL, "diff", *_NO_PROGRAMS, "HEAD", "--", path)
    elif not (root / path).is_file():
        raise GitError("that file is not in the repository")
    else:
        # Exit 1 means "there are differences" for a comparison outside the index.
        text = run(root, "diff", "--no-index", *_NO_PROGRAMS, "--", os.devnull, path, ok=(0, 1))
    if len(text) > MAX_DIFF:
        raise GitError("the change is too large to show")
    return redact(text)


def check_branch(root: Path, name: str) -> str:
    """*name* when git accepts it as a branch name and it cannot be read as an option."""
    if not isinstance(name, str) or not name or name.startswith("-"):
        raise GitError("that is not a branch name")
    # "@{-1}" and "@" name another commit, "refs/…" a full reference: never a branch the user typed.
    if any(c in name for c in "\0\n\r") or "@{" in name or name == "@" or name.startswith("refs/"):
        raise GitError("that is not a branch name")
    run(root, "check-ref-format", "--branch", name)
    return name


def switch(root: Path, name: str) -> None:
    """Go to branch *name*; a remote one (``origin/x``) becomes the local tracking branch ``x``."""
    check_branch(root, name)
    known = branches(root)
    if name in {b.name for b in known if b.remote}:
        local = name.split("/", 1)[1]
        if local in {b.name for b in known if not b.remote}:
            run(root, "switch", "--no-guess", local, timeout=120)
        else:
            run(root, "switch", "--track", name, timeout=120)
    else:
        run(root, "switch", "--no-guess", name, timeout=120)


def create(root: Path, name: str) -> None:
    """Create branch *name* where ``HEAD`` is and go to it."""
    check_branch(root, name)
    # A local "origin/x" would make "origin/x" mean two things.
    remotes = run(root, "remote").split()
    if name.split("/", 1)[0] in remotes:
        raise GitError("a branch name may not start with the name of a remote")
    run(root, "switch", "-c", name, timeout=120)


def fetch(root: Path) -> None:
    run(root, "fetch", "--prune", timeout=120)


def pull(root: Path) -> None:
    """Bring the branch up to its remote when that needs no merge; otherwise change nothing."""
    if not status(root).upstream:
        raise GitError("This branch has no remote branch to pull from.")
    try:
        # Never a rebase, never a stash, whatever the repository's config says.
        run(root, "pull", "--ff-only", "--no-rebase", "--no-autostash", timeout=120)
    except GitError as exc:
        if "Not possible to fast-forward" in str(exc) or "Diverging branches" in str(exc):
            raise GitError(
                "This branch and its remote have both moved. "
                "Merge or rebase with your own git tool, then come back."
            ) from exc
        raise


def push(root: Path) -> None:
    """Publish the current branch; a branch without a remote one is published to origin."""
    found = status(root)
    if found.detached or not found.branch:
        raise GitError("Switch to a branch before pushing.")
    source = f"refs/heads/{found.branch}"
    if found.upstream:
        remote, target = (
            run(
                root,
                "for-each-ref",
                "--format=%(upstream:remotename)%00%(upstream:remoteref)",
                source,
            ).strip()
            + "\0"
        ).split("\0")[:2]
        if remote == ".":
            raise GitError("This branch follows a local branch; there is no remote to push to.")
        if not remote or not target:
            raise GitError("This branch's remote branch cannot be found.")
        # An explicit refspec without "+": a configured forcing refspec never applies.
        run(root, "push", "--", remote, f"{source}:{target}", timeout=120)
        return
    if "origin" not in run(root, "remote").split():
        raise GitError("This repository has no remote named origin.")
    run(root, "push", "-u", "--", "origin", f"{source}:{source}", timeout=120)


def commit(root: Path, paths: Sequence[str], message: str) -> None:
    """Commit exactly *paths* (changed files) with *message*; whatever else is staged stays."""
    if not paths:
        raise GitError("Choose the files to commit.")
    if not isinstance(message, str) or not message.strip():
        raise GitError("Write a commit message.")
    for path in paths:
        check_path(root, path)
    changed = {changed.path: changed.state for changed in status(root).files}
    for path in paths:
        if path not in changed:
            raise GitError(f"{path} has no change to commit")
        # Committing it would record the conflict markers and end the conflict.
        if changed[path] == "conflicted":
            raise GitError(f"{path} has a conflict; resolve it with your own git tool first.")
    selected = list(dict.fromkeys(paths))
    # "--only" takes tracked files as they are in the working tree and leaves the index as it
    # was when the commit is refused. Only untracked files must be known to the index first.
    untracked = [path for path in selected if changed[path] == "untracked"]
    if untracked:
        run(root, _LITERAL, "add", "--intent-to-add", "--", *untracked, timeout=120)
    try:
        run(
            root,
            _LITERAL,
            "commit",
            "--only",
            "-F",
            "-",
            "--",
            *selected,
            stdin=message.strip() + "\n",
            timeout=120,
        )
    except GitError:
        if untracked:  # untracked again, as they were
            run(root, _LITERAL, "rm", "--cached", "--quiet", "--", *untracked, timeout=120)
        raise


def _web_base(host: str, port: Optional[int], path: str) -> Optional[str]:
    """``https://host[:port]/owner/repo`` when every part is plain, else None."""
    labels = host.split(".")
    if not _HOST.match(host) or any(
        not label or label.startswith("-") or label.endswith("-") for label in labels
    ):
        return None
    path = path[:-1] if path.endswith("/") else path
    path = path[:-4] if path.endswith(".git") else path
    segments = path.split("/")
    if path.startswith("/"):
        segments = segments[1:]
    if len(segments) < 2 or any(
        not _SEGMENT.match(segment) or segment in (".", "..") for segment in segments
    ):
        return None
    authority = host.lower() if port is None else f"{host.lower()}:{port}"
    return f"https://{authority}/{'/'.join(segments)}"


def _kind(host: str) -> str:
    host = host.lower()
    if host == "github.com":
        return "github"
    if host == "gitlab.com" or host.startswith("gitlab."):
        return "gitlab"
    if host == "bitbucket.org":
        return "bitbucket"
    return "other"


def remote_web(root: Path) -> Optional[Tuple[str, str]]:
    """``(kind, web address)`` of the ``origin`` remote; None for a local or unusual one.

    Credentials and ssh ports are dropped. Anything that is not plain letters, digits,
    dots, hyphens and underscores in the host or a path segment gives None, so a remote
    can never turn into a link to some other place.
    """
    if not is_repository(root):
        return None
    try:
        url = run(root, "remote", "get-url", "origin").strip()
    except GitError:
        return None
    if not url.isprintable() or any(c.isspace() or c == "\\" for c in url):
        return None
    if "://" in url:
        try:
            parts = urlsplit(url)
            port = parts.port
        except ValueError:
            return None
        if parts.scheme not in ("https", "ssh") or "?" in url or "#" in url:
            return None
        host = parts.hostname or ""
        base = _web_base(host, port if parts.scheme == "https" else None, parts.path)
    else:
        match = _SCP.match(url)
        if match is None or match["path"].startswith("/"):
            return None
        host = match["host"]
        base = _web_base(host, None, match["path"])
    return None if base is None else (_kind(host), base)


def pull_request_url(kind: str, base: str, branch: str, title: str, body: str) -> Optional[str]:
    """A link opening a new pull (or merge) request for *branch*, or None for another host."""
    if not base.startswith("https://") or not branch:
        return None

    def encoded(value: str) -> str:
        return quote(value, safe="")

    if kind == "github":
        return (
            f"{base}/compare/{quote(branch, safe='/')}?expand=1"
            f"&title={encoded(title)}&body={encoded(body[:MAX_PULL_REQUEST_BODY])}"
        )
    if kind == "gitlab":
        return (
            f"{base}/-/merge_requests/new?merge_request%5Bsource_branch%5D={encoded(branch)}"
            f"&merge_request%5Btitle%5D={encoded(title)}"
        )
    if kind == "bitbucket":
        return f"{base}/pull-requests/new?source={encoded(branch)}"
    return None
