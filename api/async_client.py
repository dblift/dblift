"""Async facade over :class:`DBLiftClient` for asyncio apps.

Each operation runs in a worker thread via ``asyncio.to_thread`` so the event
loop is not blocked. This is not native async DB I/O: the call occupies a
worker thread. A per-instance ``asyncio.Lock`` serializes operations because
the underlying sync client holds a single shared connection and is not safe for
concurrent use.
"""

from __future__ import annotations

import asyncio
from typing import Any

from api.client import DBLiftClient
from api.events import EventEmitter


class AsyncDBLiftClient:
    """Async wrapper around a synchronous :class:`DBLiftClient`."""

    def __init__(self, sync_client: DBLiftClient) -> None:
        self._sync = sync_client
        self._lock = asyncio.Lock()
        self._closed = False

    @classmethod
    def from_sqlalchemy(cls, engine: Any = None, **kwargs: Any) -> "AsyncDBLiftClient":
        return cls(DBLiftClient.from_sqlalchemy(engine, **kwargs))

    @classmethod
    def from_config(cls, config: Any, **kwargs: Any) -> "AsyncDBLiftClient":
        return cls(DBLiftClient.from_config(config, **kwargs))

    @classmethod
    def from_config_file(cls, config_path: str, **kwargs: Any) -> "AsyncDBLiftClient":
        return cls(DBLiftClient.from_config_file(config_path, **kwargs))

    @property
    def events(self) -> EventEmitter:
        return self._sync.events

    async def _run(self, fn: Any, *args: Any, **kwargs: Any) -> Any:
        async with self._lock:
            if self._closed:
                raise RuntimeError("AsyncDBLiftClient is closed")
            return await asyncio.to_thread(fn, *args, **kwargs)

    async def migrate(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.migrate, *args, **kwargs)

    async def info(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.info, *args, **kwargs)

    async def validate(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.validate, *args, **kwargs)

    async def undo(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.undo, *args, **kwargs)

    async def generate_undo_script(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.generate_undo_script, *args, **kwargs)

    async def generate_undo_scripts(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.generate_undo_scripts, *args, **kwargs)

    async def clean(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.clean, *args, **kwargs)

    async def baseline(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.baseline, *args, **kwargs)

    async def repair(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.repair, *args, **kwargs)

    async def import_flyway(self, *args: Any, **kwargs: Any) -> Any:
        return await self._run(self._sync.import_flyway, *args, **kwargs)

    async def aclose(self) -> None:
        async with self._lock:
            if self._closed:
                return
            await asyncio.to_thread(self._sync.close)
            self._closed = True

    async def __aenter__(self) -> "AsyncDBLiftClient":
        return self

    async def __aexit__(self, exc_type: Any, exc: Any, tb: Any) -> None:
        await self.aclose()
