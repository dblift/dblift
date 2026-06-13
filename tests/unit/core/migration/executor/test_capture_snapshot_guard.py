"""Regression test: ``_capture_snapshot`` must only skip NoSQL providers.

The BUG-COSMOS-1 fix introduced a guard that excluded CosmosDB from snapshot
capture. A too-broad guard form — ``isinstance(provider, TransactionalProvider)
and provider.supports_transactions()`` — would also skip any SQL provider that
happened to not inherit from the ``TransactionalProvider`` protocol class
(e.g. SQLite, which is fully transactional but uses a separate provider branch).

Guard intent: skip only when the provider explicitly declares
``supports_transactions() == False``. SQL providers (default True) must proceed.
"""

from unittest.mock import MagicMock

import pytest

from core.migration.executor.migration_executor import MigrationExecutor


def _make_executor_with_provider(provider):
    """Build a minimal MigrationExecutor with just what _capture_snapshot needs."""
    executor = MigrationExecutor.__new__(MigrationExecutor)
    executor.provider = provider
    executor.snapshot_service = MagicMock()
    executor.log = MagicMock()
    return executor


@pytest.mark.unit
class TestCaptureSnapshotGuard:
    def test_sql_provider_without_transactional_protocol_still_captures(self):
        """A SQL provider that supports transactions must NOT be skipped,
        even if it does not inherit from TransactionalProvider."""
        provider = MagicMock(spec=["supports_transactions"])
        provider.supports_transactions.return_value = True

        executor = _make_executor_with_provider(provider)
        result = MagicMock(success=True)

        executor._capture_snapshot("migrate", result=result)

        executor.snapshot_service.capture_snapshot.assert_called_once()

    def test_cosmos_like_provider_is_skipped(self):
        """A provider that declares supports_snapshots() → False must be skipped."""
        provider = MagicMock(spec=["supports_snapshots"])
        provider.supports_snapshots.return_value = False

        executor = _make_executor_with_provider(provider)
        result = MagicMock(success=True)

        executor._capture_snapshot("migrate", result=result)

        executor.snapshot_service.capture_snapshot.assert_not_called()

    def test_provider_with_supports_snapshots_false_is_skipped(self):
        """A provider declaring supports_snapshots() → False must be skipped,
        even if supports_transactions() → True."""
        provider = MagicMock(spec=["supports_transactions", "supports_snapshots"])
        provider.supports_transactions.return_value = True
        provider.supports_snapshots.return_value = False

        executor = _make_executor_with_provider(provider)
        result = MagicMock(success=True)

        executor._capture_snapshot("migrate", result=result)

        executor.snapshot_service.capture_snapshot.assert_not_called()

    def test_provider_with_supports_snapshots_true_and_no_transactions_still_captures(self):
        """CosmosDB post-fix: supports_transactions()=False but supports_snapshots()=True
        must proceed with snapshot capture."""
        provider = MagicMock(spec=["supports_transactions", "supports_snapshots"])
        provider.supports_transactions.return_value = False
        provider.supports_snapshots.return_value = True

        executor = _make_executor_with_provider(provider)
        result = MagicMock(success=True)

        executor._capture_snapshot("migrate", result=result)

        executor.snapshot_service.capture_snapshot.assert_called_once()

    def test_provider_without_supports_transactions_still_captures(self):
        """A provider missing the method entirely is assumed SQL-capable
        (defensive — matches default behavior of BaseProvider hierarchy)."""
        provider = MagicMock(spec=[])  # no methods exposed

        executor = _make_executor_with_provider(provider)
        result = MagicMock(success=True)

        executor._capture_snapshot("migrate", result=result)

        executor.snapshot_service.capture_snapshot.assert_called_once()

    def test_failed_result_skips_regardless_of_provider(self):
        """Pre-existing behavior: failed operations never capture snapshots."""
        provider = MagicMock(spec=["supports_transactions"])
        provider.supports_transactions.return_value = True

        executor = _make_executor_with_provider(provider)
        failed = MagicMock(success=False)

        executor._capture_snapshot("migrate", result=failed)

        executor.snapshot_service.capture_snapshot.assert_not_called()

    def test_snapshot_capture_failure_adds_user_visible_warning(self):
        provider = MagicMock(spec=["supports_snapshots"])
        provider.supports_snapshots.return_value = True

        executor = _make_executor_with_provider(provider)
        executor.snapshot_service.capture_snapshot.side_effect = RuntimeError("ServiceUnavailable")
        result = MagicMock(success=True)

        executor._capture_snapshot("migrate", result=result)

        result.add_warning.assert_called_once()
        warning = result.add_warning.call_args[0][0]
        assert "Failed to capture schema snapshot after migrate" in warning
        assert "database-stored" in warning
