"""pytest-dblift fixtures.

Session scope for config/engine/client. Function scope for migrate/clean/validate/undo.
No autouse: tests opt in by requesting a fixture.
"""

from __future__ import annotations

from typing import Any, Callable, Iterator

import pytest
from sqlalchemy import create_engine

from api import DBLiftClient

from ._client import create_dblift_client, resolve_dblift_config


@pytest.fixture(scope="session")
def dblift_config(
    pytestconfig: pytest.Config, tmp_path_factory: pytest.TempPathFactory
) -> dict[str, Any]:
    """Session config from CLI or temp SQLite. Overridable in consumer conftest.py."""
    return resolve_dblift_config(pytestconfig, tmp_path_factory=tmp_path_factory)


@pytest.fixture(scope="session")
def dblift_engine(dblift_config: dict[str, Any]) -> Iterator[Any]:
    engine = create_engine(dblift_config["url"])
    yield engine
    engine.dispose()


@pytest.fixture(scope="session")
def dblift_client(dblift_engine: Any, dblift_config: dict[str, Any]) -> Iterator[DBLiftClient]:
    client = create_dblift_client(
        dblift_engine,
        migrations_dir=dblift_config.get("migrations_dir"),
        schema=dblift_config.get("schema"),
    )
    yield client
    client.close()


@pytest.fixture
def dblift_migrated_db(dblift_client: DBLiftClient) -> Iterator[DBLiftClient]:
    result = dblift_client.migrate()
    assert getattr(result, "success", False), (
        f"migrate failed: {getattr(result, 'error_message', result)}"
    )
    yield dblift_client


@pytest.fixture
def dblift_empty_db(dblift_client: DBLiftClient) -> Iterator[DBLiftClient]:
    result = dblift_client.clean(clean_enabled=True)
    assert getattr(result, "success", False), (
        f"clean failed: {getattr(result, 'error_message', result)}"
    )
    yield dblift_client


@pytest.fixture
def dblift_validate(dblift_client: DBLiftClient) -> Callable[..., Any]:
    def _run_validate(**kwargs: Any) -> Any:
        result = dblift_client.validate(**kwargs)
        assert getattr(result, "success", False), (
            f"validate failed: {getattr(result, 'error_message', result)}"
        )
        return result

    return _run_validate
