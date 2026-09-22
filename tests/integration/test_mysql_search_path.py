"""MySQL's ``USE <database>`` is the ``search_path`` equivalent, with the same
lazy-apply cache (``MySqlProvider._current_database_set``). See
``tests/integration/test_postgresql_search_path.py`` for the PostgreSQL
counterparts of these two tests.
"""

import uuid
from typing import Any

import pytest

from dblift.api import DBLiftClient
from dblift.config import DbliftConfig
from dblift.db.plugins.mysql.config import MySqlConfig
from dblift.db.provider_registry import ProviderRegistry
from tests.integration.helpers.migration_helper import create_versioned_migration

pytestmark = pytest.mark.integration


def _mysql_config(mysql_container: dict[str, Any], schema: str) -> DbliftConfig:
    db = MySqlConfig(
        type="mysql",
        host=mysql_container["host"],
        port=mysql_container["port"],
        database=mysql_container["database"],
        username=mysql_container["username"],
        password=mysql_container["password"],
        schema=schema,
    )
    return DbliftConfig(database=db)


def test_second_migration_unqualified_read_does_not_leak_previous_database(
    mysql_container: dict[str, Any], tmp_path
) -> None:
    """A row-returning statement must resolve in the configured database too.

    A ``SELECT`` is routed to ``provider.execute_query()``, which never
    applies the configured database. A previous migration's own ``USE``
    must not leak into it.
    """
    configured_db = f"dblift_cfg_{uuid.uuid4().hex[:8]}"
    leaked_db = f"dblift_leak_{uuid.uuid4().hex[:8]}"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "change_database",
        f"""
        CREATE DATABASE `{leaked_db}`;
        CREATE TABLE `{leaked_db}`.probe (v VARCHAR(64));
        INSERT INTO `{leaked_db}`.probe VALUES ('from leaked schema');
        CREATE TABLE `{configured_db}`.probe (v VARCHAR(64));
        INSERT INTO `{configured_db}`.probe VALUES ('from configured schema');
        USE `{leaked_db}`;
        """,
    )
    create_versioned_migration(
        migrations_dir,
        "2.0.0",
        "unqualified_read",
        "SELECT v FROM probe;",
    )

    config = _mysql_config(mysql_container, configured_db)
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        provider.execute_statement(f"CREATE DATABASE IF NOT EXISTS `{configured_db}`")
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)

        result = client.migrate(show_query_results=True)

        assert result.success, result.error_message
        assert result.query_results
        rows = result.query_results[-1].results[0]["rows"]
        assert rows == [["from configured schema"]]
    finally:
        provider.execute_statement(f"DROP DATABASE IF EXISTS `{leaked_db}`")
        provider.execute_statement(f"DROP DATABASE IF EXISTS `{configured_db}`")
        provider.close()


def test_migration_own_use_then_unqualified_read_sees_migration_database(
    mysql_container: dict[str, Any], tmp_path
) -> None:
    """A migration's own ``USE`` must still win for its own read.

    Guard against reapplying the configured database before every statement
    of the same migration and overriding the migration's own choice.
    """
    configured_db = f"dblift_cfg_{uuid.uuid4().hex[:8]}"
    own_db = f"dblift_own_{uuid.uuid4().hex[:8]}"
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    create_versioned_migration(
        migrations_dir,
        "1.0.0",
        "self_use_then_read",
        f"""
        CREATE DATABASE `{own_db}`;
        CREATE TABLE `{own_db}`.probe (v VARCHAR(64));
        INSERT INTO `{own_db}`.probe VALUES ('from migration schema');
        USE `{own_db}`;
        SELECT v FROM probe;
        """,
    )

    config = _mysql_config(mysql_container, configured_db)
    config.migrations.directory = str(migrations_dir)
    provider = ProviderRegistry.create_provider(config)
    provider.create_connection()
    try:
        provider.execute_statement(f"CREATE DATABASE IF NOT EXISTS `{configured_db}`")
        client = DBLiftClient(provider=provider, migrations_dir=migrations_dir, config=config)

        result = client.migrate(show_query_results=True)

        assert result.success, result.error_message
        assert result.query_results
        rows = result.query_results[-1].results[0]["rows"]
        assert rows == [["from migration schema"]]
    finally:
        provider.execute_statement(f"DROP DATABASE IF EXISTS `{own_db}`")
        provider.execute_statement(f"DROP DATABASE IF EXISTS `{configured_db}`")
        provider.close()
