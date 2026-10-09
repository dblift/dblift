"""Contracts for first-party provider descriptors."""

import importlib
import tomllib
from pathlib import Path

import pytest

from tests.unit.lightweight_core._support import run_python

ROOT = Path(__file__).resolve().parents[3]


def _entry_points():
    project = tomllib.loads((ROOT / "pyproject.toml").read_text())
    return project["project"]["entry-points"]


def test_descriptor_surface_and_entry_points_cover_legacy_plugins():
    from dblift.extensions.providers import PluginDescriptor

    points = _entry_points()
    legacy = points["dblift.providers"]
    descriptors = points["dblift.provider_descriptors"]
    assert set(descriptors) == set(legacy)
    for name, reference in descriptors.items():
        module_name, attribute = reference.split(":")
        descriptor = getattr(importlib.import_module(module_name), attribute)
        assert isinstance(descriptor, PluginDescriptor)
        assert descriptor.name == name
        assert descriptor.dialects
        assert descriptor.factory == legacy[name]
        with pytest.raises(AttributeError):
            descriptor.name = "changed"


@pytest.mark.parametrize("name", _entry_points()["dblift.providers"])
def test_loading_descriptor_does_not_load_provider_or_optional_sdk(name):
    reference = _entry_points()["dblift.provider_descriptors"][name]
    run = run_python(
        f"""
import importlib
import sys
module_name, attribute = {reference!r}.split(':')
descriptor = getattr(importlib.import_module(module_name), attribute)
assert descriptor.dialects
assert not any(name.startswith('dblift.db.plugins.') and name.endswith('.provider') for name in sys.modules)
""",
        blocked=("rich", "jinja2", "sqlglot", "psycopg", "pymongo", "snowflake"),
    )
    assert run.returncode == 0, run.stderr


def test_descriptor_aliases_match_legacy_and_package_metadata():
    points = _entry_points()
    for name, reference in points["dblift.provider_descriptors"].items():
        module_name, attribute = reference.split(":")
        descriptor = getattr(importlib.import_module(module_name), attribute)
        package_name = module_name.rsplit(".", 1)[0]
        package = importlib.import_module(package_name)
        legacy_module, legacy_attribute = points["dblift.providers"][name].split(":")
        plugin = getattr(importlib.import_module(legacy_module), legacy_attribute)
        assert descriptor.name == plugin.name == package.__plugin_name__
        assert descriptor.dialects == tuple(plugin.dialects) == tuple(package.__plugin_dialects__)


def test_legacy_provider_class_import_remains_canonical():
    from dblift.db.plugins.sqlite import SQLiteProvider
    from dblift.db.plugins.sqlite.provider import SQLiteProvider as ConcreteSQLiteProvider

    assert SQLiteProvider is ConcreteSQLiteProvider


def test_cockroach_package_import_registers_sqlalchemy_dialect():
    run = run_python("""
import dblift.db.plugins.cockroachdb
from sqlalchemy.dialects import registry
assert registry.load("cockroachdb.psycopg").name == "cockroachdb"
""")
    assert run.returncode == 0, run.stderr
