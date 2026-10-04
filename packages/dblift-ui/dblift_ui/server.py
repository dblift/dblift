"""HTTP application: security guard and route wiring."""

import secrets
from pathlib import Path
from typing import Awaitable, Callable

from dblift_ui import __version__
from fastapi import FastAPI, Request, Response
from fastapi.responses import FileResponse, JSONResponse

TOKEN_HEADER = "X-DBLift-Token"
STATIC_DIR = Path(__file__).resolve().parent / "static"
_SAFE_METHODS = frozenset({"GET", "HEAD", "OPTIONS"})


def create_app(token: str, port: int) -> FastAPI:
    """Build the application for one launch.

    *token* is the per-launch secret every ``/api/`` call must present.
    *port* is the port the server listens on; requests whose ``Host`` header
    names anything else are refused, which blocks DNS rebinding.
    """
    app = FastAPI(title="DBLift UI", docs_url=None, redoc_url=None, openapi_url=None)
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

    @app.get("/api/health")
    def health() -> dict:
        return {"status": "ok", "version": __version__}

    @app.get("/")
    def index() -> FileResponse:
        return FileResponse(STATIC_DIR / "index.html")

    return app
