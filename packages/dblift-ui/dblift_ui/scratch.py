"""Prove a new migration and its undo script on a database that holds nothing of value.

The cycle is: build from zero (apply every migration), undo the new migration, apply it
again. It runs on a temporary SQLite file, or on the config's environment named
``scratch`` once that environment is known not to share a database with any other.
"""

import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple
from urllib.parse import parse_qs, urlsplit

import yaml
from dblift_ui.masking import redact
from dblift_ui.scripts import SCRIPT_NAME, ScriptError, ScriptStore, yaml_problem

from dblift.api import DBLiftClient

SCRATCH = "scratch"
_SQLITE = frozenset({"sqlite", "sqlite3"})
_FILES = _SQLITE | {"duckdb"}
_LOOPBACK = frozenset({"localhost", "127.0.0.1", "::1", "[::1]"})
# The engine's own placeholder syntax: ${VAR} or ${VAR:-default}.
_PLACEHOLDER = re.compile(r"\$\{([^}:]+)(?::-(.*?))?\}")
MAX_CONFIG_BYTES = 200_000
NOT_RUN = "Not run."
NOTHING_DONE = "Nothing was done."
UNIDENTIFIED = "The scratch environment's database could not be identified."


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


def _read(config_path: str) -> Dict[Any, Any]:
    """The config as a mapping; ValueError with the reason when it cannot be read."""
    try:
        # The read itself is bounded: the size on disk may change after it is measured.
        with open(config_path, "rb") as handle:
            raw = handle.read(MAX_CONFIG_BYTES + 1)
    except OSError as exc:
        reason = exc.strerror or "it cannot be opened"
        raise ValueError(f"the config cannot be read: {reason}") from exc
    if len(raw) > MAX_CONFIG_BYTES:
        raise ValueError("the config is too large to read")
    try:
        data = yaml.safe_load(raw.decode("utf-8", errors="replace")) or {}
    except yaml.YAMLError as exc:
        raise ValueError(f"the config cannot be read: {yaml_problem(exc)}") from exc
    if not isinstance(data, dict):
        raise ValueError("the config is not a mapping")
    if not isinstance(data.get("environments") or {}, dict):
        raise ValueError("the config's environments are not a mapping")
    return data


def _substitute(value: Any) -> Any:
    """*value* with ``${VAR}`` and ``${VAR:-default}`` filled in from the process environment.

    A variable that is unset and has no default stays as its placeholder text, so two
    environments naming the same unset variable still compare as the same database.
    """
    if not isinstance(value, str):
        return value

    def fill(match: "re.Match[str]") -> str:
        found = os.environ.get(match[1])
        if found is not None:
            return found
        return match[2] if match[2] is not None else match[0]

    return _PLACEHOLDER.sub(fill, value)


def _section(data: Dict[Any, Any], environment: Optional[str]) -> Optional[Dict[str, Any]]:
    """The effective ``database`` mapping of the root (None) or of *environment*.

    The environment's keys go over the root's, empty ones left out, as the engine merges
    them. None when the environment's block or its database section is not a mapping.
    """
    root = data.get("database")
    merged: Dict[str, Any] = dict(root) if isinstance(root, dict) else {}
    if environment is not None:
        block = (data.get("environments") or {}).get(environment)
        if not isinstance(block, dict):
            return None
        override = block.get("database") or {}
        if not isinstance(override, dict):
            return None
        merged.update({k: v for k, v in override.items() if v not in (None, "")})
    return {str(key): _substitute(value) for key, value in merged.items()}


def _engine(database: Dict[str, Any]) -> str:
    """The engine a database mapping declares: its ``type``, else its URL's scheme."""
    declared = str(database.get("type") or "").lower()
    url = database.get("url")
    if not declared and isinstance(url, str) and "://" in url:
        declared = url.split("://", 1)[0].split("+", 1)[0].lower()
    return "sqlite" if declared in _SQLITE else declared


def plan(config_path: str) -> Plan:
    """How a scratch test of this project would run, read from the config file alone."""
    try:
        data = _read(config_path)
    except ValueError as exc:
        return Plan("skip", "", str(exc), "")
    engine = _engine(_section(data, None) or {})
    if engine == "sqlite":
        return Plan(
            "file",
            "sqlite",
            "A temporary SQLite database is created, used and deleted. "
            "Your databases are not touched.",
            "",
        )
    if SCRATCH in (data.get("environments") or {}):
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
# ("text", placeholder text) when an unset variable hides it, or ("memory",) for an
# in-memory database, which never shares anything with another one.
_Where = Tuple[Any, ...]


def _file(path: str, folder: Path) -> Optional[_Where]:
    if not path:
        return None
    if path == ":memory:" or path.startswith("file::memory:"):
        return ("memory",)
    if "${" in path:
        return ("text", path)
    found = Path(path).expanduser()
    return ("file", os.path.realpath(found if found.is_absolute() else folder / found))


