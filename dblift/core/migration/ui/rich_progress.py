"""Rich adapter for migration progress."""

from contextlib import contextmanager
from typing import Iterator

from .progress import ProgressSink


@contextmanager
def rich_migration_progress(total: int) -> Iterator[ProgressSink]:
    """Keep the CLI's existing Rich progress display."""
    from rich.progress import (
        BarColumn,
        MofNCompleteColumn,
        Progress,
        SpinnerColumn,
        TextColumn,
        TimeElapsedColumn,
    )

    from dblift.core.logger.console import get_stderr_console, is_progress_disabled

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        MofNCompleteColumn(),
        TimeElapsedColumn(),
        console=get_stderr_console(),
        transient=True,
        disable=is_progress_disabled(),
    ) as progress:
        task = progress.add_task("Migrating", total=total)

        class RichProgressSink:
            """Bind the migration loop's progress operations to one Rich task."""

            def describe(self, name: str) -> None:
                """Show the current script name."""
                progress.update(task, description=name)

            def advance(self) -> None:
                """Advance after a successful script."""
                progress.advance(task)

        yield RichProgressSink()
