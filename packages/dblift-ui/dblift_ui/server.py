"""HTTP application: security guard and route wiring."""

import json
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict
from pathlib import Path
from typing import Any, AsyncIterator, Awaitable, Callable, Dict, Iterator, List, Optional

import yaml
from dblift_ui import __version__
from dblift_ui.jobs import JobRunner, ProjectBusy
from dblift_ui.registry import (
    Project,
    ProjectRegistry,
    RegistryError,
    RegistryFileError,
)
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
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


def describe(project: Project) -> Dict[str, Any]:
    """A project as the browser sees it: registry fields plus what its config declares."""
    environments: List[str] = []
    engine = ""
    error: Optional[str] = None
    try:
        data = yaml.safe_load(Path(project.config_path).read_text()) or {}
        if not isinstance(data, dict):
            error = "config is not a mapping"
        elif not isinstance(data.get("environments") or {}, dict):
            error = "environments is not a mapping"
            engine = engine_of(data)
        else:
            environments = list((data.get("environments") or {}).keys())
            engine = engine_of(data)
    except (OSError, yaml.YAMLError) as exc:
        error = str(exc)
    return {**asdict(project), "environments": environments, "engine": engine, "error": error}


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

    @app.post("/api/projects/{project_id}/jobs", status_code=202)
    def start_job(project_id: str, body: NewJob) -> Dict[str, str]:
        try:
            job = runner.start(project_id, body.command, body.environment, body.params)
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
