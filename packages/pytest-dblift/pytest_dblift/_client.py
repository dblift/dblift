"""Internal helpers for pytest-dblift fixtures (Task 4.2).

Thin wrappers and config resolution. Includes xdist worker isolation (Task 4.3)
via _worker_id for default SQLite paths only.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from api import DBLiftClient


def _worker_id(config) -> str:
    """Return xdist worker id ('gw0', 'gw1', ...) or 'master' when not under xdist.

    Uses the workerinput injected by pytest-xdist on worker Config objects.
    """
    workerinput = getattr(config, "workerinput", None)
    if workerinput:
        return workerinput.get("workerid", "master")
    return "master"


def default_sqlite_file_url(tmp_path_factory: pytest.TempPathFactory, config: pytest.Config | None = None) -> str:
    """Return sqlalchemy URL for a session-scoped temp SQLite file.

    Uses tmp_path_factory.mktemp so the file lives for the pytest session.
    When under xdist (workerinput present and workerid != 'master'), appends
    worker suffix to produce per-worker DB file (e.g. test_gw0.db) so session
    fixtures do not collide across workers.
    """
    base = tmp_path_factory.mktemp("dblift_pytest", numbered=True)
    wid = _worker_id(config) if config is not None else "master"
    if wid != "master":
        db_path = base / f"test_{wid}.db"
    else:
        db_path = base / "test.db"
    # 4 slashes total for absolute path on POSIX: sqlite:////abs/path
    return f"sqlite:///{db_path}"


def resolve_dblift_config(
    pytestconfig: pytest.Config,
    *,
    tmp_path_factory: pytest.TempPathFactory,
) -> dict[str, Any]:
    """Build config dict from CLI options + defaults.

    Returns dict with 'url' and 'migrations_dir' (absolute path str).
    Schema omitted for SQLite (default works).
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
    """Thin wrapper around DBLiftClient.from_sqlalchemy.

    Keeps fixtures.py minimal and provides hook point for later (xdist etc).
    """
    return DBLiftClient.from_sqlalchemy(
        engine,
        migrations_dir=migrations_dir,
        schema=schema,
    )
