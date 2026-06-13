# FastAPI Lifespan + DBLift Migration Guard

Use `dblift.integrations.fastapi` (thin read-only helpers) to protect FastAPI startup from unapplied migrations.

The helpers only inspect state via `client.info()`; **they never call `migrate()` themselves**. The application (or explicit caller) decides when to apply.

## Runnable example

```python
from contextlib import asynccontextmanager
from fastapi import FastAPI
from sqlalchemy import create_engine

from api import DBLiftClient
from integrations.fastapi import (
    check_migrations_current,
    migration_guard,
    health_payload,
)

# Your existing engine (owned by you). Pass to from_sqlalchemy so DBLift
# re-uses it instead of opening its own connection.
engine = create_engine("sqlite:///./app.db")  # or postgresql+psycopg://...

migrations_dir = "migrations"


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Create a short-lived client for the guard (cheap; from_sqlalchemy does not own the engine).
    # In real apps you may store the client (or a factory) on app.state.
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations_dir)
    try:
        # Blocks startup by default if any migrations are pending.
        # on_pending="warn" logs a warning (via warnings.warn) and continues.
        # on_pending="ignore" is a no-op (useful for dev or when you apply elsewhere).
        migration_guard(client, on_pending="raise")

        # You can also expose health/read info for /health endpoints.
        app.state.dblift_client = client
        yield
    finally:
        client.close()
        # Do NOT dispose engine here if your app still needs it after shutdown.


app = FastAPI(lifespan=lifespan)


@app.get("/health")
def health():
    """Example health endpoint using the read-only helper."""
    # health_payload never applies migrations.
    return health_payload(app.state.dblift_client)


@app.get("/migrations/pending")
def pending_migrations():
    """Returns [] when current, otherwise list[str] of pending ids/descriptions."""
    return {"pending": check_migrations_current(app.state.dblift_client)}
```

Run with uvicorn as usual:

```
uvicorn your_app:app --reload
```

If you start with pending migrations and the default guard, the app will fail to start with a clear error telling you to run migrations.

## Explicitly migrate (when you want to)

The integration helpers are deliberately **read-only**. To apply:

```python
with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations_dir) as client:
    client.migrate()
```

Call this from a management command, admin-only route (behind auth), or your deploy script — never automatically inside the web path unless you have made that choice.

## Sync-only limitation (v1)

These helpers (and `DBLiftClient.from_sqlalchemy`) work with **sync SQLAlchemy Engine / Connection only**.

There is no `AsyncEngine` support in v1. If you use async FastAPI endpoints + async SQLAlchemy, create the engine in a thread-friendly way and run the (sync) guard / info calls via `asyncio.to_thread` or a thread pool executor from your lifespan / dependency code.

Follow-up work may add an async variant in a later version; the current design keeps the core substrate and helpers deliberately thin and sync.

## Notes

- `check_migrations_current(client)` → `list[str]` of pending migration identifiers (scripts or version+desc). Empty list means the DB is current for the given migrations_dir.
- `health_payload(client)` → `dict` with at least `{"pending_migrations": [...], "current": bool, "current_schema_version": ...}`. Safe for public /health.
- `migration_guard(...)` is the typical call in lifespan startup.
- All three delegate exclusively to `client.info()` (plus trivial post-processing). No hidden migrate, no side effects on the read paths.
- Package the feature with `pip install "dblift[fastapi]"` (declares the optional dep).
