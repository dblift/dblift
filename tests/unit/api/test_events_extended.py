"""Extended tests for api/events.py."""

import unittest
from unittest.mock import MagicMock

from dblift.api.events import Event, EventEmitter, EventType


class TestEventEmitterOn(unittest.TestCase):
    def _make(self):
        return EventEmitter(keep_history=True)

    def test_on_registers_callback(self):
        emitter = self._make()
        cb = MagicMock()
        emitter.on(EventType.MIGRATION_STARTED, cb)
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1.0"})
        cb.assert_called_once()

    def test_off_unregisters_callback(self):
        emitter = self._make()
        cb = MagicMock()
        emitter.on(EventType.MIGRATION_STARTED, cb)
        emitter.off(EventType.MIGRATION_STARTED, cb)
        emitter.emit(EventType.MIGRATION_STARTED, {})
        cb.assert_not_called()

    def test_emit_passes_event(self):
        emitter = self._make()
        received = []
        emitter.on(EventType.MIGRATION_SCRIPT_STARTED, received.append)
        emitter.emit(EventType.MIGRATION_SCRIPT_STARTED, {"script": "V1__a.sql"})
        self.assertIsInstance(received[0], Event)
        self.assertEqual(received[0].script, "V1__a.sql")

    def test_subscribe_alias(self):
        emitter = self._make()
        cb = MagicMock()
        emitter.subscribe(EventType.MIGRATION_STARTED, cb)
        emitter.emit(EventType.MIGRATION_STARTED, {})
        cb.assert_called_once()

    def test_unsubscribe_alias(self):
        emitter = self._make()
        cb = MagicMock()
        emitter.subscribe(EventType.MIGRATION_STARTED, cb)
        emitter.unsubscribe(EventType.MIGRATION_STARTED, cb)
        emitter.emit(EventType.MIGRATION_STARTED, {})
        cb.assert_not_called()


class TestEventEmitterHistory(unittest.TestCase):
    def _make(self):
        return EventEmitter(keep_history=True)

    def test_records_history(self):
        emitter = self._make()
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1"})
        history = emitter.get_history()
        self.assertGreater(len(history), 0)
        self.assertIsInstance(history[0], Event)
        self.assertEqual(history[0].version, "1")

    def test_clear_history(self):
        emitter = self._make()
        emitter.emit(EventType.MIGRATION_STARTED, {})
        emitter.clear_history()
        self.assertEqual(emitter.get_history(), [])

    def test_no_history_when_disabled(self):
        emitter = EventEmitter(keep_history=False)
        emitter.emit(EventType.MIGRATION_STARTED, {})
        self.assertEqual(emitter.get_history(), [])


class TestEventEmitterClear(unittest.TestCase):
    def test_clear_specific_event(self):
        emitter = EventEmitter()
        cb = MagicMock()
        emitter.on(EventType.MIGRATION_STARTED, cb)
        emitter.on(EventType.MIGRATION_COMPLETED, cb)
        emitter.clear(EventType.MIGRATION_STARTED)
        emitter.emit(EventType.MIGRATION_STARTED, {})
        emitter.emit(EventType.MIGRATION_COMPLETED, {})
        # MIGRATION_STARTED cleared, MIGRATION_COMPLETED should still fire
        cb.assert_called_once()

    def test_clear_all(self):
        emitter = EventEmitter()
        cb = MagicMock()
        emitter.on(EventType.MIGRATION_STARTED, cb)
        emitter.on(EventType.MIGRATION_COMPLETED, cb)
        emitter.clear()
        emitter.emit(EventType.MIGRATION_STARTED, {})
        emitter.emit(EventType.MIGRATION_COMPLETED, {})
        cb.assert_not_called()


class TestEventEmitterBatch(unittest.TestCase):
    def test_start_stop_batch(self):
        emitter = EventEmitter()
        emitter.start_batch()
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1"})
        emitter.emit(EventType.MIGRATION_COMPLETED, {})
        events = emitter.stop_batch()
        self.assertEqual(len(events), 2)
        for evt in events:
            self.assertIsInstance(evt, Event)

    def test_flush_batch(self):
        emitter = EventEmitter()
        cb = MagicMock()
        emitter.on(EventType.MIGRATION_STARTED, cb)
        emitter.start_batch()
        emitter.emit(EventType.MIGRATION_STARTED, {"version": "1"})
        emitter.flush_batch()
        cb.assert_called()


class TestWildcardMatch(unittest.TestCase):
    def _make(self):
        return EventEmitter()

    def test_exact_match(self):
        emitter = self._make()
        self.assertTrue(emitter._matches_wildcard("event.start", "event.start"))

    def test_wildcard_match(self):
        emitter = self._make()
        self.assertTrue(emitter._matches_wildcard("event.*", "event.start"))

    def test_no_match(self):
        emitter = self._make()
        self.assertFalse(emitter._matches_wildcard("other.*", "event.start"))


class TestGetDefaultEmitter(unittest.TestCase):
    def test_returns_emitter(self):
        from dblift.api.events import get_default_emitter

        emitter = get_default_emitter()
        self.assertIsInstance(emitter, EventEmitter)

    def test_returns_same_instance(self):
        from dblift.api.events import get_default_emitter

        e1 = get_default_emitter()
        e2 = get_default_emitter()
        self.assertIs(e1, e2)


class TestEmitEvent(unittest.TestCase):
    def test_emit_event_no_crash(self):
        from dblift.api.events import emit_event

        # Should not crash even with no listeners.
        emit_event(EventType.MIGRATION_APPLIED, {"version": "1.0"})

    def test_emit_event_unknown_string_raises(self):
        """Strings that do not correspond to an EventType member must raise
        ValueError instead of being silently emitted."""
        from dblift.api.events import emit_event

        with self.assertRaises(ValueError):
            emit_event("not.a.real.event", {})
