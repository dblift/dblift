from unittest.mock import patch

from dblift.core.introspection import vendor_queries_factory as factory_module
from dblift.core.introspection.vendor_queries_factory import (
    VendorQueriesFactory,
    register_vendor_queries,
)


class _Queries:
    pass


def test_create_runs_registered_introspection_seam():
    original_registry = dict(factory_module._VENDOR_QUERIES_REGISTRY)
    original_defaults = factory_module._DEFAULTS_REGISTERED
    factory_module._VENDOR_QUERIES_REGISTRY.clear()
    factory_module._DEFAULTS_REGISTERED = True

    def attach():
        register_vendor_queries("seamdb", _Queries)  # type: ignore[arg-type]

    try:
        with patch(
            "dblift.core.seams.introspection.attach_registered_introspection", side_effect=attach
        ):
            queries = VendorQueriesFactory.create("seamdb")
    finally:
        factory_module._VENDOR_QUERIES_REGISTRY.clear()
        factory_module._VENDOR_QUERIES_REGISTRY.update(original_registry)
        factory_module._DEFAULTS_REGISTERED = original_defaults

    assert isinstance(queries, _Queries)
