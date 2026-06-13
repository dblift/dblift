# SQLAlchemy Integration with DBLift

`DBLiftClient.from_sqlalchemy(...)` is the primary entry point for Python application runtimes, test suites, management scripts, and framework startup code. You hand DBLift an `Engine` (or `Connection`) you already own; DBLift re-uses it for migrations and never disposes it.

## Basic Pattern (Script or Startup)

```python
import tempfile
from pathlib import Path

from sqlalchemy import create_engine

from api import DBLiftClient


def main():
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        migrations = tmp_path / "migrations"
        migrations.mkdir()

        # A minimal SQL migration (Python migrations work identically)
        (migrations / "V1__app_schema.sql").write_text(
            "CREATE TABLE app_users (id INTEGER PRIMARY KEY, email TEXT UNIQUE);"
        )

        # Your app's engine (you control its lifecycle, pool, etc.)
        db_file = tmp_path / "app.db"
        engine = create_engine(f"sqlite:///{db_file}", echo=False)

        # Create the client. Pass engine (or connection=). DBLift will not own it.
        client = DBLiftClient.from_sqlalchemy(
            engine=engine,
            migrations_dir=migrations,
            # schema=..., log_level=..., etc. also accepted
        )

        # Read-only check (used by health endpoints, guards, etc.)
        info = client.info()
        print(f"Current version: {getattr(info, 'current_version', None)}")
        print(f"Pending count: {getattr(info, 'pending_count', 0)}")
        if getattr(info, "pending_count", 0) > 0:
            print("Migrations are needed.")

        # Apply (idempotent; safe to call on every deploy if you want)
        result = client.migrate()
        print(f"Migrate success={result.success}, applied={len(getattr(result, 'migrations_applied', []))}")

        # After close(), your engine is untouched and fully usable.
        client.close()
        with engine.connect() as conn:
            conn.exec_driver_sql("SELECT 1").fetchone()
            print("Engine still works after client.close() (ownership respected).")

        # Context manager form also supported
        with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations) as c2:
            _ = c2.info()


if __name__ == "__main__":
    main()
```

## Using a Live Connection (connection=)

When you already have an open `Connection` (e.g. inside a test transaction or a request-scoped session), pass it directly:

```python
engine = create_engine("sqlite:///:memory:")
conn = engine.connect()

client = DBLiftClient.from_sqlalchemy(connection=conn, migrations_dir=your_migrations)
client.migrate()
# client.close() will NOT close the caller's conn (see test coverage for _external_connection flag)
assert conn.exec_driver_sql("SELECT 1").scalar() == 1
conn.close()
```

Rejects passing both `engine=` and `connection=` (raises `ConfigurationError`).

## Engine / Connection Ownership Rules (D4)

- When you supply `engine=` or `connection=`, DBLift sets `owns_engine=False`.
- `client.close()` (and internal provider close) will never call `engine.dispose()` or close your connection.
- You remain responsible for disposing the engine when your app shuts down.
- The same guarantee holds for the context-manager form (`with DBLiftClient.from_sqlalchemy(...) as client:`).
- This is why the FastAPI lifespan example does `client.close()` in the `finally` but **never** disposes the engine there.

## Checking Pending Migrations Without Applying (info / health)

Use `client.info()` for read-only status. It powers:

- Startup guards (refuse to start if schema is behind)
- `/health` or readiness endpoints
- CI validation steps

```python
client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations_dir)
info = client.info()
pending = getattr(info, "pending_migrations", []) or []
if pending:
    # e.g. raise or log
    print("Pending:", [getattr(m, "script_name", m) for m in pending])
```

The thin helpers in `dblift.integrations.fastapi` (`check_migrations_current`, `health_payload`, `migration_guard`) and `dblift.integrations.flask` (`init_dblift` + guard) are thin wrappers around exactly this `info()` pattern. You can call `client.info()` directly in scripts or your own wiring.

## Using Python Migrations With the Integrated Client

When your migrations dir contains `.py` files, the same `from_sqlalchemy` client will execute them and inject a fully populated `MigrationContext`:

```python
# In your migrations/V2__using_runtime_ctx.py
from api import MigrationContext

def migrate(context: MigrationContext) -> None:
    context.log.info("Running under app runtime integration")
    eng = context.engine          # the exact Engine you passed to from_sqlalchemy
    conn = context.connection     # active connection if provided
    schema = context.schema
    ph = context.placeholders     # from config or migrate(..., placeholders=...)
    # ... your logic using the caller's engine/connection if needed
    context.execute("CREATE TABLE ...")
```

See `docs/examples/python-migrations.md` for a complete runnable round-trip that includes Python migrations + `migrate` + `undo` + full surface inspection.

## Typical Runtime Patterns

### One-off management script

```python
from sqlalchemy import create_engine
from api import DBLiftClient

engine = get_app_engine()  # your normal factory
with DBLiftClient.from_sqlalchemy(engine, migrations_dir="migrations") as client:
    if client.info().pending_count:
        client.migrate()
```

### Inside a test (or pytest-dblift fixture)

```python
engine = create_engine("sqlite:///:memory:")
client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=tests_migrations)
client.migrate()
# ... run test against engine ...
client.close()
# engine still usable for more assertions or the next test
```

(The dedicated `pytest-dblift` package provides reusable fixtures that do the above plus isolation for xdist.)

### Framework startup (light tie-in)

The exact `from_sqlalchemy` + `client.info()` + conditional `migrate()` (or guard) pattern is what the official thin integrations (`dblift[fastapi]` / `dblift[flask]`) use internally. You can replicate the same in any framework or plain WSGI/ASGI app without pulling in the optional extras.

Always keep the decision to actually call `migrate()` outside hot request paths unless you have made that explicit architectural choice.

## Sync-Only Note (v1)

`from_sqlalchemy`, the client, and `MigrationContext` currently support only **sync** SQLAlchemy `Engine` / `Connection`. 

If your app uses `AsyncEngine` + async endpoints:

- Create a sync engine (or use `run_sync`) just for the migration client at startup / in a background task.
- Or wrap the sync migration calls with `asyncio.to_thread` / a thread pool.

Async support is out of scope for the initial Python-native substrate.

## Summary of the API

- `DBLiftClient.from_sqlalchemy(engine=..., migrations_dir=..., schema=..., config=..., logger=..., **kwargs)`
- `DBLiftClient.from_sqlalchemy(connection=..., ...)` — mutually exclusive with engine
- Returned client behaves like any other `DBLiftClient` (`migrate`, `info`, `undo`, `validate`, `clean`, ...).
- `client.close()` never disposes an externally supplied engine/connection.
- Inside `.py` migrations you get `context.engine`, `context.connection`, `context.schema`, `context.placeholders`, `context.config`, plus `execute` / `log` / shims.
- Public type: `from api import DBLiftClient, MigrationContext`

All examples above are copy-paste runnable with a stock Python + `sqlalchemy` + `dblift` (plus the sqlite extra if you want the provider bits isolated).

This completes the Python-native integration story alongside the existing SQL migration files and the thin framework helpers.
