"""Unit tests for dblift.integrations.fastapi (thin helpers only).

TDD: these were written first to drive the implementation.
Uses real temp SQLite + DBLiftClient.from_sqlalchemy (no Docker).
Tests cover guard blocking startup in FastAPI lifespan, plus the read helpers.
"""

from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path
from typing import Any

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient

# NOTE: imports of the module under test (integrations.fastapi) are performed
# *inside* each test function. This ensures:
# - test collection succeeds even before the integrations/ package exists (TDD RED phase)
# - fastapi is only required for the lifespan tests (via pytest.importorskip inside)
# All per "write failing smoke tests" first.


def _setup_pending_db(tmp_path: Path) -> tuple[Any, Path, DBLiftClient]:
    """Create a migrations dir + sqlite DB with one pending migration. Return (engine, mig_dir, client)."""
    mig_dir = tmp_path / "migrations"
    mig_dir.mkdir(exist_ok=True)
    (mig_dir / "V1__init.sql").write_text(
        "CREATE TABLE fastapi_test (id INTEGER PRIMARY KEY, name TEXT);"
    )
    db_file = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_file}")
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=mig_dir)
    # Intentionally do NOT call migrate() here -> pending state
    return engine, mig_dir, client


def _setup_current_db(tmp_path: Path) -> tuple[Any, Path, DBLiftClient]:
    """Same setup but call migrate() so DB is current."""
    engine, mig_dir, client = _setup_pending_db(tmp_path)
    result = client.migrate()
    assert result.success, "setup migrate must succeed for 'current' tests"
    return engine, mig_dir, client


def test_check_migrations_current_returns_empty_when_current(tmp_path: Path) -> None:
    """check_migrations_current returns [] when no pending migrations."""
    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, _, client = _setup_current_db(tmp_path)
    try:
        pending = check_migrations_current(client)
        assert pending == []
    finally:
        client.close()


def test_check_migrations_current_returns_list_when_pending(tmp_path: Path) -> None:
    """check_migrations_current returns list[str] of pending identifiers when behind."""
    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, _, client = _setup_pending_db(tmp_path)
    try:
        pending = check_migrations_current(client)
        assert isinstance(pending, list)
        assert len(pending) == 1
        # The identifiers include version+desc (as produced by check) or the script.
        # "1 - init" or "V1__init.sql" are both acceptable per "ids/descriptions".
        assert any("init" in str(x) or "V1__init" in str(x) or str(x) == "1" for x in pending)
    finally:
        client.close()


def test_health_payload_shape_and_current_flag(tmp_path: Path) -> None:
    """health_payload is read-only and returns expected keys + current bool."""
    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, _, client = _setup_current_db(tmp_path)
    try:
        payload = health_payload(client)
        assert isinstance(payload, dict)
        assert "pending_migrations" in payload
        assert "current" in payload
        assert payload["current"] is True
        assert payload["pending_migrations"] == []
        # Also carries version info for /health endpoints
        assert "current_schema_version" in payload
    finally:
        client.close()


def test_health_payload_reports_pending_when_behind(tmp_path: Path) -> None:
    """health_payload reports pending when migrations not applied."""
    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, _, client = _setup_pending_db(tmp_path)
    try:
        payload = health_payload(client)
        assert payload["current"] is False
        assert len(payload["pending_migrations"]) == 1
    finally:
        client.close()


def test_migration_guard_noop_on_current_or_ignore(tmp_path: Path) -> None:
    """migration_guard is a no-op (does not raise) when current or on_pending=ignore."""
    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    # current
    _, _, client = _setup_current_db(tmp_path)
    try:
        migration_guard(client, on_pending="raise")
    finally:
        client.close()

    # pending but ignore
    _, _, client = _setup_pending_db(tmp_path)
    try:
        migration_guard(client, on_pending="ignore")
    finally:
        client.close()


def test_migration_guard_warns_on_pending(tmp_path: Path) -> None:
    """on_pending='warn' emits a warning but does not raise."""
    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, _, client = _setup_pending_db(tmp_path)
    try:
        with pytest.warns(Warning):
            migration_guard(client, on_pending="warn")
    finally:
        client.close()


def test_migration_guard_raises_on_pending_by_default(tmp_path: Path) -> None:
    """Default (raise) and explicit on_pending='raise' block when pending."""
    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, _, client = _setup_pending_db(tmp_path)
    try:
        with pytest.raises(Exception) as exc:
            migration_guard(client)
        assert "pending" in str(exc.value).lower() or "Pending" in str(exc.value)
    finally:
        client.close()

    _, _, client = _setup_pending_db(tmp_path)
    try:
        with pytest.raises(Exception):
            migration_guard(client, on_pending="raise")
    finally:
        client.close()


def test_fastapi_lifespan_guard_blocks_startup_on_pending(tmp_path: Path) -> None:
    """FastAPI TestClient + lifespan: pending + on_pending='raise' causes startup to fail."""
    fastapi = pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, mig_dir, _ = _setup_pending_db(tmp_path)  # client not needed here; recreate inside lifespan
    db_file = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_file}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = DBLiftClient.from_sqlalchemy(engine, migrations_dir=mig_dir)
        try:
            migration_guard(c, on_pending="raise")
            yield
        finally:
            c.close()

    app = FastAPI(lifespan=lifespan)

    with pytest.raises(Exception) as exc:
        with TestClient(app):
            pass  # startup happens on context enter
    assert "pending" in str(exc.value).lower() or "Pending" in str(exc.value)


def test_fastapi_lifespan_succeeds_when_current_and_health_route_works(tmp_path: Path) -> None:
    """Startup succeeds when current; routes can call the read-only helpers via app.state."""
    fastapi = pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, mig_dir, client = _setup_current_db(tmp_path)
    db_file = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_file}")
    # ensure the 'current' client from setup is not the one used by app; recreate inside

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = DBLiftClient.from_sqlalchemy(engine, migrations_dir=mig_dir)
        try:
            migration_guard(c, on_pending="raise")
            app.state.dblift = c
            yield
        finally:
            c.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def get_health():
        return health_payload(app.state.dblift)

    @app.get("/check")
    def get_check():
        return {"pending": check_migrations_current(app.state.dblift)}

    try:
        with TestClient(app) as tc:
            # guard passed, app is up
            r = tc.get("/health")
            assert r.status_code == 200
            data = r.json()
            assert data["current"] is True
            assert data["pending_migrations"] == []

            r2 = tc.get("/check")
            assert r2.status_code == 200
            assert r2.json()["pending"] == []
    finally:
        client.close()


def test_fastapi_lifespan_ignore_allows_pending_startup(tmp_path: Path) -> None:
    """on_pending='ignore' lets lifespan proceed even with pending migrations."""
    fastapi = pytest.importorskip("fastapi")
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from integrations.fastapi import (
        check_migrations_current,
        health_payload,
        migration_guard,
    )

    _, mig_dir, _ = _setup_pending_db(tmp_path)
    db_file = tmp_path / "app.db"
    engine = create_engine(f"sqlite:///{db_file}")

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        c = DBLiftClient.from_sqlalchemy(engine, migrations_dir=mig_dir)
        try:
            migration_guard(c, on_pending="ignore")
            app.state.dblift = c
            yield
        finally:
            c.close()

    app = FastAPI(lifespan=lifespan)

    @app.get("/health")
    def get_health():
        return health_payload(app.state.dblift)

    with TestClient(app) as tc:
        r = tc.get("/health")
        assert r.status_code == 200
        assert r.json()["current"] is False
