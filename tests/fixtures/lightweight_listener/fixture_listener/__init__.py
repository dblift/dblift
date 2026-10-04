"""Independent installed event registrar."""

from dblift.api.events import EventType

EVENTS = []


def register(emitter):
    emitter.on(EventType.MIGRATION_COMPLETED, EVENTS.append)
    emitter.on(EventType.MIGRATION_FAILED, EVENTS.append)
