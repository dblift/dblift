"""Clone a repository the user named, without letting the URL become a command."""

import os
import re
import shutil
import subprocess
from pathlib import Path

from dblift_ui.jobs import redact

# https, ssh, and the scp-like git@host:path form. Everything else (http, git, ext, …) is refused.
_REMOTE = re.compile(r"^(?:https://|ssh://|[\w.-]+@[\w.-]+:)[^\s\x00-\x1f]+\Z")
_FOLDER = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*\Z")
_TIMEOUT = 300


class CloneError(Exception):
    """The clone was refused or failed; the message is for the user."""


def check_url(url: str) -> str:
    text = str(url or "").strip()
    if not text:
        raise CloneError("give the repository's address")
    if text.startswith("-") or re.search(r"[\s\x00-\x1f]", text):
        raise CloneError("that is not a repository address")
    if _REMOTE.match(text):
        return text
    local = text[len("file://") :] if text.startswith("file://") else text
    if os.path.isabs(local):
        return text
    raise CloneError(
        "use an https:// or ssh:// address, git@host:path, or the full path of a local repository"
    )


def folder_name(url: str) -> str:
    # Only the path names the folder: an address without one (https://host/) has no name.
    path = re.sub(r"^(?:[A-Za-z][\w+.-]*://[^/]*|[\w.-]+@[\w.-]+:)", "", url)
    last = path.rstrip("/").rsplit("/", 1)[-1]
    name = last[:-4] if last.endswith(".git") else last
    if not _FOLDER.match(name) or name in (".", ".."):
        raise CloneError("cannot tell a folder name from that address")
    return name


def clone(url: str, parent: str) -> Path:
    address = check_url(url)
    name = folder_name(address)
    if shutil.which("git") is None:
        raise CloneError("git is not installed on this machine")
    folder = Path(str(parent or "").strip()).expanduser()
    if not folder.is_absolute():
        raise CloneError("give the full path of the folder to clone into")
    target = folder.resolve() / name
    if target.exists():
        raise CloneError(f"{target} already exists")
    target.parent.mkdir(parents=True, exist_ok=True)
    environment = {
        **os.environ,
        "GIT_TERMINAL_PROMPT": "0",
        "GIT_ALLOW_PROTOCOL": "https:ssh:file",
        "GIT_SSH_COMMAND": "ssh -oBatchMode=yes",
    }
    try:
        done = subprocess.run(
            [
                "git",
                "-c",
                "protocol.ext.allow=never",
                "clone",
                "--no-recurse-submodules",
                "--",
                address,
                str(target),
            ],
            capture_output=True,
            timeout=_TIMEOUT,
            env=environment,
        )
    except subprocess.TimeoutExpired as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise CloneError("the clone took too long and was stopped") from exc
    except OSError as exc:
        shutil.rmtree(target, ignore_errors=True)
        raise CloneError(f"git could not be started: {exc.strerror or exc}") from exc
    if done.returncode != 0:
        shutil.rmtree(target, ignore_errors=True)
        # redact() masks user:password@ but not a token given as the user name alone.
        anonymous = re.sub(r"//[^/@]*@", "//", address)
        text = done.stderr.decode("utf-8", errors="replace").replace(address, anonymous)
        reason = redact(text).strip().splitlines()
        raise CloneError("git could not clone it: " + (reason[-1] if reason else "unknown error"))
    return target
