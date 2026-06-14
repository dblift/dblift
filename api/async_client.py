"""Async facade over :class:`DBLiftClient` for asyncio apps.

Each operation runs in one dedicated worker thread so the event loop is not
blocked and the wrapped synchronous client keeps thread affinity. This is not
native async DB I/O: the call occupies that worker thread. A per-instance
``asyncio.Lock`` serializes operations because the underlying sync client holds
a single shared connection and is not safe for concurrent use.
"""

from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from functools import partial
from typing import Any

from api.client import DBLiftClient
from api.events import EventEmitter


class AsyncDBLiftClient:
    """Async wrapper around a synchronous :class:`DBLiftClient`."""

    def __init__(self, sync_client: DBLiftClient) -> None:
        """Wrap an existing synchronous DBLift client."""
        self._sync = sync_client
        self._executor = ThreadPoolExecutor(
            max_workers=1,
            thread_name_prefix="dblift-async-client",
        )
        self._lock = asyncio.Lock()
        self._closed = False

    @classmethod
    def from_sqlalchemy(cls, engine: Any = None, **kwargs: Any) -> "AsyncDBLiftClient":
        """Create an async client from a SQLAlchemy engine or connection."""
        return cls(DBLiftClient.from_sqlalchemy(engine, **kwargs))

    @classmethod
    def from_config(cls, config: Any, **kwargs: Any) -> "AsyncDBLiftClient":
        """Create an async client from a DBLift config object."""
        return cls(DBLiftClient.from_config(config, **kwargs))

    @classmethod
    def from_config_file(cls, config_path: str, **kwargs: Any) -> "AsyncDBLiftClient":
        """Create an async client from a DBLift config file path."""
        return cls(DBLiftClient.from_config_file(config_path, **kwargs))

    @property
    def events(self) -> EventEmitter:
        """Return the wrapped sync client's event emitter."""
        return self._sync.events

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            if self._closed:
                raise RuntimeError("AsyncDBLiftClient is closed")
            return await self._run_in_thread(fn, *args, **kwargs)

    async def _run_in_thread(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        loop = asyncio.get_running_loop()
        worker = loop.run_in_executor(self._executor, partial(fn, *args, **kwargs))
        cancelled = False
        while True:
            try:
                result = await asyncio.shield(worker)
            except asyncio.CancelledError:
                cancelled = True
                if worker.done():
                    raise
                continue
            except Exception:
                if cancelled:
                    raise asyncio.CancelledError from None
                raise
            if cancelled:
                raise asyncio.CancelledError
            return result

    async def migrate(self, *args: Any, **kwargs: Any) -> Any:
        """Apply pending migrations without blocking the event loop."""
        return await self._run(self._sync.migrate, *args, **kwargs)

    async def info(self, *args: Any, **kwargs: Any) -> Any:
        """Return migration status information without blocking the event loop."""
        return await self._run(self._sync.info, *args, **kwargs)

    async def validate(self, *args: Any, **kwargs: Any) -> Any:
        """Validate migrations without blocking the event loop."""
        return await self._run(self._sync.validate, *args, **kwargs)

    async def undo(self, *args: Any, **kwargs: Any) -> Any:
        """Undo migrations without blocking the event loop."""
        return await self._run(self._sync.undo, *args, **kwargs)

    async def generate_undo_script(self, *args: Any, **kwargs: Any) -> Any:
        """Generate one undo script without blocking the event loop."""
        return await self._run(self._sync.generate_undo_script, *args, **kwargs)

    async def generate_undo_scripts(self, *args: Any, **kwargs: Any) -> Any:
        """Generate undo scripts without blocking the event loop."""
        return await self._run(self._sync.generate_undo_scripts, *args, **kwargs)

    async def clean(self, *args: Any, **kwargs: Any) -> Any:
        """Clean database objects without blocking the event loop."""
        return await self._run(self._sync.clean, *args, **kwargs)

    async def baseline(self, *args: Any, **kwargs: Any) -> Any:
        """Create a baseline without blocking the event loop."""
        return await self._run(self._sync.baseline, *args, **kwargs)

    async def repair(self, *args: Any, **kwargs: Any) -> Any:
        """Repair migration metadata without blocking the event loop."""
        return await self._run(self._sync.repair, *args, **kwargs)

    async def import_flyway(self, *args: Any, **kwargs: Any) -> Any:
        """Import Flyway metadata without blocking the event loop."""
        return await self._run(self._sync.import_flyway, *args, **kwargs)

    async def aclose(self) -> None:
        """Release resources held by the wrapped sync client."""
        await self._exit(None, None, None)

    async def _exit(self, exc_type: Any, exc: Any, tb: Any) -> None:
        async with self._lock:
            if self._closed:
                return
            try:
                await self._run_in_thread(self._sync.__exit__, exc_type, exc, tb)
            finally:
                self._closed = True
                self._executor.shutdown(wait=False)

    async def __aenter__(self) -> "AsyncDBLiftClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self._exit(exc_type, exc, tb)
