"""Event system for IDE and tooling integration.

Listeners receive a typed :class:`Event` object — the ``event_type`` and
``timestamp`` are always populated, and the rest of the fields are optional
attributes that the dispatching site may set. Unknown keyword arguments at
emit time raise ``TypeError`` so emit sites cannot silently accumulate
fields the dataclass does not declare.
"""

import contextvars
import logging
import re
import time
from contextlib import contextmanager
from dataclasses import dataclass, fields
from enum import Enum
from functools import lru_cache
from typing import Any, Callable, Dict, Iterator, List, Mapping, Optional, Pattern, Tuple, Union


@lru_cache(maxsize=256)
def _compile_wildcard(pattern: str) -> Pattern[str]:
    """Compile and cache a wildcard event pattern into a regex.

    Patterns are typically registered at :meth:`EventEmitter.on` time and
    then dispatched against many events; caching avoids recompiling the
    same regex on every emit. ``maxsize=256`` is well above the realistic
    number of distinct wildcard subscribers per process.
    """
    regex_pattern = pattern.replace(".", r"\.").replace("*", ".*")
    return re.compile(regex_pattern)


_logger = logging.getLogger(__name__)


class EventType(Enum):
    """Event types for IDE/tooling integration.

    Events are organized by category:
    - Migration: Operation and script-level events
    - Validation: Validation operation and rule-level events
    - Schema: Schema introspection events
    - Connection: Database connection lifecycle
    - History: Migration history operations
    - Operations: Other operations (undo, clean, baseline, repair, info)
    - Export/Snapshot: Export and snapshot operations
    """

    # ===== Migration Events (10 events) =====
    # Operation level
    MIGRATION_STARTED = "migration.started"
    MIGRATION_COMPLETED = "migration.completed"
    MIGRATION_FAILED = "migration.failed"

    # Script level (granular)
    MIGRATION_SCRIPT_STARTED = "migration.script.started"
    # ``MIGRATION_APPLIED`` is the canonical name; ``MIGRATION_SCRIPT_COMPLETED`` is a
    # backward-compatible alias with the same string value. Python enum aliasing means:
    #   * ``EventType.MIGRATION_SCRIPT_COMPLETED is EventType.MIGRATION_APPLIED`` — same object.
    #   * ``EventType.MIGRATION_APPLIED.name == "MIGRATION_APPLIED"`` (canonical).
    #   * Iterating ``EventType`` yields the canonical member once; the alias is not a
    #     separate entry.
    MIGRATION_APPLIED = "migration.script.completed"
    MIGRATION_SCRIPT_COMPLETED = "migration.script.completed"  # backward-compat alias
    MIGRATION_SCRIPT_FAILED = "migration.script.failed"
    MIGRATION_SCRIPT_SKIPPED = "migration.script.skipped"

    # Progress events
    MIGRATION_PROGRESS = "migration.progress"
    MIGRATION_SCRIPT_VALIDATED = "migration.script.validated"
    MIGRATION_SCRIPT_VALIDATION_FAILED = "migration.script.validation_failed"

    # ===== Validation Events (6 events) =====
    # Operation level
    VALIDATION_STARTED = "validation.started"
    VALIDATION_COMPLETED = "validation.completed"
    VALIDATION_FAILED = "validation.failed"

    # Rule level (granular)
    VALIDATION_RULE_CHECKED = "validation.rule.checked"
    VALIDATION_RULE_VIOLATION = "validation.rule.violation"
    VALIDATION_RULE_PASSED = "validation.rule.passed"

    # ===== Schema Events (4 events) =====
    SCHEMA_INTROSPECTION_STARTED = "schema.introspection.started"
    SCHEMA_INTROSPECTION_COMPLETED = "schema.introspection.completed"
    SCHEMA_INTROSPECTION_FAILED = "schema.introspection.failed"
    SCHEMA_OBJECT_DETECTED = "schema.object.detected"

    # ===== Connection & Provider Events (6 events) =====
    CONNECTION_ESTABLISHED = "connection.established"
    CONNECTION_CLOSED = "connection.closed"
    CONNECTION_ERROR = "connection.error"
    PROVIDER_INITIALIZED = "provider.initialized"
    DRIVER_VALIDATION_STARTED = "driver.validation.started"
    DRIVER_VALIDATION_COMPLETED = "driver.validation.completed"
    DRIVER_VALIDATION_FAILED = "driver.validation.failed"

    # ===== History & State Events (4 events) =====
    HISTORY_LOADED = "history.loaded"
    HISTORY_UPDATED = "history.updated"
    STATE_SYNC_STARTED = "state.sync.started"
    STATE_SYNC_COMPLETED = "state.sync.completed"

    # ===== Other Operations (15 events) =====
    # Undo
    UNDO_STARTED = "undo.started"
    UNDO_COMPLETED = "undo.completed"
    UNDO_FAILED = "undo.failed"
    UNDO_SCRIPT_ROLLED_BACK = "undo.script.rolled_back"

    # Clean
    CLEAN_STARTED = "clean.started"
    CLEAN_COMPLETED = "clean.completed"
    CLEAN_FAILED = "clean.failed"
    CLEAN_OBJECT_REMOVED = "clean.object.removed"

    # Baseline
    BASELINE_STARTED = "baseline.started"
    BASELINE_COMPLETED = "baseline.completed"
    BASELINE_FAILED = "baseline.failed"

    # Repair
    REPAIR_STARTED = "repair.started"
    REPAIR_COMPLETED = "repair.completed"
    REPAIR_FAILED = "repair.failed"

    # Info
    INFO_STARTED = "info.started"
    INFO_COMPLETED = "info.completed"
    INFO_FAILED = "info.failed"

    # ===== Export & Snapshot Events (7 events) =====
    # Export
    EXPORT_STARTED = "export.started"
    EXPORT_COMPLETED = "export.completed"
    EXPORT_FAILED = "export.failed"
    EXPORT_OBJECT_EXPORTED = "export.object.exported"
    EXPORT_FILE_WRITTEN = "export.file.written"

    # Snapshot
    SNAPSHOT_STARTED = "snapshot.started"
    SNAPSHOT_COMPLETED = "snapshot.completed"
    SNAPSHOT_LOADED = "snapshot.loaded"
    SNAPSHOT_SAVED = "snapshot.saved"

    # ===== Callback Lifecycle Events (24 events) =====
    # Callback execution (generic)
    CALLBACK_STARTED = "callback.started"
    CALLBACK_COMPLETED = "callback.completed"
    CALLBACK_FAILED = "callback.failed"

    # Migration callbacks
    CALLBACK_BEFORE_MIGRATE = "callback.before_migrate"
    CALLBACK_AFTER_MIGRATE = "callback.after_migrate"
    CALLBACK_AFTER_MIGRATE_ERROR = "callback.after_migrate_error"
    CALLBACK_BEFORE_EACH = "callback.before_each"
    CALLBACK_AFTER_EACH = "callback.after_each"
    CALLBACK_BEFORE_EACH_MIGRATE = "callback.before_each_migrate"
    CALLBACK_AFTER_EACH_MIGRATE = "callback.after_each_migrate"
    CALLBACK_BEFORE_REPEATABLE = "callback.before_repeatable"
    CALLBACK_AFTER_REPEATABLE = "callback.after_repeatable"
    CALLBACK_BEFORE_VERSIONED = "callback.before_versioned"
    CALLBACK_AFTER_VERSIONED = "callback.after_versioned"

    # Validation callbacks
    CALLBACK_BEFORE_VALIDATE = "callback.before_validate"
    CALLBACK_AFTER_VALIDATE = "callback.after_validate"
    CALLBACK_BEFORE_EACH_VALIDATE = "callback.before_each_validate"
    CALLBACK_AFTER_EACH_VALIDATE = "callback.after_each_validate"

    # Clean callbacks
    CALLBACK_BEFORE_CLEAN = "callback.before_clean"
    CALLBACK_AFTER_CLEAN = "callback.after_clean"
    CALLBACK_AFTER_CLEAN_ERROR = "callback.after_clean_error"
    CALLBACK_BEFORE_EACH_CLEAN = "callback.before_each_clean"
    CALLBACK_AFTER_EACH_CLEAN = "callback.after_each_clean"

    # Undo callbacks
    CALLBACK_BEFORE_UNDO = "callback.before_undo"
    CALLBACK_AFTER_UNDO = "callback.after_undo"
    CALLBACK_AFTER_UNDO_ERROR = "callback.after_undo_error"


