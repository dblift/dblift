"""
Integration tests for Cosmos DB provider.

These tests validate that Cosmos DB provider works correctly against real Cosmos DB instances.
They test connection, query execution, migration history, and container operations.

Prerequisites:
- Azure Cosmos DB Emulator running in Docker (see tests/integration/docker-compose.yml)
  OR
- External Cosmos DB instance configured via environment variables:
  - DBLIFT_COSMOSDB_ENDPOINT
  - DBLIFT_COSMOSDB_KEY
  - DBLIFT_COSMOSDB_DATABASE

Usage:
    # Run all Cosmos DB integration tests
    pytest tests/integration/db/test_cosmosdb_integration.py -v

    # Run with external Cosmos DB instance
    DBLIFT_COSMOSDB_ENDPOINT=https://your-account.documents.azure.com:443/ \
    DBLIFT_COSMOSDB_KEY=your-key \
    DBLIFT_COSMOSDB_DATABASE=testdb \
    pytest tests/integration/db/test_cosmosdb_integration.py -v
"""

import datetime
from pathlib import Path

import pytest

from config import DbliftConfig
from core.logger import DbliftLogger, LogFormat, LogLevel
from db.plugins.cosmosdb.provider import CosmosDbProvider
from db.provider_registry import ProviderRegistry


