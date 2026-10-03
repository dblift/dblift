"""The OSS package does not ship a schema-discovery engine."""

import importlib.util


def test_internal_schema_discovery_modules_are_absent() -> None:
    assert importlib.util.find_spec("dblift.core.introspection") is None
    assert importlib.util.find_spec("dblift.core.seams.introspection") is None
    assert importlib.util.find_spec("dblift.db.plugins.nosql_base.introspection") is None


def test_public_client_and_version_leaf_remain_importable() -> None:
    from dblift.api import DBLiftClient
    from dblift.db.version import DatabaseVersion, parse_version

    assert callable(DBLiftClient)
    parsed = parse_version("16.2")
    assert isinstance(parsed, DatabaseVersion)
    assert (parsed.major, parsed.minor) == (16, 2)
