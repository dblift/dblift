"""URL resolution and DBLiftClient construction for pytest-dblift fixtures."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from api import DBLiftClient


def _worker_id(config: pytest.Config) -> str:
    """Return xdist worker id ('gw0', ...) or 'master' when not under xdist."""
    workerinput = getattr(config, "workerinput", None)
    if workerinput:
        return workerinput.get("workerid", "master")
    return "master"


def default_sqlite_file_url(
    tmp_path_factory: pytest.TempPathFactory, config: pytest.Config | None = None
) -> str:
    """Session-scoped temp SQLite file URL. Under xdist, suffix the filename with the worker id."""
    base = tmp_path_factory.mktemp("dblift_pytest", numbered=True)
    wid = _worker_id(config) if config is not None else "master"
    if wid != "master":
        db_path = base / f"test_{wid}.db"
    else:
        db_path = base / "test.db"
    return f"sqlite:///{db_path}"


def resolve_dblift_config(
    pytestconfig: pytest.Config,
    *,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    """Build config dict from CLI options + defaults.

    Returns dict with 'url' and 'migrations_dir' (absolute path str).
    A relative migrations dir is resolved against pytest rootdir.
    """
    url = pytestconfig.getoption("--dblift-url")
    if not url:
        url = default_sqlite_file_url(tmp_path_factory, pytestconfig)

    raw_mig = pytestconfig.getoption("--dblift-migrations-dir") or "migrations"
    rootdir = getattr(pytestconfig, "rootdir", None) or Path.cwd()
    rootdir = Path(rootdir)
    mig_path = Path(raw_mig)
    if not mig_path.is_absolute():
        mig_path = (rootdir / mig_path).resolve()

    return {
        "url": url,
        "migrations_dir": str(mig_path),
    }


def create_dblift_client(
    engine: Any,
    *,
    migrations_dir: str | Path | list[str | Path] | None,
    schema: str | None = None,
) -> DBLiftClient:
    return DBLiftClient.from_sqlalchemy(
        engine,
        migrations_dir=migrations_dir,
        schema=schema,
    )
