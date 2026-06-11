"""Unit tests for event system."""

import pytest

from api.events import Event, EventEmitter, EventType


@pytest.mark.unit
class TestEventEmitter:
    """Unit tests for EventEmitter."""

    def test_emit_single_listener(self):
        """Test emitting event to single listener."""
        emitter = EventEmitter()
        received_data = []

        def listener(event):
            received_data.append(event)

        emitter.on(EventType.MIGRATION_STARTED, listener)
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1.0.0"})

        assert len(received_data) == 1
        assert isinstance(received_data[0], Event)
        assert received_data[0].event_type is EventType.MIGRATION_STARTED
        assert received_data[0].version == "1.0.0"

    def test_emit_migration_started_accepts_show_sql(self):
        """Show-SQL is part of operation event metadata."""
        emitter = EventEmitter()
        received_data = []

        emitter.on(EventType.MIGRATION_STARTED, received_data.append)
        emitter.emit(EventType.MIGRATION_STARTED, {"show_sql": True})

        assert len(received_data) == 1
        assert received_data[0].show_sql is True

    def test_emit_multiple_listeners(self):
        """Test emitting event to multiple listeners."""
        emitter = EventEmitter()
        received_data = []

        def listener1(event):
            received_data.append(("listener1", event.version))

        def listener2(event):
            received_data.append(("listener2", event.version))

        emitter.on(EventType.MIGRATION_STARTED, listener1)
        emitter.on(EventType.MIGRATION_STARTED, listener2)
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1.0.0"})

        assert len(received_data) == 2
        assert ("listener1", "1.0.0") in received_data
        assert ("listener2", "1.0.0") in received_data

    def test_emit_string_event_type(self):
        """Test emitting event with string event type."""
        emitter = EventEmitter()
        received_data = []

        def listener(event):
            received_data.append(event)

        emitter.on("migration.started", listener)
        emitter.emit("migration.started", {"version": "1.0.0"})

        assert len(received_data) == 1
        assert received_data[0].version == "1.0.0"

    def test_off_remove_listener(self):
        """Test removing event listener."""
        emitter = EventEmitter()
        received_data = []

        def listener(event):
            received_data.append(event)

        emitter.on(EventType.MIGRATION_STARTED, listener)
        emitter.off(EventType.MIGRATION_STARTED, listener)
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1.0.0"})

        assert len(received_data) == 0

    def test_off_nonexistent_listener(self):
        """Test removing nonexistent listener (should not error)."""
        emitter = EventEmitter()

        def listener(event):
            pass

        # Should not raise error
        emitter.off(EventType.MIGRATION_STARTED, listener)

    def test_clear_all_events(self):
        """Test clearing all event listeners."""
        emitter = EventEmitter()
        received_data = []

        def listener(event):
            received_data.append(event)

        emitter.on(EventType.MIGRATION_STARTED, listener)
        emitter.on(EventType.MIGRATION_COMPLETED, listener)
        emitter.clear()
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1.0.0"})
        emitter.emit(EventType.MIGRATION_COMPLETED, {"version": "1.0.0"})

        assert len(received_data) == 0

    def test_clear_specific_event(self):
        """Test clearing listeners for specific event."""
        emitter = EventEmitter()
        received_data = []

        def listener(event):
            received_data.append(event)

        emitter.on(EventType.MIGRATION_STARTED, listener)
        emitter.on(EventType.MIGRATION_COMPLETED, listener)
        emitter.clear(EventType.MIGRATION_STARTED)
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1.0.0"})
        emitter.emit(EventType.MIGRATION_COMPLETED, {"version": "1.0.0"})

        assert len(received_data) == 1
        assert received_data[0].version == "1.0.0"

    def test_listener_error_handling(self):
        """Test that listener errors don't break execution."""
        emitter = EventEmitter()
        received_data = []

        def error_listener(event):
            raise ValueError("Listener error")

        def good_listener(event):
            received_data.append(event)

        emitter.on(EventType.MIGRATION_STARTED, error_listener)
        emitter.on(EventType.MIGRATION_STARTED, good_listener)
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1.0.0"})

        # Good listener should still receive event
        assert len(received_data) == 1
        assert received_data[0].version == "1.0.0"

    def test_no_listeners(self):
        """Test emitting event with no listeners (should not error)."""
        emitter = EventEmitter()
        # Should not raise error
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1.0.0"})

    def test_emit_no_data_uses_defaults(self):
        """Emitting without a data dict produces an Event with default Nones."""
        emitter = EventEmitter()
        received = []
        emitter.on(EventType.VALIDATION_STARTED, received.append)
        emitter.emit(EventType.VALIDATION_STARTED)
        assert len(received) == 1
        assert received[0].event_type is EventType.VALIDATION_STARTED
        assert received[0].error is None

    def test_emit_unknown_field_raises(self):
        """Unknown payload keys must surface immediately, not silently drop."""
        emitter = EventEmitter()
        with pytest.raises(TypeError, match="Unknown Event fields"):
            emitter.emit(EventType.MIGRATION_STARTED, {"this_is_not_a_field": True})

    def test_emit_rejects_reserved_event_type_field(self):
        """``event_type`` is owned by the emitter; passing it via data must
        produce a clear error, not a cryptic ``multiple values for argument``."""
        emitter = EventEmitter()
        with pytest.raises(TypeError, match="Reserved Event fields"):
            emitter.emit(EventType.MIGRATION_STARTED, {"event_type": "spoofed"})

    def test_emit_rejects_reserved_timestamp_field(self):
        """``timestamp`` is populated from the clock; passing it via data must
        produce a clear error rather than collide with the keyword argument."""
        emitter = EventEmitter()
        with pytest.raises(TypeError, match="Reserved Event fields"):
            emitter.emit(EventType.MIGRATION_STARTED, {"timestamp": 0.0})

    def test_flush_batch_records_history_exactly_once(self):
        """Events emitted in batch mode are recorded to history at emit time
        (before the batch queue). ``flush_batch`` only re-dispatches to
        listeners — it must not double-record.
        """
        emitter = EventEmitter(keep_history=True)
        emitter.start_batch()
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1"})
        emitter.flush_batch()
        history = emitter.get_history()
        assert len(history) == 1
        assert history[0].version == "1"

    def test_flush_batch_dispatches_events_emitted_by_listeners(self):
        """A listener that calls ``emit()`` during ``flush_batch`` must have
        its event dispatched immediately, not appended to the cleared
        ``_batched_events`` queue and silently dropped.
        """
        emitter = EventEmitter()
        received: list = []

        def reentrant_listener(event):
            received.append(("primary", event.event_type))
            if event.event_type is EventType.MIGRATION_STARTED:
                emitter.emit(EventType.MIGRATION_COMPLETED, {"version": event.version})

        def secondary_listener(event):
            received.append(("secondary", event.event_type))

        emitter.on(EventType.MIGRATION_STARTED, reentrant_listener)
        emitter.on(EventType.MIGRATION_COMPLETED, reentrant_listener)
        emitter.on(EventType.MIGRATION_COMPLETED, secondary_listener)

        emitter.start_batch()
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1"})
        emitter.flush_batch()

        assert ("primary", EventType.MIGRATION_STARTED) in received
        assert ("primary", EventType.MIGRATION_COMPLETED) in received
        assert ("secondary", EventType.MIGRATION_COMPLETED) in received

    def test_flush_batch_preserves_batch_mode_for_periodic_drain(self):
        """``flush_batch`` is used as a periodic drain — events emitted
        between ``flush_batch()`` and ``stop_batch()`` must continue to be
        batched, not dispatched immediately.
        """
        emitter = EventEmitter()
        dispatched: list = []
        emitter.on(EventType.MIGRATION_STARTED, lambda e: dispatched.append(e.version))

        emitter.start_batch()
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1"})
        emitter.flush_batch()
        assert dispatched == ["1"]

        emitter.emit(EventType.MIGRATION_STARTED, {"version": "2"})
        # Still in batch mode → second event must be queued, not dispatched.
        assert dispatched == ["1"]
        assert emitter._batch_mode is True

        batched = emitter.stop_batch()
        assert [e.version for e in batched] == ["2"]

    def test_flush_batch_respects_stop_batch_called_by_listener(self):
        """A listener that calls ``stop_batch()`` during ``flush_batch``
        signals intent to leave batch mode. The post-loop restore must not
        silently re-enable batching against the caller's wishes.
        """
        emitter = EventEmitter()

        def stopper(event):
            emitter.stop_batch()

        emitter.on(EventType.MIGRATION_STARTED, stopper)

        emitter.start_batch()
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1"})
        emitter.flush_batch()

        assert emitter._batch_mode is False

        dispatched: list = []
        emitter.on(EventType.MIGRATION_COMPLETED, lambda e: dispatched.append(e.version))
        emitter.emit(EventType.MIGRATION_COMPLETED, {"version": "2"})
        assert dispatched == ["2"]

    def test_start_batch_clears_stop_during_flush_flag(self):
        """``stop_batch`` outside a flush still sets the internal flag.
        ``start_batch`` must clear it so the next ``flush_batch`` cycle
        does not inherit a stale value.
        """
        emitter = EventEmitter()
        emitter.start_batch()
        emitter.stop_batch()
        assert emitter._batch_stopped_during_flush is True

        emitter.start_batch()
        assert emitter._batch_stopped_during_flush is False


