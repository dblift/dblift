"""Prove a new migration and its undo script on a database that holds nothing of value.

The cycle is: build from zero (apply every migration), undo the new migration, apply it
again. It runs on a temporary SQLite file, or on the config's environment named
``scratch`` once that environment is known not to share a database with any other.
"""

import os
import tempfile
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple

import yaml
from dblift_ui.masking import redact
from dblift_ui.scripts import SCRIPT_NAME, ScriptError, ScriptStore, yaml_problem

from dblift.api import DBLiftClient

SCRATCH = "scratch"
_SQLITE = frozenset({"sqlite", "sqlite3"})
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
NOT_RUN = "Not run."


class NotChecked(Exception):
    """Whether the scratch environment shares a database with another one cannot be told."""


@dataclass(frozen=True)
class Plan:
    strategy: str
    engine: str
    summary: str
    warning: str


@dataclass
class Phase:
    name: str
    ok: Optional[bool]
    detail: str


def check_script(name: Any) -> str:
    """The version of *name* when it is a versioned migration's file name, else ValueError."""
    match = SCRIPT_NAME.match(name) if isinstance(name, str) else None
    if match is None or match["prefix"] != "V":
        raise ValueError(
            "the scratch test needs the file name of a versioned migration, "
            "like V1_2_0__add_invoices.sql"
        )
    return str(match["version"]).replace("_", ".")


def _environments(config_path: str) -> Dict[Any, Any]:
    """The ``environments`` mapping of the config; ValueError with the reason when unreadable."""
    try:
        data = yaml.safe_load(Path(config_path).read_text(encoding="utf-8")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"the config cannot be read: {yaml_problem(exc)}") from exc
    except (OSError, UnicodeDecodeError) as exc:
        reason = getattr(exc, "strerror", None) or "it is not UTF-8 text"
        raise ValueError(f"the config cannot be read: {reason}") from exc
    if not isinstance(data, dict):
        raise ValueError("the config is not a mapping")
    environments = data.get("environments") or {}
    if not isinstance(environments, dict):
        raise ValueError("the config's environments are not a mapping")
    return environments


def _database(config_path: str, environment: Optional[str], folder: Optional[Path]) -> Any:
    """The database section the loader resolves for *environment*, without connecting."""
    with tempfile.TemporaryDirectory(prefix="dblift-ui-scratch-", dir=folder) as logs:
        client = DBLiftClient.from_config_file(
            config_path,
            environment=environment,
            relative_to_config=True,
            log_dir=logs,
            log_file=os.path.join(logs, "resolve.log"),
        )
        try:
            return client.config.database
        finally:
            client.close()


def _reason(exc: BaseException) -> str:
    return redact(str(exc) or type(exc).__name__).splitlines()[0]


def plan(config_path: str, *, folder: Optional[Path] = None) -> Plan:
    """How a scratch test of this project would run; *folder* holds the loader's temporary log."""
    try:
        environments = _environments(config_path)
        engine = str(_database(config_path, None, folder).type or "").lower()
    except Exception as exc:  # the loader's error types are not public
        return Plan("skip", "", _reason(exc), "")
    if engine in _SQLITE:
        return Plan(
            "file",
            "sqlite",
            "A temporary SQLite database is created, used and deleted. "
            "Your databases are not touched.",
            "",
        )
    if SCRATCH in environments:
        return Plan(
            "environment",
            engine,
            "The environment named scratch is emptied, then used for the test.",
            "Everything in the scratch environment's database is deleted first.",
        )
    return Plan(
        "skip",
        engine,
        "No scratch database is available for this engine yet. Add an environment named "
        "scratch to the config, or continue without the test.",
        "",
    )


# Where a database lives: ("file", real path), ("server", host/database, port, schema),
# or ("memory",) for an in-memory database, which never shares anything with another one.
_Where = Tuple[Any, ...]


def _where(database: Any) -> _Where:
    path = getattr(database, "path", None)
    if path:
        if str(path) == ":memory:" or str(path).startswith("file::memory:"):
            return ("memory",)
        return ("file", os.path.realpath(str(path)))
    host = str(database.host or "").lower()
    name = str(database.database or "").lower()
    if not host and not name:
        raise NotChecked("its database cannot be identified")
    port = database.port if isinstance(database.port, int) else None
    host = "localhost" if host in _LOOPBACK else host
    return ("server", f"{host}/{name}", port, str(database.schema or "").lower())


def _same(a: _Where, b: _Where) -> bool:
    """Whether *a* and *b* may be one database; a missing port or schema matches any."""
    if a[0] == "memory" or a[:2] != b[:2]:
        return False
    if a[0] == "file":
        return True
    ports = a[2] is None or b[2] is None or a[2] == b[2]
    schemas = not a[3] or not b[3] or a[3] == b[3]
    return ports and schemas


def same_database(config_path: str, *, folder: Optional[Path] = None) -> Optional[str]:
    """The environment (``default`` for the root) sharing the scratch environment's database.

    NotChecked when that cannot be told for any environment: the test must not run then.
    """
    try:
        environments = _environments(config_path)
    except ValueError as exc:
        raise NotChecked(str(exc)) from exc
    if SCRATCH not in environments:
        raise NotChecked("the config has no environment named scratch")
    others: List[Optional[str]] = [None, *(str(n) for n in environments if n != SCRATCH)]
    try:
        target = _where(_database(config_path, SCRATCH, folder))
    except Exception as exc:
        raise NotChecked(f"the environment scratch could not be checked: {_reason(exc)}") from exc
    for name in others:
        label = name or "default"
        try:
            where = _where(_database(config_path, name, folder))
        except Exception as exc:
            raise NotChecked(
                f"the environment {label} could not be checked: {_reason(exc)}"
            ) from exc
        if _same(target, where):
            return label
    return None