@dataclass(frozen=True)
class Event:
    """Typed payload delivered to event listeners.

    ``event_type`` and ``timestamp`` are always populated. Every other
    attribute is optional and defaults to ``None`` — only the subset that
    the dispatching site provides is set. The full union of fields below
    matches every emit callsite in the codebase; adding a new field at an
    emit site must be reflected here so the dataclass stays the single
    source of truth for the event contract.
    """

    event_type: EventType
    timestamp: float

    # ----- Common operation context (used across multiple event types) -----
    operation: Optional[str] = None
    target_version: Optional[str] = None
    dry_run: Optional[bool] = None
    show_sql: Optional[bool] = None
    tags: Optional[str] = None
    error: Optional[str] = None
    result: Any = None
    summary: Any = None

    # ----- Migration-script-level fields -----
    script: Optional[str] = None
    version: Optional[str] = None
    description: Optional[str] = None
    type: Optional[str] = None
    execution_time: Optional[float] = None

    # ----- Generation / undo / introspection -----
    dialect: Optional[str] = None
    migration_path: Optional[str] = None
    count: Optional[int] = None
    migrations_applied: Optional[List[Any]] = None
    results: Optional[List[Any]] = None
    success_count: Optional[int] = None
    failure_count: Optional[int] = None


def _event_field_names() -> frozenset[str]:
    """Return all attribute names the :class:`Event` dataclass declares."""
    return frozenset(f.name for f in fields(Event))


