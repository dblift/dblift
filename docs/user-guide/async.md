# Async usage (FastAPI / asyncio)

`AsyncDBLiftClient` lets you run dblift from an asyncio app without blocking the
event loop. It wraps the sync client and runs operations in a dedicated worker
thread.

```python
from sqlalchemy import create_engine

from api.async_client import AsyncDBLiftClient


async def run():
    engine = create_engine("postgresql+psycopg://user:pass@localhost/db")
    async with AsyncDBLiftClient.from_sqlalchemy(
        engine, migrations_dir="migrations"
    ) as client:
        await client.migrate()
        info = await client.info()
```

## FastAPI startup guard

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI

from api.async_client import AsyncDBLiftClient
from integrations.fastapi import migration_guard_async


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with AsyncDBLiftClient.from_sqlalchemy(
        engine, migrations_dir="migrations"
    ) as client:
        await migration_guard_async(client, on_pending="raise")
        yield


app = FastAPI(lifespan=lifespan)
```

## Notes / limitations

- **Single-flight per client.** Operations on one `AsyncDBLiftClient` are
  serialized by an internal lock and run on the same worker thread because the
  underlying connection is shared and not concurrency-safe. For parallelism, use
  separate clients/engines.
- **Not native async I/O.** The DB call runs in a worker thread. This suits
  migrations that run at startup, not high-frequency per-request queries.
- Constructors are synchronous because construction is cheap; only operations
  are awaited.
