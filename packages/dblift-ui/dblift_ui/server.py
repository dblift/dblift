"""HTTP application: security guard and route wiring."""

import json
import os
import secrets
import shutil
import threading
from contextlib import asynccontextmanager, contextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional, Set

import yaml
from dblift_ui import __version__, configs, flyway, gitops, scratch
from dblift_ui.clone import CloneError, clone
from dblift_ui.discovery import DiscoveryError, discover
from dblift_ui.jobs import MUTATING, Job, JobRunner, ProjectBusy
from dblift_ui.registry import (
    Project,
    ProjectRegistry,
    RegistryError,
    RegistryFileError,
)
from dblift_ui.scripts import ScriptError, ScriptNotFound, ScriptStore, yaml_problem
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, PlainTextResponse, StreamingResponse
from pydantic import BaseModel

TOKEN_HEADER = "X-DBLift-Token"
STATIC_DIR = Path(__file__).resolve().parent / "static"
APP_DIR = STATIC_DIR / "app"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class NewProject(BaseModel):
    name: str = ""
    config_path: str = ""


class NewJob(BaseModel):
    command: str
    environment: str = ""
    params: Dict[str, Any] = {}


class ProjectPatch(BaseModel):
    last_environment: str = ""


class ScriptContent(BaseModel):
    content: str


class NewScripts(BaseModel):
    kind: str = "versioned"
    language: str = "sql"
    description: str = ""


class DiscoverRequest(BaseModel):
    path: str = ""


class CloneRequest(BaseModel):
    url: str = ""
    parent: str = ""


class ConfigPreview(BaseModel):
    form: configs.ConfigForm
    project_id: str = ""


class NewConfig(BaseModel):
    folder: str = ""
    filename: str = "dblift.yaml"
    name: str = ""
    form: configs.ConfigForm


class ConfigUpdate(BaseModel):
    form: configs.ConfigForm
    revision: str = ""


class FlywayRead(BaseModel):
    root: str = ""
    path: str = ""


class BranchName(BaseModel):
    name: str = ""


class GitCommit(BaseModel):
    paths: List[str] = []
    message: str = ""


def engine_of(data: Dict[str, Any]) -> str:
    """The engine a config declares: its ``database.type``, else its URL scheme."""
    database = data.get("database")
    if not isinstance(database, dict):
        return ""
    declared = database.get("type")
    if isinstance(declared, str) and declared:
        return declared
    url = database.get("url")
    if isinstance(url, str) and "://" in url:
        return url.split("://", 1)[0].split("+", 1)[0]
    return ""


def repository_of(config: Path) -> Path:
    """The git repository that holds *config*, else the config's own folder."""
    for folder in config.parents:
        if (folder / ".git").exists():
            return folder
    return config.parent


def describe(project: Project) -> Dict[str, Any]:
    """A project as the browser sees it: registry fields plus what its config declares."""
    environments: List[str] = []
    engine = ""
    error: Optional[str] = None
    config = Path(project.config_path)
    missing = not config.is_file()
    home = repository_of(config)
    if missing:
        error = "This config file is not in the folder right now. It may be on another branch."
    else:
        try:
            data = yaml.safe_load(config.read_text()) or {}
            if not isinstance(data, dict):
                error = "config is not a mapping"
            elif not isinstance(data.get("environments") or {}, dict):
                error = "environments is not a mapping"
                engine = engine_of(data)
            else:
                environments = list((data.get("environments") or {}).keys())
                engine = engine_of(data)
        except yaml.YAMLError as exc:
            error = yaml_problem(exc)
        except OSError as exc:
            error = str(exc)
    return {
        **asdict(project),
        "environments": environments,
        "engine": engine,
        "error": error,
        "missing": missing,
        "repository": home.name,
        "repository_path": str(home),
        "flyway_table": None if missing else flyway.table_beside(project.config_path),
    }


