"""Registry of runtime checks contributed by add-on packages.

OSS core calls :func:`run_checks` at defined points; with nothing
registered these are no-ops. Installed add-on packages register their
checks here at package import, via the ``dblift.features``
entry-point loader. Check callables raise to abort the operation.

``migration.preflight_sql`` runs for migrate/undo SQL and their callbacks,
including direct migration execution. It supplies keyword arguments ``migration``, the
complete prepared ``statements`` list, a connected ``provider``, and the
ordered ``prepared_migrations`` list of (migration, statements) pairs plus
``migration_index``. The batch excludes callbacks and preserves non-SQL
migrations with an empty statements list. Callback checks receive an empty
batch and no index. Execution rechecks receive only the current migration;
previous migrations are then reflected in the live catalog. Checks
may run repeatedly (including after callbacks) and should only inspect state.
Catalog reads should use ``provider.config.database.schema`` explicitly rather
than assuming the connection already uses the configured target schema.
Raise :class:`SqlPreflightError` to refuse SQL without error callbacks.
Application checks do not run during dry-run previews.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, DefaultDict, List

_CHECKS: DefaultDict[str, List[Callable[..., None]]] = defaultdict(list)


def register_check(point: str, check: Callable[..., None]) -> None:
    """Register *check* to run whenever :func:`run_checks` is called for *point*."""
    _CHECKS[point].append(check)


class SqlPreflightError(ValueError):
    """An extension refused SQL before migration execution began."""


def run_checks(point: str, **context: object) -> None:
    """Run all checks registered for *point*, in registration order."""
    for check in _CHECKS.get(point, ()):
        check(**context)


def registered_checks(point: str) -> tuple[Callable[..., None], ...]:
    """Snapshot of the checks registered for *point* (introspection hook)."""
    return tuple(_CHECKS.get(point, ()))


def clear_checks() -> None:
    """Test hook."""
    _CHECKS.clear()