def _server(host: str, port: Any, name: str, schema: str) -> Optional[_Where]:
    host, name = host.lower(), name.lower()
    if not host and not name:
        return None
    if isinstance(port, str) and port.strip().isdigit():
        port = int(port)
    port = port if isinstance(port, int) or (isinstance(port, str) and port) else None
    # No host means the local server to the drivers.
    host = "localhost" if not host or host in _LOOPBACK else host
    return ("server", f"{host}/{name}", port, schema.lower())


def _identity(database: Dict[str, Any], folder: Path) -> Optional[_Where]:
    """Where *database* lives, credentials left out; None when that cannot be told.

    Relative file paths resolve from *folder*, the config's folder, as the engine does.
    """

    def text(key: str) -> str:
        value = database.get(key)
        return "" if value is None or isinstance(value, (dict, list)) else str(value).strip()

    url, engine = text("url"), _engine(database)
    if url:
        if "://" not in url:
            return ("text", url) if "${" in url else None
        try:
            parts = urlsplit(url)
        except ValueError:
            return ("text", url) if "${" in url else None
        try:
            port: Any = parts.port
        except ValueError:  # a placeholder, say: compared as its text
            port = parts.netloc.rpartition("@")[2].rpartition(":")[2]
        if engine in _FILES:
            # SQLAlchemy's reading: three slashes start a relative path, four an absolute one.
            return _file(parts.path[1:] if parts.path.startswith("/") else parts.path, folder)
        query = parse_qs(parts.query)
        name = parts.path.strip("/").split("/")[0] or (query.get("service_name") or [""])[0]
        schema = text("schema") or (query.get("schema") or [""])[0]
        return _server(parts.hostname or "", port, name, schema)
    if engine in _FILES:
        return _file(text("path") or text("database"), folder)
    if not engine:
        return None
    return _server(
        text("host") or text("account"),
        database.get("port"),
        text("database") or text("service_name"),
        text("schema"),
    )


def _resolved(database: Any) -> Dict[str, Any]:
    """The identity keys of a database section the loader has resolved."""
    return {
        key: getattr(database, key, None)
        for key in ("type", "host", "port", "database", "path", "schema")
    }


def _same(a: _Where, b: _Where) -> bool:
    """Whether *a* and *b* may be one database; a missing port or schema matches any."""
    if a[0] == "memory" or a[:2] != b[:2]:
        return False
    if a[0] != "server":
        return True
    ports = a[2] is None or b[2] is None or a[2] == b[2]
    schemas = not a[3] or not b[3] or a[3] == b[3]
    return ports and schemas


def same_database(config_path: str) -> Optional[str]:
    """The environment (``default`` for the root) sharing the scratch environment's database.

    Read from the config file alone: no client, no secrets, no connection. An environment
    that cannot be read is left out; NotChecked when the scratch environment itself cannot
    be identified, in which case the test must not run.
    """
    try:
        data = _read(config_path)
    except ValueError as exc:
        raise NotChecked(f"The test was not run: {exc}.") from exc
    environments = data.get("environments") or {}
    if SCRATCH not in environments:
        raise NotChecked("The config has no environment named scratch.")
    folder = Path(config_path).resolve().parent
    scratch = _section(data, SCRATCH)
    target = _identity(scratch, folder) if scratch is not None else None
    if target is None:
        raise NotChecked(UNIDENTIFIED)
    for name in [None, *(n for n in environments if n != SCRATCH)]:
        section = _section(data, name)
        where = _identity(section, folder) if section is not None else None
        if where is not None and _same(target, where):
            return "default" if name is None else str(name)
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
    found = plan(config_path)
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

    def shared_with(name: str) -> Tuple[Optional[bool], str]:
        return (
            False,
            f"The scratch environment points at the same database as {name}. {NOTHING_DONE}",
        )

    def clean() -> Tuple[Optional[bool], str]:
        try:
            shared = same_database(config_path)
        except NotChecked as exc:
            return False, f"{exc} {NOTHING_DONE}"
        if shared is not None:
            return shared_with(shared)
        # A last check that needs no other environment: what the loader resolved for
        # scratch must not be the root's database, whatever the file comparison said.
        folder = Path(config_path).resolve().parent
        resolved = _identity(_resolved(client().config.database), folder)
        if resolved is None:
            return False, f"{UNIDENTIFIED} {NOTHING_DONE}"
        try:
            root = _identity(_section(_read(config_path), None) or {}, folder)
        except ValueError as exc:
            return False, f"The test was not run: {exc}. {NOTHING_DONE}"
        if root is not None and _same(resolved, root):
            return shared_with("default")
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
