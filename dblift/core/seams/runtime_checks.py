"""Registry of runtime checks contributed by higher tiers.

OSS core calls :func:`run_checks` at defined points; with nothing
registered these are no-ops. Installed higher tiers register their
license verification here at package import, via the ``dblift.features``
entry-point loader. Check callables raise to abort the operation.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Callable, DefaultDict, List

_CHECKS: DefaultDict[str, List[Callable[[], None]]] = defaultdict(list)


def register_check(point: str, check: Callable[[], None]) -> None:
    """Register *check* to run whenever :func:`run_checks` is called for *point*."""
    _CHECKS[point].append(check)


def run_checks(point: str) -> None:
    """Run all checks registered for *point*, in registration order."""
    for check in _CHECKS.get(point, ()):
        check()


def registered_checks(point: str) -> tuple[Callable[[], None], ...]:
    """Snapshot of the checks registered for *point* (introspection hook)."""
    return tuple(_CHECKS.get(point, ()))


def clear_checks() -> None:
    """Test hook."""
    _CHECKS.clear()