@pytest.mark.integration
class TestCosmosDbIntegration:
    """Integration tests for Cosmos DB provider."""

    def _check_cosmosdb_available(self, cosmosdb_container):
        """Check if CosmosDB is available, skip test if not."""
        if "_skip_reason" in cosmosdb_container:
            pytest.skip(cosmosdb_container["_skip_reason"])

    def test_cosmosdb_connection(self, cosmosdb_container, integration_logger):
        """Test connecting to Cosmos DB."""
        self._check_cosmosdb_available(cosmosdb_container)

        # Build config
        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)

        # Test connection
        connection = provider.create_connection()
        assert connection is not None
        assert provider.is_connected() is True

        # Clean up
        provider.close()

    def test_cosmosdb_query_execution(self, cosmosdb_container, integration_logger):
        """Test executing queries against Cosmos DB."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create a test container
        create_sql = "CREATE CONTAINER test_items (id STRING) WITH (partitionKey='/id')"
        result = provider.execute_statement(create_sql)
        assert result >= 0  # 0 if already exists, 1 if created

        # Wait for container to be ready and verify it exists
        # Use direct container check via schema_operations for more reliable checking
        import time

        max_wait = 10  # Increased wait time for emulator
        wait_interval = 0.5
        waited = 0
        exists = False

        while waited < max_wait:
            # Try multiple methods to check existence
            exists = provider.table_exists("default", "test_items")
            if not exists:
                # Also try direct check via schema operations
                exists = provider.schema_operations.container_exists("test_items")
            if exists:
                break
            time.sleep(wait_interval)
            waited += wait_interval

        # If still not found, list all containers for debugging
        if not exists:
            try:
                database = provider.connection_manager.database
                containers = list(database.list_containers())
                container_names = [c.get("id") for c in containers]
                integration_logger.debug(f"Available containers: {container_names}")
            except Exception:
                pass

        assert (
            exists is True
        ), f"Container test_items should exist but check returned False after {waited}s. Created with result={result}"

        # Insert test data
        insert_sql = "INSERT INTO test_items (id, name, value) VALUES ('1', 'test', 100)"
        result = provider.execute_statement(insert_sql)
        assert result == 1

        # Query test data
        # Cosmos DB SQL API uses c.id or c['id'] syntax
        query_sql = "SELECT * FROM test_items c WHERE c.id = '1'"
        results = provider.execute_query(query_sql)
        assert len(results) == 1
        assert results[0]["id"] == "1"
        assert results[0]["name"] == "test"
        assert results[0]["value"] == 100

        # Clean up
        provider.close()

    def test_cosmosdb_container_exists(self, cosmosdb_container, integration_logger):
        """Test checking if container exists."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create a test container
        create_sql = "CREATE CONTAINER test_exists (id STRING) WITH (partitionKey='/id')"
        result = provider.execute_statement(create_sql)
        assert result >= 0  # 0 if already exists, 1 if created

        # Wait for container to be ready and verify it exists
        import time

        max_wait = 10  # Increased wait time for emulator
        wait_interval = 0.5
        waited = 0
        exists = False

        while waited < max_wait:
            # Try multiple methods to check existence
            exists = provider.table_exists("default", "test_exists")
            if not exists:
                # Also try direct check via schema operations
                exists = provider.schema_operations.container_exists("test_exists")
            if exists:
                break
            time.sleep(wait_interval)
            waited += wait_interval

        # If still not found, list all containers for debugging
        if not exists:
            try:
                database = provider.connection_manager.database
                containers = list(database.list_containers())
                container_names = [c.get("id") for c in containers]
                integration_logger.debug(f"Available containers: {container_names}")
            except Exception:
                pass

        assert (
            exists is True
        ), f"Container test_exists should exist but check returned False after {waited}s. Created with result={result}"

        # Check non-existent container
        exists = provider.table_exists("default", "non_existent")
        assert exists is False

        # Clean up
        provider.close()

    def test_cosmosdb_database_version(self, cosmosdb_container, integration_logger):
        """Test getting database version."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        version = provider.get_database_version()
        assert "Cosmos DB" in version

        # Clean up
        provider.close()

    def test_cosmosdb_migration_lock(self, cosmosdb_container, integration_logger):
        """Test migration locking mechanism."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create lock container
        provider.create_migration_lock_table_if_not_exists("default")

        # Wait a moment for container to be ready
        import time

        time.sleep(0.5)

        # Clean up any existing lock from previous test runs
        try:
            provider.release_migration_lock("default")
        except Exception:
            # Lock might not exist, that's fine
            pass

        # Small delay after cleanup
        time.sleep(0.3)

        # Acquire lock (with shorter timeout for tests)
        acquired = provider.acquire_migration_lock("default", wait_timeout_seconds=10)
        assert acquired is True, "Failed to acquire migration lock"

        # Release lock
        released = provider.release_migration_lock("default")
        assert released is True, "Failed to release migration lock"

        # Clean up
        provider.close()

    def test_cosmosdb_migration_history(self, cosmosdb_container, integration_logger):
        """Test migration history management."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create history container using the proper method (handles conflicts)
        # The method checks existence first and handles conflicts gracefully
        provider.history_manager.create_history_container_if_not_exists(
            "default", "dblift_schema_history"
        )

        # Wait for container to be ready
        import time

        time.sleep(0.5)

        # Record a migration
        migration_info = {
            "version": "1.0.0",
            "description": "test_migration",
            "type": "SQL",
            "script": "V1_0_0__test_migration.sql",
            "checksum": "abc123",
            "execution_time": 100,
            "success": True,
        }
        provider.record_migration("default", migration_info)

        # Get applied migrations
        migrations = provider.get_applied_migrations("default")
        assert len(migrations) >= 1
        assert any(m["version"] == "1.0.0" for m in migrations)

        # Clean up
        provider.close()

    def test_cosmosdb_update_operation(self, cosmosdb_container, integration_logger):
        """Test UPDATE statement execution."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create a test container
        container_name = "test_update"
        create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id')"
        provider.execute_statement(create_sql)

        import time

        time.sleep(0.5)

        # Insert test data
        insert_sql = f"INSERT INTO {container_name} (id, name, status, count) VALUES ('1', 'original', 'active', 10)"
        result = provider.execute_statement(insert_sql)
        assert result == 1

        # Update single field
        update_sql = f"UPDATE {container_name} SET status='inactive' WHERE id='1'"
        result = provider.execute_statement(update_sql)
        assert result == 1

        # Verify update
        query_sql = f"SELECT * FROM {container_name} c WHERE c.id = '1'"
        results = provider.execute_query(query_sql)
        assert len(results) == 1
        assert results[0]["status"] == "inactive"
        assert results[0]["name"] == "original"  # Other fields unchanged

        # Update multiple fields
        update_sql = f"UPDATE {container_name} SET name='updated', count=20 WHERE id='1'"
        result = provider.execute_statement(update_sql)
        assert result == 1

        # Verify multiple updates
        results = provider.execute_query(query_sql)
        assert len(results) == 1
        assert results[0]["name"] == "updated"
        assert results[0]["count"] == 20
        assert results[0]["status"] == "inactive"

        # Update with WHERE clause that matches no documents
        update_sql = f"UPDATE {container_name} SET name='notfound' WHERE id='999'"
        result = provider.execute_statement(update_sql)
        assert result == 0  # No documents updated

        # Clean up
        try:
            provider.schema_operations.delete_container(container_name)
        except Exception:
            pass
        provider.close()

    def test_cosmosdb_delete_operation(self, cosmosdb_container, integration_logger):
        """Test DELETE statement execution."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create a test container
        container_name = "test_delete"
        create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id')"
        provider.execute_statement(create_sql)

        import time

        time.sleep(0.5)

        # Insert multiple test documents
        for i in range(1, 4):
            insert_sql = f"INSERT INTO {container_name} (id, name, value) VALUES ('{i}', 'item{i}', {i * 10})"
            provider.execute_statement(insert_sql)

        # Verify all documents exist
        query_sql = f"SELECT * FROM {container_name} c"
        results = provider.execute_query(query_sql)
        assert len(results) == 3

        # Delete single document
        delete_sql = f"DELETE FROM {container_name} WHERE id='1'"
        result = provider.execute_statement(delete_sql)
        assert result == 1

        # Verify deletion
        results = provider.execute_query(query_sql)
        assert len(results) == 2
        remaining_ids = {r["id"] for r in results}
        assert "1" not in remaining_ids
        assert "2" in remaining_ids
        assert "3" in remaining_ids

        # Delete with WHERE clause that matches no documents
        delete_sql = f"DELETE FROM {container_name} WHERE id='999'"
        result = provider.execute_statement(delete_sql)
        assert result == 0  # No documents deleted

        # Clean up
        try:
            provider.schema_operations.delete_container(container_name)
        except Exception:
            pass
        provider.close()

    def test_cosmosdb_advanced_create_container(self, cosmosdb_container, integration_logger):
        """Test CREATE CONTAINER with advanced options."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        import time

        # Test CREATE CONTAINER with throughput
        container_name = "test_throughput"
        create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id', throughput=400)"
        result = provider.execute_statement(create_sql)
        assert result >= 0
        time.sleep(0.5)

        # Verify container exists
        exists = provider.table_exists("default", container_name)
        assert exists is True

        # Clean up
        try:
            provider.schema_operations.delete_container(container_name)
        except Exception:
            pass

        # Test CREATE CONTAINER with indexing policy
        container_name = "test_indexing"
        indexing_policy = '{"indexingMode":"consistent","automatic":true,"includedPaths":[{"path":"/*"}],"excludedPaths":[{"path":"/\\"_etag\\"/?"}]}'
        create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id', indexingPolicy='{indexing_policy}')"
        result = provider.execute_statement(create_sql)
        assert result >= 0
        time.sleep(0.5)

        # Verify container exists
        exists = provider.table_exists("default", container_name)
        assert exists is True

        # Clean up
        try:
            provider.schema_operations.delete_container(container_name)
        except Exception:
            pass

        # Test CREATE CONTAINER with unique key policy
        container_name = "test_unique"
        unique_key_policy = '{"uniqueKeys":[{"paths":["/email"]}]}'
        create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id', uniqueKeyPolicy='{unique_key_policy}')"
        result = provider.execute_statement(create_sql)
        assert result >= 0
        time.sleep(0.5)

        # Verify container exists
        exists = provider.table_exists("default", container_name)
        assert exists is True

        # Clean up
        try:
            provider.schema_operations.delete_container(container_name)
        except Exception:
            pass

        # Test CREATE CONTAINER with default TTL
        container_name = "test_ttl"
        create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id', defaultTtl=3600)"
        result = provider.execute_statement(create_sql)
        assert result >= 0
        time.sleep(0.5)

        # Verify container exists
        exists = provider.table_exists("default", container_name)
        assert exists is True

        # Clean up
        try:
            provider.schema_operations.delete_container(container_name)
        except Exception:
            pass

        # Test CREATE CONTAINER with multiple options
        container_name = "test_multiple"
        create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id', throughput=400, defaultTtl=7200)"
        result = provider.execute_statement(create_sql)
        assert result >= 0
        time.sleep(0.5)

        # Verify container exists
        exists = provider.table_exists("default", container_name)
        assert exists is True

        # Clean up
        try:
            provider.schema_operations.delete_container(container_name)
        except Exception:
            pass

        provider.close()

    def test_cosmosdb_clean_schema(self, cosmosdb_container, integration_logger):
        """Test clean_schema operation."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create multiple user containers plus dblift-managed internal containers.
        test_containers = ["clean_test1", "clean_test2", "clean_test3"]
        for container_name in test_containers:
            create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id')"
            provider.execute_statement(create_sql)
        provider.create_migration_history_table_if_not_exists("default")
        provider.create_migration_lock_table_if_not_exists("default")
        provider.create_snapshot_table_if_not_exists("default")

        import time

        time.sleep(1)  # Wait for containers to be ready

        # Verify containers exist
        internal_containers = [
            "dblift_schema_history",
            "dblift_migration_lock",
            "dblift_schema_snapshots",
        ]
        all_containers = test_containers + internal_containers
        for container_name in all_containers:
            exists = provider.table_exists("default", container_name)
            assert exists is True, f"Container {container_name} should exist before clean"

        # Run clean_schema
        summary = provider.clean_schema("default")

        # Verify every container is deleted (may take a moment)
        time.sleep(0.5)
        for container_name in all_containers:
            exists = provider.table_exists("default", container_name)
            assert exists is False, f"Container {container_name} should be deleted after clean"

        # Verify summary
        assert summary is not None
        assert len(summary.objects) >= len(
            all_containers
        ), "Summary should record dropped containers"
        assert sorted(obj.name for obj in summary.objects) == sorted(all_containers)

        provider.close()

    def test_cosmosdb_migration_lock_timeout(self, cosmosdb_container, integration_logger):
        """Test lock acquisition timeout when lock is held."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider1 = ProviderRegistry.create_provider(config, integration_logger)
        provider1.create_connection()
        provider1.create_migration_lock_table_if_not_exists("default")

        import time

        time.sleep(0.5)

        # Acquire lock with first provider
        acquired1 = provider1.acquire_migration_lock("default", wait_timeout_seconds=1)
        assert acquired1 is True, "First provider should acquire lock"

        # Try to acquire lock with second provider (should timeout)
        provider2 = ProviderRegistry.create_provider(config, integration_logger)
        provider2.create_connection()
        provider2.create_migration_lock_table_if_not_exists("default")

        acquired2 = provider2.acquire_migration_lock("default", wait_timeout_seconds=2)
        assert acquired2 is False, "Second provider should fail to acquire lock (timeout)"

        # Release lock from first provider
        provider1.release_migration_lock("default")

        # Now second provider should be able to acquire
        acquired2_retry = provider2.acquire_migration_lock("default", wait_timeout_seconds=5)
        assert acquired2_retry is True, "Second provider should acquire lock after release"

        provider2.release_migration_lock("default")
        provider1.close()
        provider2.close()

    def test_cosmosdb_migration_lock_expired(self, cosmosdb_container, integration_logger):
        """Test handling of expired locks."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()
        provider.create_migration_lock_table_if_not_exists("default")

        import time

        time.sleep(0.5)

        # Manually create an expired lock document
        database = provider.connection_manager.database
        lock_container = database.get_container_client("dblift_migration_lock")
        expired_lock = {
            "id": "migration_lock",
            "schema": "default",
            "locked_by": "test@host",
            "locked_at": (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(hours=1)
            ).isoformat(),
            "expires_at": (
                datetime.datetime.now(datetime.timezone.utc) - datetime.timedelta(minutes=1)
            ).isoformat(),
        }
        try:
            lock_container.upsert_item(body=expired_lock)
        except Exception:
            pass  # May already exist

        time.sleep(0.3)

        # Try to acquire lock - should clean up expired lock and succeed
        acquired = provider.acquire_migration_lock("default", wait_timeout_seconds=10)
        assert acquired is True, "Should acquire lock after cleaning up expired lock"

        provider.release_migration_lock("default")
        provider.close()

    def test_cosmosdb_migration_history_duplicate(self, cosmosdb_container, integration_logger):
        """Test recording duplicate migration (should use upsert)."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        provider.history_manager.create_history_container_if_not_exists(
            "default", "dblift_schema_history"
        )

        import time

        time.sleep(0.5)

        migration_info = {
            "version": "1.0.0",
            "description": "test_migration",
            "type": "SQL",
            "script": "V1_0_0__test_migration.sql",
            "checksum": "abc123",
            "execution_time": 100,
            "success": True,
        }

        # Record migration first time
        provider.record_migration("default", migration_info)

        # Record same migration again (should use upsert, not fail)
        provider.record_migration("default", migration_info)

        # Should still have only one migration
        migrations = provider.get_applied_migrations("default")
        assert len([m for m in migrations if m["version"] == "1.0.0"]) == 1

        provider.close()

    def test_cosmosdb_complex_query(self, cosmosdb_container, integration_logger):
        """Test complex queries with JOINs and aggregations."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create test containers
        create_sql1 = "CREATE CONTAINER orders (id STRING) WITH (partitionKey='/id')"
        create_sql2 = "CREATE CONTAINER customers (id STRING) WITH (partitionKey='/id')"
        provider.execute_statement(create_sql1)
        provider.execute_statement(create_sql2)

        import time

        time.sleep(0.5)

        # Insert test data
        provider.execute_statement(
            "INSERT INTO customers (id, name, email) VALUES ('1', 'Alice', 'alice@test.com')"
        )
        provider.execute_statement(
            "INSERT INTO customers (id, name, email) VALUES ('2', 'Bob', 'bob@test.com')"
        )
        provider.execute_statement(
            "INSERT INTO orders (id, customerId, total) VALUES ('1', '1', 100)"
        )
        provider.execute_statement(
            "INSERT INTO orders (id, customerId, total) VALUES ('2', '1', 200)"
        )
        provider.execute_statement(
            "INSERT INTO orders (id, customerId, total) VALUES ('3', '2', 150)"
        )

        # Test aggregation query
        query_sql = "SELECT c.customerId, SUM(c.total) as total FROM orders c GROUP BY c.customerId"
        results = provider.execute_query(query_sql)
        assert len(results) > 0

        # Test query with WHERE and ORDER BY
        query_sql = "SELECT * FROM orders c WHERE c.total > 100 ORDER BY c.total DESC"
        results = provider.execute_query(query_sql)
        assert len(results) > 0

        # Clean up
        try:
            provider.schema_operations.delete_container("orders")
            provider.schema_operations.delete_container("customers")
        except Exception:
            pass
        provider.close()

    def test_cosmosdb_list_containers(self, cosmosdb_container, integration_logger):
        """Test listing all containers."""
        self._check_cosmosdb_available(cosmosdb_container)

        config_dict = {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", "default"),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }

        config = DbliftConfig.from_dict(config_dict)
        provider = ProviderRegistry.create_provider(config, integration_logger)
        provider.create_connection()

        # Create test containers
        test_containers = ["list_test1", "list_test2"]
        for container_name in test_containers:
            create_sql = f"CREATE CONTAINER {container_name} (id STRING) WITH (partitionKey='/id')"
            provider.execute_statement(create_sql)

        import time

        time.sleep(0.5)

        # List containers
        containers = provider.schema_operations.list_containers()
        assert isinstance(containers, list)
        assert len(containers) > 0

        # Verify test containers are in the list
        container_names = [c if isinstance(c, str) else c.get("id", c) for c in containers]
        for test_container in test_containers:
            assert (
                test_container in container_names
            ), f"Container {test_container} should be in list"

        # Clean up
        for container_name in test_containers:
            try:
                provider.schema_operations.delete_container(container_name)
            except Exception:
                pass
        provider.close()
