"""Run a client operation in a worker thread and expose what happens as events."""

import re
import shutil
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, Iterator, List, Optional

from dblift_ui.flyway import TABLE_NAME
from dblift_ui.masking import redact
from dblift_ui.registry import Project, ProjectRegistry

from dblift.api import DBLiftClient

# Scalar attributes of a client event that may be sent to the browser. Events
# also carry the config, provider and result objects; those hold credentials
# and must never be serialised.
EVENT_FIELDS = (
    "operation",
    "script",
    "version",
    "description",
    "type",
    "execution_time",
    "error",
    "count",
    "dry_run",
)
FINISHED = "job.finished"
_KEPT_JOBS = 50
MUTATING = frozenset({"migrate", "undo", "repair", "baseline", "flyway_import"})
_VERSION = re.compile(r"^\d+(\.\d+)*$")
# The most of a run's text log the browser receives: its last characters.
LOG_LIMIT = 200_000


class ProjectBusy(Exception):
    """A change is already running on this project."""


def read_log(folder: Path) -> str:
    """The engine's text log for one job: redacted, and only its tail when very long."""
    parts = []
    for path in sorted(folder.glob("*.log")):
        try:
            parts.append(path.read_text(encoding="utf-8", errors="replace"))
        except OSError:
            continue
    return redact("".join(parts))[-LOG_LIMIT:]


def check_params(command: str, params: Dict[str, Any]) -> None:
    """Refuse parameters a command cannot run with, before any thread starts."""
    if command == "baseline":
        version = str(params.get("version") or "").strip()
        if not _VERSION.match(version):
            raise ValueError("baseline needs a version made of numbers and dots, like 1.4.0")
    if command in ("flyway_preview", "flyway_import"):
        if not TABLE_NAME.match(str(params.get("table") or "")):
            raise ValueError("the history table name must be a plain identifier")


def _baseline(client: DBLiftClient, params: Dict[str, Any]) -> Any:
    description = str(params.get("description") or "").strip() or None
    return client.baseline(version=str(params["version"]).strip(), description=description)


def _flyway(dry_run: bool) -> Callable[[DBLiftClient, Dict[str, Any]], Any]:
    return lambda client, params: client.import_flyway(
        dry_run=dry_run, flyway_table=str(params["table"])
    )


