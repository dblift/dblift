"""AsyncDBLiftClient: threadpool facade over the sync client."""

import asyncio
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from api.async_client import AsyncDBLiftClient


def _make(tmp_path: Path) -> AsyncDBLiftClient:
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "V1_0_0__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
    engine = create_engine(f"sqlite:///{tmp_path/'db.sqlite'}")
    return AsyncDBLiftClient.from_sqlalchemy(engine, migrations_dir=str(migrations))


@pytest.mark.asyncio
async def test_migrate_runs(tmp_path):
    client = _make(tmp_path)
    result = await client.migrate()
    assert result.success
    await client.aclose()


@pytest.mark.asyncio
async def test_concurrent_ops_are_serialized(tmp_path):
    client = _make(tmp_path)
    await client.migrate()
    info_res, validate_res = await asyncio.gather(client.info(), client.validate())
    assert info_res is not None
    assert validate_res.success
    await client.aclose()


@pytest.mark.asyncio
async def test_async_context_manager_closes(tmp_path):
    async with _make(tmp_path) as client:
        result = await client.migrate()
        assert result.success
    with pytest.raises(Exception):
        await client.info()


@pytest.mark.asyncio
async def test_events_property_exposes_bus(tmp_path):
    client = _make(tmp_path)
    seen = []
    client.events.on("migration.started", lambda e: seen.append(e.event_type.value))
    await client.migrate()
    assert "migration.started" in seen
    await client.aclose()
