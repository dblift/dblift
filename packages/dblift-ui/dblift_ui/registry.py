"""Registry of projects known to the interface, kept in one versioned JSON file."""

import json
import os
import uuid
from dataclasses import asdict, dataclass, replace
from pathlib import Path
from typing import List

import platformdirs

SCHEMA_VERSION = 1
HOME_ENV_VAR = "DBLIFT_UI_HOME"
_CONFIG_SUFFIXES = (".yaml", ".yml")


class RegistryError(Exception):
    """The registry file or a requested change is not acceptable."""


class RegistryFileError(RegistryError):
    """The registry file itself cannot be read."""


@dataclass(frozen=True)
class Project:
    id: str
    name: str
    config_path: str
    last_environment: str = ""


class ProjectRegistry:
    """Projects are identified by an opaque id; the file never holds credentials."""

    def __init__(self, path: Path) -> None:
        self.path = Path(path)

    @classmethod
    def default(cls) -> "ProjectRegistry":
        home = os.environ.get(HOME_ENV_VAR) or platformdirs.user_config_dir("dblift-ui")
        return cls(Path(home) / "projects.json")

    def list(self) -> List[Project]:
        if not self.path.exists():
            return []
        try:
            data = json.loads(self.path.read_text())
        except json.JSONDecodeError as exc:
            raise self._invalid(f"not JSON ({exc})") from exc
        if not isinstance(data, dict):
            raise self._invalid("not a JSON object")
        version = data.get("schema_version", 0)
        if not isinstance(version, int):
            raise self._invalid(f"schema_version {version!r} is not an integer")
        if version > SCHEMA_VERSION:
            raise RegistryFileError(
                f"{self.path} was written by a newer version of dblift-ui "
                f"(schema {version}, this version reads up to {SCHEMA_VERSION})"
            )
        entries = data.get("projects", [])
        if not isinstance(entries, list):
            raise self._invalid("projects is not a list")
        try:
            return [Project(**entry) for entry in entries]
        except TypeError as exc:
            raise self._invalid(f"bad project entry ({exc})") from exc

    def add(self, name: str, config_path: str) -> Project:
        resolved = Path(config_path).expanduser().resolve()
        if resolved.suffix not in _CONFIG_SUFFIXES:
            raise RegistryError("config file must be a .yaml or .yml file")
        if not resolved.is_file():
            raise RegistryError(f"config file not found: {resolved}")
        if not name.strip():
            raise RegistryError("project name is required")
        projects = self.list()
        if any(p.config_path == str(resolved) for p in projects):
            raise RegistryError(f"{resolved} is already a project")
        project = Project(id=uuid.uuid4().hex[:12], name=name.strip(), config_path=str(resolved))
        self._write([*projects, project])
        return project

    def get(self, project_id: str) -> Project:
        for project in self.list():
            if project.id == project_id:
                return project
        raise KeyError(project_id)

    def remove(self, project_id: str) -> None:
        self.get(project_id)
        self._write([p for p in self.list() if p.id != project_id])

    def set_environment(self, project_id: str, environment: str) -> Project:
        updated = replace(self.get(project_id), last_environment=environment)
        self._write([updated if p.id == project_id else p for p in self.list()])
        return updated

    def _invalid(self, reason: str) -> RegistryFileError:
        return RegistryFileError(f"{self.path} is not a valid registry file: {reason}")

    def _write(self, projects: List[Project]) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"schema_version": SCHEMA_VERSION, "projects": [asdict(p) for p in projects]}
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(payload, indent=2))
        os.replace(temporary, self.path)
