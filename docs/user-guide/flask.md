# Flask Integration

Install the optional dependency:

```bash
pip install "dblift[flask]"
```

The Flask helpers create a DBLift client, optionally run a read-only startup
guard, and register an explicit migration command.

## App Factory

```python
from flask import Flask
from sqlalchemy import create_engine

from integrations.flask import init_dblift, register_cli

engine = create_engine("postgresql+psycopg://user:password@localhost/app")


def create_app() -> Flask:
    app = Flask(__name__)

    client = init_dblift(
        app,
        engine,
        "migrations",
        guard=True,
    )
    register_cli(app, client)

    return app
```

`init_dblift` stores the client in `app.extensions["dblift"]` and returns it.
With `guard=True`, startup checks for pending migrations using `client.info()`.
The guard does not apply migrations.

## Migration Command

`register_cli` adds:

```bash
flask --app your_app:create_app dblift-migrate
```

Running `flask dblift-migrate` is the explicit action that calls
`client.migrate()`.

## Guard Options

Use `guard=False` when your deploy process runs migrations before the web app is
created, or when the Flask CLI needs to load the app while migrations are still
pending:

```python
client = init_dblift(app, engine, "migrations", guard=False)
```

## Accessing The Client

```python
@app.get("/health")
def health():
    client = app.extensions["dblift"]
    info = client.info()
    return {
        "pending_count": len(getattr(info, "pending_migrations", []) or []),
    }
```

See [Flask Integration Example](../examples/flask-integration.md) for a complete
app factory.
