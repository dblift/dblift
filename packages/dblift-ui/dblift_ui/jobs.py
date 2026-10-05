"""Run a client operation in a worker thread and expose what happens as events."""

import re
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, List, Optional

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
# The password of a ``scheme://user:password@host`` URL: everything after the
# user's colon up to the last ``@`` before the path, so a password containing
# ``@`` is masked whole.
_URL_PASSWORD = re.compile(r"([A-Za-z][\w+.-]*://[^:/@\s]*:)[^\s/]*@")
_PASSWORD_PARAMETER = re.compile(r"(password|pwd)=[^&;\s]*", re.IGNORECASE)
MUTATING = frozenset({"migrate", "undo", "repair", "baseline"})
_VERSION = re.compile(r"^\d+(\.\d+)*$")


def redact(text: str) -> str:
    """Mask passwords that engine error messages may echo back."""
    text = _URL_PASSWORD.sub(r"\1***@", text)
    return _PASSWORD_PARAMETER.sub(r"\1=***", text)


def check_params(command: str, params: Dict[str, Any]) -> None:
    """Refuse parameters a command cannot run with, before any thread starts."""
    if command == "baseline":
        version = str(params.get("version") or "").strip()
        if not _VERSION.match(version):
            raise ValueError("baseline needs a version made of numbers and dots, like 1.4.0")


def _baseline(client: DBLiftClient, params: Dict[str, Any]) -> Any:
    description = str(params.get("description") or "").strip() or None
    return client.baseline(version=str(params["version"]).strip(), description=description)


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

    def publish(self, payload: Dict[str, Any]) -> None:
        with self.changed:
            self.events.append(payload)
            self.changed.notify_all()


class JobRunner:
    COMMANDS: Dict[str, Callable[[DBLiftClient, Dict[str, Any]], Any]] = {
        "info": lambda client, params: client.info(),
        "validate": lambda client, params: client.validate(),
        "preview": lambda client, params: client.migrate(dry_run=True, show_sql=True),
        "migrate": lambda client, params: client.migrate(),
        "undo": lambda client, params: client.undo(),
        "repair": lambda client, params: client.repair(),
        "baseline": _baseline,
    }

    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry
        self._jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._lock = threading.Lock()

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
        with self._lock:
            self._jobs[job.id] = job
            while len(self._jobs) > _KEPT_JOBS:
                self._jobs.popitem(last=False)
        threading.Thread(
            target=self._run, args=(job, project, environment or None), daemon=True
        ).start()
        return job

    def stream(self, job_id: str) -> Iterator[Dict[str, Any]]:
        with self._lock:
            job = self._jobs[job_id]
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
        try:
            with DBLiftClient.from_config_file(
                project.config_path, environment=environment, relative_to_config=True
            ) as client:
                client.events.on("*", lambda event: job.publish(serialize_event(event)))
                result = serialize_result(self.COMMANDS[job.command](client, job.params))
        except Exception as exc:  # the browser must always receive a final event
            result = {
                "success": False,
                "error": redact(str(exc)),
                "current_version": None,
                "repaired": None,
                "baseline_version": None,
                "sql": [],
                "migrations": [],
            }
        job.publish({"event": FINISHED, "result": result})
