"""OpenTelemetry span instrumentation for DBLift, driven off the event bus.

Opt-in and per-client::

    from dblift.integrations.opentelemetry import instrument
    handle = instrument(client)   # registers listeners on client.events
    ...
    handle.uninstrument()         # detach

API-only: requires ``opentelemetry-api`` (the ``dblift[otel]`` extra). The host
application owns the SDK + exporter; spans attach to the current OTel context.
"""

from __future__ import annotations

import logging
from contextvars import Token
from typing import TYPE_CHECKING, Callable, List, Tuple

from opentelemetry import context as otel_context
from opentelemetry import trace
from opentelemetry.context import Context
from opentelemetry.trace import Span, Status, StatusCode

from dblift.api.events import Event, EventType

if TYPE_CHECKING:
    from dblift.api import DBLiftClient

_log = logging.getLogger(__name__)

_START_EVENTS = (
    "migration.started",
    "migration.script.started",
    "validation.started",
    "info.started",
    "undo.started",
    "clean.started",
    "baseline.started",
    "repair.started",
)
_END_EVENTS = (
    "migration.completed",
    "migration.failed",
    "migration.script.completed",
    "migration.script.failed",
    "validation.completed",
    "validation.failed",
    "info.completed",
    "info.failed",
    "undo.completed",
    "undo.failed",
    "clean.completed",
    "clean.failed",
    "baseline.completed",
    "baseline.failed",
    "repair.completed",
    "repair.failed",
)
_FAIL_EVENTS = frozenset(e for e in _END_EVENTS if e.endswith(".failed"))

# Sub-operation events (callback lifecycle, per-object clean, per-script undo
# rollback) that don't get their own span — they're recorded as timestamped
# events on the currently active span instead, so tracing UIs aren't flooded
# with one span per callback/object.
_SPAN_MARKER_EVENTS = frozenset(e.value for e in EventType if e.value.startswith("callback.")) | {
    "clean.object.removed",
    "undo.script.rolled_back",
}

_MARKER_ATTR_FIELDS = ("name", "script", "type", "count", "error")

_ATTR_FIELDS = (
    "operation",
    "target_version",
    "version",
    "script",
    "description",
    "type",
    "count",
    "success_count",
    "failure_count",
    "dry_run",
    "execution_time",
)


def _span_name(event: Event) -> str:
    et = event.event_type.value
    if et == "migration.script.started":
        return "dblift.script"
    if et == "migration.started":
        return f"dblift.{event.operation or 'migrate'}"
    if et == "undo.started":
        return "dblift.undo"
    if et == "clean.started":
        return "dblift.clean"
    if et == "baseline.started":
        return "dblift.baseline"
    if et == "repair.started":
        return "dblift.repair"
    if et == "validation.started":
        return "dblift.validate"
    return "dblift.info"


def _set_attrs(span: Span, event: Event) -> None:
    if event.dialect:
        span.set_attribute("db.system", event.dialect)
    for field in _ATTR_FIELDS:
        value = getattr(event, field, None)
        if value is not None:
            span.set_attribute(f"dblift.{field}", value)


def _marker_attrs(event: Event) -> dict:
    return {
        f"dblift.{field}": value
        for field in _MARKER_ATTR_FIELDS
        if (value := getattr(event, field, None)) is not None
    }


def _dblift_version() -> str:
    try:
        from importlib.metadata import version

        return version("dblift")
    except Exception:
        return "unknown"


class OtelHandle:
    """Tracks active spans for one instrumented client; supports teardown."""

    def __init__(self, client: "DBLiftClient", tracer: trace.Tracer) -> None:
        self._client = client
        self._tracer = tracer
        self._stack: List[Tuple[Span, Token[Context], str]] = []  # span, token, name
        self._registered: List[Tuple[str, Callable[[Event], None]]] = []

    def _on_event(self, event: Event) -> None:
        try:
            et = event.event_type.value
            if et in _START_EVENTS:
                span = self._tracer.start_span(_span_name(event))
                _set_attrs(span, event)
                token = otel_context.attach(trace.set_span_in_context(span))
                self._stack.append((span, token, _span_name(event)))
            elif et in _END_EVENTS:
                if not self._stack:
                    return
                # Defensive drain: if a top-level op end (e.g. migration.failed) arrives while
                # a script child span is still open (missing script.*.failed in some error paths),
                # close the leaked child first as ERROR so nesting stays correct. ``undo`` also
                # emits migration.script.* child events for each rolled-back script.
                if et in (
                    "migration.completed",
                    "migration.failed",
                    "undo.completed",
                    "undo.failed",
                ):
                    while self._stack and self._stack[-1][2] == "dblift.script":
                        child, child_token, _ = self._stack.pop()
                        _set_attrs(child, event)
                        child.set_status(
                            Status(
                                StatusCode.ERROR,
                                event.error or "leaked script span (missing script end event)",
                            )
                        )
                        otel_context.detach(child_token)
                        child.end()
                span, token, _ = self._stack.pop()
                _set_attrs(span, event)
                if et in _FAIL_EVENTS or event.failure_count or event.error:
                    span.set_status(Status(StatusCode.ERROR, event.error or ""))
                else:
                    span.set_status(Status(StatusCode.OK))
                otel_context.detach(token)
                span.end()
            elif et in _SPAN_MARKER_EVENTS and self._stack:
                self._stack[-1][0].add_event(et, attributes=_marker_attrs(event))
        except Exception as exc:  # telemetry must never break the engine
            _log.debug("dblift otel listener error: %s", exc)

    def uninstrument(self) -> None:
        for event_str, cb in self._registered:
            self._client.events.off(event_str, cb)
        self._registered.clear()


def instrument(client: "DBLiftClient") -> OtelHandle:
    """Register OTel span listeners on ``client.events``. Returns a handle."""
    tracer = trace.get_tracer("dblift", _dblift_version())
    handle = OtelHandle(client, tracer)
    for event_str in (*_START_EVENTS, *_END_EVENTS, *_SPAN_MARKER_EVENTS):
        client.events.on(event_str, handle._on_event)
        handle._registered.append((event_str, handle._on_event))
    return handle
