"""Pluggable comparator registry (roadmap action #13).

Resolves which class implements each ``ObjectComparator.<comparator_name>``
attribute, with two sources merged in priority order:

1. **First-party comparators** declared by ``_FIRST_PARTY_COMPARATORS``
   below (the 15 classes that originally lived in
   ``ObjectComparator._COMPARATOR_REGISTRY``). Always available, no
   discovery required.
2. **External comparators** discovered through the
   ``dblift.comparators`` entry-point group at first lookup, mirroring the
   ``ProviderRegistry.discover_plugins`` pattern in :mod:`db.provider_registry`.

Third-party packages register a comparator by declaring the entry point in
their ``pyproject.toml``::

    [project.entry-points."dblift.comparators"]
    my_custom_comparator = "my_package.comparators:MyCustomComparator"

The ``ep.name`` becomes the lookup key (``comparator.my_custom_comparator``
on an :class:`ObjectComparator` instance); the loaded value must be a class
that accepts ``(type_normalizer)`` at construction time (matching the
single-arg first-party comparators — the ``log=`` kwarg is reserved for the
``table_comparator`` slot).
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Set, Type

from core.comparison.database_link_comparator import DatabaseLinkComparator
from core.comparison.event_comparator import EventComparator
from core.comparison.extension_comparator import ExtensionComparator
from core.comparison.foreign_data_wrapper_comparator import ForeignDataWrapperComparator
from core.comparison.foreign_server_comparator import ForeignServerComparator
from core.comparison.function_comparator import FunctionComparator
from core.comparison.index_comparator import IndexComparator
from core.comparison.linked_server_comparator import LinkedServerComparator
from core.comparison.module_comparator import ModuleComparator
from core.comparison.package_comparator import PackageComparator
from core.comparison.procedure_comparator import ProcedureComparator
from core.comparison.sequence_comparator import SequenceComparator
from core.comparison.synonym_comparator import SynonymComparator
from core.comparison.table_comparator import TableComparator
from core.comparison.trigger_comparator import TriggerComparator
from core.comparison.user_defined_type_comparator import UserDefinedTypeComparator

_logger = logging.getLogger(__name__)

ENTRY_POINT_GROUP = "dblift.comparators"

_FIRST_PARTY_COMPARATORS: Dict[str, Type[Any]] = {
    "table_comparator": TableComparator,
    "index_comparator": IndexComparator,
    "trigger_comparator": TriggerComparator,
    "procedure_comparator": ProcedureComparator,
    "function_comparator": FunctionComparator,
    "synonym_comparator": SynonymComparator,
    "user_defined_type_comparator": UserDefinedTypeComparator,
    "module_comparator": ModuleComparator,
    "package_comparator": PackageComparator,
    "extension_comparator": ExtensionComparator,
    "event_comparator": EventComparator,
    "database_link_comparator": DatabaseLinkComparator,
    "linked_server_comparator": LinkedServerComparator,
    "foreign_data_wrapper_comparator": ForeignDataWrapperComparator,
    "foreign_server_comparator": ForeignServerComparator,
    "sequence_comparator": SequenceComparator,
}

_external_comparators: Dict[str, Type[Any]] = {}
_external_discovered = False


def _discover_external_comparators() -> None:
    """Load comparator classes from the ``dblift.comparators`` entry-point group.

    Idempotent — guarded by the module-level ``_external_discovered`` flag.
    Failures on individual entry points are logged at WARNING and skipped so
    one malformed plugin can't disable the others. Mirrors
    :meth:`db.provider_registry.ProviderRegistry._discover_via_entry_points`.
    """
    global _external_discovered
    if _external_discovered:
        return
    _external_discovered = True

    try:
        from importlib.metadata import entry_points

        eps = entry_points(group=ENTRY_POINT_GROUP)
    except Exception as exc:  # pragma: no cover - defensive: importlib unavailable
        _logger.warning("Could not enumerate %s entry points: %s", ENTRY_POINT_GROUP, exc)
        return

    for ep in eps:
        try:
            loaded = ep.load()
        except Exception as exc:
            _logger.warning("Failed to load comparator entry point %s: %s", ep.name, exc)
            continue
        if not isinstance(loaded, type):
            _logger.warning(
                "Comparator entry point %s did not load a class (got %r); skipping",
                ep.name,
                type(loaded).__name__,
            )
            continue
        _external_comparators[ep.name] = loaded


def get_comparator_class(name: str) -> Optional[Type[Any]]:
    """Return the comparator class registered under ``name``, or ``None``.

    First-party comparators win when a name collision exists with an
    external plugin — defends against a third-party registering
    ``table_comparator`` (deliberate or accidental) and silently swapping
    the contract.
    """
    direct = _FIRST_PARTY_COMPARATORS.get(name)
    if direct is not None:
        return direct
    _discover_external_comparators()
    return _external_comparators.get(name)


def get_registered_names() -> Set[str]:
    """Return the union of first-party + discovered external comparator names."""
    _discover_external_comparators()
    return set(_FIRST_PARTY_COMPARATORS) | set(_external_comparators)


def register_external_comparator(name: str, cls: Type[Any]) -> None:
    """Programmatically register a comparator (intended for tests / fixtures).

    Production callers should use the ``dblift.comparators`` entry-point
    group instead — that's the supported plugin surface. This helper exists
    so tests can register a synthetic comparator without monkey-patching
    ``importlib.metadata.entry_points``.
    """
    if not isinstance(cls, type):
        raise TypeError(f"register_external_comparator: expected a class, got {type(cls).__name__}")
    if name in _FIRST_PARTY_COMPARATORS:
        raise ValueError(
            f"register_external_comparator: '{name}' is reserved for the first-party "
            f"comparator {_FIRST_PARTY_COMPARATORS[name].__name__}"
        )
    _external_comparators[name] = cls


def _reset_for_tests() -> None:
    """Test-only: clear external state so a fresh discovery can be exercised.

    Not part of the public API — never call from production code.
    """
    global _external_discovered
    _external_comparators.clear()
    _external_discovered = False
