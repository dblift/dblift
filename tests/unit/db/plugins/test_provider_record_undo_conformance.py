"""Structural guard for ``Provider.record_undo``.

Batch 11 surfaced ``BUG-06``: ``SQLiteProvider`` shipped without
``record_undo`` and crashed with ``AttributeError`` whenever
``MigrationHistoryManager.record_undo`` tried to dispatch. ``CosmosDbProvider``
had the same latent gap. The class-level fix adds a default delegation on
``BaseProvider``: if the provider exposes a ``history_manager`` and a
``connection``, ``record_undo`` simply forwards.

This test enforces the contract structurally so a future provider can't
ship without it:

* every concrete ``BaseProvider`` subclass under ``db/plugins/<dialect>/``
  must expose a callable ``record_undo`` with the same signature as
  ``BaseProvider.record_undo``,
* the default delegation on ``BaseProvider`` must call
  ``history_manager.record_undo`` with the provider's ``connection``,
* a provider missing ``history_manager`` must raise ``NotImplementedError``
  rather than ``AttributeError`` (so the operator gets a real error message).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest
from unittest.mock import MagicMock

from db.base_provider import BaseProvider


def _iter_concrete_provider_classes() -> list[type[BaseProvider]]:
    """Return every concrete subclass of ``BaseProvider`` under ``db.plugins``.

    Walks the ``db.plugins`` package tree, imports each ``provider`` module,
    and collects classes that subclass ``BaseProvider`` and are not
    abstract. We rely on import side-effects only — no instantiation, so
    optional drivers (JPype, Cosmos SDK) don't need to be installed.
    """
    import db.plugins as plugins_pkg

    discovered: dict[str, type[BaseProvider]] = {}
    for module_info in pkgutil.walk_packages(
        plugins_pkg.__path__, prefix=f"{plugins_pkg.__name__}."
    ):
        if not module_info.name.endswith(".provider"):
            continue
        module = importlib.import_module(module_info.name)
        for _, obj in inspect.getmembers(module, inspect.isclass):
            if obj is BaseProvider or not issubclass(obj, BaseProvider):
                continue
            if inspect.isabstract(obj):
                continue
            discovered[f"{obj.__module__}.{obj.__name__}"] = obj
    return list(discovered.values())


class TestRecordUndoStructuralContract(unittest.TestCase):
    def test_every_concrete_provider_has_callable_record_undo(self) -> None:
        providers = _iter_concrete_provider_classes()
        self.assertGreaterEqual(
            len(providers),
            5,
            "expected at least 5 provider plugins (sqlite, cosmosdb, mysql, "
            "oracle, postgresql, sqlserver, db2)",
        )
        for provider_cls in providers:
            with self.subTest(provider=provider_cls.__name__):
                self.assertTrue(
                    callable(getattr(provider_cls, "record_undo", None)),
                    f"{provider_cls.__name__} is missing record_undo (BUG-06 regression)",
                )

    def test_record_undo_signature_matches_base(self) -> None:
        base_sig = inspect.signature(BaseProvider.record_undo)
        base_params = list(base_sig.parameters.keys())
        for provider_cls in _iter_concrete_provider_classes():
            with self.subTest(provider=provider_cls.__name__):
                sig = inspect.signature(provider_cls.record_undo)
                self.assertEqual(
                    list(sig.parameters.keys())[: len(base_params)],
                    base_params,
                    f"{provider_cls.__name__}.record_undo signature drifted from base",
                )


class _StubProvider(BaseProvider):
    """Bare-minimum concrete subclass: implement just the abstract surface."""

    def acquire_migration_lock(self, schema, wait_timeout_seconds=60):  # pragma: no cover
        return True

    def begin_transaction(self):  # pragma: no cover
        pass

    def clean_schema(self, schema):  # pragma: no cover
        pass

    def commit_transaction(self):  # pragma: no cover
        pass

    def connect(self):  # pragma: no cover
        pass

    def create_connection(self):  # pragma: no cover
        return None

    def create_history_table(self, schema, table_name):  # pragma: no cover
        return ""

    def create_migration_history_table_if_not_exists(  # pragma: no cover
        self, schema, create_schema=False, table_name="dblift_schema_history"
    ):
        pass

    def create_migration_lock_table_if_not_exists(self, schema):  # pragma: no cover
        pass

    def create_schema_if_not_exists(self, schema):  # pragma: no cover
        pass

    def create_snapshot_table_if_not_exists(  # pragma: no cover
        self, schema, table_name="dblift_schema_snapshots"
    ):
        pass

    def execute_query(self, sql, params=None):  # pragma: no cover
        return []

    def execute_statement(self, sql, schema=None, params=None):  # pragma: no cover
        return 0

    def get_applied_migrations(
        self, schema, table_name="dblift_schema_history"
    ):  # pragma: no cover
        return []

    def get_database_version(self):  # pragma: no cover
        return ""

    def get_schema_qualified_name(self, schema, object_name):  # pragma: no cover
        return f"{schema}.{object_name}"

    def is_connected(self):  # pragma: no cover
        return True

    def record_migration(  # pragma: no cover
        self, schema, migration_info, table_name="dblift_schema_history"
    ):
        pass

    def release_migration_lock(self, schema):  # pragma: no cover
        return True

    def rollback_transaction(self):  # pragma: no cover
        pass

    def set_current_schema(self, schema):  # pragma: no cover
        pass

    def table_exists(self, schema, table_name):  # pragma: no cover
        return False


class TestBaseProviderRecordUndoDefault(unittest.TestCase):
    """Behaviour of the default delegation on ``BaseProvider``."""

    def _make_provider(self) -> _StubProvider:
        provider = _StubProvider.__new__(_StubProvider)
        provider.config = MagicMock()
        provider.log = MagicMock()
        provider.connection = MagicMock()
        provider.history_manager = MagicMock()
        provider.history_manager.record_undo.return_value = True
        return provider

    def test_default_delegates_to_history_manager(self) -> None:
        provider = self._make_provider()
        result = provider.record_undo("main", "1.0.0", "dblift_schema_history")
        self.assertTrue(result)
        provider.history_manager.record_undo.assert_called_once_with(
            provider.connection, "main", "1.0.0", "dblift_schema_history", None
        )

    def test_default_passes_none_table_name(self) -> None:
        provider = self._make_provider()
        provider.record_undo("main", "2.0.0")
        provider.history_manager.record_undo.assert_called_once_with(
            provider.connection, "main", "2.0.0", None, None
        )

    def test_default_passes_script_name_when_provided(self) -> None:
        provider = self._make_provider()
        provider.record_undo("main", "4", "dblift_schema_history", "V4__python_migration.py")
        provider.history_manager.record_undo.assert_called_once_with(
            provider.connection,
            "main",
            "4",
            "dblift_schema_history",
            "V4__python_migration.py",
        )

    def test_default_propagates_failure(self) -> None:
        provider = self._make_provider()
        provider.history_manager.record_undo.return_value = False
        self.assertFalse(provider.record_undo("main", "3.0.0"))

    def test_default_raises_when_history_manager_missing(self) -> None:
        provider = _StubProvider.__new__(_StubProvider)
        provider.config = MagicMock()
        provider.log = MagicMock()
        provider.connection = MagicMock()
        # No history_manager attribute on purpose.
        with self.assertRaises(NotImplementedError) as ctx:
            provider.record_undo("main", "1.0.0")
        self.assertIn("history_manager", str(ctx.exception))


class TestSqliteInheritsDefault(unittest.TestCase):
    """SQLiteProvider's own override was dropped — it must inherit the base."""

    def test_sqlite_uses_inherited_record_undo(self) -> None:
        from db.plugins.sqlite.provider import SQLiteProvider

        self.assertNotIn(
            "record_undo",
            SQLiteProvider.__dict__,
            "SQLiteProvider should inherit record_undo from BaseProvider, "
            "not redeclare it (the override was dead weight after the base default).",
        )
        # The MRO must still resolve to a callable.
        self.assertTrue(callable(SQLiteProvider.record_undo))


if __name__ == "__main__":
    unittest.main()
