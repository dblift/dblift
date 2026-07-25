"""SQL migrations are rejected on dialects that do not execute SQL.

NoSQL dialects (Cosmos DB, and any future document store) run Python
migrations only. A ``.sql`` migration aimed at one of them is a hard
error — ``DBLIFT-NOSQL-001`` — rather than a statement stream handed to a
pseudo-SQL translator.
"""

from pathlib import Path

import pytest

from core.exceptions import UnsupportedMigrationFormatError
from core.migration.executors.executor_factory import MigrationExecutorFactory
from core.migration.formats import MigrationFormat
from core.migration.migration import Migration
from db.base_quirks import BaseQuirks


class _NoSqlQuirks(BaseQuirks):
    is_nosql = True
    supports_sql_migrations = False


class _SqlQuirks(BaseQuirks):
    pass


class _Provider:
    def __init__(self, quirks):
        self.quirks = quirks


def _migration(tmp_path: Path, name: str, content: str) -> Migration:
    script = tmp_path / name
    script.write_text(content, encoding="utf-8")
    return Migration(script_path=script)


def _factory(quirks) -> MigrationExecutorFactory:
    return MigrationExecutorFactory(provider=_Provider(quirks), config=None, log=None)


def test_base_quirks_allow_sql_migrations_by_default():
    assert BaseQuirks().supports_sql_migrations is True


def test_cosmosdb_quirks_reject_sql_migrations():
    from db.plugins.cosmosdb.quirks import CosmosdbQuirks

    assert CosmosdbQuirks().supports_sql_migrations is False
    assert CosmosdbQuirks().is_nosql is True


def test_sql_migration_on_nosql_dialect_raises(tmp_path):
    migration = _migration(tmp_path, "V1_0_0__create.sql", "CREATE TABLE t (id INT);")

    with pytest.raises(UnsupportedMigrationFormatError) as excinfo:
        _factory(_NoSqlQuirks("cosmosdb")).get_executor(migration)

    message = str(excinfo.value)
    assert "DBLIFT-NOSQL-001" in message
    assert "V1_0_0__create.sql" in message
    assert "cosmosdb" in message


def test_execute_surfaces_the_same_error(tmp_path):
    migration = _migration(tmp_path, "V1_0_1__seed.sql", "INSERT INTO t VALUES (1);")

    with pytest.raises(UnsupportedMigrationFormatError):
        _factory(_NoSqlQuirks("cosmosdb")).execute(migration)


def test_validate_surfaces_the_same_error(tmp_path):
    migration = _migration(tmp_path, "V1_0_2__seed.sql", "INSERT INTO t VALUES (1);")

    with pytest.raises(UnsupportedMigrationFormatError):
        _factory(_NoSqlQuirks("cosmosdb")).validate(migration)


def test_python_migration_on_nosql_dialect_is_accepted(tmp_path):
    migration = _migration(tmp_path, "V1_0_3__containers.py", "def migrate(context):\n    pass\n")

    executor = _factory(_NoSqlQuirks("cosmosdb")).get_executor(migration)

    assert executor is not None
    assert MigrationFormat.PYTHON in executor.get_supported_formats()


def test_sql_migration_on_relational_dialect_is_unaffected(tmp_path):
    migration = _migration(tmp_path, "V1_0_4__create.sql", "CREATE TABLE t (id INT);")

    executor = _factory(_SqlQuirks("postgresql")).get_executor(migration)

    assert executor is not None
    assert MigrationFormat.SQL in executor.get_supported_formats()


def test_provider_without_quirks_does_not_break_routing(tmp_path):
    """A bare provider stub (no ``quirks``) keeps the historical SQL path."""
    migration = _migration(tmp_path, "V1_0_5__create.sql", "CREATE TABLE t (id INT);")
    factory = MigrationExecutorFactory(provider=object(), config=None, log=None)

    assert factory.get_executor(migration) is not None
