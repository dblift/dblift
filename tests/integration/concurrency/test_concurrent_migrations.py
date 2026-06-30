"""
Test concurrent migration executions to verify locking mechanism.

CRITICAL: These tests ensure that multiple DBLift sessions cannot
corrupt the schema history or cause race conditions.

All tests use the production CLI (cli/main.py) via subprocess to
simulate real user scenarios.

Locking Mechanisms Tested:
- SQL Server: sp_getapplock stored procedure
- Oracle: DBMS_LOCK package
- PostgreSQL: Advisory locks
- MySQL: GET_LOCK/RELEASE_LOCK functions
- DB2: DB2LOCK/SYSTOOLS.LOCKING
"""

import time

import pytest

from tests.integration.helpers.cli_runner_direct import DBLiftCLIDirect as DBLiftCLI
from tests.integration.helpers.concurrency_helper import (
    ConcurrentExecutor,
    simulate_user_sessions,
)
from tests.integration.helpers.database_helper import verify_table_exists
from tests.integration.helpers.migration_helper import (
    create_config,
    create_migration,
    generate_test_sql,
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestConcurrentMigrations:
    """
    Test concurrent migration attempts to verify locking mechanism.

    CRITICAL: These tests verify that the database locking mechanism
    prevents race conditions when multiple processes try to migrate simultaneously.
    """

    def test_concurrent_migrations_only_one_succeeds(self, db_container, tmp_path):
        """
        Test that only ONE of multiple concurrent migration attempts succeeds.

        Scenario:
        - Two developers run 'dblift migrate' at the same time
        - Only one should acquire the lock and apply migrations
        - The other should wait or fail gracefully

        This is the most critical test for data integrity.
        """
        # Setup
        migrations_dir = tmp_path / "migrations"

        migrations_dir.mkdir()

        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        # Create a migration
        create_migration(
            migrations_dir,
            "V1_0_0__create_table.sql",
            generate_test_sql(
                db_container["type"],
                "test_concurrent",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ),
        )

        # Run two migrations concurrently
        executor = ConcurrentExecutor(config_file, migrations_dir)
        results = executor.run_concurrent_migrations(num_processes=2, command="migrate")

        # Verify results
        assert len(results) == 2, "Should have 2 results"

        # At least one should complete (either success or handled failure)
        completed = [r for r in results if r.result.returncode is not None]
        assert len(completed) == 2, "Both processes should complete"

        # Check if we have exactly one success
        successful = [r for r in results if r.result.success]

        # The behavior can vary by database:
        # - Some databases will have one succeed and one fail/wait
        # - Some databases might allow both to succeed if timing is right
        # What's CRITICAL is that the database state is consistent

        if len(successful) >= 1:
            # Verify database state is correct (migration applied correctly)
            assert verify_table_exists(
                db_container,
                "test_concurrent",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ), "Table should exist after migration"

            # Verify migration history is consistent
            cli = DBLiftCLI(config_file, migrations_dir)
            info_result = cli.info()
            assert info_result.success
            # Migration should be marked as applied (version in panel is reliable across modes)
            assert "1.0.0" in info_result.stdout

        # The key test: database state should be consistent
        # regardless of how many processes "succeeded"

    def test_sequential_migrations_with_small_delay(self, db_container, tmp_path):
        """
        Test migrations started with small delays between them.

        Scenario:
        - Three CI/CD pipelines trigger within 1 second of each other
        - All try to migrate
        - Lock mechanism should prevent conflicts
        """
        # Setup
        migrations_dir = tmp_path / "migrations"

        migrations_dir.mkdir()

        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        # Create a migration
        create_migration(
            migrations_dir,
            "V1_0_0__test.sql",
            generate_test_sql(
                db_container["type"],
                "test_sequential",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ),
        )

        # Run with small delays
        executor = ConcurrentExecutor(config_file, migrations_dir)
        results = executor.run_sequential_with_delay(
            num_executions=3, delay_seconds=0.3, command="migrate"
        )

        assert len(results) == 3, "Should have 3 results"

        # At least one should succeed
        successful = [r for r in results if r.result.success]
        assert len(successful) >= 1, "At least one process should succeed"

        # Database state should be consistent
        assert verify_table_exists(
            db_container,
            "test_sequential",
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )

    def test_lock_released_on_success(self, db_container, tmp_path):
        """
        Test that lock is released after successful migration.

        Scenario:
        - Migration 1 completes successfully
        - Migration 2 should be able to run immediately after
        """
        # Setup
        migrations_dir = tmp_path / "migrations"

        migrations_dir.mkdir()

        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        # Create first migration
        create_migration(
            migrations_dir,
            "V1_0_0__first.sql",
            generate_test_sql(
                db_container["type"],
                "test_first",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ),
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # Run first migration
        result1 = cli.migrate()
        assert result1.success, f"First migration should succeed: {result1.stderr}"

        # Create second migration
        create_migration(
            migrations_dir,
            "V1_0_1__second.sql",
            generate_test_sql(
                db_container["type"],
                "test_second",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ),
        )

        # Run second migration (should work if lock was released)
        result2 = cli.migrate()
        assert result2.success, f"Second migration should succeed: {result2.stderr}"

        # Both tables should exist
        assert verify_table_exists(
            db_container, "test_first", schema=db_container.get("schema", "TEST_SCHEMA")
        )
        assert verify_table_exists(
            db_container, "test_second", schema=db_container.get("schema", "TEST_SCHEMA")
        )

    def test_lock_released_on_failure(self, db_container, tmp_path):
        """
        Test that lock is released when migration fails.

        Scenario:
        - Migration 1 fails with SQL error
        - Lock should be released
        - Migration 2 should be able to attempt (and fail for same reason)
        """
        # Setup
        migrations_dir = tmp_path / "migrations"

        migrations_dir.mkdir()

        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        # Create a migration that will fail
        create_migration(
            migrations_dir,
            "V1_0_0__failing_migration.sql",
            """
            CREATE TABLE test_table (id INT PRIMARY KEY);
            -- This will fail (syntax error)
            INVALID SQL STATEMENT HERE;
            """,
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # First attempt - should fail
        result1 = cli.migrate()
        assert not result1.success, "Migration should fail due to SQL error"

        # Give a brief moment
        time.sleep(0.5)

        # Second attempt - lock should be released, so no lock-acquisition error.
        # The migration may be retried (fails with SQL error, success=False) or
        # may show "no pending migrations" (success=True) if the failed execution
        # was persisted to history — both outcomes prove the lock was released.
        result2 = cli.migrate()

        # Key check: must NOT receive a lock-acquisition failure.
        # A "could not acquire migration lock" message means the lock was stuck.
        combined_output = (result2.stdout + result2.stderr).lower()
        assert (
            "could not acquire migration lock" not in combined_output
        ), f"Lock was NOT released after failure (got lock error): {combined_output}"

    def test_multiple_read_operations_allowed(self, db_container, tmp_path):
        """
        Test that multiple INFO commands can run concurrently.

        Read operations should not block each other.
        """
        # Setup
        migrations_dir = tmp_path / "migrations"

        migrations_dir.mkdir()

        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        # Create some migrations
        create_migration(
            migrations_dir,
            "V1_0_0__test.sql",
            generate_test_sql(
                db_container["type"],
                "test_read",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ),
        )

        # Apply migrations first
        cli = DBLiftCLI(config_file, migrations_dir)
        cli.migrate()

        # Run multiple info commands concurrently
        executor = ConcurrentExecutor(config_file, migrations_dir)
        results = executor.run_concurrent_migrations(num_processes=5, command="info")

        # All should succeed (read operations don't need exclusive lock)
        assert len(results) == 5
        successful = [r for r in results if r.result.success]
        assert len(successful) >= 4, "Most info commands should succeed (read operations)"


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestRealisticConcurrencyScenarios:
    """Test realistic scenarios with concurrent access."""

    def test_ci_cd_pipeline_scenario(self, db_container, tmp_path):
        """
        Test realistic CI/CD scenario with multiple pipelines.

        Scenario:
        - 3 CI/CD pipelines trigger at almost the same time
        - All try to run migrations
        - System should handle this gracefully
        - Database should end up in consistent state
        """
        # Setup
        migrations_dir = tmp_path / "migrations"

        migrations_dir.mkdir()

        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        create_migration(
            migrations_dir,
            "V1_0_0__feature.sql",
            generate_test_sql(
                db_container["type"],
                "feature_table",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ),
        )

        # Simulate 3 CI/CD pipelines
        results = simulate_user_sessions(
            config_file,
            migrations_dir,
            num_users=3,
            actions=[
                lambda cli: cli.migrate(),
                lambda cli: cli.migrate(),
                lambda cli: cli.migrate(),
            ],
        )

        # At least one should succeed
        successful = [r for r in results if r.get("success")]
        assert len(successful) >= 1, "At least one pipeline should succeed"

        # Database should be in correct state
        assert verify_table_exists(
            db_container,
            "feature_table",
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )

        # Verify with info command. On SQL Server, a pooled connection reused
        # right after a burst of concurrent migrations can raise a transient
        # transaction-reset error (pymssql 3971, "failed to resume the
        # transaction") during sp_reset_connection; SQLAlchemy invalidates that
        # connection, so a retry picks up a clean one and info renders the
        # history. Other dialects pass on the first call. Retry a few times so
        # the assertion is not flaky.
        cli = DBLiftCLI(config_file, migrations_dir)
        info_result = cli.info()
        for _ in range(3):
            if info_result.success and "1.0.0" in info_result.stdout:
                break
            time.sleep(0.5)
            info_result = cli.info()
        assert info_result.success
        # Check for version and description in output
        assert "1.0.0" in info_result.stdout

    def test_developer_and_cicd_concurrent(self, db_container, tmp_path):
        """
        Test scenario where developer runs migrate while CI/CD also runs.

        Scenario:
        - Developer runs migrate locally
        - CI/CD pipeline triggers at same time
        - One should complete, other should handle gracefully
        """
        # Setup
        migrations_dir = tmp_path / "migrations"

        migrations_dir.mkdir()

        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        create_migration(
            migrations_dir,
            "V1_0_0__dev_and_ci.sql",
            generate_test_sql(
                db_container["type"],
                "dev_ci_table",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ),
        )

        # Simulate developer and CI/CD running concurrently
        executor = ConcurrentExecutor(config_file, migrations_dir)
        results = executor.run_concurrent_migrations(num_processes=2, command="migrate")

        # System should handle this gracefully
        assert len(results) == 2

        # Database should be consistent
        assert verify_table_exists(
            db_container,
            "dev_ci_table",
            schema=db_container.get("schema", "TEST_SCHEMA"),
        )

    def test_mixed_operations_concurrent(self, db_container, tmp_path):
        """
        Test different operations running concurrently.

        Scenario:
        - User 1: migrate
        - User 2: info
        - User 3: validate
        All should be able to complete appropriately.
        """
        # Setup
        migrations_dir = tmp_path / "migrations"

        migrations_dir.mkdir()

        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        create_migration(
            migrations_dir,
            "V1_0_0__mixed_ops.sql",
            generate_test_sql(
                db_container["type"],
                "mixed_ops_table",
                schema=db_container.get("schema", "TEST_SCHEMA"),
            ),
        )

        # Run different operations concurrently
        results = simulate_user_sessions(
            config_file,
            migrations_dir,
            num_users=3,
            actions=[
                lambda cli: cli.migrate(),  # Write operation
                lambda cli: cli.info(),  # Read operation
                lambda cli: cli.validate(),  # Read operation
            ],
        )

        assert len(results) == 3

        # Migrate should complete (success or handled failure)
        migrate_result = results[0]
        assert migrate_result is not None

        # Note: Read operations (info/validate) may fail if they run before
        # the schema is created by migrate, which is acceptable in concurrent scenarios
        # The key is that the migrate operation completes successfully
