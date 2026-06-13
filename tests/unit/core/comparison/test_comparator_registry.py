"""Tests for the pluggable comparator registry (roadmap action #13).

Action #13 makes ``ObjectComparator``'s comparator lookup pluggable through
the ``dblift.comparators`` entry-point group (mirroring
``dblift.providers``). The 15 first-party comparators stay registered
unchanged; third-party comparators can be added without touching ``core/``.

These tests pin:
- the 15 first-party comparators remain reachable;
- a synthetic third-party comparator registered via the entry-point
  mechanism is reachable on an :class:`ObjectComparator` instance;
- first-party names win against accidental third-party shadows;
- unknown names raise ``AttributeError``;
- ``register_external_comparator`` validates inputs.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import patch

import pytest

from core.comparison import _comparator_registry
from core.comparison._comparator_registry import (
    _FIRST_PARTY_COMPARATORS,
    ENTRY_POINT_GROUP,
    _reset_for_tests,
    get_comparator_class,
    get_registered_names,
    register_external_comparator,
)
from core.comparison.comparator import ObjectComparator
from core.comparison.type_normalizer import DataTypeNormalizer

# ---------------------------------------------------------------------------
# Synthetic third-party comparator.
# ---------------------------------------------------------------------------


class _SyntheticComparator:
    """Single-arg comparator matching the first-party convention."""

    def __init__(self, type_normalizer: Any) -> None:
        self.type_normalizer = type_normalizer

    def compare(self, expected: Any, actual: Any) -> str:
        return "synthetic-diff"


@pytest.fixture(autouse=True)
def _isolated_registry():
    """Snapshot + restore external comparator state across every test."""
    saved_external = dict(_comparator_registry._external_comparators)
    saved_discovered = _comparator_registry._external_discovered
    yield
    _comparator_registry._external_comparators.clear()
    _comparator_registry._external_comparators.update(saved_external)
    _comparator_registry._external_discovered = saved_discovered


# ---------------------------------------------------------------------------
# First-party invariants — no regression after the extraction.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFirstPartyComparators:
    def test_first_party_table_lists_sixteen_comparators(self):
        """The 16 comparators that lived in
        ``ObjectComparator._COMPARATOR_REGISTRY`` must all be present
        in the first-party table now (15 at PR open + ``module_comparator``
        added on develop while this branch was open)."""
        expected = {
            "table_comparator",
            "index_comparator",
            "trigger_comparator",
            "procedure_comparator",
            "function_comparator",
            "synonym_comparator",
            "user_defined_type_comparator",
            "module_comparator",
            "package_comparator",
            "extension_comparator",
            "event_comparator",
            "database_link_comparator",
            "linked_server_comparator",
            "foreign_data_wrapper_comparator",
            "foreign_server_comparator",
            "sequence_comparator",
        }
        assert set(_FIRST_PARTY_COMPARATORS.keys()) == expected

    def test_get_comparator_class_resolves_first_party_without_discovery(self):
        """First-party lookup must not trigger external entry-point
        discovery — keeps the hot path cheap and side-effect-free."""
        _reset_for_tests()
        cls = get_comparator_class("table_comparator")
        assert cls is not None
        assert cls is _FIRST_PARTY_COMPARATORS["table_comparator"]
        # No discovery should have run.
        assert _comparator_registry._external_discovered is False

    def test_object_comparator_class_var_still_exposes_first_party(self):
        """Some legacy callers may have introspected
        ``ObjectComparator._COMPARATOR_REGISTRY``; it must still surface
        the same first-party names they always saw."""
        assert dict(ObjectComparator._COMPARATOR_REGISTRY) == _FIRST_PARTY_COMPARATORS

    def test_object_comparator_class_var_is_read_only(self):
        """A legacy caller mutating ``ObjectComparator._COMPARATOR_REGISTRY``
        in place would silently pollute ``_FIRST_PARTY_COMPARATORS`` if the
        class var were a direct alias. ``MappingProxyType`` turns the
        mutation into a loud ``TypeError`` so the failure is immediate."""
        with pytest.raises(TypeError, match="does not support item assignment"):
            ObjectComparator._COMPARATOR_REGISTRY["should_not_take"] = object  # type: ignore[index]
        # And the source-of-truth dict stayed clean.
        assert "should_not_take" not in _FIRST_PARTY_COMPARATORS


# ---------------------------------------------------------------------------
# External entry-point plumbing.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestExternalDiscovery:
    def _make_entry_point(self, name: str, loaded: Any) -> Any:
        """Return a stand-in entry-point object matching ``importlib.metadata`` shape."""

        class _FakeEntryPoint:
            def __init__(self, _name: str, _loaded: Any) -> None:
                self.name = _name
                self.value = "synthetic:Synthetic"
                self.group = ENTRY_POINT_GROUP
                self._loaded = _loaded

            def load(self) -> Any:
                return self._loaded

        return _FakeEntryPoint(name, loaded)

    def test_external_comparator_resolved_via_entry_point(self):
        """A class published under the ``dblift.comparators`` group must
        become reachable through ``get_comparator_class``."""
        _reset_for_tests()
        fake_ep = self._make_entry_point("synthetic_comparator", _SyntheticComparator)

        with patch(
            "importlib.metadata.entry_points",
            return_value=[fake_ep],
        ):
            resolved = get_comparator_class("synthetic_comparator")

        assert resolved is _SyntheticComparator

    def test_discovery_is_idempotent(self):
        """Two calls to ``get_comparator_class`` must trigger entry-point
        enumeration at most once — guards against repeated import cost."""
        _reset_for_tests()
        fake_ep = self._make_entry_point("synthetic_comparator", _SyntheticComparator)

        with patch(
            "importlib.metadata.entry_points",
            return_value=[fake_ep],
        ) as mocked:
            get_comparator_class("synthetic_comparator")
            get_comparator_class("synthetic_comparator")
            get_comparator_class("does_not_exist")

        assert mocked.call_count == 1

    def test_failed_entry_point_load_does_not_break_others(self):
        """An exception during ``ep.load()`` must not abort the loop —
        one malformed plugin shouldn't disable the rest."""
        _reset_for_tests()

        class _BadEntryPoint:
            name = "bad_comparator"
            value = "x:y"
            group = ENTRY_POINT_GROUP

            def load(self):
                raise RuntimeError("boom")

        good_ep = self._make_entry_point("synthetic_comparator", _SyntheticComparator)

        with patch(
            "importlib.metadata.entry_points",
            return_value=[_BadEntryPoint(), good_ep],
        ):
            assert get_comparator_class("bad_comparator") is None
            assert get_comparator_class("synthetic_comparator") is _SyntheticComparator

    def test_non_class_entry_point_is_ignored(self):
        """An entry point that loads to something other than a class
        (typo'd ``module:obj`` pointing at a function) must be skipped."""
        _reset_for_tests()

        def _not_a_class():  # pragma: no cover - never invoked
            pass

        bad_ep = self._make_entry_point("not_a_class_comparator", _not_a_class)

        with patch("importlib.metadata.entry_points", return_value=[bad_ep]):
            assert get_comparator_class("not_a_class_comparator") is None

    def test_first_party_wins_against_external_collision(self):
        """If a third-party plugin registers under a first-party name (e.g.
        ``table_comparator``) — by accident or malice — the first-party
        class must still resolve. Protects the contract from silent swaps."""
        _reset_for_tests()

        class _Shadow:
            def __init__(self, _: Any) -> None:
                pass

        shadow_ep = self._make_entry_point("table_comparator", _Shadow)

        with patch("importlib.metadata.entry_points", return_value=[shadow_ep]):
            resolved = get_comparator_class("table_comparator")

        assert resolved is _FIRST_PARTY_COMPARATORS["table_comparator"]
        assert resolved is not _Shadow


