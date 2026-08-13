"""
Integration tests for the MongoDB provider.

MongoDB has no SQL and no string query language. Collections, indexes and
documents are changed through ``pymongo`` from a **Python migration**
(``def migrate(context)``), reaching the driver via ``context.db``
(``pymongo.database.Database``) and ``context.raw_client``
(``pymongo.MongoClient``). A ``.sql`` migration is rejected up front with
``DBLIFT-NOSQL-001``; a string handed to ``context.execute()`` raises
``DBLIFT-NOSQL-002``.

See ``docs/user-guide/nosql-python-migrations.md``.

Prerequisites (one of):
- MongoDB via Docker (CI default): from ``tests/integration``,
  ``docker compose up -d mongodb``
- External mongod (local Apple Container, remote host, …): set
  ``DBLIFT_MONGODB_HOST`` (optional ``DBLIFT_MONGODB_PORT`` /
  ``DBLIFT_MONGODB_DATABASE``). When that is set the fixture does not
  start a Docker container.

Usage:
    export DBLIFT_DISABLE_CLI_EXTENSIONS=1
    export DBLIFT_CORE_TEST_DB=mongodb
    # CI / Docker path — leave DBLIFT_MONGODB_HOST unset
    # Local Apple Container example:
    #   container run -d --name dblift_mongodb -p 27017:27017 mongo:7
    #   export DBLIFT_MONGODB_HOST=localhost
    pytest tests/integration/db/test_mongodb_integration.py -v
"""

from pathlib import Path

import pytest

from config import DbliftConfig
from db.provider_registry import ProviderRegistry
from tests.integration.helpers.cli_runner_direct import DBLiftCLIDirect as DBLiftCLI
from tests.integration.helpers.migration_helper import create_config, create_migration

# MongoDB has a single logical schema; dblift addresses it as "default".
SCHEMA = "default"

HISTORY = "dblift_schema_history"
LOCK = "dblift_migration_lock"


# ---------------------------------------------------------------------------
# Python migration scripts used as test fixtures
#
# Written verbatim into the migrations directory, so they are the supported
# authoring model exactly as a user would write it.
# ---------------------------------------------------------------------------

PY_CREATE_USERS = '''
"""Create the users collection with a unique index on email."""

from pymongo import ASCENDING

COLLECTION = "users"


def migrate(context):
    if context.dry_run:
        context.log.info(f"[DRY-RUN] would create collection '{COLLECTION}'")
        return

    context.db.create_collection(COLLECTION)
    context.db[COLLECTION].create_index(
        [("email", ASCENDING)], unique=True, name="ux_users_email"
    )
'''

PY_CREATE_ORDERS = '''
"""Create a second collection, to prove ordering and repeat runs."""


def migrate(context):
    if context.dry_run:
        return
    context.db.create_collection("orders")
'''

PY_RAISES = '''
"""A migration that fails after doing nothing, to exercise repair."""


def migrate(context):
    raise RuntimeError("deliberate failure")
'''

PY_USES_EXECUTE = '''
"""A migration that wrongly reaches for a string statement."""


def migrate(context):
    context.execute("SELECT 1")
'''

SQL_MIGRATION_REJECTED = "CREATE TABLE users (id INT);"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def mongo_config(mongodb_container):
    """Build a DbliftConfig pointed at the test container."""
    return DbliftConfig.from_dict(
        {
            "database": {
                "type": "mongodb",
                "host": mongodb_container["host"],
                "port": mongodb_container["port"],
                "database": mongodb_container["database"],
            },
            "migrations": {"directory": str(Path("/tmp")), "table": "schema_version"},
            "logging": {"level": "DEBUG", "file": "dblift_mongodb_integration.log"},
        }
    )


@pytest.fixture
def mongo_provider(mongo_config, integration_logger):
    """A connected MongoDbProvider, closed at teardown."""
    provider = ProviderRegistry.create_provider(mongo_config, integration_logger)
    provider.create_connection()
    yield provider
    provider.close()


@pytest.fixture
def mongo_db(mongo_provider):
    """The raw ``pymongo.database.Database`` used for direct assertions."""
    return mongo_provider.connection_manager.database


@pytest.fixture(autouse=True)
def clean_database(mongo_db):
    """Drop every collection before each test so runs cannot bleed together."""
    for name in mongo_db.list_collection_names():
        mongo_db.drop_collection(name)
    yield


@pytest.fixture
def migrations_dir(tmp_path):
    """An empty migrations directory for a Python-migration test."""
    directory = tmp_path / "migrations"
    directory.mkdir()
    return directory


