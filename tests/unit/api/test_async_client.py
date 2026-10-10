"""AsyncDBLiftClient: threadpool facade over the sync client."""

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from pathlib import Path

import pytest
from sqlalchemy import create_engine

from dblift.api.async_client import AsyncDBLiftClient
from dblift.core.logger import DbliftLogger, LogFormat, NullLog


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


@pytest.mark.asyncio
async def test_two_async_clients_keep_events_output_and_external_engines_separate(tmp_path, capsys):
    captures = []
    event_lists = []
    for name, logger in (
        ("silent", NullLog()),
        (
            "text",
            DbliftLogger("async-text", format=LogFormat.TEXT, logfile_dir=tmp_path / "logs"),
        ),
    ):
        migrations = tmp_path / name / "migrations"
        migrations.mkdir(parents=True)
        (migrations / "V1__t.sql").write_text("CREATE TABLE t (id INTEGER PRIMARY KEY);")
        (migrations / "U1__t.sql").write_text("DROP TABLE t;")
        engine = create_engine(f"sqlite:///{tmp_path / name / 'db.sqlite'}")
        events = []
        capsys.readouterr()
        async with AsyncDBLiftClient.from_sqlalchemy(
            engine, migrations_dir=migrations, logger=logger
        ) as client:
            client.events.on("*", lambda event: events.append(event.event_type.value))
            assert (await client.migrate()).success
            assert (await client.info()).success
            assert (await client.validate()).success
            assert (await client.undo()).success
        if isinstance(logger, DbliftLogger):
            logger.close()
        captures.append(capsys.readouterr())
        event_lists.append(events)
        with engine.connect() as connection:
            assert connection.exec_driver_sql("SELECT 1").scalar_one() == 1
        engine.dispose()

    assert captures[0].out == captures[0].err == ""
    assert captures[1].out or captures[1].err
    for events in event_lists:
        assert events.count("migration.started") == 1
        assert events.count("migration.completed") == 1
        assert events.count("undo.started") == 1
        assert events.count("undo.completed") == 1


@pytest.mark.asyncio
async def test_cancelled_operation_keeps_serialization_until_worker_finishes():
    class BlockingSyncClient:
        def __init__(self) -> None:
            self.events = object()
            self.migrate_started = threading.Event()
            self.release_migrate = threading.Event()
            self.info_started = threading.Event()

        def migrate(self) -> str:
            self.migrate_started.set()
            assert self.release_migrate.wait(timeout=1)
            return "migrated"

        def info(self) -> str:
            self.info_started.set()
            return "info"

        def close(self) -> None:
            return None

        def __exit__(self, exc_type, exc, tb) -> None:
            self.close()

    sync_client = BlockingSyncClient()
    client = AsyncDBLiftClient(sync_client)  # type: ignore[arg-type]

    task = asyncio.create_task(client.migrate())
    assert await asyncio.to_thread(sync_client.migrate_started.wait, 1)

    task.cancel()
    await asyncio.sleep(0.05)
    assert not task.done()

    info_task = asyncio.create_task(client.info())
    await asyncio.sleep(0.05)
    assert not sync_client.info_started.is_set()

    sync_client.release_migrate.set()
    with pytest.raises(asyncio.CancelledError):
        await task
    assert await info_task == "info"
    await client.aclose()


@pytest.mark.asyncio
async def test_operations_reuse_one_worker_thread(monkeypatch):
    calls = 0

    async def rotating_to_thread(fn, /, *args, **kwargs):
        nonlocal calls
        calls += 1
        loop = asyncio.get_running_loop()
        with ThreadPoolExecutor(max_workers=1, thread_name_prefix=f"rotating-{calls}") as executor:
            return await loop.run_in_executor(executor, partial(fn, *args, **kwargs))

    class ThreadBoundSyncClient:
        def __init__(self) -> None:
            self.events = object()
            self.thread_name = None

        def _check_thread(self) -> None:
            thread_name = threading.current_thread().name
            if self.thread_name is None:
                self.thread_name = thread_name
                return
            assert thread_name == self.thread_name

        def migrate(self) -> str:
            self._check_thread()
            return "migrated"

        def info(self) -> str:
            self._check_thread()
            return "info"

        def close(self) -> None:
            self._check_thread()

        def __exit__(self, exc_type, exc, tb) -> None:
            self.close()

    monkeypatch.setattr(asyncio, "to_thread", rotating_to_thread)

    sync_client = ThreadBoundSyncClient()
    client = AsyncDBLiftClient(sync_client)  # type: ignore[arg-type]

    assert await client.migrate() == "migrated"
    assert await client.info() == "info"
    await client.aclose()


@pytest.mark.asyncio
async def test_async_exit_forwards_exception_to_sync_exit():
    class ExitingSyncClient:
        def __init__(self) -> None:
            self.events = object()
            self.exit_args = None

        def __exit__(self, exc_type, exc, tb) -> None:
            self.exit_args = (exc_type, exc, tb)

        def close(self) -> None:
            self.__exit__(None, None, None)

    sync_client = ExitingSyncClient()
    client = AsyncDBLiftClient(sync_client)  # type: ignore[arg-type]
    error = ValueError("boom")

    await client.__aexit__(ValueError, error, None)

    assert sync_client.exit_args == (ValueError, error, None)
