# Flask Integration + DBLift

Use `dblift.integrations.flask` (thin app wiring + CLI helpers) with your Flask app factory to protect startup and provide a `flask dblift-migrate` command.

The helpers only inspect state via `client.info()` (when guard is used); **they never call `migrate()` themselves** unless you explicitly invoke the registered CLI command (or call `client.migrate()` from elsewhere). The application / deploy process decides when to apply.

## Runnable example (app factory pattern)

```python
from flask import Flask
from sqlalchemy import create_engine

from api import DBLiftClient
from integrations.flask import init_dblift, register_cli

# Your existing engine (owned by you). Pass to from_sqlalchemy so DBLift
# re-uses it instead of opening its own connection.
engine = create_engine("sqlite:///./app.db")  # or postgresql+psycopg://...

migrations_dir = "migrations"


def create_app() -> Flask:
    app = Flask(__name__)

    # init_dblift creates the client, optionally guards at startup time,
    # and stores it at app.extensions["dblift"] for later access (e.g. in routes).
    # guard=True (default) blocks app creation / startup if pending migrations exist.
    # Use guard=False if you prefer to apply via the CLI / deploy step below.
    client = init_dblift(app, engine, migrations_dir, guard=True)

    # Wire the CLI command. After this, `flask --app yourmodule:create_app dblift-migrate`
    # (or FLASK_APP=...) will run client.migrate() when invoked.
    register_cli(app, client)

    return app


app = create_app()
```

Run the web app as usual:

```
flask --app your_app:create_app run
```

If you start (or import the factory) with pending migrations and the default guard, the app will fail to initialize with a clear error telling you to run migrations.

## CLI migration command

After `register_cli`, the command is available:

```
flask --app your_app:create_app dblift-migrate
```

This is the explicit trigger that calls `client.migrate()`. Use it from CI, deploy scripts, or manually when the guard (or health) reports pending work.

## Guard usage and explicit migrate

- Pass `guard=True` (the default) to `init_dblift` when you want the web / WSGI startup path to refuse to run against a stale schema.
- The guard only reads (via `client.info()`). It never writes or migrates.
- To actually apply, either:
  - Run the registered CLI command above, or
  - Explicitly (from a protected admin route, one-off script, or deploy step):

```python
with DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations_dir) as client:
    client.migrate()
```

Never automatically call migrate() inside a web request handler unless you have deliberately chosen that for your app.

If using `guard=True` you may find that even the Flask CLI loader refuses to start when pending (because it loads your create_app). In that case either:
- Temporarily use `guard=False` when you know you are about to run the migrate command, or
- Create a separate client + `register_cli(app, client)` without going through the guarded `init_dblift`, or
- Control the guard value via environment variable inside your factory.

## Accessing the client from routes / other code

```python
@app.route("/health")
def health():
    client = app.extensions.get("dblift")
    if client is None:
        return {"error": "dblift not initialized"}, 500
    # You can build your own small payload or import the generic helpers:
    # from integrations.fastapi import health_payload
    # return health_payload(client)
    info = client.info()
    return {"current": len(getattr(info, "pending_migrations", [])) == 0}
```

## Sync-only limitation (v1)

These helpers (and `DBLiftClient.from_sqlalchemy`) work with **sync SQLAlchemy Engine / Connection only**.

There is no `AsyncEngine` support in v1. If you use async Flask patterns (or Quart etc.) + async SQLAlchemy, create the engine in a thread-friendly way and run the (sync) guard / info / migrate calls via a thread pool or `concurrent.futures` from your factory / CLI code.

Follow-up work may add an async variant in a later version; the current design keeps the core substrate and helpers deliberately thin and sync.

## Notes

- `init_dblift(app, engine, migrations_dir, *, guard=True) -> DBLiftClient`
- `register_cli(app, client) -> None` — adds the `dblift-migrate` command.
- Package the feature with `pip install "dblift[flask]"` (declares the optional dep `flask>=2.3`).
- The pattern is deliberately minimal / thin — no magic, no auto-migrate on import, full control left to the caller.
