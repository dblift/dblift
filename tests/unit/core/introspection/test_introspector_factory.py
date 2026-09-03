"""Tests for db/introspection/introspector_factory.py."""

import unittest
from unittest.mock import MagicMock


class TestIntrospectorFactoryRegister(unittest.TestCase):
    def setUp(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        # Clear map to isolate tests
        self._orig = dict(IntrospectorFactory._DIALECT_MAP)
        IntrospectorFactory._DIALECT_MAP.clear()

    def tearDown(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        IntrospectorFactory._DIALECT_MAP.clear()
        IntrospectorFactory._DIALECT_MAP.update(self._orig)

    def test_register_stores_lowercase(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        cls = MagicMock()
        IntrospectorFactory.register("PostgreSQL", cls)
        self.assertIn("postgresql", IntrospectorFactory._DIALECT_MAP)
        self.assertIs(IntrospectorFactory._DIALECT_MAP["postgresql"], cls)

    def test_is_supported_true(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        IntrospectorFactory.register("oracle", MagicMock())
        self.assertTrue(IntrospectorFactory.is_supported("oracle"))
        self.assertTrue(IntrospectorFactory.is_supported("ORACLE"))

    def test_is_supported_false(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        self.assertFalse(IntrospectorFactory.is_supported("unknown_db"))

    def test_supported_dialects_returns_list(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        IntrospectorFactory.register("mysql", MagicMock())
        dialects = IntrospectorFactory.supported_dialects()
        self.assertIn("mysql", dialects)


class TestIntrospectorFactoryCreate(unittest.TestCase):
    def setUp(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        self._orig = dict(IntrospectorFactory._DIALECT_MAP)

    def tearDown(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        IntrospectorFactory._DIALECT_MAP.clear()
        IntrospectorFactory._DIALECT_MAP.update(self._orig)

    def _make_provider(self, dialect):
        p = MagicMock()
        p.config.database.type = dialect
        return p

    def test_create_known_dialect(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        mock_class = MagicMock(return_value=MagicMock())
        IntrospectorFactory._DIALECT_MAP["testdb"] = mock_class
        provider = self._make_provider("testdb")
        result = IntrospectorFactory.create(provider)
        mock_class.assert_called_once_with(provider, None, True)

    def test_create_unknown_falls_back_to_schema_introspector(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory
        from dblift.core.introspection.schema_introspector import SchemaIntrospector

        provider = self._make_provider("unknown_db_xyz")
        result = IntrospectorFactory.create(provider)
        self.assertIsInstance(result, SchemaIntrospector)

    def test_create_no_config_uses_unknown(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        provider = MagicMock(spec=[])  # no config attr
        result = IntrospectorFactory.create(provider)
        self.assertIsNotNone(result)

    def test_create_postgresql(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("postgresql")
        result = IntrospectorFactory.create(provider)
        self.assertIsNotNone(result)

    def test_create_mysql(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("mysql")
        result = IntrospectorFactory.create(provider)
        self.assertIsNotNone(result)

    def test_create_oracle(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("oracle")
        result = IntrospectorFactory.create(provider)
        self.assertIsNotNone(result)

    def test_create_with_log(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("unknown_xyz")
        log = MagicMock()
        result = IntrospectorFactory.create(provider, log=log)
        self.assertIsNotNone(result)

    def test_register_defaults_called_once(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory
        from dblift.core.introspection.schema_introspector import SchemaIntrospector

        # Clear map to trigger _register_defaults
        IntrospectorFactory._DIALECT_MAP.clear()
        provider = self._make_provider("postgresql")
        result = IntrospectorFactory.create(provider)
        # After P3 relocation, OSS quirks return no introspector_class; PRO
        # registration is guarded by _REGISTERED (set on first startup), so a
        # cleared map causes a SchemaIntrospector fallback — not a crash.
        self.assertIsNotNone(result)

    def test_create_runs_registered_introspection_seam(self):
        from dblift.core.introspection.introspector_factory import IntrospectorFactory

        provider = self._make_provider("seamdb")
        introspector_class = MagicMock(return_value=MagicMock())
        IntrospectorFactory._DIALECT_MAP.clear()

        def attach():
            IntrospectorFactory.register("seamdb", introspector_class)

        with unittest.mock.patch(
            "dblift.core.seams.introspection.attach_registered_introspection",
            side_effect=attach,
        ):
            result = IntrospectorFactory.create(provider)

        self.assertIsNotNone(result)
        introspector_class.assert_called_once_with(provider, None, True)
