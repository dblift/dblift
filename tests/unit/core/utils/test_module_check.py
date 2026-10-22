"""``module_available`` answers without importing the module or raising."""

import sys
import types

import pytest

from dblift.core.utils.module_check import module_available

pytestmark = [pytest.mark.unit]


def test_installed_module_is_available():
    assert module_available("json") is True


def test_missing_module_is_not_available():
    assert module_available("dblift_no_such_module_installed") is False


def test_missing_submodule_of_a_missing_package_is_not_available():
    # find_spec imports the parent package, which raises ModuleNotFoundError (an ImportError).
    assert module_available("dblift_no_such_package.sub") is False


def test_module_stub_without_a_spec_is_not_available(monkeypatch):
    # find_spec raises ValueError for a sys.modules entry whose __spec__ is None.
    stub = types.ModuleType("dblift_stubbed_module")
    stub.__spec__ = None
    monkeypatch.setitem(sys.modules, "dblift_stubbed_module", stub)
    assert module_available("dblift_stubbed_module") is False


def test_checking_does_not_import_the_module(monkeypatch):
    monkeypatch.delitem(sys.modules, "colorsys", raising=False)
    assert module_available("colorsys") is True
    assert "colorsys" not in sys.modules