_EVENT_FIELD_NAMES = _event_field_names()
# ``event_type`` and ``timestamp`` are owned by the emitter — they are
# populated from the call signature and the clock, never from the
# emit-site payload. Listing them here lets ``_build_event`` reject them
# with a clear error instead of falling through to the dataclass
# constructor and raising the cryptic "got multiple values for argument".
_RESERVED_EVENT_FIELDS = frozenset({"event_type", "timestamp"})
_ASSIGNABLE_EVENT_FIELDS = _EVENT_FIELD_NAMES - _RESERVED_EVENT_FIELDS


class EventEmitter:
    """Event emitter for real-time updates to IDE/tooling.

    Supports:
    - Exact event matching
    - Wildcard patterns (e.g., "migration.script.*", "*.started")
    - Event history (optional)
    - Event batching (optional)

    Listeners receive a typed :class:`Event` instance — never a raw dict.
    """

    def __init__(self, keep_history: bool = False):
        """Initialize event emitter.

        Args:
            keep_history: If True, keep a history of all emitted events
        """
        self._listeners: Dict[str, List[Callable[[Event], None]]] = {}
        self._wildcard_listeners: List[Tuple[str, Callable[[Event], None]]] = []
        self.keep_history = keep_history
        self._history: Optional[List[Event]] = [] if keep_history else None
        self._batch_mode = False
        self._batched_events: List[Event] = []
        # Set by ``stop_batch`` so a reentrant call from a listener during
        # ``flush_batch`` suppresses the post-loop batch-mode restore.
        self._batch_stopped_during_flush = False

    def on(self, event: Union[str, EventType], callback: Callable[[Event], None]) -> None:
        """Register event listener.

        Supports wildcard patterns:
        - "migration.script.*" - All script-level migration events
        - "*.started" - All started events
        - "*.completed" - All completed events

        Args:
            event: Event type (string or EventType enum), supports wildcards
            callback: Callback function that receives a typed :class:`Event`
        """
        event_str = event.value if isinstance(event, EventType) else event

        # Check if it's a wildcard pattern
        if "*" in event_str:
            self._wildcard_listeners.append((event_str, callback))
        else:
            if event_str not in self._listeners:
                self._listeners[event_str] = []
            self._listeners[event_str].append(callback)

    def off(self, event: Union[str, EventType], callback: Callable[[Event], None]) -> None:
        """Unregister event listener.

        Args:
            event: Event type (string or EventType enum)
            callback: Callback function to remove
        """
        event_str = event.value if isinstance(event, EventType) else event

        # Remove from exact listeners
        if event_str in self._listeners:
            try:
                self._listeners[event_str].remove(callback)
            except ValueError:
                pass  # Callback not in list

        # Remove from wildcard listeners
        self._wildcard_listeners = [
            (pattern, cb)
            for pattern, cb in self._wildcard_listeners
            if not (pattern == event_str and cb == callback)
        ]

    # Batch-6 BUG-05: ``subscribe``/``unsubscribe`` are the naming conventions
    # used by RxJS, blinker and many Node.js EventEmitter wrappers. Provide
    # them as aliases for ``on``/``off`` so API consumers coming from those
    # ecosystems don't hit an ``AttributeError`` on their first call.
    def subscribe(self, event: Union[str, EventType], callback: Callable[[Event], None]) -> None:
        """Alias for :meth:`on` — register an event listener."""
        self.on(event, callback)

    def unsubscribe(self, event: Union[str, EventType], callback: Callable[[Event], None]) -> None:
        """Alias for :meth:`off` — unregister an event listener."""
        self.off(event, callback)

    def _matches_wildcard(self, pattern: str, event_str: str) -> bool:
        """Check if event matches wildcard pattern.

        Args:
            pattern: Wildcard pattern (e.g., "migration.script.*", "*.started")
            event_str: Event string to match

        Returns:
            True if event matches pattern
        """
        if "*" not in pattern:
            return pattern == event_str

        # Pattern → compiled regex, cached so a wildcard registered at
        # ``on()`` time pays the regex compilation cost once even when
        # dispatched against thousands of script-level events (one per
        # migration file). ``re.fullmatch`` (rather than ``re.match`` without
        # an end anchor) prevents partial matches: ``"*.started"`` must not
        # match ``"migration.started.extra"``.
        return bool(_compile_wildcard(pattern).fullmatch(event_str))

    def _build_event(
        self, event: Union[str, EventType], data: Optional[Mapping[str, Any]]
    ) -> Event:
        """Construct a typed :class:`Event` from ``event`` + ``data`` kwargs.

        Raises:
            ValueError: when ``event`` is a string that does not correspond
                to any :class:`EventType` member.
            TypeError: when ``data`` contains a key not declared on
                :class:`Event` — emit sites must surface new fields by
                adding them to the dataclass, not by silently passing
                arbitrary kwargs.
        """
        if isinstance(event, EventType):
            event_type = event
        else:
            event_type = EventType(event)

        # ``is not None`` (not bare truthiness) so that an explicitly
        # empty dict from the caller is preserved as ``{}`` instead of
        # being silently coerced through the ``data is None`` branch.
        kwargs = dict(data) if data is not None else {}
        reserved = set(kwargs).intersection(_RESERVED_EVENT_FIELDS)
        if reserved:
            raise TypeError(
                f"Reserved Event fields cannot be passed in emit() data for "
                f"{event_type.name}: {sorted(reserved)}. The emitter populates "
                f"these from the call signature and the clock."
            )
        unknown = set(kwargs).difference(_ASSIGNABLE_EVENT_FIELDS)
        if unknown:
            raise TypeError(
                f"Unknown Event fields for {event_type.name}: {sorted(unknown)}. "
                f"Add them to api.events.Event before emitting."
            )

        return Event(event_type=event_type, timestamp=self._get_timestamp(), **kwargs)

    def emit(self, event: Union[str, EventType], data: Optional[Mapping[str, Any]] = None) -> None:
        """Emit event to all registered listeners.

        Args:
            event: Event type (string or EventType enum)
            data: Mapping of fields to populate on :class:`Event`. Each key
                must be a declared field name on :class:`Event`; unknown
                keys raise ``TypeError``.
        """
        payload = self._build_event(event, data)

        # Add event to history if enabled
        if self.keep_history and self._history is not None:
            self._history.append(payload)

        # Batch events if in batch mode — defer dispatch until flush_batch.
        if self._batch_mode:
            self._batched_events.append(payload)
            return

        self._dispatch(payload)

    def _handle_listener_error(self, event_str: str, error: Exception) -> None:
        """Handle listener errors without breaking execution.

        Args:
            event_str: Event string
            error: Exception that occurred
        """
        _logger.error(f"Event listener error for {event_str}: {error}")

    def _get_timestamp(self) -> float:
        """Get current timestamp.

        Returns:
            Current timestamp as float
        """
        return time.time()

    def clear(self, event: Union[str, EventType, None] = None) -> None:
        """Clear event listeners.

        Args:
            event: Event type to clear (None clears all)
        """
        if event is None:
            self._listeners.clear()
            self._wildcard_listeners.clear()
        else:
            event_str = event.value if isinstance(event, EventType) else event
            self._listeners.pop(event_str, None)
            self._wildcard_listeners = [
                (pattern, cb) for pattern, cb in self._wildcard_listeners if pattern != event_str
            ]

    def get_history(self) -> List[Event]:
        """Get event history.

        Returns:
            List of :class:`Event` instances in dispatch order.
        """
        if not self.keep_history or self._history is None:
            return []
        return list(self._history)

    def clear_history(self) -> None:
        """Clear event history."""
        if self._history is not None:
            self._history.clear()

    def start_batch(self) -> None:
        """Start batching events. Events will be collected until stop_batch() is called."""
        self._batch_mode = True
        self._batched_events.clear()
        self._batch_stopped_during_flush = False

    def stop_batch(self) -> List[Event]:
        """Stop batching events and return all batched events.

        Returns:
            List of :class:`Event` instances captured during batching.
        """
        self._batch_mode = False
        self._batch_stopped_during_flush = True
        batched = list(self._batched_events)
        self._batched_events.clear()
        return batched

    def flush_batch(self) -> None:
        """Emit all batched events immediately."""
        if not self._batch_mode:
            return

        batched = list(self._batched_events)
        self._batched_events.clear()
        # Disable batch mode before dispatching so that any events emitted by
        # listeners during the flush are dispatched immediately rather than
        # appended to the cleared ``_batched_events`` and silently dropped.
        self._batch_mode = False
        self._batch_stopped_during_flush = False
        try:
            for event in batched:
                self._dispatch(event)
        finally:
            # Restore batch mode so callers using flush_batch as a periodic
            # drain (start_batch → emit → flush_batch → emit more → stop_batch)
            # keep batching subsequent events. Skip the restore when a
            # listener called ``stop_batch`` during dispatch — that caller's
            # intent to leave batch mode wins.
            if not self._batch_stopped_during_flush:
                self._batch_mode = True

    def _dispatch(self, payload: Event) -> None:
        """Send ``payload`` to exact + wildcard listeners. Internal helper."""
        event_str = payload.event_type.value
        for callback in self._listeners.get(event_str, []):
            try:
                callback(payload)
            except Exception as e:
                self._handle_listener_error(event_str, e)
        for pattern, callback in self._wildcard_listeners:
            if self._matches_wildcard(pattern, event_str):
                try:
                    callback(payload)
                except Exception as e:
                    self._handle_listener_error(event_str, e)


