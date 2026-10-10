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


@pytest.mark.parametrize(
    ("plugin", "class_name"),
    [
        ("cockroachdb", "CockroachdbProvider"),
        ("cosmosdb", "CosmosDbProvider"),
        ("db2", "Db2Provider"),
        ("duckdb", "DuckDBProvider"),
        ("mariadb", "MariadbProvider"),
        ("mongodb", "MongoDbProvider"),
        ("mysql", "MySqlProvider"),
        ("oracle", "OracleProvider"),
        ("postgresql", "PostgreSqlProvider"),
        ("redshift", "RedshiftProvider"),
        ("snowflake", "SnowflakeProvider"),
        ("sqlite", "SQLiteProvider"),
        ("sqlserver", "SqlServerProvider"),
    ],
)
def test_legacy_provider_package_export_is_lazy_and_canonical(plugin, class_name):
    package = importlib.import_module(f"dblift.db.plugins.{plugin}")
    concrete = importlib.import_module(f"dblift.db.plugins.{plugin}.provider")
    package.__dict__.pop(class_name, None)
    assert class_name in dir(package)
    assert getattr(package, class_name) is getattr(concrete, class_name)
    assert getattr(package, class_name) is getattr(concrete, class_name)
    with pytest.raises(AttributeError, match="missing_provider"):
        getattr(package, "missing_provider")


def test_cockroach_package_import_registers_sqlalchemy_dialect():
    run = run_python("""
import dblift.db.plugins.cockroachdb
from sqlalchemy.dialects import registry
assert registry.load("cockroachdb.psycopg").name == "cockroachdb"
""")
    assert run.returncode == 0, run.stderr
