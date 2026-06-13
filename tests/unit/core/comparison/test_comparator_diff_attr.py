"""Tests for _diff_attr() helper in comparator.py (Story 14-4, DEDUP-09)."""

import unittest

import pytest

from core.comparison.comparator import _diff_attr

pytestmark = [pytest.mark.unit]


class TestDiffAttr(unittest.TestCase):
    """AC#5 — Tests for the _diff_attr() module-level helper."""

    def test_identical_values_returns_correct_tuple(self):
        """Both objects have the same attribute value."""

        class Obj:
            attr = "value"

        expected, actual = Obj(), Obj()
        result = _diff_attr(expected, actual, "attr")
        self.assertEqual(result, ("value", "value"))

    def test_different_values_returns_both(self):
        """Objects have different attribute values."""

        class Expected:
            attr = "a"

        class Actual:
            attr = "b"

        result = _diff_attr(Expected(), Actual(), "attr")
        self.assertEqual(result, ("a", "b"))

    def test_missing_attr_uses_default_none(self):
        """Attribute absent on both objects → default=None for both."""

        class Empty:
            pass

        result = _diff_attr(Empty(), Empty(), "missing")
        self.assertEqual(result, (None, None))

    def test_missing_attr_uses_custom_default(self):
        """Attribute absent on both objects → uses provided default=False."""

        class Empty:
            pass

        result = _diff_attr(Empty(), Empty(), "missing", False)
        self.assertEqual(result, (False, False))

    def test_default_none_vs_default_false(self):
        """Verify default=None and default=False produce different results."""

        class Empty:
            pass

        result_none = _diff_attr(Empty(), Empty(), "missing", None)
        result_false = _diff_attr(Empty(), Empty(), "missing", False)
        self.assertEqual(result_none, (None, None))
        self.assertEqual(result_false, (False, False))
        self.assertNotEqual(result_none, result_false)

    def test_same_default_for_both_objects(self):
        """Default applies equally to expected and actual."""

        class HasAttr:
            x = 42

        class NoAttr:
            pass

        result = _diff_attr(HasAttr(), NoAttr(), "x", 0)
        self.assertEqual(result, (42, 0))

    def test_bool_attribute_with_false_default(self):
        """Typical usage: bool attr like 'temporary' with default=False."""

        class WithTemp:
            temporary = True

        class WithoutTemp:
            pass

        result = _diff_attr(WithTemp(), WithoutTemp(), "temporary", False)
        self.assertEqual(result, (True, False))


if __name__ == "__main__":
    unittest.main()
