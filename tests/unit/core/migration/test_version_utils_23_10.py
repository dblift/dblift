"""Story 23-10: Tests for shared compare_versions utility (DEDUP-31)."""

import pytest

from core.migration.version_utils import compare_versions

pytestmark = [pytest.mark.unit]


# --- Shared utility behaviour ---


def test_none_both_equal():
    assert compare_versions(None, None) == 0


def test_none_version1_less_than_non_none():
    assert compare_versions(None, "1.0") == -1


def test_non_none_greater_than_none():
    assert compare_versions("1.0", None) == 1


def test_equal_numeric_versions():
    assert compare_versions("1.2.3", "1.2.3") == 0


def test_numeric_less_than():
    assert compare_versions("1.2.3", "1.2.4") == -1


def test_numeric_greater_than():
    assert compare_versions("1.10.0", "1.9.0") == 1  # 10 > 9 numerically


def test_underscore_separator():
    assert compare_versions("1_2_3", "1_2_4") == -1


def test_underscore_equals_dot():
    assert compare_versions("1_2_3", "1.2.3") == 0


def test_letter_based_version_less():
    assert compare_versions("VA", "VB") == -1


def test_letter_based_version_greater():
    assert compare_versions("VB", "VA") == 1


def test_letter_based_version_equal():
    assert compare_versions("VA", "VA") == 0


def test_alphanumeric_numeric_prefix_sorts_before_larger_numeric_versions():
    assert compare_versions("8b", "9") == -1
    assert compare_versions("8b", "12") == -1
    assert compare_versions("8b", "17") == -1


def test_alphanumeric_suffix_sorts_after_same_numeric_prefix():
    assert compare_versions("8", "8a") == -1
    assert compare_versions("8a", "8b") == -1
    assert compare_versions("8b", "8") == 1


def test_alpha_only_versions_still_sort_after_numeric_versions():
    assert compare_versions("A", "10") == 1
    assert compare_versions("10", "A") == -1


def test_empty_strings_equal():
    assert compare_versions("", "") == 0


# --- Structural: remaining consumer delegates and no longer defines the method body ---


def test_migration_script_manager_no_inline_body():
    import inspect

    from core.migration.scripting.migration_script_manager import MigrationScriptManager

    src = inspect.getsource(MigrationScriptManager.compare_versions)
    assert "_compare_versions_shared" in src
