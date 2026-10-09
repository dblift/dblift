"""Built-in providers leave catalog enrichment to its consumer."""

import importlib.util

import pytest

from dblift.db.base_quirks import BaseQuirks
from dblift.db.plugins.db2.quirks import Db2Quirks
from dblift.db.plugins.mysql.quirks import MysqlQuirks
from dblift.db.plugins.oracle.quirks import OracleQuirks
from dblift.db.plugins.postgresql.quirks import PostgresqlQuirks
from dblift.db.plugins.sqlserver.quirks import SqlserverQuirks

CATALOG_HOOKS = (
    "normalize_view_name",
    "enrich_view_from_row",
    "enrich_materialized_view_from_row",
    "enrich_table_extra",
    "supplement_table_list",
    "is_temporary_sequence",
    "is_generated_not_null_check",
    "is_internal_sequence",
    "identity_owned_sequence_names",
    "should_skip_index",
    "normalize_index_predicate",
    "is_index_hidden_column",
    "apply_index_vendor_properties",
    "fetch_unique_constraints",
    "sanitize_constraint_name",
    "correct_computed_column_flag",
    "enhance_columns",
    "clean_source_text",
    "normalize_partition_bound",
    "extract_partition_scheme_from_row",
    "fetch_view_algorithm",
    "extract_computed_column_expression",
    "enrich_packages_from_catalog",
    "filter_user_defined_types",
    "fetch_routine_parameters_fallback",
    "fetch_routine_full_definition",
    "apply_routine_volatility_from_row",
    "apply_routine_definer_from_row",
    "postprocess_routine",
    "enrich_trigger_from_row",
    "apply_vendor_table_properties",
    "index_no_sort_types",
    "time_type_supports_only_fractional_precision",
    "varchar_max_sentinel_sizes",
    "identity_uses_catalog_fallback",
    "provides_view_algorithm",
    "introspector_class",
    "vendor_queries_class",
)


@pytest.mark.parametrize(
    "quirks_class",
    (BaseQuirks, Db2Quirks, MysqlQuirks, OracleQuirks, PostgresqlQuirks, SqlserverQuirks),
)
def test_builtin_quirks_have_no_catalog_hooks(quirks_class):
    assert not set(CATALOG_HOOKS).intersection(quirks_class.__dict__)
    assert all(not hasattr(quirks_class, name) for name in CATALOG_HOOKS)


def test_oracle_catalog_helper_package_is_absent():
    assert importlib.util.find_spec("dblift.db.plugins.oracle.introspection") is None