_default_emitter: Optional[EventEmitter] = None


def get_default_emitter() -> EventEmitter:
    """Return the process-wide default ``EventEmitter``.

    Used as a fallback bus for core-layer code that runs outside any active
    ``DBLiftClient`` scope. When a client is executing an operation, the
    client binds its own per-instance emitter (see :func:`use_client_emitter`)
    and core-layer events route there instead — preserving per-client event
    isolation.
    """
    global _default_emitter
    if _default_emitter is None:
        _default_emitter = EventEmitter()
    return _default_emitter


# BUG-06 (batch 6 follow-up): per-client event isolation. ``DBLiftClient``
# owns its own ``EventEmitter`` and binds it to this context variable for the
# duration of each public operation. ``emit_event`` (called from the core
# layer) reads the bound emitter so script-level events land on the emitter
# the user subscribed to, not on a process-wide singleton shared by every
# client instance.
_active_client_emitter: "contextvars.ContextVar[Optional[EventEmitter]]" = contextvars.ContextVar(
    "dblift_active_client_emitter", default=None
)


@contextmanager
def use_client_emitter(emitter: Optional["EventEmitter"]) -> Iterator[None]:
    """Bind ``emitter`` as the active emitter for the enclosing block.

    ``emit_event`` in the core layer will dispatch to ``emitter`` instead of
    the process-wide default while the block is executing. When ``emitter``
    is ``None`` the block is a no-op — callers pass ``self.events`` directly
    without worrying about the optional case.
    """
    if emitter is None:
        yield
        return
    token = _active_client_emitter.set(emitter)
    try:
        yield
    finally:
        _active_client_emitter.reset(token)


def emit_event(event: Union[str, EventType], data: Optional[Mapping[str, Any]] = None) -> None:
    """Emit ``event`` on the active client emitter, falling back to the default.

    When called from inside a ``DBLiftClient`` operation (which wraps its body
    in :func:`use_client_emitter`), events land on that client's per-instance
    emitter. Outside a client scope the process-wide default is used so
    stand-alone core-layer callers still have a functional bus.
    """
    emitter = _active_client_emitter.get() or get_default_emitter()
    emitter.emit(event, data)
