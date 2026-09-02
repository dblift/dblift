"""Structural guard for ``Provider.delete_failed_migration_entry``.

``repair`` used to compose its own ``DELETE`` and send it through
``provider.execute_statement``. Moving that statement behind a provider
method broke every plugin that owns no ``history_manager`` component —
which is all of them except SQLite and CosmosDB — because the first
implementation delegated unconditionally and raised ``NotImplementedError``
otherwise. Nothing went red: the repair unit tests mock the history
facade wholesale, and the Oracle regression test hand-builds a provider
stub that has the attribute the real class lacks.

This mirrors ``test_provider_record_undo_conformance.py``, which exists
because ``record_undo`` shipped with the same class of gap (BUG-06).
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest
from unittest.mock import MagicMock

from dblift.db.base_provider import BaseProvider


def _iter_concrete_provider_classes() -> list[type[BaseProvider]]:
    """Every concrete ``BaseProvider`` subclass under ``dblift.db.plugins``.

    Import side-effects only — no instantiation, so optional drivers
    (JPype, the Cosmos SDK) need not be installed.
    """
    import dblift.db.plugins as plugins_pkg

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


def _prepare(cls: type[BaseProvider]) -> BaseProvider:
    """Build an uninitialised provider with just enough state to call through."""
    provider = object.__new__(cls)
    provider.config = MagicMock()
    provider.config.database.type = getattr(cls, "canonical_dialect_key", "") or "postgresql"
    provider._quirks = None
    provider.log = MagicMock()
    provider.execute_statement = MagicMock(return_value=1)  # type: ignore[method-assign]
    provider.get_schema_qualified_name = (  # type: ignore[method-assign]
        lambda schema, table: f'"{schema}"."{table}"'
    )
    return provider


class TestDeleteFailedMigrationEntryContract(unittest.TestCase):
    def test_every_concrete_provider_exposes_it(self) -> None:
        for cls in _iter_concrete_provider_classes():
            with self.subTest(provider=cls.__name__):
                self.assertTrue(
                    callable(getattr(cls, "delete_failed_migration_entry", None)),
                    f"{cls.__name__} has no callable delete_failed_migration_entry",
                )

    def test_no_provider_raises_notimplemented(self) -> None:
        """The regression itself: providers without a history_manager must still work."""
        for cls in _iter_concrete_provider_classes():
            if hasattr(cls, "history_manager"):
                continue
            with self.subTest(provider=cls.__name__):
                provider = _prepare(cls)
                try:
                    rows = provider.delete_failed_migration_entry("public", "V1__x.sql")
                except NotImplementedError as exc:  # pragma: no cover - the bug
                    self.fail(f"{cls.__name__} cannot delete a failed history row: {exc}")
                self.assertEqual(rows, 1)

    def test_default_emits_a_parameterised_delete(self) -> None:
        """The script name is bound, never interpolated into the statement."""
        cls = next(
            c
            for c in _iter_concrete_provider_classes()
            if c.__name__ == "PostgreSqlProvider"  # lint: allow-dialect-string
        )
        provider = _prepare(cls)

        provider.delete_failed_migration_entry("public", "V1__x.sql")

        sql = provider.execute_statement.call_args.args[0]  # type: ignore[attr-defined]
        params = provider.execute_statement.call_args.kwargs["params"]  # type: ignore[attr-defined]
        self.assertIn("DELETE FROM", sql)
        self.assertIn("script = ?", sql)
        self.assertNotIn("V1__x.sql", sql)
        self.assertEqual(params, ["V1__x.sql"])

    def test_a_history_manager_component_takes_precedence(self) -> None:
        """SQLite / CosmosDB express the delete through their own component."""

        cls = next(c for c in _iter_concrete_provider_classes() if c.__name__ == "SQLiteProvider")
        provider = object.__new__(cls)
        provider.history_manager = MagicMock()
        provider.history_manager.delete_failed_migration_entry.return_value = 3
        provider.connection = object()
        provider.execute_statement = MagicMock()  # type: ignore[method-assign]

        self.assertEqual(provider.delete_failed_migration_entry("s", "V1__x.sql"), 3)
        provider.execute_statement.assert_not_called()


if __name__ == "__main__":
    unittest.main()
