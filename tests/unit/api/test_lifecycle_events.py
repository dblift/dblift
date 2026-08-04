"""Issue #823: undo/clean/baseline/repair must emit their own dedicated
EventType members (UNDO_*/CLEAN_*/BASELINE_*/REPAIR_*), not the generic
MIGRATION_* events with an ``operation`` discriminator.

``EventType`` already declares ``UNDO_STARTED``/``UNDO_COMPLETED``/
``UNDO_FAILED`` and the equivalent ``CLEAN_*``/``BASELINE_*``/``REPAIR_*``
members, but api.client.DBLiftClient never emitted them — a listener
subscribed to e.g. ``EventType.CLEAN_STARTED`` received nothing when
``clean()`` was called, even though the command completed successfully.
"""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from api.events import EventType


def _make_client(executor_method: str, result: MagicMock) -> "DBLiftClient":  # noqa: F821
    """Build a minimal DBLiftClient stub for event-emission tests."""
    from api.client import DBLiftClient

    provider = MagicMock()
    provider.supports_transactions.return_value = False

    executor = MagicMock()
    getattr(executor, executor_method).return_value = result

    client = DBLiftClient.__new__(DBLiftClient)
    client.provider = provider
    client.executor = executor
    client.events = MagicMock()
    client._get_scripts_dir = lambda: "migrations"
    return client


def _make_failing_client(executor_method: str, exc: Exception) -> "DBLiftClient":  # noqa: F821
    from api.client import DBLiftClient

    provider = MagicMock()
    provider.supports_transactions.return_value = False

    executor = MagicMock()
    getattr(executor, executor_method).side_effect = exc

    client = DBLiftClient.__new__(DBLiftClient)
    client.provider = provider
    client.executor = executor
    client.events = MagicMock()
    client._get_scripts_dir = lambda: "migrations"
    return client


@pytest.mark.unit
class TestCleanEvents:
    def test_clean_success_emits_clean_started_and_completed(self):
        result = MagicMock()
        result.success = True

        client = _make_client("clean", result)
        client.clean()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.CLEAN_STARTED in emitted
        assert EventType.CLEAN_COMPLETED in emitted
        assert EventType.MIGRATION_STARTED not in emitted
        assert EventType.MIGRATION_COMPLETED not in emitted

    def test_clean_soft_failure_emits_failed_not_completed(self):
        """Issue #848: executor.clean() returning success=False (without
        raising) must emit CLEAN_FAILED, not CLEAN_COMPLETED."""
        result = MagicMock()
        result.success = False
        result.error_message = "Clean disabled by config"

        client = _make_client("clean", result)
        client.clean()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.CLEAN_FAILED in emitted
        assert EventType.CLEAN_COMPLETED not in emitted

    def test_clean_exception_emits_clean_failed(self):
        client = _make_failing_client("clean", RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            client.clean()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.CLEAN_STARTED in emitted
        assert EventType.CLEAN_FAILED in emitted
        assert EventType.MIGRATION_FAILED not in emitted


@pytest.mark.unit
class TestBaselineEvents:
    def test_baseline_success_emits_baseline_started_and_completed(self):
        result = MagicMock()
        result.success = True

        client = _make_client("baseline", result)
        client.baseline(version="1.0.0")

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.BASELINE_STARTED in emitted
        assert EventType.BASELINE_COMPLETED in emitted
        assert EventType.MIGRATION_STARTED not in emitted
        assert EventType.MIGRATION_COMPLETED not in emitted

    def test_baseline_soft_failure_emits_failed_not_completed(self):
        """Issue #848: executor.baseline() returning success=False (without
        raising) must emit BASELINE_FAILED, not BASELINE_COMPLETED."""
        result = MagicMock()
        result.success = False
        result.error_message = "Schema history table already has entries"

        client = _make_client("baseline", result)
        client.baseline(version="1.0.0")

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.BASELINE_FAILED in emitted
        assert EventType.BASELINE_COMPLETED not in emitted

    def test_baseline_exception_emits_baseline_failed(self):
        client = _make_failing_client("baseline", RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            client.baseline(version="1.0.0")

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.BASELINE_STARTED in emitted
        assert EventType.BASELINE_FAILED in emitted
        assert EventType.MIGRATION_FAILED not in emitted


@pytest.mark.unit
class TestRepairEvents:
    def test_repair_success_emits_repair_started_and_completed(self):
        result = MagicMock()
        result.success = True

        client = _make_client("repair", result)
        client.repair()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.REPAIR_STARTED in emitted
        assert EventType.REPAIR_COMPLETED in emitted
        assert EventType.MIGRATION_STARTED not in emitted
        assert EventType.MIGRATION_COMPLETED not in emitted

    def test_repair_soft_failure_emits_failed_not_completed(self):
        """Issue #848: executor.repair() returning success=False (without
        raising) must emit REPAIR_FAILED, not REPAIR_COMPLETED."""
        result = MagicMock()
        result.success = False
        result.error_message = "No mismatched checksums to repair"

        client = _make_client("repair", result)
        client.repair()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.REPAIR_FAILED in emitted
        assert EventType.REPAIR_COMPLETED not in emitted

    def test_repair_exception_emits_repair_failed(self):
        client = _make_failing_client("repair", RuntimeError("boom"))

        with pytest.raises(RuntimeError):
            client.repair()

        emitted = [call.args[0] for call in client.events.emit.call_args_list]
        assert EventType.REPAIR_STARTED in emitted
        assert EventType.REPAIR_FAILED in emitted
        assert EventType.MIGRATION_FAILED not in emitted
