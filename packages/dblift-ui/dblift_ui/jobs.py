"""Run a client operation in a worker thread and expose what happens as events."""

import queue
import threading
import uuid
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterator, Optional

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


def serialize_event(event: Any) -> Dict[str, Any]:
    payload: Dict[str, Any] = {"event": event.event_type.value, "timestamp": event.timestamp}
    for name in EVENT_FIELDS:
        value = getattr(event, name, None)
        if value is not None:
            payload[name] = value
    return payload


def serialize_result(result: Any) -> Dict[str, Any]:
    return {
        "success": bool(result.success),
        "error": result.error_message or None,
        "current_version": getattr(result, "current_schema_version", None),
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
    events: "queue.Queue[Dict[str, Any]]" = field(default_factory=queue.Queue)


class JobRunner:
    COMMANDS: Dict[str, Callable[[DBLiftClient], Any]] = {
        "info": lambda client: client.info(),
    }

    def __init__(self, registry: ProjectRegistry) -> None:
        self._registry = registry
        self._jobs: "OrderedDict[str, Job]" = OrderedDict()
        self._lock = threading.Lock()

    def start(self, project_id: str, command: str, environment: str = "") -> Job:
        project = self._registry.get(project_id)
        if command not in self.COMMANDS:
            raise ValueError(f"unknown command: {command}")
        job = Job(id=uuid.uuid4().hex, project_id=project_id, command=command)
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
        while True:
            event = job.events.get()
            yield event
            if event["event"] == FINISHED:
                return

    def _run(self, job: Job, project: Project, environment: Optional[str]) -> None:
        try:
            with DBLiftClient.from_config_file(
                project.config_path, environment=environment, relative_to_config=True
            ) as client:
                client.events.on("*", lambda event: job.events.put(serialize_event(event)))
                result = serialize_result(self.COMMANDS[job.command](client))
        except Exception as exc:  # the browser must always receive a final event
            result = {
                "success": False,
                "error": str(exc),
                "current_version": None,
                "migrations": [],
            }
        job.events.put({"event": FINISHED, "result": result})
