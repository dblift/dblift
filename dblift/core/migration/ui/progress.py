"""Internal migration progress selection."""

from contextlib import contextmanager
from typing import Iterator, Protocol

from dblift.core.logger import Log, NullLog


class ProgressSink(Protocol):
    """Minimal progress operations required by the migration loop."""

    def describe(self, name: str) -> None:
        """Name the migration currently being executed."""
        ...

    def advance(self) -> None:
        """Record one successfully completed migration."""
        ...


class NullProgress:
    """Discard progress updates for a silent logger."""

    def describe(self, name: str) -> None:
        """Ignore the current migration name."""
        pass

    def advance(self) -> None:
        """Ignore a completed migration."""
        pass


@contextmanager
def migration_progress(log: Log, total: int) -> Iterator[ProgressSink]:
    """Select silent or Rich progress for the existing logger."""
    if isinstance(log, NullLog):
        yield NullProgress()
    else:
        from .rich_progress import rich_migration_progress

        with rich_migration_progress(total) as sink:
            yield sink
