"""Story 23-11: Tests for is_migration_success/is_migration_failure utilities (SMELL-10)."""

import pytest

from core.migration.version_utils import is_migration_failure, is_migration_success

pytestmark = [pytest.mark.unit]


# --- is_migration_success ---


def test_bool_true_is_success():
    assert is_migration_success(True) is True


def test_int_one_is_success():
    assert is_migration_success(1) is True


def test_string_true_is_success():
    assert is_migration_success("true") is True
    assert is_migration_success("True") is True
    assert is_migration_success("1") is True


def test_bool_false_not_success():
    assert is_migration_success(False) is False


def test_int_zero_not_success():
    assert is_migration_success(0) is False


def test_none_not_success():
    assert is_migration_success(None) is False


def test_string_false_not_success():
    assert is_migration_success("False") is False
    assert is_migration_success("false") is False


# --- is_migration_failure ---


def test_bool_false_is_failure():
    assert is_migration_failure(False) is True


def test_int_zero_is_failure():
    assert is_migration_failure(0) is True


def test_string_false_is_failure():
    assert is_migration_failure("False") is True
    assert is_migration_failure("false") is True


def test_bool_true_not_failure():
    assert is_migration_failure(True) is False


def test_int_one_not_failure():
    assert is_migration_failure(1) is False


def test_none_not_failure():
    assert is_migration_failure(None) is False


# --- Structural: consumers use the helpers ---


def test_migration_state_manager_uses_is_migration_failure():
    import inspect

    import core.migration.state.migration_state_manager as mod

    src = inspect.getsource(mod)
    assert "is_migration_failure" in src


