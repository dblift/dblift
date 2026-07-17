"""Extended tests for db/provider_registry.py."""

import unittest
from unittest.mock import MagicMock, patch


class TestPluginInfo(unittest.TestCase):
    def test_basic_creation(self):
        from db.base_provider import BaseProvider
        from db.provider_registry import PluginInfo

        class FakeProvider(BaseProvider):
            provider_transport = "native"

            def create_connection(self):
                pass

            def close_connection(self):
                pass

            def create_migration_history_table_if_not_exists(self, s, cs=False, tn="t"):
                pass

            def create_snapshot_table_if_not_exists(self, s, tn="t"):
                pass

            def execute_query(self, sql, params=None, schema=None):
                return []

            def execute_statement(self, sql, params=None, schema=None):
                pass

            def get_schema_qualified_name(self, s, n):
                return f"{s}.{n}"

            def get_parameter_placeholders(self, c):
                return "?"

            def begin_transaction(self):
                pass

            def commit_transaction(self):
                pass

            def rollback_transaction(self):
                pass

            def supports_transactions(self):
                return True

            def record_migration(self, s, i, tn=None):
                pass

            def get_applied_migrations(self, s, tn=None):
                return []

            def table_exists(self, s, t):
                return False

            def acquire_migration_lock(self, s, t=60):
                return True

            def release_migration_lock(self, s):
                return True

            def create_migration_lock_table_if_not_exists(self, s):
                pass

            def create_history_table(self, s, t):
                return ""

            def clean_schema(self, s, **kw):
                return MagicMock()

            def create_schema_if_not_exists(self, s):
                pass

            def get_database_version(self, c=None):
                return "1.0"

            def set_current_schema(self, s):
                pass

        plugin = PluginInfo(
            name="postgresql",
            version="1.0",
            description="PostgreSQL provider",
            dialects=["postgresql"],
            provider_class=FakeProvider,
        )
        self.assertEqual(plugin.name, "postgresql")
        self.assertEqual(plugin.transport, "native")


class TestProviderRegistryGetProviderClass(unittest.TestCase):
    def test_returns_class_for_known_type(self):
        from db.provider_registry import ProviderRegistry

        cls = ProviderRegistry.get_provider_class("postgresql")
        self.assertIsNotNone(cls)

    def test_returns_none_for_unknown_type(self):
        from db.provider_registry import ProviderRegistry

        cls = ProviderRegistry.get_provider_class("unknown_db_xyz")
        self.assertIsNone(cls)

    def test_case_insensitive(self):
        from db.provider_registry import ProviderRegistry

        cls1 = ProviderRegistry.get_provider_class("postgresql")
        cls2 = ProviderRegistry.get_provider_class("PostgreSQL")
        self.assertIs(cls1, cls2)


class TestProviderRegistryGetProviderByUrl(unittest.TestCase):
    def test_postgresql_url(self):
        from db.provider_registry import ProviderRegistry

        cls = ProviderRegistry.get_provider_by_url("postgresql+psycopg://localhost/db")
        self.assertIsNotNone(cls)

    def test_mysql_url(self):
        from db.provider_registry import ProviderRegistry

        cls = ProviderRegistry.get_provider_by_url("mysql+pymysql://localhost/db")
        self.assertIsNotNone(cls)

    def test_db2_sqlalchemy_url(self):
        from db.provider_registry import ProviderRegistry

        cls = ProviderRegistry.get_provider_by_url("ibm_db_sa://localhost:50000/testdb")
        self.assertIsNotNone(cls)

    def test_unknown_url(self):
        from db.provider_registry import ProviderRegistry

        cls = ProviderRegistry.get_provider_by_url("jdbc:unknowndb://localhost/db")
        self.assertIsNone(cls)


class TestProviderRegistryListPlugins(unittest.TestCase):
    def test_returns_list(self):
        from db.provider_registry import ProviderRegistry

        plugins = ProviderRegistry.list_plugins()
        self.assertIsInstance(plugins, list)
        self.assertGreater(len(plugins), 0)


class TestProviderRegistryGetTransport(unittest.TestCase):
    def test_postgresql_is_native(self):
        from db.provider_registry import ProviderRegistry

        transport = ProviderRegistry.get_provider_transport("postgresql")
        self.assertEqual(transport, "native")

    def test_cosmosdb_is_native(self):
        from db.provider_registry import ProviderRegistry

        transport = ProviderRegistry.get_provider_transport("cosmosdb")
        self.assertEqual(transport, "native")


class TestNativeDriverManager(unittest.TestCase):
    def test_get_available_drivers(self):
        from db.provider_registry import NativeDriverManager

        result = NativeDriverManager.get_available_drivers([])
        self.assertIsInstance(result, dict)

    def test_missing_dotted_driver_module_returns_false(self):
        """A missing parent package must not crash optional driver checks."""
        from db.base_provider import BaseProvider
        from db.provider_registry import NativeDriverManager, PluginInfo

        plugin = PluginInfo(
            name="missingdb",
            version="0.0.0",
            description="Missing driver test plugin",
            dialects=["missingdb"],
            provider_class=BaseProvider,
            native_driver_module="definitely_missing_parent.driver",
        )

        self.assertFalse(NativeDriverManager.check_driver_installed(plugin))