@pytest.mark.unit
class TestEventType:
    """Unit tests for EventType enum."""

    def test_event_type_values(self):
        """Test that EventType has expected values."""
        assert EventType.MIGRATION_STARTED.value == "migration.started"
        assert EventType.MIGRATION_COMPLETED.value == "migration.completed"
        assert EventType.MIGRATION_FAILED.value == "migration.failed"
        assert EventType.VALIDATION_STARTED.value == "validation.started"
        assert EventType.VALIDATION_COMPLETED.value == "validation.completed"
        assert EventType.SCHEMA_INTROSPECTION_STARTED.value == "schema.introspection.started"


@pytest.mark.unit
class TestEventDataclass:
    """The :class:`Event` dataclass is the single source of truth for the
    payload contract — emit sites and consumers both speak through it.
    """

    def test_required_fields_only(self):
        """Constructing with just event_type + timestamp leaves the rest None."""
        e = Event(event_type=EventType.VALIDATION_STARTED, timestamp=0.0)
        assert e.event_type is EventType.VALIDATION_STARTED
        assert e.timestamp == 0.0
        assert e.error is None
        assert e.result is None

    def test_is_frozen(self):
        """Events are immutable so listener stacks cannot mutate them."""
        e = Event(event_type=EventType.MIGRATION_FAILED, timestamp=0.0, error="boom")
        with pytest.raises(Exception):  # FrozenInstanceError on dataclass
            e.error = "different"  # type: ignore[misc]

    def test_failure_event_carries_error(self):
        e = Event(event_type=EventType.MIGRATION_FAILED, timestamp=0.0, error="oops")
        assert e.error == "oops"

    def test_migration_applied_alias_resolves_to_canonical(self):
        """``MIGRATION_APPLIED`` is an enum alias for ``MIGRATION_SCRIPT_COMPLETED``."""
        assert EventType.MIGRATION_APPLIED is EventType.MIGRATION_SCRIPT_COMPLETED
        e = Event(event_type=EventType.MIGRATION_APPLIED, timestamp=0.0)
        assert e.event_type is EventType.MIGRATION_SCRIPT_COMPLETED

    def test_migrations_applied_field_holds_a_list(self):
        """``MIGRATION_COMPLETED`` payloads pass the ``MigrateResult``'s
        ``migrations_applied`` list (e.g. ``[Migration(...), ...]``), so the
        dataclass field must accept a list — not an int.
        """
        e = Event(
            event_type=EventType.MIGRATION_COMPLETED,
            timestamp=0.0,
            migrations_applied=["V1__a.sql", "V2__b.sql"],
        )
        assert e.migrations_applied == ["V1__a.sql", "V2__b.sql"]
        assert isinstance(e.migrations_applied, list)