class RepositoryGuard:
    """The one place that decides whether a database change or a git verb may start.

    Both decisions are taken under one lock, so a job and a git verb starting at the
    same instant never both pass. Git verbs on one repository also run one at a time.
    """

    # Jobs that read the scripts while a git verb could be rewriting them.
    _JOBS_READING_SCRIPTS = MUTATING | {"preview"}

    def __init__(self, runner: JobRunner, projects: ProjectRegistry) -> None:
        self._runner = runner
        self._projects = projects
        self._lock = threading.Lock()
        self._serial: Dict[Path, threading.Lock] = {}
        self._rewriting: Set[Path] = set()

    def start_job(self, project: Project, command: str, start: Callable[[], Job]) -> Job:
        """Run *start* unless a git verb is rewriting the files of *project*'s repository."""
        if command not in self._JOBS_READING_SCRIPTS:
            return start()
        with self._lock:
            if repository_of(Path(project.config_path)) in self._rewriting:
                raise HTTPException(
                    status_code=409,
                    detail="A git operation is running on this repository. Wait for it to finish.",
                )
            return start()

    @contextmanager
    def git_verb(self, root: Path, rewrites_files: bool) -> Iterator[None]:
        """Hold *root* for one git verb; refused while a database change runs in it."""
        with self._lock:
            serial = self._serial.setdefault(root, threading.Lock())
        with serial:
            if rewrites_files:
                with self._lock:
                    if any(
                        self._runner.is_changing(p.id)
                        for p in self._projects.list()
                        if repository_of(Path(p.config_path)) == root
                    ):
                        raise HTTPException(
                            status_code=409,
                            detail="A change is running on a project of this repository. "
                            "Try again once it has finished.",
                        )
                    self._rewriting.add(root)
            try:
                yield
            finally:
                if rewrites_files:
                    with self._lock:
                        self._rewriting.discard(root)


