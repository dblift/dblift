"""Compose CLI presentation without making library operations depend on the CLI."""

from contextlib import contextmanager
from typing import Iterator

from dblift.core.migration.ui.command_presentation import CommandPresentation


@contextmanager
def command_presentation(client: object) -> Iterator[None]:
    """Bind this operation's adapter and restore it on every return or exception."""
    engine = getattr(getattr(client, "executor", None), "execution_engine", None)
    if engine is None:
        yield
        return
    previous = vars(engine).get("_presentation")
    was_bound = "_presentation" in vars(engine)
    engine._presentation = CommandPresentation()
    try:
        yield
    finally:
        if was_bound:
            engine._presentation = previous
        else:
            del engine._presentation
