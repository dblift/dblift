"""Find the config files of a folder without the user typing a path. Read-only."""

import os
import re
import shutil
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, List, Optional, Set, Tuple

import yaml
from dblift_ui.scripts import SCRIPT_NAME, ScriptError, ScriptStore, yaml_problem

MAX_FILES = 20_000
MAX_YAML_BYTES = 200_000

_CONFIG_NAME = re.compile(
    r"^dblift.*\.ya?ml(?P<template>\.(?:template|example|sample))?\Z", re.IGNORECASE
)
_YAML_NAME = re.compile(r".+\.ya?ml\Z", re.IGNORECASE)
_FLYWAY_NAMES = frozenset({"flyway.conf", "flyway.toml"})
_EXAMPLE_FOLDERS = frozenset(
    {"doc", "docs", "example", "examples", "sample", "samples", "templates"}
)
_SKIPPED_FOLDERS = frozenset(
    {".git", ".hg", ".svn", "node_modules", ".venv", "venv", "__pycache__", ".tox", "dist", "build"}
)
_ORDER = {"named": 0, "content": 1, "template": 2}


class DiscoveryError(Exception):
    """The folder cannot be scanned; the message is for the user."""


@dataclass(frozen=True)
class FoundConfig:
    path: str
    kind: str
    problem: Optional[str]
    registered: bool


@dataclass(frozen=True)
class Discovery:
    root: str
    name: str
    repository: bool
    branch: str
    configs: List[FoundConfig]
    flyway: List[str]
    script_folders: List[str]
    truncated: bool


def _git(root: Path, *args: str) -> Optional[str]:
    """Output of a read-only git command in *root*, or None when git cannot answer."""
    if shutil.which("git") is None:
        return None
    try:
        done = subprocess.run(
            # A repository's own config must not make git run a program of its choosing.
            [
                "git",
                "-C",
                str(root),
                "-c",
                "core.fsmonitor=false",
                "-c",
                "core.untrackedCache=false",
                *args,
            ],
            capture_output=True,
            timeout=30,
            env={**os.environ, "GIT_TERMINAL_PROMPT": "0", "GIT_OPTIONAL_LOCKS": "0"},
        )
    except (OSError, subprocess.SubprocessError):
        return None
    return done.stdout.decode("utf-8", errors="replace") if done.returncode == 0 else None


def _list(root: Path) -> Tuple[List[str], bool, bool]:
    """Relative paths of the files to consider, whether the list was cut, whether git gave it."""
    listed: Optional[str] = None
    if (root / ".git").exists():
        # Tracked files plus untracked ones that are not ignored: the repository's own view.
        listed = _git(root, "ls-files", "-co", "--exclude-standard", "-z")
    if listed is not None:
        paths = [p for p in listed.split("\0") if p]
        return paths[:MAX_FILES], len(paths) > MAX_FILES, True
    paths = []
    for current, folders, names in os.walk(root):
        folders[:] = sorted(f for f in folders if f not in _SKIPPED_FOLDERS)
        for name in sorted(names):
            if len(paths) >= MAX_FILES:
                return paths, True, False
            paths.append(os.path.relpath(os.path.join(current, name), root))
    return paths, False, False


def _shape(path: Path) -> Tuple[bool, bool, Optional[str]]:
    """(has a database mapping, has a migrations mapping, problem) for a YAML file."""
    try:
        # The read itself is bounded: the size on disk may change after it is measured.
        with open(path, "rb") as handle:
            raw = handle.read(MAX_YAML_BYTES + 1)
        if len(raw) > MAX_YAML_BYTES:
            return False, False, "too large to inspect"
        data = yaml.safe_load(raw.decode("utf-8", errors="replace"))
    except OSError as exc:
        return False, False, exc.strerror or "cannot be read"
    except yaml.YAMLError as exc:
        return False, False, yaml_problem(exc)
    if not isinstance(data, dict):
        return False, False, "not a mapping"
    database = isinstance(data.get("database"), dict)
    migrations = isinstance(data.get("migrations"), dict)
    return database, migrations, None if database else "no database section"


def discover(folder: str, registered: Iterable[str] = ()) -> Discovery:
    text = str(folder or "").strip()
    candidate = Path(text).expanduser()
    if not text or not candidate.is_absolute():
        raise DiscoveryError("give the full path of a folder")
    root = candidate.resolve()
    if not root.is_dir():
        raise DiscoveryError(f"{root} is not a folder")
    known = {str(Path(p).resolve()) for p in registered}
    paths, truncated, from_git = _list(root)

    configs: List[FoundConfig] = []
    flyway: List[str] = []
    script_folders: Set[Path] = set()
    for relative in paths:
        parts = Path(relative).parts
        if not parts or any(part in _SKIPPED_FOLDERS for part in parts[:-1]):
            continue
        name = parts[-1]
        path = root / relative
        try:
            real = path.resolve(strict=True)
        except (OSError, RuntimeError):
            continue
        # Nothing reached through a link that leaves the folder is considered.
        if root not in real.parents or not real.is_file():
            continue
        posix = Path(relative).as_posix()
        in_examples = any(part.lower() in _EXAMPLE_FOLDERS for part in parts[:-1])
        named = _CONFIG_NAME.match(name)
        if name in _FLYWAY_NAMES:
            flyway.append(posix)
        elif named:
            if named["template"] or in_examples:
                configs.append(FoundConfig(posix, "template", None, False))
            else:
                _, _, problem = _shape(path)
                configs.append(FoundConfig(posix, "named", problem, str(real) in known))
        elif _YAML_NAME.match(name) and not in_examples:
            database, migrations, problem = _shape(path)
            if database and migrations and problem is None:
                configs.append(FoundConfig(posix, "content", None, str(real) in known))
        elif SCRIPT_NAME.match(name):
            script_folders.add(real.parent)

    covered: List[Path] = []
    for config in configs:
        if config.kind != "template" and config.problem is None:
            try:
                covered += [
                    directory for directory, _ in ScriptStore(str(root / config.path)).directories
                ]
            except ScriptError:
                continue
    orphans = sorted(
        Path(os.path.relpath(folder_, root)).as_posix()
        for folder_ in script_folders
        if not any(directory == folder_ or directory in folder_.parents for directory in covered)
    )

    branch = (_git(root, "rev-parse", "--abbrev-ref", "HEAD") or "").strip() if from_git else ""
    configs.sort(key=lambda c: (_ORDER[c.kind], c.path))
    return Discovery(
        root=str(root),
        name=root.name,
        repository=from_git,
        branch=branch,
        configs=configs,
        flyway=sorted(flyway),
        script_folders=orphans,
        truncated=truncated,
    )
