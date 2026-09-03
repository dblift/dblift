"""Structural guard for ``Provider.repair_migration_history``.

``MigrationHistoryManager.repair_checksum`` calls the method on the provider
and catches every exception, so a plugin that simply does not define it does
not raise — ``repair`` reports "may require manual intervention" and exits
having changed nothing. SQLite shipped in exactly that state: the method is
declared on no base class, so nothing forced a plugin to provide it.

This mirrors ``test_provider_delete_failed_entry_conformance.py`` and
``test_provider_record_undo_conformance.py``, which exist because
``delete_failed_migration_entry`` and ``record_undo`` shipped with the same
class of gap.
"""

from __future__ import annotations

import importlib
import inspect
import pkgutil
import unittest

from dblift.db.base_provider import BaseProvider

_REQUIRED_PARAMETERS = ("schema", "script_name", "checksum", "table_name", "success_value")


def _iter_concrete_provider_classes() -> list[type[BaseProvider]]:
    """Every concrete ``BaseProvider`` subclass under ``dblift.db.plugins``.

    Import side-effects only — no instantiation, so optional drivers need not
    be installed.
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


class TestRepairMigrationHistoryContract(unittest.TestCase):
    def test_every_concrete_provider_exposes_it(self) -> None:
        for cls in _iter_concrete_provider_classes():
            with self.subTest(provider=cls.__name__):
                self.assertTrue(
                    callable(getattr(cls, "repair_migration_history", None)),
                    f"{cls.__name__} has no callable repair_migration_history; "
                    "repair silently leaves the drifted checksum in place",
                )

    def test_every_implementation_accepts_the_call_repair_makes(self) -> None:
        """``repair_checksum`` passes ``success_value`` and ``table_name`` by keyword."""
        for cls in _iter_concrete_provider_classes():
            with self.subTest(provider=cls.__name__):
                signature = inspect.signature(cls.repair_migration_history)
                for name in _REQUIRED_PARAMETERS:
                    self.assertIn(
                        name,
                        signature.parameters,
                        f"{cls.__name__}.repair_migration_history has no {name!r} parameter",
                    )


if __name__ == "__main__":
    unittest.main()