def _undo_script(config_path: str, script: str, version: str) -> Optional[str]:
    """The project's undo script for *version*; ValueError when *script* is not in the project."""
    try:
        store = ScriptStore(config_path)
        store.describe(script)
        undos = store.undo_paths()
    except ScriptError as exc:
        raise ValueError(str(exc)) from exc
    for migration in sorted(undos):
        match = SCRIPT_NAME.match(migration)
        if match and str(match["version"]).replace("_", ".") == version:
            return f"U{migration[1:]}"
    return None


def _ran(result: Any) -> List[str]:
    return [str(entry.script) for entry in (getattr(result, "migrations", None) or [])]


def run_test(
    config_path: str,
    script: str,
    workdir: Path,
    log_dir: Path,
    on_phase: Callable[[Phase, str], None],
    on_event: Callable[[Any], None],
) -> Dict[str, Any]:
    """Build, undo *script* and apply it again on a scratch database; report each phase."""
    version = check_script(script)
    workdir.mkdir(parents=True, exist_ok=True)
    found = plan(config_path, folder=workdir)
    if found.strategy == "skip":
        return {
            "strategy": "skip",
            "passed": False,
            "skipped": True,
            "phases": [],
            "script": script,
        }
    undo_name = _undo_script(config_path, script, version)
    opened: List[DBLiftClient] = []

    def client() -> DBLiftClient:
        if not opened:
            if found.strategy == "environment":
                built = DBLiftClient.from_config_file(
                    config_path,
                    environment=SCRATCH,
                    relative_to_config=True,
                    log_dir=str(log_dir),
                )
            else:
                database = (workdir / "scratch.db").resolve()
                built = DBLiftClient.from_config_file(
                    config_path,
                    relative_to_config=True,
                    database_url=f"sqlite:///{database}",
                    log_dir=str(log_dir),
                )
                # Never on the word of an override alone: the client must name the file.
                chosen = getattr(built.config.database, "path", None)
                if os.path.realpath(str(chosen or "")) != str(database):
                    built.close()
                    raise RuntimeError(
                        "The temporary database could not be selected. Nothing was done."
                    )
            built.events.on("*", on_event)
            opened.append(built)
        return opened[0]

    def clean() -> Tuple[Optional[bool], str]:
        try:
            shared = same_database(config_path, folder=workdir)
        except NotChecked as exc:
            return False, f"The test was not run: {exc}. Nothing was done."
        if shared is not None:
            return (
                False,
                f"The scratch environment points at the same database as {shared}. "
                "Nothing was done.",
            )
        result = client().clean(clean_enabled=True)
        if not result.success:
            return False, result.error_message or "The scratch database could not be emptied."
        return True, "The scratch database was emptied."

    def build() -> Tuple[Optional[bool], str]:
        result = client().migrate()
        if not result.success:
            return False, result.error_message or "The migrations could not be applied."
        return True, f"{len(_ran(result))} migrations applied from an empty database."

    def undo() -> Tuple[Optional[bool], str]:
        if undo_name is None:
            return None, "This migration has no undo script."
        result = client().undo()
        if not result.success:
            return False, result.error_message or f"{undo_name} failed."
        ran = _ran(result)
        if ran != [undo_name]:
            return (
                False,
                "The undo did not target the new migration: "
                f"it ran {', '.join(ran) or 'nothing'}.",
            )
        return True, f"{undo_name} reverted {script}."

    def reapply() -> Tuple[Optional[bool], str]:
        if undo_name is None:
            return None, "Nothing was undone, so nothing is applied again."
        result = client().migrate()
        if not result.success:
            return False, result.error_message or f"{script} could not be applied again."
        ran = _ran(result)
        if ran != [script]:
            return (
                False,
                "Applying again did not run the new migration alone: "
                f"it ran {', '.join(ran) or 'nothing'}.",
            )
        return True, f"{script} applied again after its undo."

    steps: List[Tuple[str, Callable[[], Tuple[Optional[bool], str]]]] = [
        ("build", build),
        ("undo", undo),
        ("reapply", reapply),
    ]
    if found.strategy == "environment":
        steps.insert(0, ("clean", clean))
    phases: List[Phase] = []
    failed = False
    try:
        for name, step in steps:
            if failed:
                phase = Phase(name, None, NOT_RUN)
            else:
                on_phase(Phase(name, None, ""), "started")
                try:
                    ok, detail = step()
                except Exception as exc:  # the engine's error types are not public
                    ok, detail = False, str(exc) or type(exc).__name__
                phase = Phase(name, ok, redact(detail))
                failed = ok is False
            phases.append(phase)
            status = {True: "passed", False: "failed", None: "skipped"}[phase.ok]
            on_phase(phase, status)
    finally:
        for opened_client in opened:
            opened_client.close()
    return {
        "strategy": found.strategy,
        "passed": not failed,
        "skipped": False,
        "phases": [asdict(phase) for phase in phases],
        "script": script,
    }
