"""Thin Flask integration helpers (app factory + CLI registration).

Follows the same thin/read-only philosophy as the FastAPI helpers:
- init_dblift creates the client via DBLiftClient.from_sqlalchemy (reusing caller's Engine),
  optionally runs a guard (which only ever calls client.info()), wires the client
  onto app.extensions["dblift"], and returns it.
- register_cli wires a Click-based Flask CLI command. Invoking the command is
  what calls client.migrate(); nothing in the wiring or init auto-applies migrations.

Intended usage (app factory):
    from flask import Flask
    from sqlalchemy import create_engine
    from api import DBLiftClient
    from integrations.flask import init_dblift, register_cli

    engine = create_engine(...)
    app = Flask(__name__)
    client = init_dblift(app, engine, "migrations", guard=True)
    register_cli(app, client)

The guard (when enabled) and all read paths are info()-only. Use the registered
CLI command (or explicit client.migrate() elsewhere) to apply.

Sync-only limitation (v1): DBLiftClient + these helpers use sync SQLAlchemy
Engine/Connection exclusively. No AsyncEngine support in v1.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from api import DBLiftClient

if TYPE_CHECKING:
    from flask import Flask
    from sqlalchemy import Engine

import click
from flask.cli import with_appcontext


def init_dblift(
    app: Flask, engine: Engine, migrations_dir: str, *, guard: bool = True
) -> DBLiftClient:
    """Wire a DBLiftClient into a Flask app and optionally guard at init time.

    Creates the client with DBLiftClient.from_sqlalchemy (caller owns the Engine),
    calls migration_guard (read-only) if guard=True (default raises on pending),
    stores the client at app.extensions["dblift"], and returns the client.

    Thin: guard (if any) only inspects via client.info(). The caller / CLI command
    is responsible for calling migrate() explicitly when desired.
    """
    client = DBLiftClient.from_sqlalchemy(engine, migrations_dir=migrations_dir)

    if guard:
        from .fastapi import migration_guard

        try:
            migration_guard(client)
        except Exception:
            client.close()
            raise

    app.extensions["dblift"] = client

    return client


def register_cli(app: Flask, client: DBLiftClient) -> None:
    """Register a Flask CLI command that calls client.migrate() on invocation.

    After calling this, `flask dblift-migrate` (or equivalent via FLASK_APP)
    will apply pending migrations using the provided client.
    """

    @click.command("dblift-migrate")
    @with_appcontext
    def dblift_migrate() -> None:
        """Apply pending DBLift migrations."""
        client.migrate()

    app.cli.add_command(dblift_migrate)
