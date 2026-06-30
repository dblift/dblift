# FastAPI Integration

Install the optional dependency:

```bash
pip install "dblift[fastapi]"
```

The FastAPI helpers are thin, read-only wrappers around `client.info()`. They
do not apply migrations.

## Startup Guard

```python
from contextlib import asynccontextmanager

from fastapi import FastAPI
from sqlalchemy import create_engine

from api import DBLiftClient
from integrations.fastapi import migration_guard

engine = create_engine("postgresql+psycopg://user:password@localhost/app")


@asynccontextmanager
async def lifespan(app: FastAPI):
    client = DBLiftClient.from_sqlalchemy(engine=engine, migrations_dir="migrations")
    try:
        migration_guard(client, on_pending="raise")
        app.state.dblift_client = client
        yield
    finally:
        client.close()


app = FastAPI(lifespan=lifespan)
```

`on_pending` accepts:

| Value | Behavior |
|-------|----------|
| `"raise"` | Raise when migrations are pending. |
| `"warn"` | Emit a warning and continue. |
| `"ignore"` | Do nothing. |

## Health Endpoints

```python
from integrations.fastapi import check_migrations_current, health_payload


@app.get("/health")
def health():
    return health_payload(app.state.dblift_client)


@app.get("/migrations/pending")
def pending():
    return {
        "pending": check_migrations_current(app.state.dblift_client),
    }
```

`health_payload` returns a dictionary with `pending_migrations`, `current`,
`current_schema_version`, and `pending_count`.

## Async Client Helpers

When using `AsyncDBLiftClient`, import the async mirrors:

```python
from api.async_client import AsyncDBLiftClient
from integrations.fastapi import (
    check_migrations_current_async,
    health_payload_async,
    migration_guard_async,
)


async with AsyncDBLiftClient.from_sqlalchemy(
    engine,
    migrations_dir="migrations",
) as client:
    await migration_guard_async(client, on_pending="raise")
    payload = await health_payload_async(client)
```

See [FastAPI Lifespan Example](../examples/fastapi-lifespan.md) for a complete
application.
