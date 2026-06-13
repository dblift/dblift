"""pytest-dblift fixtures (core implementation for Task 4.2).

Six fixtures per the plan table + dependency graph.
Uses DBLiftClient.from_sqlalchemy exclusively.
Session scope for expensive (config/engine/client); function for state (migrate/empty/validate).

--dblift-no-migrate is intentionally not wired (out of scope for 4.2).
"""

from __future__ import annotations

from typing import Any, Callable

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient

from ._client import create_dblift_client, resolve_dblift_config


@pytest.fixture(scope="session")
def dblift_config(pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory) -> dict[str, Any]:
    """Session config dict derived from CLI or temp SQLite default.

    Overridable by consumer tests (return {'url': ..., 'migrations_dir': ...}).
    """
    return resolve_dblift_config(pytestconfig, tmp_path_factory=tmp_path_factory)


@pytest.fixture(scope="session")
def dblift_engine(dblift_config: dict[str, Any]) -> Any:
    """Session-scoped SQLAlchemy Engine created from dblift_config['url'].

    Disposes on session teardown (only for engines created here).
    """
    engine = create_engine(dblift_config["url"])
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def dblift_client(dblift_engine: Any, dblift_config: dict[str, Any]) -> DBLiftClient:
    """Session-scoped DBLiftClient via from_sqlalchemy (engine owned by caller)."""
    cfg = dblift_config
    client = create_dblift_client(
        dblift_engine,
        migrations_dir=cfg.get("migrations_dir"),
        schema=cfg.get("schema"),
    )
    yield client
    client.close()


@pytest.fixture
def dblift_migrated_db(dblift_client: DBLiftClient) -> DBLiftClient:
    """Function-scoped: ensure migrations applied; yields the session client for convenience."""
    result = dblift_client.migrate()
    assert getattr(result, "success", False), f"migrate failed: {getattr(result, 'error_message', result)}"
    yield dblift_client


@pytest.fixture
def dblift_empty_db(dblift_client: DBLiftClient) -> DBLiftClient:
    """Function-scoped: clean schema + history (drops all user + dblift internal objects)."""
    result = dblift_client.clean(clean_enabled=True)
    assert getattr(result, "success", False), f"clean failed: {getattr(result, 'error_message', result)}"
    yield dblift_client


@pytest.fixture
def dblift_validate(dblift_client: DBLiftClient) -> Callable[..., Any]:
    """Function-scoped: returns a callable that invokes client.validate(**kwargs) and asserts success."""
    def _run_validate(**kwargs: Any) -> Any:
        result = dblift_client.validate(**kwargs)
        assert getattr(result, "success", False), f"validate failed: {getattr(result, 'error_message', result)}"
        return result

    return _run_validate


@pytest.fixture
def dblift_undo_smoke(dblift_migrated_db: DBLiftClient) -> DBLiftClient:
    """Function-scoped: forward-migrated client for smoke-testing undo path on Python migrations declaring `undo`.

    Thin delegate to dblift_migrated_db (ensures migrate() ran, so the `migrate(context)` in the .py executed).
    Yields the client so tests can drive client.undo(target_version=...) and assert state revert
    (the "optional undo assert" is performed by the test after the yield).
    """
    yield dblift_migrated_db