def serialize_event(event: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": event.event_type.value, "timestamp": event.timestamp}
    for name in EVENT_FIELDS:
        value = getattr(event, name, None)
        if value is not None:
            payload[name] = redact(value) if name == "error" else value
    return payload


def serialize_result(result: Any) -> Dict[str, Any]:
    return {
        "success": bool(result.success),
        "error": redact(result.error_message) if result.error_message else None,
        "message": redact(message) if (message := getattr(result, "message", None)) else None,
        "current_version": getattr(result, "current_schema_version", None),
        "repaired": getattr(result, "failed_migrations_removed", None),
        "baseline_version": getattr(result, "baseline_version", None),
        "sql": [
            {"script": entry.script, "statements": [str(s) for s in entry.statements]}
            for entry in (getattr(result, "sql", None) or [])
        ],
        "migrations": [
            {
                "script": m.script,
                "version": str(m.version or ""),
                "description": m.description,
                "type": m.type,
                "status": str(m.status).upper(),
                "installed_on": str(m.installed_on or ""),
                "installed_by": m.installed_by or "",
                "execution_time": m.execution_time,
            }
            for m in getattr(result, "migrations", [])
        ],
    }


@dataclass
class Job:
    id: str
    project_id: str
    command: str
    params: Dict[str, Any] = field(default_factory=dict)
    # Every event the job has produced, in order, so any number of readers can
    # replay it from the start; ``changed`` is notified on each append.
    events: List[Dict[str, Any]] = field(default_factory=list)
    changed: threading.Condition = field(default_factory=threading.Condition)
    done: threading.Event = field(default_factory=threading.Event)
    log_text: str = ""

    def publish(self, payload: Dict[str, Any]) -> None:
        with self.changed:
            self.events.append(payload)
            self.changed.notify_all()
        if payload["event"] == FINISHED:
            self.done.set()


class JobRunner:
    COMMANDS: Dict[str, Callable[[DBLiftClient, Dict[str, Any]], Any]] = {
        "info": lambda client, params: client.info(),
        "validate": lambda client, params: client.validate(),
        "preview": lambda client, params: client.migrate(dry_run=True, show_sql=True),
        "migrate": lambda client, params: client.migrate(),
        "undo": lambda client, params: client.undo(),
        "repair": lambda client, params: client.repair(),
        "baseline": _baseline,
        "flyway_preview": _flyway(True),
        "flyway_import": _flyway(False),
    }

    def __init__(self, registry: ProjectRegistry, runs_dir: Optional[Path] = None) -> None:
        self._registry = registry
        # Each job's engine log goes to its own folder here, never into the project.
        self._runs = Path(runs_dir) if runs_dir is not None else registry.path.parent / "runs"
        self._jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._lock = threading.Lock()
        self._changing: Dict[str, Job] = {}
        self._threads: Dict[str, threading.Thread] = {}

    def start(
        self,
        project_id: str,
        command: str,
        environment: str = "",
        params: Optional[Dict[str, Any]] = None,
    ) -> Job:
        project = self._registry.get(project_id)
        if command not in self.COMMANDS:
            raise ValueError(f"unknown command: {command}")
        params = dict(params or {})
        check_params(command, params)
        job = Job(id=uuid.uuid4().hex, project_id=project_id, command=command, params=params)
        mutating = command in MUTATING
        # A change must never be cut off by the process exiting: not a daemon.
        thread = threading.Thread(
            target=self._run, args=(job, project, environment or None), daemon=not mutating
        )
        with self._lock:
            if mutating:
                if project_id in self._changing:
                    raise ProjectBusy(project_id)
                self._changing[project_id] = job
                # Registered and started under the lock, so ``drain`` never
                # misses a change nor joins a thread that has not started.
                self._threads[job.id] = thread
            self._jobs[job.id] = job
            finished = [key for key, known in self._jobs.items() if known.done.is_set()]
            for key in finished[: max(0, len(self._jobs) - _KEPT_JOBS)]:
                del self._jobs[key]
            thread.start()
        return job

    def get(self, job_id: str) -> Job:
        with self._lock:
            return self._jobs[job_id]

    def is_changing(self, project_id: str) -> bool:
        with self._lock:
            return project_id in self._changing

    def drain(self) -> int:
        """Wait for every running change to finish; return how many there were."""
        with self._lock:
            running = list(self._threads.values())
        for thread in running:
            thread.join()
        return len(running)

    def stream(self, job_id: str) -> Iterator[Dict[str, Any]]:
        job = self.get(job_id)
        index = 0
        while True:
            with job.changed:
                job.changed.wait_for(lambda: len(job.events) > index)
                event = job.events[index]
            index += 1
            yield event
            if event["event"] == FINISHED:
                return

    def _run(self, job: Job, project: Project, environment: Optional[str]) -> None:
        folder = self._runs / job.id
        try:
            try:
                with DBLiftClient.from_config_file(
                    project.config_path,
                    environment=environment,
                    relative_to_config=True,
                    log_dir=str(folder),
                ) as client:
                    client.events.on("*", lambda event: job.publish(serialize_event(event)))
                    result = serialize_result(self.COMMANDS[job.command](client, job.params))
            except BaseException as exc:  # the browser must always receive a final event
                failure = {
                    "success": False,
                    "error": redact(str(exc) or type(exc).__name__),
                    "message": None,
                    "current_version": None,
                    "repaired": None,
                    "baseline_version": None,
                    "sql": [],
                    "migrations": [],
                }
                self._finish(job, failure, folder)
                # An ordinary failure is fully reported by the final event and a worker
                # thread has nobody to re-raise to; SystemExit/KeyboardInterrupt still reach
                # the interpreter, harmlessly: in a thread they end only that thread.
                if not isinstance(exc, Exception):
                    raise
            else:
                self._finish(job, result, folder)
        finally:
            shutil.rmtree(folder, ignore_errors=True)
            # Released only once the last event exists, whatever happened above.
            with self._lock:
                if self._changing.get(job.project_id) is job:
                    del self._changing[job.project_id]
                self._threads.pop(job.id, None)

    @staticmethod
    def _finish(job: Job, result: Dict[str, Any], folder: Path) -> None:
        """Keep the run's log on the job, remove its folder, then publish the final event."""
        job.log_text = read_log(folder) if folder.is_dir() else ""
        # Removed before the final event, so whoever sees the job finished finds no folder.
        shutil.rmtree(folder, ignore_errors=True)
        job.publish(
            {
                "event": FINISHED,
                "result": {**result, "job_id": job.id, "has_log": bool(job.log_text)},
            }
        )