@pytest.fixture
def mongo_cli(mongodb_container, migrations_dir, tmp_path):
    """The production CLI wired to a MongoDB config and migrations dir."""
    config_file = create_config(tmp_path, mongodb_container, migrations_dir=migrations_dir)
    return DBLiftCLI(config_file, migrations_dir)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


@pytest.mark.integration
@pytest.mark.mongodb
class TestMongoDbPythonMigrations:
    """Python migrations drive pymongo; SQL never reaches the server."""

    def test_migrate_applies_a_python_migration(self, mongo_cli, migrations_dir, mongo_db):
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)

        result = mongo_cli.migrate()

        assert result.success, f"migrate failed: {result.output}"
        assert "users" in mongo_db.list_collection_names()
        index_names = [index["name"] for index in mongo_db["users"].list_indexes()]
        assert "ux_users_email" in index_names

    def test_history_records_the_applied_migration(self, mongo_cli, migrations_dir, mongo_db):
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)

        assert mongo_cli.migrate().success

        rows = list(mongo_db[HISTORY].find({}))
        assert len(rows) == 1
        assert rows[0]["script"] == "V1_0_0__create_users.py"
        assert rows[0]["success"] is True

    def test_second_migrate_is_a_no_op(self, mongo_cli, migrations_dir, mongo_db):
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        assert mongo_cli.migrate().success

        assert mongo_cli.migrate().success

        assert mongo_db[HISTORY].count_documents({}) == 1

    def test_migrations_apply_in_version_order(self, mongo_cli, migrations_dir, mongo_db):
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        create_migration(migrations_dir, "V1_1_0__create_orders.py", PY_CREATE_ORDERS)

        assert mongo_cli.migrate().success

        ordered = list(mongo_db[HISTORY].find({}).sort("installed_rank", 1))
        ranks = [row["installed_rank"] for row in ordered]
        scripts = [row["script"] for row in ordered]
        assert ranks == [1, 2]
        assert scripts == ["V1_0_0__create_users.py", "V1_1_0__create_orders.py"]

    def test_sql_migration_is_rejected(self, mongo_cli, migrations_dir, mongo_db):
        """The dialect declares ``supports_sql_migrations = False``, so the
        executor factory rejects the file before anything executes."""
        create_migration(migrations_dir, "V1_0_0__create_users.sql", SQL_MIGRATION_REJECTED)

        result = mongo_cli.migrate()

        assert result.failed, f"SQL migration should not succeed: {result.output}"
        assert "DBLIFT-NOSQL-001" in result.output
        assert "users" not in mongo_db.list_collection_names()

    def test_context_execute_is_rejected(self, mongo_cli, migrations_dir):
        """No string language exists, so a statement is an error whatever it
        says — reads included."""
        create_migration(migrations_dir, "V1_0_0__uses_execute.py", PY_USES_EXECUTE)

        result = mongo_cli.migrate()

        assert result.failed, f"context.execute should not succeed: {result.output}"
        assert "DBLIFT-NOSQL-002" in result.output


