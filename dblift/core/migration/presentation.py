"""Internal optional presentation selection; hosts need only the existing Log API."""

from typing import TYPE_CHECKING, Optional, cast

from dblift.core.logger import DbliftLogger, Log
from dblift.core.logger.log import ConsoleLog, FileLog, MultiLog

if TYPE_CHECKING:
    from dblift.core.migration.ui.command_presentation import CommandPresentation


def _has_presentation_sink(log: Log) -> bool:
    """Recognize concrete sinks through existing MultiLog composition."""
    return isinstance(log, (ConsoleLog, FileLog, DbliftLogger)) or (
        isinstance(log, MultiLog) and any(_has_presentation_sink(sink) for sink in log.logs)
    )


def presentation_for(
    engine: object, log: Log, *, requested: bool = False
) -> Optional["CommandPresentation"]:
    """Return explicit composition or the compatibility adapter for concrete sinks."""
    if engine is not None and "_presentation" in vars(engine):
        return cast("Optional[CommandPresentation]", vars(engine)["_presentation"])
    if requested or _has_presentation_sink(log):
        from dblift.core.migration.ui.command_presentation import CommandPresentation

        return CommandPresentation()
    return None
