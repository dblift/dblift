"""Tests for ModuleComparator wiring in ObjectComparator (Story OBS-modules)."""

import importlib

import pytest

from core.comparison.comparator import ObjectComparator
from core.comparison.type_normalizer import DataTypeNormalizer


@pytest.mark.unit
class TestObjectComparatorModuleCleanup:
    """Verify module_comparator is properly wired into ObjectComparator."""

    def test_object_comparator_has_compare_modules_method(self):
        assert hasattr(ObjectComparator, "compare_modules")

    def test_object_comparator_has_module_comparator_in_registry(self):
        assert "module_comparator" in ObjectComparator._COMPARATOR_REGISTRY

    def test_module_comparator_importable(self):
        mod = importlib.import_module("core.comparison.module_comparator")
        assert hasattr(mod, "ModuleComparator")