@pytest.mark.integration
@pytest.mark.mongodb
class TestMongoDbCommandFlows:
    """info / repair / clean / baseline / locking over Python migrations."""

    def test_info_lists_the_applied_migration(self, mongo_cli, migrations_dir):
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        assert mongo_cli.migrate().success

        result = mongo_cli.info()

        assert result.success, f"info failed: {result.output}"
        assert "1.0.0" in result.output

    def test_repair_clears_a_failed_migration_and_allows_retry(
        self, mongo_cli, migrations_dir, mongo_db
    ):
        """The delete_failed_migration_entry path end to end.

        A failed row is a tombstone migrate skips; without repair removing
        it, the migration could never be retried.
        """
        failing = create_migration(migrations_dir, "V1_0_0__create_users.py", PY_RAISES)
        assert mongo_cli.migrate().failed

        failed_rows = list(mongo_db[HISTORY].find({"success": False}))
        assert len(failed_rows) == 1

        assert mongo_cli.repair().success
        assert mongo_db[HISTORY].count_documents({"success": False}) == 0

        failing.write_text(PY_CREATE_USERS)
        assert mongo_cli.migrate().success
        assert "users" in mongo_db.list_collection_names()

    def test_lock_is_released_after_a_run(self, mongo_cli, migrations_dir, mongo_db):
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        assert mongo_cli.migrate().success

        assert mongo_db[LOCK].count_documents({"_id": "migration_lock"}) == 0

    def test_clean_drops_every_collection(self, mongo_cli, migrations_dir, mongo_db):
        """Clean returns the database to empty — dblift's own storage
        included, matching every other dialect."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        assert mongo_cli.migrate().success

        assert mongo_cli.clean().success

        assert mongo_db.list_collection_names() == []

    def test_clean_drops_a_view_without_reporting_failure(self, mongo_cli, mongo_db):
        """Regression for the ordering bug: dropping ``system.views`` erases
        every view definition it describes, so clean's own later attempt to
        drop the now-vanished view used to find nothing and report
        "Failed to drop COLLECTION" for an object clean itself had already
        removed. Both halves of the bug are checked: the command must report
        success, and every user collection — the view included — must
        actually be gone server-side. ``system.views`` itself is left behind
        empty by MongoDB even after its last view is dropped; that is a
        server property, not a partial clean, so it is allowed to remain.
        """
        mongo_db.create_collection("big")
        mongo_db.command("create", "recent", viewOn="big", pipeline=[])
        assert sorted(mongo_db.list_collection_names()) == ["big", "recent", "system.views"]

        result = mongo_cli.clean()

        assert result.success, f"clean failed: {result.output}"
        remaining = mongo_db.list_collection_names()
        assert "big" not in remaining
        assert "recent" not in remaining
        assert set(remaining) <= {"system.views"}

        # A view can be created again on the cleaned database — proves the
        # view namespace was left in a usable state, not merely emptied.
        mongo_db.create_collection("big")
        mongo_db.command("create", "recent", viewOn="big", pipeline=[])
        assert list(mongo_db["recent"].find({})) == []

    def test_clean_drops_a_view_defined_on_another_view(self, mongo_cli, mongo_db):
        """A view chain must not change the outcome: the whole namespace
        still comes from the single ``system.views`` collection."""
        mongo_db.create_collection("big")
        mongo_db.command("create", "orders", viewOn="big", pipeline=[])
        mongo_db.command("create", "recent", viewOn="orders", pipeline=[])
        assert "system.views" in mongo_db.list_collection_names()

        result = mongo_cli.clean()

        assert result.success, f"clean failed: {result.output}"
        remaining = mongo_db.list_collection_names()
        assert "big" not in remaining
        assert "orders" not in remaining
        assert "recent" not in remaining
        assert set(remaining) <= {"system.views"}

    def test_clean_drops_views_and_dblift_storage_together(
        self, mongo_cli, migrations_dir, mongo_db
    ):
        """Views and dblift's own collections must both be gone afterward —
        clean is a full reset, not a partial one that stops at the first
        namespace collection it trips over. dblift's own storage is the
        property most at risk from excluding ``system.*``: it must not be
        mistaken for server bookkeeping."""
        create_migration(migrations_dir, "V1_0_0__create_users.py", PY_CREATE_USERS)
        assert mongo_cli.migrate().success
        mongo_db.create_collection("big")
        mongo_db.command("create", "recent", viewOn="big", pipeline=[])
        names_before = mongo_db.list_collection_names()
        assert HISTORY in names_before
        assert "system.views" in names_before

        result = mongo_cli.clean()

        assert result.success, f"clean failed: {result.output}"
        remaining = mongo_db.list_collection_names()
        assert "big" not in remaining
        assert "recent" not in remaining
        assert "users" not in remaining
        assert HISTORY not in remaining
        assert LOCK not in remaining
        assert set(remaining) <= {"system.views"}

    def test_clean_with_no_views_still_drops_everything(self, mongo_cli, mongo_db):
        """Ordinary-path regression: with no views, ``system.views`` never
        exists in the first place, so plain collections must clean exactly
        as before."""
        mongo_db.create_collection("big")
        mongo_db.create_collection("orders")

        result = mongo_cli.clean()

        assert result.success, f"clean failed: {result.output}"
        assert mongo_db.list_collection_names() == []

    def test_clean_drops_a_collection_that_merely_contains_system_dot(self, mongo_cli, mongo_db):
        """``system.`` is a reserved *prefix*, not a banned substring: the
        server itself accepts a real collection named ``orders_system.log``
        (only creation directly under ``system.`` is refused). A substring
        match would silently spare it from a full-reset ``clean`` — a worse
        failure than the one this filter exists to fix, since it has no
        error to notice."""
        mongo_db.create_collection("orders_system.log")

        result = mongo_cli.clean()

        assert result.success, f"clean failed: {result.output}"
        assert "orders_system.log" not in mongo_db.list_collection_names()

    def test_baseline_records_a_baseline_row(self, mongo_cli, migrations_dir, mongo_db):
        result = mongo_cli.baseline("1.0.0", baseline_description="initial baseline")

        assert result.success, f"baseline failed: {result.output}"
        assert mongo_db[HISTORY].count_documents({}) >= 1
