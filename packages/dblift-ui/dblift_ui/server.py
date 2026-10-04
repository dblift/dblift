"""HTTP application: security guard and route wiring."""

import secrets
from dataclasses import asdict
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, List, Optional

import yaml
from dblift_ui import __version__
from dblift_ui.registry import (
    Project,
    ProjectRegistry,
    RegistryError,
    RegistryFileError,
)
from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel

TOKEN_HEADER = "X-DBLift-Token"
STATIC_DIR = Path(__file__).resolve().parent / "static"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


class NewProject(BaseModel):
    name: str = ""
    config_path: str = ""


def describe(project: Project) -> Dict[str, Any]:
    """A project as the browser sees it: registry fields plus what its config declares."""
    environments: List[str] = []
    error: Optional[str] = None
    try:
        data = yaml.safe_load(Path(project.config_path).read_text()) or {}
        if not isinstance(data, dict):
            error = "config is not a mapping"
        elif not isinstance(data.get("environments") or {}, dict):
            error = "environments is not a mapping"
        else:
            environments = list((data.get("environments") or {}).keys())
    except (OSError, yaml.YAMLError) as exc:
        error = str(exc)
    return {**asdict(project), "environments": environments, "error": error}


def create_app(token: str, port: int, registry: Optional[ProjectRegistry] = None) -> FastAPI:
    """Build the application for one launch.

    *token* is the per-launch secret every ``/api/`` call must present.
    *port* is the port the server listens on; requests whose ``Host`` header
    names anything else are refused, which blocks DNS rebinding.
    *registry* defaults to the per-user registry file.
    """
    app = FastAPI(title="DBLift UI", docs_url=None, redoc_url=None, openapi_url=None)
    projects = registry or ProjectRegistry.default()
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

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
