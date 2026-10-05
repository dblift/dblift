"""A narrow set of git verbs for the interface. Never a shell, never a prompt, never a forced change."""

import os
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from dblift_ui.masking import redact

MAX_FILES = 2_000
MAX_DIFF = 400_000

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
