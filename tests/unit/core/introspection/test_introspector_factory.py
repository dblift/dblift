"""Tests for db/introspection/introspector_factory.py."""

import unittest
from unittest.mock import MagicMock


class TestIntrospectorFactoryRegister(unittest.TestCase):
    def setUp(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        # Clear map to isolate tests
        self._orig = dict(IntrospectorFactory._DIALECT_MAP)
        IntrospectorFactory._DIALECT_MAP.clear()

    def tearDown(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        IntrospectorFactory._DIALECT_MAP.clear()
        IntrospectorFactory._DIALECT_MAP.update(self._orig)

    def test_register_stores_lowercase(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        cls = MagicMock()
        IntrospectorFactory.register("PostgreSQL", cls)
        self.assertIn("postgresql", IntrospectorFactory._DIALECT_MAP)
        self.assertIs(IntrospectorFactory._DIALECT_MAP["postgresql"], cls)

    def test_is_supported_true(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        IntrospectorFactory.register("oracle", MagicMock())
        self.assertTrue(IntrospectorFactory.is_supported("oracle"))
        self.assertTrue(IntrospectorFactory.is_supported("ORACLE"))

    def test_is_supported_false(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        self.assertFalse(IntrospectorFactory.is_supported("unknown_db"))

    def test_supported_dialects_returns_list(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        IntrospectorFactory.register("mysql", MagicMock())
        dialects = IntrospectorFactory.supported_dialects()
        self.assertIn("mysql", dialects)


class TestIntrospectorFactoryCreate(unittest.TestCase):
    def setUp(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        self._orig = dict(IntrospectorFactory._DIALECT_MAP)

    def tearDown(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        IntrospectorFactory._DIALECT_MAP.clear()
        IntrospectorFactory._DIALECT_MAP.update(self._orig)

    def _make_provider(self, dialect):
        p = MagicMock()
        p.config.database.type = dialect
        return p

    def test_create_known_dialect(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        mock_class = MagicMock(return_value=MagicMock())
        IntrospectorFactory._DIALECT_MAP["testdb"] = mock_class
        provider = self._make_provider("testdb")
        result = IntrospectorFactory.create(provider)
        mock_class.assert_called_once_with(provider, None, True)

    def test_create_unknown_falls_back_to_schema_introspector(self):
        from core.introspection.introspector_factory import IntrospectorFactory
        from core.introspection.schema_introspector import SchemaIntrospector

        provider = self._make_provider("unknown_db_xyz")
        result = IntrospectorFactory.create(provider)
        self.assertIsInstance(result, SchemaIntrospector)

    def test_create_no_config_uses_unknown(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        provider = MagicMock(spec=[])  # no config attr
        result = IntrospectorFactory.create(provider)
        self.assertIsNotNone(result)

    def test_create_postgresql(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("postgresql")
        result = IntrospectorFactory.create(provider)
        self.assertIsNotNone(result)

    def test_create_mysql(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("mysql")
        result = IntrospectorFactory.create(provider)
        self.assertIsNotNone(result)

    def test_create_oracle(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("oracle")
        result = IntrospectorFactory.create(provider)
        self.assertIsNotNone(result)

    def test_create_with_log(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("unknown_xyz")
        log = MagicMock()
        result = IntrospectorFactory.create(provider, log=log)
        self.assertIsNotNone(result)

    def test_register_defaults_called_once(self):
        from core.introspection.introspector_factory import IntrospectorFactory

        # Clear map to trigger _register_defaults
        IntrospectorFactory._DIALECT_MAP.clear()
        provider = self._make_provider("postgresql")
        IntrospectorFactory.create(provider)
        # After creation, map should be populated
        self.assertTrue(len(IntrospectorFactory._DIALECT_MAP) > 0)
