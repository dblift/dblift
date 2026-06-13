"""BUG-04: ``create_snapshot_table_if_not_exists`` retries on transient errors.

Cosmos DB emulator first-boot returns ServiceUnavailable / 503 for several
seconds. Without retry, the migration body succeeded but the user saw an
ERROR wall ("Failed to create snapshot container …") because the post-migrate
snapshot capture path raised RuntimeError. Retry-with-backoff masks the
transient failure; only a persistent failure surfaces as RuntimeError.
"""

import unittest
from unittest.mock import MagicMock, patch

from db.plugins.cosmosdb.provider import CosmosDbProvider


def _make_provider() -> CosmosDbProvider:
    # CosmosDbProvider.__init__ pulls config-driven components from the
    # azure SDK. Bypass it via __new__ + attribute injection so the test is
    # narrowly scoped to the retry method.
    provider = CosmosDbProvider.__new__(CosmosDbProvider)
    provider.log = MagicMock()
    provider.schema_operations = MagicMock()
    provider.schema_operations.container_exists.return_value = False
    provider.execute_statement = MagicMock()
    return provider


class TestSnapshotRetry(unittest.TestCase):
    def test_succeeds_first_try_no_sleep(self):
        provider = _make_provider()
        with patch("db.plugins.cosmosdb.provider.time.sleep") as sleep_mock:
            provider.create_snapshot_table_if_not_exists("public")

        provider.execute_statement.assert_called_once()
        sleep_mock.assert_not_called()

    def test_retries_on_service_unavailable_then_succeeds(self):
        provider = _make_provider()
        calls = [
            RuntimeError("(ServiceUnavailable) emulator warming up"),
            RuntimeError("ServiceUnavailable retry 2"),
            None,  # success on third attempt
        ]

        def _execute(_sql):
            result = calls.pop(0)
            if isinstance(result, Exception):
                raise result

        provider.execute_statement.side_effect = _execute

        with patch("db.plugins.cosmosdb.provider.time.sleep") as sleep_mock:
            provider.create_snapshot_table_if_not_exists("public")

        self.assertEqual(provider.execute_statement.call_count, 3)
        self.assertEqual(sleep_mock.call_count, 2)
        # Backoff = BASE**attempt with BASE=2.0 → 1.0, 2.0, 4.0, 8.0.
        self.assertEqual(sleep_mock.call_args_list[0].args[0], 1.0)
        self.assertEqual(sleep_mock.call_args_list[1].args[0], 2.0)

    def test_non_transient_failure_raises_immediately(self):
        provider = _make_provider()
        provider.execute_statement.side_effect = RuntimeError("Forbidden: bad auth")

        with patch("db.plugins.cosmosdb.provider.time.sleep") as sleep_mock:
            with self.assertRaises(RuntimeError) as ctx:
                provider.create_snapshot_table_if_not_exists("public")

        self.assertIn("Failed to create snapshot container", str(ctx.exception))
        # Only one execute_statement; no retry; no sleep for non-transient failure.
        self.assertEqual(provider.execute_statement.call_count, 1)
        sleep_mock.assert_not_called()

    def test_existing_container_short_circuits(self):
        provider = _make_provider()
        provider.schema_operations.container_exists.return_value = True

        provider.create_snapshot_table_if_not_exists("public")

        provider.execute_statement.assert_not_called()

    def test_concurrent_create_recognized_after_failure(self):
        provider = _make_provider()
        # First call: container doesn't exist (entry guard). Then create_sql
        # fails, container_exists check after failure returns True (created
        # by a concurrent caller).
        provider.schema_operations.container_exists.side_effect = [False, True]
        provider.execute_statement.side_effect = RuntimeError("Conflict")

        with patch("db.plugins.cosmosdb.provider.time.sleep") as sleep_mock:
            provider.create_snapshot_table_if_not_exists("public")

        # No retry — concurrent create wins.
        provider.execute_statement.assert_called_once()
        sleep_mock.assert_not_called()

    def test_persistent_transient_failure_exhausts_retries_and_raises(self):
        provider = _make_provider()
        provider.execute_statement.side_effect = RuntimeError("ServiceUnavailable")

        with patch("db.plugins.cosmosdb.provider.time.sleep") as sleep_mock:
            with self.assertRaises(RuntimeError):
                provider.create_snapshot_table_if_not_exists("public")

        self.assertEqual(
            provider.execute_statement.call_count,
            provider._SNAPSHOT_CREATE_MAX_RETRIES,
        )
        # Sleeps between attempts: MAX_RETRIES - 1.
        self.assertEqual(sleep_mock.call_count, provider._SNAPSHOT_CREATE_MAX_RETRIES - 1)


if __name__ == "__main__":
    unittest.main()
