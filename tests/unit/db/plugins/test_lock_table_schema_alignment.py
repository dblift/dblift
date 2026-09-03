"""Lock-table column alignment for the MySQL and DB2 providers.

The lock table must use the standard column names ``lock_name`` /
``acquired_at`` / ``acquired_by``. A drifted name only surfaces at runtime
against a real database, when the DDL and the DML disagree.

These tests target the providers, which own the lock SQL for every
relational dialect. Only SQLite and CosmosDB still delegate to a locking
manager component.
"""

from unittest.mock import MagicMock, patch

import pytest

from dblift.db.plugins.db2.provider import Db2Provider
from dblift.db.plugins.mysql.provider import MySqlProvider


def _provider(provider_class):
    """Build a provider with connection handling stubbed out."""
    provider = provider_class.__new__(provider_class)
    provider.log = MagicMock()
    provider.execute_statement = MagicMock(return_value=0)
    provider.execute_query = MagicMock(return_value=[])
    provider.create_schema_if_not_exists = MagicMock()
    provider.table_exists = MagicMock(return_value=False)
    provider.get_schema_qualified_name = MagicMock(return_value="myschema.dblift_migration_lock")
    return provider


def _executed_sql(provider):
    return " ".join(str(call) for call in provider.execute_statement.call_args_list).lower()


@pytest.mark.unit
class TestMySqlLockTableSchema:
    """MySQL creates the lock table but takes the lock via GET_LOCK, not DML."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.provider = _provider(MySqlProvider)
        self.provider.create_migration_lock_table_if_not_exists("myschema")
        self.sql = _executed_sql(self.provider)

    @pytest.mark.parametrize("column", ["lock_name", "acquired_at", "acquired_by"])
    def test_create_table_declares_standard_column(self, column):
        assert column in self.sql

    def test_create_table_has_no_drifted_column(self):
        assert "lock_id" not in self.sql
        assert "locked_at" not in self.sql
        assert "locked_by" not in self.sql


@pytest.mark.unit
class TestDb2LockTableSchema:
    """DB2 is table-backed: DDL and DML must agree on the column names."""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.provider = _provider(Db2Provider)
        self.provider.create_migration_lock_table_if_not_exists("myschema")
        self.sql = _executed_sql(self.provider)

    @pytest.mark.parametrize("column", ["lock_name", "acquired_at", "acquired_by"])
    def test_create_table_declares_standard_column(self, column):
        assert column in self.sql

    def test_create_table_has_no_drifted_column(self):
        assert "lock_id" not in self.sql
        assert "locked_at" not in self.sql
        assert "locked_by" not in self.sql

    @pytest.mark.parametrize("column", ["lock_name", "acquired_at", "acquired_by"])
    def test_acquire_dml_uses_the_same_columns(self, column):
        provider = _provider(Db2Provider)
        with patch("dblift.db.plugins.db2.provider.socket.gethostname", return_value="host"):
            provider.acquire_migration_lock("myschema", wait_timeout_seconds=0)

        assert column in _executed_sql(provider)
