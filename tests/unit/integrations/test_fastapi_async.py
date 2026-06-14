"""Async FastAPI guard helpers."""

from pathlib import Path

import pytest
from sqlalchemy import create_engine

from api.async_client import AsyncDBLiftClient
from core.exceptions import DbliftError
from integrations.fastapi import (
    check_migrations_current_async,
    health_payload_async,
    migration_guard_async,
)


def _client(tmp_path: Path) -> AsyncDBLiftClient:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    return AsyncDBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))


@pytest.mark.asyncio
async def test_guard_raises_when_pending(tmp_path):
    client = _client(tmp_path)
    with pytest.raises(DbliftError):
        await migration_guard_async(client, on_pending="raise")
    await client.aclose()


@pytest.mark.asyncio
async def test_guard_passes_when_current(tmp_path):
    client = _client(tmp_path)
    await client.migrate()
    await migration_guard_async(client)  # no raise
    assert await check_migrations_current_async(client) == []
    payload = await health_payload_async(client)
    assert payload["current"] is True
    assert payload["pending_count"] == 0
    await client.aclose()
