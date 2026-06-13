"""Tests for ObjectComparator lazy initialization via _COMPARATOR_REGISTRY + __getattr__ (story 18-11)."""

import inspect
from unittest.mock import MagicMock, patch

import pytest

from core.comparison.comparator import ObjectComparator
from core.comparison.index_comparator import IndexComparator
from core.comparison.type_normalizer import DataTypeNormalizer


@pytest.mark.unit
class TestComparatorRegistry:
    """AC#1: _COMPARATOR_REGISTRY class attribute with 15 entries."""

    def test_registry_has_16_entries(self):
        assert len(ObjectComparator._COMPARATOR_REGISTRY) == 16

    def test_registry_is_class_attribute(self):
        assert "_COMPARATOR_REGISTRY" in ObjectComparator.__dict__


@pytest.mark.unit
class TestGetattr:
    """AC#2: __getattr__ for lazy initialization."""

    def test_getattr_raises_for_unknown(self):
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)
        with pytest.raises(AttributeError, match="no_such_attr"):
            c.no_such_attr

    def test_lazy_init_stores_in_instance_dict(self):
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)
        _ = c.index_comparator
        assert "index_comparator" in c.__dict__


@pytest.mark.unit
class TestInitClean:
    """AC#3: No backing fields in __init__."""

    def test_no_backing_fields_in_init(self):
        src = inspect.getsource(ObjectComparator.__init__)
        for key in ObjectComparator._COMPARATOR_REGISTRY:
            assert f"_{key}" not in src, f"Backing field '_{key}' should not be in __init__"

    def test_type_normalizer_stored(self):
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)
        assert c.type_normalizer is normalizer


@pytest.mark.unit
class TestNoPropertyInClassDict:
    """AC#4: No @property in class dict."""

    def test_no_property_in_class_dict(self):
        assert not isinstance(ObjectComparator.__dict__.get("index_comparator"), property)

    def test_getattr_in_class_dict(self):
        assert "__getattr__" in ObjectComparator.__dict__


@pytest.mark.unit
class TestPropertyCaching:
    """AC#5: Comparators return correct type and cache instances."""

    @pytest.mark.parametrize(
        "prop_name,expected_class", list(ObjectComparator._COMPARATOR_REGISTRY.items())
    )
    def test_property_returns_correct_type_and_caches(self, prop_name, expected_class):
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)

        first = getattr(c, prop_name)
        second = getattr(c, prop_name)

        assert isinstance(
            first, expected_class
        ), f"{prop_name} should return {expected_class.__name__}"
        assert first is second, f"{prop_name} should return same instance on second access"

    def test_accessing_one_does_not_initialize_others(self):
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)

        _ = c.index_comparator

        assert "trigger_comparator" not in c.__dict__
        assert "sequence_comparator" not in c.__dict__
        assert "package_comparator" not in c.__dict__


@pytest.mark.unit
class TestDelegationTransparency:
    """AC#5.3: Direct assignment works for mock injection."""

    def test_compare_indexes_delegates_to_index_comparator(self):
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)

        with patch.object(IndexComparator, "compare_indexes", return_value=[]) as mock_cmp:
            result = c.compare_indexes([], [], "postgresql")
            mock_cmp.assert_called_once_with([], [], "postgresql")
            assert result == []

    def test_mock_via_direct_assignment(self):
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)

        mock_idx = MagicMock(spec=IndexComparator)
        mock_idx.compare_indexes.return_value = ["diff"]
        c.index_comparator = mock_idx

        result = c.compare_indexes([], [], "postgresql")
        assert result == ["diff"]
        mock_idx.compare_indexes.assert_called_once_with([], [], "postgresql")


@pytest.mark.unit
class TestNonRegressionsDeadCode:
    """AC#5.5/5.6: table_comparator exists (lazy); view_comparator must not exist (story 13-16)."""

    def test_table_comparator_in_registry_and_lazy(self):
        """table_comparator is in _COMPARATOR_REGISTRY and lazily initialized (story 18-11)."""
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)
        assert "table_comparator" in ObjectComparator._COMPARATOR_REGISTRY
        assert "table_comparator" not in c.__dict__
        _ = c.table_comparator
        assert "table_comparator" in c.__dict__

    def test_hasattr_view_comparator_false(self):
        normalizer = DataTypeNormalizer()
        c = ObjectComparator(normalizer)
        assert not hasattr(
            c, "view_comparator"
        ), "view_comparator must not exist (removed in story 13-16)"
