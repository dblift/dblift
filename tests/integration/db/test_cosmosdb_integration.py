"""
Integration tests for the Cosmos DB provider.

Cosmos DB has no SQL DDL. Containers, throughput, indexing policy, TTL and
documents are changed through ``azure-cosmos`` from a **Python migration**
(``def migrate(context)``), reaching the SDK via ``context.db`` (DatabaseProxy)
and ``context.raw_client`` (CosmosClient). The Cosmos SQL API is read-only:
``SELECT`` runs, every write raises ``NoSqlWriteNotSupportedError``, and a
``.sql`` migration is rejected up front with ``DBLIFT-NOSQL-001``.

See ``docs/user-guide/nosql-python-migrations.md``.

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
import time
from pathlib import Path
from typing import Any, Dict

import pytest
from azure.cosmos import PartitionKey

from config import DbliftConfig
from core.exceptions import NoSqlWriteNotSupportedError
from db.provider_registry import ProviderRegistry
from tests.integration.helpers.cli_runner_direct import DBLiftCLIDirect as DBLiftCLI
from tests.integration.helpers.migration_helper import create_config, create_migration

# Cosmos DB has a single logical schema; dblift addresses it as "default".
SCHEMA = "default"


# ---------------------------------------------------------------------------
# Python migration scripts used as test fixtures
#
# These are written verbatim into the migrations directory, so they are the
# supported authoring model exactly as a user would write it.
# ---------------------------------------------------------------------------

PY_CREATE_USERS = '''
"""Create the users container with an explicit partition key."""

from azure.cosmos import PartitionKey

CONTAINER = "users"
PARTITION_KEY = "/tenant_id"


def migrate(context):
    if context.dry_run:
        context.log.info(f"[DRY-RUN] would create container '{CONTAINER}'")
        return

    context.db.create_container(
        id=CONTAINER,
        partition_key=PartitionKey(path=PARTITION_KEY),
        offer_throughput=400,
    )
    context.log.info(f"Created container '{CONTAINER}'")


def undo(context):
    if context.dry_run:
        context.log.info(f"[DRY-RUN] would delete container '{CONTAINER}'")
        return

    context.db.delete_container(CONTAINER)
    context.log.info(f"Deleted container '{CONTAINER}'")
'''


PY_SET_THROUGHPUT = '''
"""Raise manual throughput on the users container."""


def migrate(context):
    container = context.db.get_container_client("users")
    if context.dry_run:
        context.log.info("[DRY-RUN] would set throughput to 1000 RU/s")
        return

    container.replace_throughput(1000)
    context.log.info("Set throughput to 1000 RU/s")
'''


PY_SET_AUTOSCALE = '''
"""Switch the users container to autoscale throughput."""

from azure.cosmos import ThroughputProperties


def migrate(context):
    container = context.db.get_container_client("users")
    if context.dry_run:
        context.log.info("[DRY-RUN] would set autoscale max to 4000 RU/s")
        return

    container.replace_throughput(ThroughputProperties(auto_scale_max_throughput=4000))
    context.log.info("Set autoscale max throughput to 4000 RU/s")
'''


PY_SET_TTL = '''
"""Enable a default TTL on the users container."""

from azure.cosmos import PartitionKey

TTL_SECONDS = 3600


def migrate(context):
    container = context.db.get_container_client("users")
    properties = container.read()

    if context.dry_run:
        context.log.info(f"[DRY-RUN] would set default TTL to {TTL_SECONDS}s")
        return

    context.db.replace_container(
        container,
        partition_key=PartitionKey(path=properties["partitionKey"]["paths"][0]),
        indexing_policy=properties["indexingPolicy"],
        default_ttl=TTL_SECONDS,
    )
    context.log.info(f"Set default TTL to {TTL_SECONDS}s")
'''


PY_DISABLE_TTL = '''
"""Turn the default TTL back off."""

from azure.cosmos import PartitionKey


def migrate(context):
    container = context.db.get_container_client("users")
    properties = container.read()

    if context.dry_run:
        context.log.info("[DRY-RUN] would disable default TTL")
        return

    context.db.replace_container(
        container,
        partition_key=PartitionKey(path=properties["partitionKey"]["paths"][0]),
        indexing_policy=properties["indexingPolicy"],
        default_ttl=None,
    )
    context.log.info("Disabled default TTL")
'''


PY_EXCLUDE_INDEX_PATH = '''
"""Exclude a large blob property from indexing."""

from azure.cosmos import PartitionKey

EXCLUDED_PATH = "/profile_blob/*"


def migrate(context):
    container = context.db.get_container_client("users")
    properties = container.read()

    indexing_policy = properties["indexingPolicy"]
    excluded = indexing_policy.setdefault("excludedPaths", [])
    if not any(entry.get("path") == EXCLUDED_PATH for entry in excluded):
        excluded.append({"path": EXCLUDED_PATH})

    if context.dry_run:
        context.log.info(f"[DRY-RUN] would exclude '{EXCLUDED_PATH}' from indexing")
        return

    context.db.replace_container(
        container,
        partition_key=PartitionKey(path=properties["partitionKey"]["paths"][0]),
        indexing_policy=indexing_policy,
    )
    context.log.info(f"Excluded '{EXCLUDED_PATH}' from indexing")
'''


PY_CREATE_SPARSE_INDEX_CONTAINER = '''
"""Create a container that indexes only the paths it is told to."""

from azure.cosmos import PartitionKey

CONTAINER = "events"


def migrate(context):
    if context.dry_run:
        context.log.info(f"[DRY-RUN] would create container '{CONTAINER}'")
        return

    context.db.create_container(
        id=CONTAINER,
        partition_key=PartitionKey(path="/tenant_id"),
        indexing_policy={
            "indexingMode": "consistent",
            "automatic": True,
            "includedPaths": [{"path": "/tenant_id/?"}],
            "excludedPaths": [{"path": "/*"}],
        },
    )
    context.log.info(f"Created container '{CONTAINER}'")
'''


PY_INCLUDE_INDEX_PATH = '''
"""Add an indexed path to the events container."""

from azure.cosmos import PartitionKey

INCLUDED_PATH = "/kind/?"


def migrate(context):
    container = context.db.get_container_client("events")
    properties = container.read()

    indexing_policy = properties["indexingPolicy"]
    included = indexing_policy.setdefault("includedPaths", [])
    if not any(entry.get("path") == INCLUDED_PATH for entry in included):
        included.append({"path": INCLUDED_PATH})

    if context.dry_run:
        context.log.info(f"[DRY-RUN] would index '{INCLUDED_PATH}'")
        return

    context.db.replace_container(
        container,
        partition_key=PartitionKey(path=properties["partitionKey"]["paths"][0]),
        indexing_policy=indexing_policy,
    )
    context.log.info(f"Indexed '{INCLUDED_PATH}'")
'''


PY_SEED_USERS = '''
"""Insert seed documents (the INSERT replacement)."""

DOCUMENTS = [
    {"id": "1", "tenant_id": "acme", "name": "Alice", "status": "active", "count": 10},
    {"id": "2", "tenant_id": "acme", "name": "Bob", "status": "active", "count": 20},
    {"id": "3", "tenant_id": "globex", "name": "Carol", "status": "active", "count": 30},
]


def migrate(context):
    container = context.db.get_container_client("users")
    if context.dry_run:
        context.log.info(f"[DRY-RUN] would create {len(DOCUMENTS)} documents")
        return

    for document in DOCUMENTS:
        container.create_item(body=document)
    context.log.info(f"Created {len(DOCUMENTS)} documents")
'''


PY_UPDATE_USER = '''
"""Replace a document in place (the UPDATE replacement)."""


def migrate(context):
    container = context.db.get_container_client("users")

    # Conditional work still reads through the Cosmos SQL API.
    existing = context.execute("SELECT * FROM users c WHERE c.id = '1'")
    if not existing:
        raise RuntimeError("expected document '1' to exist")

    document = dict(existing[0])
    document["status"] = "inactive"
    document["name"] = "Alice Updated"

    if context.dry_run:
        context.log.info("[DRY-RUN] would replace document '1'")
        return

    container.replace_item(item=document["id"], body=document)
    context.log.info("Replaced document '1'")
'''


PY_DELETE_USER = '''
"""Delete a document (the DELETE replacement)."""


def migrate(context):
    container = context.db.get_container_client("users")
    if context.dry_run:
        context.log.info("[DRY-RUN] would delete document '3'")
        return

    container.delete_item(item="3", partition_key="globex")
    context.log.info("Deleted document '3'")
'''


PY_UNDO_USERS = '''
"""Undo companion for V1_0_0 — drops the users container."""


def migrate(context):
    """Undo scripts are only ever driven through ``undo``."""
    undo(context)


def undo(context):
    if context.dry_run:
        context.log.info("[DRY-RUN] would delete container 'users'")
        return

    context.db.delete_container("users")
    context.log.info("Deleted container 'users'")
'''


SQL_MIGRATION_REJECTED = """
CREATE TABLE users (
    id VARCHAR(64) NOT NULL PRIMARY KEY
);
"""


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


def _skip_if_unavailable(cosmosdb_container: Dict[str, Any]) -> None:
    """Skip the test when no Cosmos DB emulator/account is reachable."""
    if "_skip_reason" in cosmosdb_container:
        pytest.skip(cosmosdb_container["_skip_reason"])


@pytest.fixture
def cosmos_config(cosmosdb_container):
    """Build a DbliftConfig pointed at the emulator (or external account)."""
    _skip_if_unavailable(cosmosdb_container)

    return DbliftConfig.from_dict(
        {
            "database": {
                "type": "cosmosdb",
                "url": cosmosdb_container["account_endpoint"],
                "account_endpoint": cosmosdb_container["account_endpoint"],
                "account_key": cosmosdb_container["account_key"],
                "database_name": cosmosdb_container["database_name"],
                "container_name": cosmosdb_container.get("container_name", SCHEMA),
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_cosmosdb_integration.log"},
        }
    )


@pytest.fixture
def cosmos_provider(cosmos_config, integration_logger):
    """A connected CosmosDbProvider, closed at teardown."""
    provider = ProviderRegistry.create_provider(cosmos_config, integration_logger)
    provider.create_connection()
    yield provider
    provider.close()


@pytest.fixture
def cosmos_db(cosmos_provider):
    """The raw ``azure.cosmos.DatabaseProxy`` used for direct SDK assertions."""
    return cosmos_provider.connection_manager.database


@pytest.fixture
def migrations_dir(tmp_path):
    """An empty migrations directory for a Python-migration test."""
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


@pytest.fixture
def cosmos_cli(cosmosdb_container, migrations_dir, tmp_path):
    """The production CLI wired to a Cosmos DB config and migrations dir."""
    _skip_if_unavailable(cosmosdb_container)

    config_file = create_config(tmp_path, cosmosdb_container, migrations_dir=migrations_dir)
    return DBLiftCLI(config_file, migrations_dir)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _wait_for_container(provider, name: str, should_exist: bool = True, timeout: float = 10.0):
    """Poll until *name* reaches the expected existence state (emulator lag)."""
    deadline = time.monotonic() + timeout
    exists = provider.table_exists(SCHEMA, name)
    while exists is not should_exist and time.monotonic() < deadline:
        time.sleep(0.5)
        exists = provider.table_exists(SCHEMA, name)
    return exists


def _read_throughput(container):
    """Read throughput across ``azure-cosmos`` releases."""
    if hasattr(container, "get_throughput"):
        return container.get_throughput()
    return container.read_offer()


def _index_paths(properties, key: str):
    """Return the indexing-policy paths under *key* (included/excluded)."""
    return {entry.get("path") for entry in properties["indexingPolicy"].get(key, [])}


@pytest.mark.integration
@pytest.mark.cosmosdb
class TestCosmosDbProvider:
    """Provider-level behaviour: connection, native SELECT, history, locking."""

    def test_connection(self, cosmos_provider):
        """The provider connects and reports itself connected."""
        assert cosmos_provider.connection is not None
        assert cosmos_provider.is_connected() is True

    def test_database_version(self, cosmos_provider):
        """The provider reports a Cosmos DB version string."""
        assert "Cosmos DB" in cosmos_provider.get_database_version()

    def test_native_select_query(self, cosmos_provider, cosmos_db):
        """``execute_query`` runs native Cosmos SQL against a container."""
        cosmos_db.create_container(id="items", partition_key=PartitionKey(path="/id"))
        assert _wait_for_container(cosmos_provider, "items") is True

        container = cosmos_db.get_container_client("items")
        container.create_item(body={"id": "1", "name": "test", "value": 100})

        results = cosmos_provider.execute_query("SELECT * FROM items c WHERE c.id = '1'")
        assert len(results) == 1
        assert results[0]["id"] == "1"
        assert results[0]["name"] == "test"
        assert results[0]["value"] == 100

    def test_execute_statement_accepts_select(self, cosmos_provider, cosmos_db):
        """``execute_statement`` runs a SELECT and returns the document count."""
        cosmos_db.create_container(id="items", partition_key=PartitionKey(path="/id"))
        assert _wait_for_container(cosmos_provider, "items") is True

        container = cosmos_db.get_container_client("items")
        container.create_item(body={"id": "1", "value": 1})
        container.create_item(body={"id": "2", "value": 2})

        assert cosmos_provider.execute_statement("SELECT * FROM items c") == 2

    @pytest.mark.parametrize(
        "write_sql",
        [
            "INSERT INTO items (id, name) VALUES ('1', 'test')",
            "UPDATE items SET name='updated' WHERE id='1'",
            "DELETE FROM items WHERE id='1'",
            "CREATE TABLE items (id STRING)",
        ],
        ids=["insert", "update", "delete", "create-table"],
    )
    def test_execute_statement_rejects_writes(self, cosmos_provider, write_sql):
        """Any write reaching the query API raises NoSqlWriteNotSupportedError.

        The Cosmos SQL API reads only — writes belong in a Python migration
        driving ``context.db``, so they are surfaced, never translated.
        """
        with pytest.raises(NoSqlWriteNotSupportedError):
            cosmos_provider.execute_statement(write_sql)

    def test_container_exists(self, cosmos_provider, cosmos_db):
        """``table_exists`` reflects containers created through the SDK."""
        cosmos_db.create_container(id="test_exists", partition_key=PartitionKey(path="/id"))

        assert _wait_for_container(cosmos_provider, "test_exists") is True
        assert cosmos_provider.table_exists(SCHEMA, "non_existent") is False

    def test_list_containers(self, cosmos_provider, cosmos_db):
        """``list_containers`` reports every container in the database."""
        for name in ("list_test1", "list_test2"):
            cosmos_db.create_container(id=name, partition_key=PartitionKey(path="/id"))
            assert _wait_for_container(cosmos_provider, name) is True

        containers = cosmos_provider.schema_operations.list_containers()
        names = [c if isinstance(c, str) else c.get("id", c) for c in containers]
        assert "list_test1" in names
        assert "list_test2" in names

    def test_drop_object_deletes_container(self, cosmos_provider, cosmos_db):
        """``drop_object`` deletes through the SDK — the path ``clean`` uses."""
        cosmos_db.create_container(id="drop_me", partition_key=PartitionKey(path="/id"))
        assert _wait_for_container(cosmos_provider, "drop_me") is True

        droppable = cosmos_provider.list_droppable_objects(SCHEMA)
        target = next(obj for obj in droppable if obj.name == "drop_me")
        assert target.object_type == "CONTAINER"

        cosmos_provider.drop_object(target)
        assert _wait_for_container(cosmos_provider, "drop_me", should_exist=False) is False

    def test_aggregate_and_ordered_queries(self, cosmos_provider, cosmos_db):
        """Aggregations and ORDER BY run natively on Cosmos."""
        cosmos_db.create_container(id="orders", partition_key=PartitionKey(path="/id"))
        assert _wait_for_container(cosmos_provider, "orders") is True

        orders = cosmos_db.get_container_client("orders")
        for document in (
            {"id": "1", "customerId": "1", "total": 100},
            {"id": "2", "customerId": "1", "total": 200},
            {"id": "3", "customerId": "2", "total": 150},
        ):
            orders.create_item(body=document)

        grouped = cosmos_provider.execute_query(
            "SELECT c.customerId, SUM(c.total) as total FROM orders c GROUP BY c.customerId"
        )
        assert len(grouped) > 0

        ordered = cosmos_provider.execute_query(
            "SELECT * FROM orders c WHERE c.total > 100 ORDER BY c.total DESC"
        )
        assert [row["total"] for row in ordered] == [200, 150]

    def test_migration_lock_acquire_and_release(self, cosmos_provider):
        """The SDK-backed migration lock can be taken and released."""
        cosmos_provider.create_migration_lock_table_if_not_exists(SCHEMA)
        time.sleep(0.5)

        try:
            cosmos_provider.release_migration_lock(SCHEMA)
        except Exception:
            pass  # No lock held from a previous run — fine.

        assert cosmos_provider.acquire_migration_lock(SCHEMA, wait_timeout_seconds=10) is True
        assert cosmos_provider.release_migration_lock(SCHEMA) is True

    def test_migration_lock_timeout(self, cosmos_config, integration_logger):
        """A second holder times out until the first releases the lock."""
        provider1 = ProviderRegistry.create_provider(cosmos_config, integration_logger)
        provider1.create_connection()
        provider1.create_migration_lock_table_if_not_exists(SCHEMA)
        time.sleep(0.5)

        provider2 = ProviderRegistry.create_provider(cosmos_config, integration_logger)
        provider2.create_connection()
        provider2.create_migration_lock_table_if_not_exists(SCHEMA)

        try:
            assert provider1.acquire_migration_lock(SCHEMA, wait_timeout_seconds=1) is True
            assert provider2.acquire_migration_lock(SCHEMA, wait_timeout_seconds=2) is False

            provider1.release_migration_lock(SCHEMA)
            assert provider2.acquire_migration_lock(SCHEMA, wait_timeout_seconds=5) is True
            provider2.release_migration_lock(SCHEMA)
        finally:
            provider1.close()
            provider2.close()

    def test_migration_lock_expired_is_reclaimed(self, cosmos_provider, cosmos_db):
        """An expired lock document is cleaned up and the lock re-acquired."""
        cosmos_provider.create_migration_lock_table_if_not_exists(SCHEMA)
        time.sleep(0.5)

        now = datetime.datetime.now(datetime.timezone.utc)
        lock_container = cosmos_db.get_container_client("dblift_migration_lock")
        lock_container.upsert_item(
            body={
                "id": "migration_lock",
                "schema": SCHEMA,
                "locked_by": "test@host",
                "locked_at": (now - datetime.timedelta(hours=1)).isoformat(),
                "expires_at": (now - datetime.timedelta(minutes=1)).isoformat(),
            }
        )
        time.sleep(0.3)

        assert cosmos_provider.acquire_migration_lock(SCHEMA, wait_timeout_seconds=10) is True
        cosmos_provider.release_migration_lock(SCHEMA)

    def test_migration_history_record_and_read(self, cosmos_provider):
        """History rows are written and read back through the SDK."""
        cosmos_provider.history_manager.create_history_container_if_not_exists(
            SCHEMA, "dblift_schema_history"
        )
        time.sleep(0.5)

        migration_info = {
            "version": "1.0.0",
            "description": "test_migration",
            "type": "PYTHON",
            "script": "V1_0_0__test_migration.py",
            "checksum": "abc123",
            "execution_time": 100,
            "success": True,
        }
        cosmos_provider.record_migration(SCHEMA, migration_info)

        applied = cosmos_provider.get_applied_migrations(SCHEMA)
        assert any(m["version"] == "1.0.0" for m in applied)

    def test_migration_history_record_is_idempotent(self, cosmos_provider):
        """Recording the same migration twice upserts rather than duplicating."""
        cosmos_provider.history_manager.create_history_container_if_not_exists(
            SCHEMA, "dblift_schema_history"
        )
        time.sleep(0.5)

        migration_info = {
            "version": "1.0.0",
            "description": "test_migration",
            "type": "PYTHON",
            "script": "V1_0_0__test_migration.py",
            "checksum": "abc123",
            "execution_time": 100,
            "success": True,
        }
        cosmos_provider.record_migration(SCHEMA, migration_info)
        cosmos_provider.record_migration(SCHEMA, migration_info)

        applied = cosmos_provider.get_applied_migrations(SCHEMA)
        assert len([m for m in applied if m["version"] == "1.0.0"]) == 1

    def test_clean_schema_drops_every_container(self, cosmos_provider, cosmos_db):
        """``clean_schema`` drops user and dblift-managed containers alike."""
        user_containers = ["clean_test1", "clean_test2", "clean_test3"]
        for name in user_containers:
            cosmos_db.create_container(id=name, partition_key=PartitionKey(path="/id"))

        cosmos_provider.create_migration_history_table_if_not_exists(SCHEMA)
        cosmos_provider.create_migration_lock_table_if_not_exists(SCHEMA)
        cosmos_provider.create_snapshot_table_if_not_exists(SCHEMA)

        all_containers = user_containers + [
            "dblift_schema_history",
            "dblift_migration_lock",
            "dblift_schema_snapshots",
        ]
        for name in all_containers:
            assert _wait_for_container(cosmos_provider, name) is True, f"{name} should exist"

        summary = cosmos_provider.clean_schema(SCHEMA)

        for name in all_containers:
            assert (
                _wait_for_container(cosmos_provider, name, should_exist=False) is False
            ), f"{name} should be gone after clean"

        assert summary is not None
        assert sorted(obj.name for obj in summary.objects) == sorted(all_containers)


@pytest.mark.integration
@pytest.mark.cosmosdb
class TestCosmosDbPythonMigrations:
    """Container, throughput, TTL, indexing and document changes via ``.py``."""

    def test_migrate_creates_container_with_partition_key(
        self, cosmos_cli, migrations_dir, cosmos_provider, cosmos_db
    ):
        """A Python migration creates a container with the declared partition key."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)

        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"

        assert _wait_for_container(cosmos_provider, "users") is True
        properties = cosmos_db.get_container_client("users").read()
        assert properties["partitionKey"]["paths"] == ["/tenant_id"]

    def test_migrate_sets_manual_throughput(
        self, cosmos_cli, migrations_dir, cosmos_provider, cosmos_db
    ):
        """``replace_throughput`` replaces the removed SET THROUGHPUT statement."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        create_migration(migrations_dir, "V1_1_0__users_throughput.py", PY_SET_THROUGHPUT)

        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"
        assert _wait_for_container(cosmos_provider, "users") is True

        throughput = _read_throughput(cosmos_db.get_container_client("users"))
        assert throughput.offer_throughput == 1000

    def test_migrate_sets_autoscale_throughput(
        self, cosmos_cli, migrations_dir, cosmos_provider, cosmos_db
    ):
        """``ThroughputProperties`` replaces the removed SET AUTOSCALE statement."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        create_migration(migrations_dir, "V1_1_0__users_autoscale.py", PY_SET_AUTOSCALE)

        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"
        assert _wait_for_container(cosmos_provider, "users") is True

        throughput = _read_throughput(cosmos_db.get_container_client("users"))
        assert throughput.auto_scale_max_throughput == 4000

    def test_migrate_sets_and_clears_default_ttl(
        self, cosmos_cli, migrations_dir, cosmos_provider, cosmos_db
    ):
        """``replace_container(default_ttl=...)`` replaces SET TTL ON CONTAINER."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        create_migration(migrations_dir, "V1_1_0__users_ttl.py", PY_SET_TTL)

        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"
        assert _wait_for_container(cosmos_provider, "users") is True

        container = cosmos_db.get_container_client("users")
        assert container.read()["defaultTtl"] == 3600

        create_migration(migrations_dir, "V1_2_0__users_ttl_off.py", PY_DISABLE_TTL)
        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"

        assert container.read().get("defaultTtl") is None

    def test_migrate_excludes_indexing_path(
        self, cosmos_cli, migrations_dir, cosmos_provider, cosmos_db
    ):
        """Appending to ``excludedPaths`` replaces EXCLUDE INDEX PATH."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        create_migration(migrations_dir, "V1_1_0__users_indexing.py", PY_EXCLUDE_INDEX_PATH)

        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"
        assert _wait_for_container(cosmos_provider, "users") is True

        properties = cosmos_db.get_container_client("users").read()
        assert "/profile_blob/*" in _index_paths(properties, "excludedPaths")

    def test_migrate_includes_indexing_path(
        self, cosmos_cli, migrations_dir, cosmos_provider, cosmos_db
    ):
        """Appending to ``includedPaths`` replaces CREATE INDEX / INCLUDE INDEX PATH."""
        create_migration(
            migrations_dir, "V1_0_0__create_events.py", PY_CREATE_SPARSE_INDEX_CONTAINER
        )
        create_migration(migrations_dir, "V1_1_0__events_indexing.py", PY_INCLUDE_INDEX_PATH)

        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"
        assert _wait_for_container(cosmos_provider, "events") is True

        included = _index_paths(cosmos_db.get_container_client("events").read(), "includedPaths")
        assert "/tenant_id/?" in included
        assert "/kind/?" in included

    def test_migrate_document_crud(self, cosmos_cli, migrations_dir, cosmos_provider):
        """create_item / replace_item / delete_item replace INSERT / UPDATE / DELETE."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        create_migration(migrations_dir, "V1_1_0__seed_users.py", PY_SEED_USERS)

        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"
        assert _wait_for_container(cosmos_provider, "users") is True

        assert len(cosmos_provider.execute_query("SELECT * FROM users c")) == 3

        create_migration(migrations_dir, "V1_2_0__update_user.py", PY_UPDATE_USER)
        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"

        updated = cosmos_provider.execute_query("SELECT * FROM users c WHERE c.id = '1'")
        assert len(updated) == 1
        assert updated[0]["status"] == "inactive"
        assert updated[0]["name"] == "Alice Updated"

        create_migration(migrations_dir, "V1_3_0__delete_user.py", PY_DELETE_USER)
        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"

        remaining = cosmos_provider.execute_query("SELECT * FROM users c")
        assert {row["id"] for row in remaining} == {"1", "2"}

    def test_migrate_dry_run_makes_no_changes(self, cosmos_cli, migrations_dir, cosmos_provider):
        """``--dry-run`` leaves the account untouched; the script honours the flag."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)

        result = cosmos_cli.migrate(dry_run=True)
        assert result.success, f"dry-run migrate failed: {result.output}"

        assert cosmos_provider.table_exists(SCHEMA, "users") is False

    def test_undo_python_migration(self, cosmos_cli, migrations_dir, cosmos_provider):
        """``undo`` runs the ``U…`` companion, which deletes the container."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        create_migration(migrations_dir, "U1_0_0__drop_users.py", PY_UNDO_USERS)

        result = cosmos_cli.migrate()
        assert result.success, f"migrate failed: {result.output}"
        assert _wait_for_container(cosmos_provider, "users") is True

        result = cosmos_cli.undo()
        assert result.success, f"undo failed: {result.output}"
        assert _wait_for_container(cosmos_provider, "users", should_exist=False) is False

    def test_sql_migration_is_rejected(self, cosmos_cli, migrations_dir, cosmos_provider):
        """A ``.sql`` migration on Cosmos fails with DBLIFT-NOSQL-001.

        The dialect declares ``supports_sql_migrations = False``, so the
        executor factory rejects the file before anything executes.
        """
        create_migration(migrations_dir, "V1_0_0__create_users.sql", SQL_MIGRATION_REJECTED)

        result = cosmos_cli.migrate()

        assert result.failed, f"SQL migration should not succeed: {result.output}"
        assert "DBLIFT-NOSQL-001" in result.output
        assert cosmos_provider.table_exists(SCHEMA, "users") is False


@pytest.mark.integration
@pytest.mark.cosmosdb
class TestCosmosDbCommandFlows:
    """info / validate / repair / clean / baseline over Python migrations."""

    def test_info_lists_applied_python_migration(self, cosmos_cli, migrations_dir):
        """``info`` reports the applied Python migration."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)

        assert cosmos_cli.migrate().success

        result = cosmos_cli.info()
        assert result.success, f"info failed: {result.output}"
        assert "1.0.0" in result.output

    def test_validate_passes_after_migrate(self, cosmos_cli, migrations_dir):
        """``validate`` passes when history matches the migration files."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)

        assert cosmos_cli.migrate().success

        result = cosmos_cli.validate()
        assert result.success, f"validate failed: {result.output}"

    def test_repair_fixes_modified_checksum(self, cosmos_cli, migrations_dir):
        """Editing an applied ``.py`` breaks validate; ``repair`` restores it."""
        script = create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)

        assert cosmos_cli.migrate().success
        assert cosmos_cli.validate().success

        # Change the file without changing what it does — checksum drifts.
        script.write_text(PY_CREATE_USERS + "\n# checksum drift\n")
        assert cosmos_cli.validate().failed

        result = cosmos_cli.repair()
        assert result.success, f"repair failed: {result.output}"
        assert cosmos_cli.validate().success

    def test_clean_removes_migrated_containers(self, cosmos_cli, migrations_dir, cosmos_provider):
        """``clean`` drops every container via ``provider.drop_object``."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        create_migration(
            migrations_dir, "V1_1_0__create_events.py", PY_CREATE_SPARSE_INDEX_CONTAINER
        )

        assert cosmos_cli.migrate().success
        assert _wait_for_container(cosmos_provider, "users") is True
        assert _wait_for_container(cosmos_provider, "events") is True

        result = cosmos_cli.clean()
        assert result.success, f"clean failed: {result.output}"

        assert _wait_for_container(cosmos_provider, "users", should_exist=False) is False
        assert _wait_for_container(cosmos_provider, "events", should_exist=False) is False

    def test_baseline_marks_version_applied(self, cosmos_cli, migrations_dir, cosmos_provider):
        """``baseline`` records the version without running the migration."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)

        result = cosmos_cli.baseline("1.0.0", baseline_description="initial baseline")
        assert result.success, f"baseline failed: {result.output}"

        # Baselined, so the script never runs and the container is not created.
        assert cosmos_provider.table_exists(SCHEMA, "users") is False

        info = cosmos_cli.info()
        assert info.success, f"info failed: {info.output}"
        assert "1.0.0" in info.output
