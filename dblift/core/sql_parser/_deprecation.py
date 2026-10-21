"""Notices for direct use of legacy parser constructors."""

import warnings
from contextlib import contextmanager
from contextvars import ContextVar
from threading import Lock
from typing import Iterator

_internal_construction: ContextVar[bool] = ContextVar("internal_parser_construction", default=False)
_warned: set[str] = set()
_warned_lock = Lock()


@contextmanager
def internal_parser_construction() -> Iterator[None]:
    """Keep plugin-owned parser construction silent in canonical paths."""
    token = _internal_construction.set(True)
    try:
        yield
    finally:
        _internal_construction.reset(token)


def warn_direct_parser(name: str) -> None:
    """Warn once per process for direct legacy construction only."""
    if _internal_construction.get():
        return
    with _warned_lock:
        if name in _warned:
            return
        _warned.add(name)
    try:
        warnings.warn(
            f"{name} is deprecated for direct construction and will be removed in 5.0; "
            "use StatementSplitter for script splitting, StatementFactsParser for "
            "supported statement analysis, and database introspection for schema models.",
            DeprecationWarning,
            stacklevel=3,
        )
    except BaseException:
        with _warned_lock:
            _warned.remove(name)
        raise
