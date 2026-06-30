"""
Tests de conformité ISP pour les interfaces focalisées des providers.

Vérifie que :
- Les 5 ABCs déclarent les bonnes méthodes abstraites
- Tous les providers SQL implémentent les 5 interfaces via BaseProvider
- CosmosDbProvider.supports_transactions() retourne False
- Les providers SQL supports_transactions() retournent True
- Les ABCs ne peuvent pas être instanciées directement
"""

import pytest

from db.base_provider import BaseProvider, NativeProvider
from db.provider_interfaces import (
    ConnectionProvider,
    MigrationProvider,
    QueryProvider,
    SchemaProvider,
    TransactionalProvider,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

ALL_INTERFACES = [
    ConnectionProvider,
    QueryProvider,
    SchemaProvider,
    TransactionalProvider,
    MigrationProvider,
]


# ---------------------------------------------------------------------------
# T5.4 — Tests ABC structure : chaque interface déclare les bonnes méthodes
# ---------------------------------------------------------------------------


class TestConnectionProviderABC:
    def test_abstract_methods(self):
        expected = {"create_connection", "close", "is_connected", "connect"}
        assert ConnectionProvider.__abstractmethods__ == expected

    def test_method_count(self):
        assert len(ConnectionProvider.__abstractmethods__) == 4


class TestQueryProviderABC:
    def test_abstract_methods(self):
        expected = {"execute_statement", "execute_query"}
        assert QueryProvider.__abstractmethods__ == expected

    def test_get_parameter_placeholders_is_concrete(self):
        """get_parameter_placeholders has a default implementation, not abstract."""
        assert "get_parameter_placeholders" not in QueryProvider.__abstractmethods__


class TestSchemaProviderABC:
    def test_abstract_methods(self):
        expected = {
            "create_schema_if_not_exists",
            "table_exists",
            "get_database_version",
            "set_current_schema",
            "get_schema_qualified_name",
            "clean_schema",
            "create_snapshot_table_if_not_exists",
            "create_data_history_table_if_not_exists",
            "create_data_change_set_table_if_not_exists",
        }
        assert SchemaProvider.__abstractmethods__ == expected

    def test_method_count(self):
        assert len(SchemaProvider.__abstractmethods__) == 9


class TestTransactionalProviderABC:
    def test_abstract_methods(self):
        expected = {"begin_transaction", "commit_transaction", "rollback_transaction"}
        assert TransactionalProvider.__abstractmethods__ == expected

    def test_supports_transactions_is_concrete(self):
        """supports_transactions() has a default return True, not abstract."""
        assert "supports_transactions" not in TransactionalProvider.__abstractmethods__

    def test_supports_transactions_default_returns_true(self):
        """Default supports_transactions() returns True."""

        class ConcreteTransactional(TransactionalProvider):
            def begin_transaction(self) -> None: ...
            def commit_transaction(self) -> None: ...
            def rollback_transaction(self) -> None: ...

        assert ConcreteTransactional().supports_transactions() is True


class TestMigrationProviderABC:
    def test_abstract_methods(self):
        expected = {
            "get_applied_migrations",
            "record_migration",
            "create_history_table",
            "create_history_table_if_not_exists",
            "create_migration_lock_table_if_not_exists",
            "acquire_migration_lock",
            "release_migration_lock",
        }
        assert MigrationProvider.__abstractmethods__ == expected

    def test_method_count(self):
        assert len(MigrationProvider.__abstractmethods__) == 7


# ---------------------------------------------------------------------------
# T5.5 — Test qu'on ne peut pas instancier une interface directement
# ---------------------------------------------------------------------------


class TestCannotInstantiateABCs:
    @pytest.mark.parametrize("interface", ALL_INTERFACES, ids=lambda i: i.__name__)
    def test_cannot_instantiate_abc(self, interface):
        with pytest.raises(TypeError):
            interface()


# ---------------------------------------------------------------------------
# T5.1 — Tests isinstance : native providers inherit the focused interfaces
# ---------------------------------------------------------------------------


class TestNativeProviderImplementsAllInterfaces:
    @pytest.mark.parametrize("interface", ALL_INTERFACES, ids=lambda i: i.__name__)
    def test_db2_implements_interface(self, interface):
        from db.plugins.db2.provider import Db2Provider

        assert issubclass(Db2Provider, interface)
        assert issubclass(Db2Provider, NativeProvider)

    @pytest.mark.parametrize("interface", ALL_INTERFACES, ids=lambda i: i.__name__)
    def test_oracle_implements_interface(self, interface):
        from db.plugins.oracle.provider import OracleProvider

        assert issubclass(OracleProvider, interface)
        assert issubclass(OracleProvider, NativeProvider)


# ---------------------------------------------------------------------------
# T5.1 (suite) — CosmosDbProvider est instanceof BaseProvider
# ---------------------------------------------------------------------------


class TestCosmosDbProviderInheritance:
    def test_cosmosdb_is_subclass_of_base_provider(self):
        from db.plugins.cosmosdb.provider import CosmosDbProvider

        assert issubclass(CosmosDbProvider, BaseProvider)

    def test_cosmosdb_is_subclass_of_all_interfaces(self):
        from db.plugins.cosmosdb.provider import CosmosDbProvider

        for interface in ALL_INTERFACES:
            assert issubclass(
                CosmosDbProvider, interface
            ), f"CosmosDbProvider should be subclass of {interface.__name__}"


class TestSQLiteProviderInheritance:
    def test_sqlite_is_subclass_of_base_provider(self):
        from db.plugins.sqlite.provider import SQLiteProvider

        assert issubclass(SQLiteProvider, BaseProvider)
        assert issubclass(SQLiteProvider, NativeProvider)

    def test_sqlite_is_subclass_of_all_interfaces(self):
        from db.plugins.sqlite.provider import SQLiteProvider

        for interface in ALL_INTERFACES:
            assert issubclass(
                SQLiteProvider, interface
            ), f"SQLiteProvider should be subclass of {interface.__name__}"


class TestMySqlProviderInheritance:
    def test_mysql_is_subclass_of_base_provider(self):
        from db.plugins.mysql.provider import MySqlProvider

        assert issubclass(MySqlProvider, BaseProvider)
        assert issubclass(MySqlProvider, NativeProvider)

    def test_mysql_is_subclass_of_all_interfaces(self):
        from db.plugins.mysql.provider import MySqlProvider

        for interface in ALL_INTERFACES:
            assert issubclass(
                MySqlProvider, interface
            ), f"MySqlProvider should be subclass of {interface.__name__}"


class TestSqlServerProviderInheritance:
    def test_sqlserver_is_subclass_of_base_provider(self):
        from db.plugins.sqlserver.provider import SqlServerProvider

        assert issubclass(SqlServerProvider, BaseProvider)
        assert issubclass(SqlServerProvider, NativeProvider)

    def test_sqlserver_is_subclass_of_all_interfaces(self):
        from db.plugins.sqlserver.provider import SqlServerProvider

        for interface in ALL_INTERFACES:
            assert issubclass(
                SqlServerProvider, interface
            ), f"SqlServerProvider should be subclass of {interface.__name__}"


# ---------------------------------------------------------------------------
# T5.2 — CosmosDbProvider.supports_transactions() → False
# ---------------------------------------------------------------------------


class TestCosmosDbSupportsTransactions:
    def test_supports_transactions_returns_false(self):
        from db.plugins.cosmosdb.provider import CosmosDbProvider

        # Use __new__ to avoid __init__ dependencies
        provider = CosmosDbProvider.__new__(CosmosDbProvider)
        assert provider.supports_transactions() is False


# ---------------------------------------------------------------------------
# T5.3 — Tests native supports_transactions() → True for relational providers
# ---------------------------------------------------------------------------


class TestNativeSupportsTransactions:
    def test_db2_supports_transactions(self):
        from db.plugins.db2.provider import Db2Provider

        provider = Db2Provider.__new__(Db2Provider)
        assert provider.supports_transactions() is True

    def test_oracle_supports_transactions(self):
        from db.plugins.oracle.provider import OracleProvider

        provider = OracleProvider.__new__(OracleProvider)
        assert provider.supports_transactions() is True
