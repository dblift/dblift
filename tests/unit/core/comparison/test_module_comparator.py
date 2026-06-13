"""Unit tests for ModuleComparator."""

import pytest

from core.comparison.module_comparator import ModuleComparator
from core.sql_model.module import Module


@pytest.mark.unit
class TestModuleComparator:
    """Tests for ModuleComparator.compare_modules."""

    def setup_method(self):
        """Set up comparator instance."""
        self.comparator = ModuleComparator()

    def _module(self, name="m", definition="CREATE MODULE m END MODULE;", schema=None):
        return Module(name=name, definition=definition, schema=schema, dialect="db2")

    def test_identical_modules_returns_none(self):
        """No diff when both modules have same definition."""
        m = self._module()
        assert self.comparator.compare_modules(m, m) is None

    def test_definition_changed_returns_diff(self):
        """Diff returned when definitions differ."""
        expected = self._module(definition="CREATE MODULE m PUBLISH PROC p() END MODULE;")
        actual = self._module(definition="CREATE MODULE m END MODULE;")
        diff = self.comparator.compare_modules(expected, actual)
        assert diff is not None
        assert diff.definition_changed is True

    def test_definition_whitespace_normalized(self):
        """Whitespace differences are ignored."""
        expected = self._module(definition="CREATE  MODULE  m  END  MODULE;")
        actual = self._module(definition="CREATE MODULE m END MODULE;")
        assert self.comparator.compare_modules(expected, actual) is None

    def test_diff_object_name_set(self):
        """Diff object_name uses module name."""
        expected = self._module(
            name="my_module", definition="CREATE MODULE my_module PROC p() END MODULE;"
        )
        actual = self._module(name="my_module", definition="CREATE MODULE my_module END MODULE;")
        diff = self.comparator.compare_modules(expected, actual)
        assert diff is not None
        assert diff.module_name == "my_module"

    def test_type_normalizer_ignored(self):
        """type_normalizer param accepted without error."""
        comparator = ModuleComparator(type_normalizer=object())
        m = self._module()
        assert comparator.compare_modules(m, m) is None