def create_app(
    token: str,
    port: int,
    registry: Optional[ProjectRegistry] = None,
    app_dir: Optional[Path] = None,
) -> FastAPI:
    """Build the application for one launch.

    *token* is the per-launch secret every ``/api/`` call must present.
    *port* is the port the server listens on; requests whose ``Host`` header
    names anything else are refused, which blocks DNS rebinding.
    *registry* defaults to the per-user registry file.
    *app_dir* is the folder holding the built interface; it defaults to the
    one shipped inside the package.
    """
    projects = registry or ProjectRegistry.default()
    runner = JobRunner(projects)
    repositories = RepositoryGuard(runner, projects)

    @asynccontextmanager
    async def lifespan(_: FastAPI) -> AsyncIterator[None]:
        yield
        # A migration in flight is finished, never dropped, when the server stops.
        await run_in_threadpool(runner.drain)

    app = FastAPI(
        title="DBLift UI", docs_url=None, redoc_url=None, openapi_url=None, lifespan=lifespan
    )
    app.state.runner = runner
    built = Path(app_dir) if app_dir is not None else APP_DIR
    assets = (built / "assets").resolve()
    hosts = frozenset({f"127.0.0.1:{port}", f"localhost:{port}"})
    origins = frozenset(f"http://{host}" for host in hosts)

    @app.middleware("http")
    async def guard(
        request: Request, call_next: Callable[[Request], Awaitable[Response]]
    ) -> Response:
        if request.headers.get("host") not in hosts:
            return JSONResponse({"detail": "forbidden host"}, status_code=403)
        if request.method not in _SAFE_METHODS:
            origin = request.headers.get("origin")
            if origin is not None and origin not in origins:
                return JSONResponse({"detail": "forbidden origin"}, status_code=403)
        if request.url.path.startswith("/api/"):
            supplied = request.headers.get(TOKEN_HEADER, "")
            if not secrets.compare_digest(supplied.encode(), token.encode()):
                return JSONResponse({"detail": "invalid token"}, status_code=401)
        return await call_next(request)

    @app.exception_handler(RegistryFileError)
    async def registry_file_error(request: Request, exc: RegistryFileError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=500)

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/api/projects")
    def list_projects() -> List[Dict[str, Any]]:
        return [describe(project) for project in projects.list()]

    @app.post("/api/projects", status_code=201)
    def add_project(body: NewProject) -> Dict[str, Any]:
        try:
            return describe(projects.add(body.name, body.config_path))
        except RegistryFileError:
            raise
        except RegistryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.delete("/api/projects/{project_id}", status_code=204)
    def remove_project(project_id: str) -> Response:
        try:
            projects.remove(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown project") from exc
        return Response(status_code=204)

    @app.patch("/api/projects/{project_id}")
    def patch_project(project_id: str, body: ProjectPatch) -> Dict[str, Any]:
        try:
            return describe(projects.set_environment(project_id, body.last_environment))
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown project") from exc

    @app.get("/api/defaults")
    def defaults() -> Dict[str, Any]:
        return {
            "clone_parent": str(Path.home() / "dblift-projects"),
            "git": shutil.which("git") is not None,
        }

    @app.post("/api/discover")
    def discover_folder(body: DiscoverRequest) -> Dict[str, Any]:
        try:
            return asdict(discover(body.path, registered=[p.config_path for p in projects.list()]))
        except DiscoveryError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/clone")
    def clone_repository(body: CloneRequest) -> Dict[str, str]:
        try:
            return {"path": str(clone(body.url, body.parent))}
        except CloneError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    @app.post("/api/flyway/read")
    def flyway_read(body: FlywayRead) -> Dict[str, Any]:
        try:
            found = flyway.read_project(body.root, body.path)
        except flyway.FlywayError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "folder": found.folder,
            "form": found.form.model_dump(by_alias=True),
            "table": found.table,
            "notes": found.notes,
        }

    @app.post("/api/projects/{project_id}/jobs", status_code=202)
    def start_job(project_id: str, body: NewJob) -> Dict[str, str]:
        try:
            job = repositories.start_job(
                projects.get(project_id),
                body.command,
                lambda: runner.start(project_id, body.command, body.environment, body.params),
            )
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown project") from exc
        except ProjectBusy as exc:
            raise HTTPException(
                status_code=409,
                detail="Another change is running on this project. Wait for it to finish.",
            ) from exc
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {"job_id": job.id}

    @app.get("/api/jobs/{job_id}/events")
    def job_events(job_id: str) -> StreamingResponse:
        try:
            events = runner.stream(job_id)
            first = next(events)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown job") from exc

        def lines() -> Iterator[str]:
            yield f"data: {json.dumps(first)}\n\n"
            for event in events:
                yield f"data: {json.dumps(event)}\n\n"

        return StreamingResponse(
            lines(), media_type="text/event-stream", headers={"Cache-Control": "no-store"}
        )

    @app.get("/api/jobs/{job_id}/log")
    def job_log(job_id: str) -> PlainTextResponse:
        try:
            text = runner.get(job_id).log_text
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown job") from exc
        if not text:
            raise HTTPException(status_code=404, detail="this job has no log")
        return PlainTextResponse(text, headers={"Cache-Control": "no-store"})

    def project_of(project_id: str) -> Project:
        try:
            return projects.get(project_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="unknown project") from exc

    def store_of(project_id: str) -> ScriptStore:
        return ScriptStore(project_of(project_id).config_path)

    def refuse_during_change(project_id: str) -> None:
        if runner.is_changing(project_id):
            raise HTTPException(
                status_code=409,
                detail="A change is running on this project. Save once it has finished.",
            )

    @app.get("/api/projects/{project_id}/scratch")
    def scratch_plan(project_id: str) -> Dict[str, Any]:
        return asdict(scratch.plan(project_of(project_id).config_path))

    # Starlette picks the handler of the closest class, so a missing script is a 404.
    @app.exception_handler(ScriptNotFound)
    async def script_not_found(request: Request, exc: ScriptNotFound) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=404)

    @app.exception_handler(ScriptError)
    async def script_error(request: Request, exc: ScriptError) -> JSONResponse:
        return JSONResponse({"detail": str(exc)}, status_code=400)

    @app.get("/api/projects/{project_id}/scripts")
    def list_scripts(project_id: str) -> List[Dict[str, Any]]:
        project = project_of(project_id)
        store = ScriptStore(project.config_path)
        scripts = store.list()
        home = repository_of(Path(project.config_path))
        inside = gitops.is_repository(home)
        changes: Dict[str, str] = {}
        if inside:
            try:
                changes = {f.path: f.state for f in gitops.status(home).files}
            except gitops.GitError:
                changes = {}  # the list still shows; only the marks are missing
        top = home.resolve()
        undos = store.undo_paths()

        def in_repository(path: Optional[Path]) -> str:
            """*path* relative to the repository's root, as git names it; "" when it has none."""
            if not inside or path is None:
                return ""
            relative = Path(os.path.relpath(path, top))
            return "" if relative.parts[:1] == ("..",) else relative.as_posix()

        listed = []
        for script in scripts:
            path = in_repository(store.path_of(script))
            undo_path = in_repository(undos.get(script.name)) if script.has_undo else ""
            listed.append(
                {
                    **asdict(script),
                    "path": path,
                    "change": changes.get(path, "") if path else "",
                    "undo_path": undo_path,
                    "undo_change": changes.get(undo_path, "") if undo_path else "",
                }
            )
        return listed

    @app.post("/api/projects/{project_id}/scripts", status_code=201)
    def create_scripts(project_id: str, body: NewScripts) -> Dict[str, List[str]]:
        store = store_of(project_id)
        refuse_during_change(project_id)
        return {"created": store.create(body.kind, body.language, body.description)}

    @app.get("/api/projects/{project_id}/scripts/{name}")
    def read_script(project_id: str, name: str) -> Dict[str, Any]:
        store = store_of(project_id)
        return {**asdict(store.describe(name)), "content": store.read(name)}

    @app.put("/api/projects/{project_id}/scripts/{name}")
    def write_script(project_id: str, name: str, body: ScriptContent) -> Dict[str, Any]:
        store = store_of(project_id)
        refuse_during_change(project_id)
        store.write(name, body.content)
        return asdict(store.describe(name))

    def repository(project_id: str) -> Path:
        root = repository_of(Path(project_of(project_id).config_path))
        if not gitops.is_repository(root):
            raise HTTPException(status_code=400, detail="This project is not in a git repository.")
        return root

    def git_call(verb: Callable[..., Any], *args: Any) -> Any:
        try:
            return verb(*args)
        except gitops.GitError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    def git_state(root: Path) -> Dict[str, Any]:
        return {"repository": True, "root": str(root), **asdict(git_call(gitops.status, root))}

    def git_change(
        project_id: str, verb: Callable[..., None], *args: Any, files: bool = True
    ) -> Dict[str, Any]:
        """Run *verb* on the project's repository; *files* when it rewrites the working tree."""
        root = repository(project_id)
        with repositories.git_verb(root, rewrites_files=files):
            git_call(verb, root, *args)
            return git_state(root)

    @app.get("/api/projects/{project_id}/scripts/{name}/diff")
    def script_diff(project_id: str, name: str) -> Dict[str, str]:
        store = store_of(project_id)
        path = store.path_of(store.describe(name))
        root = repository(project_id)
        relative = Path(os.path.relpath(path, root.resolve())).as_posix()
        return {"diff": git_call(gitops.diff, root, relative)}

    @app.get("/api/projects/{project_id}/git")
    def git_status(project_id: str) -> Dict[str, Any]:
        root = repository_of(Path(project_of(project_id).config_path))
        if not gitops.is_repository(root):
            return {"repository": False}
        return git_state(root)

    @app.get("/api/projects/{project_id}/git/branches")
    def git_branches(project_id: str) -> List[Dict[str, Any]]:
        return [asdict(b) for b in git_call(gitops.branches, repository(project_id))]

    @app.post("/api/projects/{project_id}/git/switch")
    def git_switch(project_id: str, body: BranchName) -> Dict[str, Any]:
        return git_change(project_id, gitops.switch, body.name)

    @app.post("/api/projects/{project_id}/git/create")
    def git_create(project_id: str, body: BranchName) -> Dict[str, Any]:
        return git_change(project_id, gitops.create, body.name)

    @app.post("/api/projects/{project_id}/git/fetch")
    def git_fetch(project_id: str) -> Dict[str, Any]:
        return git_change(project_id, gitops.fetch, files=False)

    @app.post("/api/projects/{project_id}/git/pull")
    def git_pull(project_id: str) -> Dict[str, Any]:
        return git_change(project_id, gitops.pull)

    @app.post("/api/projects/{project_id}/git/push")
    def git_push(project_id: str) -> Dict[str, Any]:
        return git_change(project_id, gitops.push, files=False)

    @app.post("/api/projects/{project_id}/git/commit")
    def git_commit(project_id: str, body: GitCommit) -> Dict[str, Any]:
        return git_change(project_id, gitops.commit, body.paths, body.message)

    def config_text(project_id: str) -> str:
        try:
            return Path(project_of(project_id).config_path).read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError) as exc:
            reason = getattr(exc, "strerror", None) or "the config cannot be read"
            raise HTTPException(status_code=400, detail=reason) from exc

    @app.get("/api/config/engines")
    def config_engines() -> List[Dict[str, Any]]:
        return [asdict(engine) for engine in configs.ENGINES]

    @app.post("/api/config/preview")
    def config_preview(body: ConfigPreview) -> Dict[str, Any]:
        existing = config_text(body.project_id) if body.project_id else None
        try:
            text = configs.render(body.form, existing)
            masked = configs.render(body.form, existing, mask=True)
        except configs.ConfigError as exc:
            return {"yaml": "", "problems": [str(exc)], "warnings": []}
        verdict = configs.check(text, [e.name for e in body.form.environments])
        return {"yaml": masked, "problems": verdict.problems, "warnings": verdict.warnings}

    @app.post("/api/config", status_code=201)
    def config_create(body: NewConfig) -> Dict[str, Any]:
        try:
            path = configs.create_file(body.folder, body.filename, body.form)
        except configs.ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        try:
            return describe(projects.add(body.name.strip() or path.parent.name, str(path)))
        except RegistryError as exc:
            # Reported like POST /api/projects; the new file stays where it was written.
            raise HTTPException(
                status_code=500 if isinstance(exc, RegistryFileError) else 400,
                detail=f"the file was written but the project could not be added: {exc}",
            ) from exc

    @app.get("/api/projects/{project_id}/config")
    def config_read(project_id: str) -> Dict[str, Any]:
        text = config_text(project_id)
        try:
            form, notes = configs.read_form(text)
        except configs.ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return {
            "form": form.model_dump(by_alias=True),
            "revision": configs.revision(text),
            "notes": notes,
        }

    @app.put("/api/projects/{project_id}/config")
    def config_update(project_id: str, body: ConfigUpdate) -> Dict[str, Any]:
        project = project_of(project_id)
        refuse_during_change(project_id)
        try:
            configs.update_file(project.config_path, body.form, body.revision)
        except configs.StaleConfig as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        except configs.ConfigError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return describe(project)

    @app.get("/assets/{asset_path:path}")
    def asset(asset_path: str) -> FileResponse:
        try:
            target = (assets / asset_path).resolve()
            servable = assets in target.parents and target.is_file()
        except (ValueError, OSError):
            servable = False
        if not servable:
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(target)

    @app.get("/")
    def index() -> FileResponse:
        page = built / "index.html"
        return FileResponse(page if page.is_file() else STATIC_DIR / "index.html")

    return app
