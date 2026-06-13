"""Thin FastAPI (and similar) integration helpers.

These are *read-only* on top of DBLiftClient. They call client.info() to
determine pending state and never apply migrations themselves.

Intended usage:
- migration_guard(...) inside a FastAPI lifespan to block startup until
  the DB is current for the migrations_dir configured on the client.
- check_migrations_current(...) and health_payload(...) for /health or
  debug endpoints (or to decide whether to show maintenance banners).

All three helpers are synchronous. See docs for AsyncEngine notes.

Sync-only limitation (v1): DBLiftClient + these helpers use sync SQLAlchemy
Engine/Connection exclusively. No AsyncEngine support in v1. For async
web frameworks run the guard via thread pool / to_thread if necessary.
"""

from __future__ import annotations

import warnings
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from api import DBLiftClient

from core.exceptions import DbliftError


def _pending_ids_from_info(info: Any) -> list[str]:
    """Build pending migration identifiers from an InfoResult.

    The strings are the migration "ids" (primarily script names, with version
    info when useful) so callers can log or surface them in health responses.
    """
    # Use the documented property that already filters status == PENDING
    pending = getattr(info, "pending_migrations", []) or []
    ids: list[str] = []
    for m in pending:
        script = getattr(m, "script", "")
        version = getattr(m, "version", None)
        desc = getattr(m, "description", "") or ""
        if version is not None:
            ver = str(version)
            if desc and desc not in (ver, script):
                ids.append(f"{ver} - {desc}")
            else:
                ids.append(ver if not script else script)
        else:
            ids.append(script or str(m))
    return ids


def check_migrations_current(client: DBLiftClient) -> list[str]:
    """Return list of pending migration identifiers (scripts or versioned ids).

    Returns [] when the database is fully current for the client's migrations_dir.

    Thin: only calls client.info(); performs no writes or migration application.
    """
    info = client.info()
    return _pending_ids_from_info(info)


def migration_guard(
    client: DBLiftClient, *, on_pending: Literal["raise", "warn", "ignore"] = "raise"
) -> None:
    """Inspect pending migrations and act according to on_pending.

    - "raise" (default): raises DbliftError listing the pending items. This is
      the normal choice inside a lifespan to prevent the app from starting
      against a stale schema.
    - "warn": emits a warnings.warn (visible to logging config) but continues.
    - "ignore": no-op.

    Thin: only reads via client.info(). The caller remains responsible for
    actually calling client.migrate() (e.g. from a deploy step or admin route).
    """
    if on_pending == "ignore":
        return

    pending = check_migrations_current(client)
    if not pending:
        return

    msg = f"Pending DBLift migrations: {pending}. Apply with client.migrate() or adjust on_pending."

    if on_pending == "warn":
        warnings.warn(msg, UserWarning, stacklevel=2)
        return
    # "raise" (or any other value falls to raise for safety)
    raise DbliftError(msg)


def health_payload(client: DBLiftClient) -> dict:
    """Return a small read-only health dict suitable for /health endpoints.

    Example shape:
        {
            "pending_migrations": [...],   # [] when current
            "current": True,
            "current_schema_version": "1" or None,
            "pending_count": 0,
        }

    Never has side effects. Does not call migrate().
    """
    info = client.info()
    pending = _pending_ids_from_info(info)
    current = len(pending) == 0
    return {
        "pending_migrations": pending,
        "current": current,
        "current_schema_version": getattr(info, "current_schema_version", None),
        "pending_count": len(pending),
    }