# ---------------------------------------------------------------------------
# Programmatic registration helper.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestRegisterExternalComparator:
    def test_register_then_resolve(self):
        register_external_comparator("synthetic_comparator", _SyntheticComparator)
        assert get_comparator_class("synthetic_comparator") is _SyntheticComparator

    def test_register_rejects_non_class(self):
        with pytest.raises(TypeError, match="expected a class"):
            register_external_comparator("synthetic_comparator", "not a class")  # type: ignore[arg-type]

    def test_register_refuses_to_shadow_first_party(self):
        with pytest.raises(ValueError, match="reserved for the first-party"):
            register_external_comparator("table_comparator", _SyntheticComparator)


# ---------------------------------------------------------------------------
# End-to-end: third-party comparator reachable through ObjectComparator.
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestObjectComparatorIntegration:
    def test_object_comparator_resolves_third_party_attribute(self):
        """The acceptance criterion: ``ObjectComparator.<external_name>``
        works without any modification to ``core/comparison/comparator.py``."""
        register_external_comparator("synthetic_comparator", _SyntheticComparator)

        comparator = ObjectComparator(DataTypeNormalizer())
        synthetic = comparator.synthetic_comparator

        assert isinstance(synthetic, _SyntheticComparator)
        # Same instance returned on repeated access (cached via
        # ``object.__setattr__`` in ``__getattr__``).
        assert comparator.synthetic_comparator is synthetic

    def test_unknown_attribute_still_raises(self):
        comparator = ObjectComparator(DataTypeNormalizer())
        with pytest.raises(AttributeError, match="has no attribute 'not_a_real_comparator'"):
            _ = comparator.not_a_real_comparator

    def test_get_registered_names_includes_first_party_and_external(self):
        register_external_comparator("synthetic_comparator", _SyntheticComparator)
        names = get_registered_names()
        assert "table_comparator" in names
        assert "synthetic_comparator" in names


