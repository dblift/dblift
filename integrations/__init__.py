"""Thin framework integration helpers for DBLift (e.g. FastAPI lifespan guards).

These are deliberately read-only thin wrappers. They only ever call
client.info() (or equivalent) to inspect pending state. They never invoke
migrate() unless the *caller* explicitly does so.

Public surface (re-exported):
- check_migrations_current
- migration_guard
- health_payload

Flask helpers (init_dblift, register_cli) are deliberately NOT re-exported
here: integrations.flask imports click/flask.cli at module load time, which
would make `import integrations` fail for callers who don't have Flask
installed. Import them from integrations.flask directly.
"""

from __future__ import annotations

from integrations.fastapi import (
    check_migrations_current,
    health_payload,
    migration_guard,
)

__all__ = [
    "check_migrations_current",
    "health_payload",
    "migration_guard",
]
