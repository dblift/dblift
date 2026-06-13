"""Tests for db/base_provider.py."""

import unittest
from unittest.mock import MagicMock, patch


def _make_config(dialect="postgresql"):
    from config import DbliftConfig

    config = MagicMock(spec=DbliftConfig)
    config.database = MagicMock()
    config.database.type = dialect
    config.database.url = f"{dialect}+driver://localhost/db"
    return config


def _make_concrete(dialect="postgresql"):
    """Create a minimal concrete BaseProvider subclass."""
    from db.base_provider import BaseProvider

    config = _make_config(dialect)

    class ConcreteProvider(BaseProvider):
        def create_connection(self):
            return MagicMock()

        def close_connection(self):
            pass

        def create_migration_history_table_if_not_exists(
            self, schema, create_schema=False, table_name="t"
        ):
            pass

        def create_snapshot_table_if_not_exists(self, schema, table_name="t"):
            pass

        def execute_query(self, sql, params=None, schema=None):
            return []

        def execute_statement(self, sql, params=None, schema=None):
            pass

        def get_schema_qualified_name(self, schema, name):
            return f"{schema}.{name}"

        def get_parameter_placeholders(self, count):
            return ", ".join(["?"] * count)

        def begin_transaction(self):
            pass

        def commit_transaction(self):
            pass

        def rollback_transaction(self):
            pass

        def supports_transactions(self):
            return True

        def record_migration(self, schema, info, table_name=None):
            pass

        def get_applied_migrations(self, schema, table_name=None):
            return []

        def table_exists(self, schema, table_name):
            return False

        def acquire_migration_lock(self, schema, timeout=60):
            return True

        def release_migration_lock(self, schema):
            return True

        def create_migration_lock_table_if_not_exists(self, schema):
            pass

        def create_history_table(self, schema, table_name):
            return ""

        def clean_schema(self, schema, **kwargs):
            return MagicMock()

        def create_schema_if_not_exists(self, schema):
            pass

        def get_database_version(self, connection=None):
            return "1.0"

        def set_current_schema(self, schema):
            pass

    return ConcreteProvider(config, MagicMock()), config


class TestBaseProviderInit(unittest.TestCase):
    def test_stores_config_and_log(self):
        provider, config = _make_concrete()
        self.assertIs(provider.config, config)
        self.assertIsNotNone(provider.log)

    def test_null_log_default(self):
        from core.logger import NullLog
        from db.base_provider import BaseProvider

        class Minimal(BaseProvider):
            def create_connection(self):
                return MagicMock()

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

        config = _make_config()
        provider = Minimal(config, None)
        self.assertIsInstance(provider.log, NullLog)

    def test_raises_on_non_dbliftconfig(self):
        from db.base_provider import BaseProvider

        class Minimal(BaseProvider):
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

        with self.assertRaises(TypeError):
            Minimal("not-a-config")


class TestBaseProviderGetDisplayUrl(unittest.TestCase):
    def test_returns_url(self):
        provider, config = _make_concrete()
        config.database.url = "postgresql+psycopg://localhost/db"
        url = provider.get_display_url()
        self.assertIn("postgresql+psycopg", url)

    def test_returns_empty_when_no_db(self):
        provider, config = _make_concrete()
        config.database = None
        url = provider.get_display_url()
        self.assertEqual(url, "")


class TestBaseProviderGetNormalizedName(unittest.TestCase):
    def test_normalizes_name(self):
        provider, _ = _make_concrete("oracle")
        name = provider.get_normalized_object_name("dblift_schema_history")
        self.assertIsNotNone(name)

    def test_postgresql_lowercase(self):
        provider, _ = _make_concrete("postgresql")
        name = provider.get_normalized_object_name("MyTable")
        self.assertEqual(name, "mytable")


class TestBaseProviderRecordUndo(unittest.TestCase):
    def test_delegates_to_history_manager(self):
        provider, _ = _make_concrete()
        hm = MagicMock()
        hm.record_undo.return_value = True
        provider.history_manager = hm
        provider.connection = MagicMock()
        result = provider.record_undo("public", "1.0")
        self.assertTrue(result)

    def test_raises_when_no_history_manager(self):
        provider, _ = _make_concrete()
        with self.assertRaises(NotImplementedError):
            provider.record_undo("public", "1.0")


class TestBaseProviderContextManager(unittest.TestCase):
    def test_enter_returns_connection(self):
        provider, _ = _make_concrete()
        conn = provider.__enter__()
        self.assertIsNotNone(conn)

    def test_exit_calls_close(self):
        provider, _ = _make_concrete()
        provider.close = MagicMock()
        provider.__exit__(None, None, None)
        provider.close.assert_called_once()


class TestBaseProviderIsConnected(unittest.TestCase):
    def test_default_false(self):
        provider, _ = _make_concrete()
        self.assertFalse(provider.is_connected())


class TestBaseProviderConnect(unittest.TestCase):
    def test_connect_calls_create_connection(self):
        provider, _ = _make_concrete()
        provider.create_connection = MagicMock()
        provider.connect()
        provider.create_connection.assert_called_once()


class TestNativeProvider(unittest.TestCase):
    def test_transport_is_native(self):
        from db.base_provider import NativeProvider

        self.assertEqual(NativeProvider.provider_transport, "native")