# ---------------------------------------------------------------------------
# Typed-property accessors (roadmap action #14).
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestFirstPartyTypedProperties:
    """Action #14 replaced the lazy ``__getattr__`` dispatch for first-party
    comparators with 16 explicit ``@cached_property`` accessors, each
    annotated with the concrete comparator class. These tests pin the
    invariants the typed properties must hold.
    """

    def test_each_first_party_accessor_returns_its_concrete_class(self):
        """Every first-party slot must instantiate the exact class declared
        in ``_FIRST_PARTY_COMPARATORS`` — so the type annotation on the
        property body isn't lying to mypy and IDE auto-complete."""
        comparator = ObjectComparator(DataTypeNormalizer())
        for name, expected_cls in _FIRST_PARTY_COMPARATORS.items():
            instance = getattr(comparator, name)
            assert isinstance(instance, expected_cls), (
                f"ObjectComparator.{name} returned {type(instance).__name__}, "
                f"expected {expected_cls.__name__}"
            )

    def test_first_party_access_is_cached_per_instance(self):
        """``cached_property`` must cache in ``self.__dict__`` so two accesses
        return the same object — matches the legacy ``object.__setattr__``
        contract the old ``__getattr__`` relied on."""
        comparator = ObjectComparator(DataTypeNormalizer())
        for name in _FIRST_PARTY_COMPARATORS:
            first = getattr(comparator, name)
            second = getattr(comparator, name)
            assert first is second, f"{name} is not cached (got two distinct instances)"

    def test_table_comparator_receives_log_kwarg(self):
        """Among the 16 first-party comparators, only ``TableComparator``
        constructor takes ``log=``. Verify the property body passes it."""
        from core.logger import NullLog

        log = NullLog()
        comparator = ObjectComparator(DataTypeNormalizer(), log=log)
        # TableComparator stores ``log`` as a public attribute; if it didn't
        # receive the kwarg it would fall back to its own default.
        assert comparator.table_comparator.log is log

    def test_first_party_access_bypasses_getattr_dispatch(self):
        """First-party names must NEVER reach ``__getattr__`` — typed
        ``cached_property`` definitions intercept them. Setting an external
        comparator under a first-party name (which ``register_external_comparator``
        forbids) wouldn't override the typed property; demonstrate by
        bypassing the guard via direct dict mutation and confirming the
        property still wins."""
        from core.comparison import _comparator_registry

        # Sneak past register_external_comparator's first-party shadow guard.
        _comparator_registry._external_comparators["table_comparator"] = _SyntheticComparator
        try:
            comparator = ObjectComparator(DataTypeNormalizer())
            # Property descriptor wins over __getattr__: still the real class.
            from core.comparison.table_comparator import TableComparator

            assert isinstance(comparator.table_comparator, TableComparator)
            assert not isinstance(comparator.table_comparator, _SyntheticComparator)
        finally:
            _comparator_registry._external_comparators.pop("table_comparator", None)

    def test_property_annotations_are_concrete_types_not_any(self):
        """``ObjectComparator.<name>`` must have a concrete class return
        annotation (not ``Any``) on the class-level descriptor. This is what
        mypy and IDE auto-complete consume. The check inspects
        ``__annotations__`` on the function the cached_property wraps."""
        import inspect

        from core.comparison.comparator import ObjectComparator as OC

        for name in _FIRST_PARTY_COMPARATORS:
            descriptor = inspect.getattr_static(OC, name)
            # cached_property stores the wrapped function on ``.func``.
            func = getattr(descriptor, "func", None)
            assert func is not None, f"{name} is not a cached_property"
            hints = func.__annotations__
            return_annotation = hints.get("return")
            assert return_annotation is not None, f"{name} has no return annotation"
            assert return_annotation is not Any, (
                f"{name} is annotated ``Any`` — the typed-property contract "
                f"requires the concrete comparator class"
            )
