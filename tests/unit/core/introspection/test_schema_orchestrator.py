"""Unit tests for :mod:`core.introspection._schema_orchestrator`.

``introspect_schema`` is a plain module function taking a structural-typing
``si`` (SchemaIntrospector-like) argument, so it can be exercised directly
against a ``MagicMock`` configured with the methods/attributes it relies on.
"""

from unittest.mock import MagicMock

import pytest

from core.introspection._schema_orchestrator import introspect_schema
from core.sql_model._base_sql_column import SqlColumn
from core.sql_model.base import ConstraintType, SqlConstraint
from core.sql_model.table import Table


def _make_table(name, columns=None, constraints=None):
    return Table(
        name=name,
        columns=columns or [],
        constraints=constraints or [],
    )


def _make_si(**overrides):
    si = MagicMock()
    si.log = MagicMock()

    si.get_tables.return_value = [_make_table("t1", columns=[SqlColumn("id", "INTEGER")])]
    si.get_views.return_value = []
    si.get_materialized_views.return_value = []
    si.get_sequences.return_value = []
    si.get_triggers.return_value = []
    si.get_events.return_value = []
    si.get_procedures.return_value = []
    si.get_functions.return_value = []
    si.get_packages.return_value = []
    si.get_synonyms.return_value = []
    si.get_user_defined_types.return_value = []
    si.get_extensions.return_value = []
    si.get_indexes.return_value = []
    si.get_table_partitions.return_value = []
    si.get_check_constraints.return_value = []

    vendor_queries = MagicMock()
    vendor_queries.supports_computed_columns.return_value = False
    vendor_queries.supports_check_constraints.return_value = False
    vendor_queries.supports_materialized_views.return_value = False
    vendor_queries.supports_partitions.return_value = False
    si.vendor_queries = vendor_queries

    for key, value in overrides.items():
        setattr(si, key, value)

    return si


class TestIntrospectSchemaHappyPath:
    def test_full_introspection_with_all_features(self):
        si = _make_si()
        si.get_tables.return_value = [_make_table("t1", columns=[SqlColumn("id", "INTEGER")])]
        si.get_views.return_value = ["view1"]
        si.get_materialized_views.return_value = ["mv1"]
        si.get_sequences.return_value = ["seq1"]
        si.get_triggers.return_value = ["trig1"]
        si.get_events.return_value = ["evt1"]
        si.get_procedures.return_value = ["proc1"]
        si.get_functions.return_value = ["fn1"]
        si.get_packages.return_value = ["pkg1"]
        si.get_synonyms.return_value = ["syn1"]
        si.get_user_defined_types.return_value = ["udt1"]
        si.get_extensions.return_value = ["ext1"]
        si.get_indexes.return_value = ["idx1"]
        si.get_table_partitions.return_value = ["part1"]

        si.vendor_queries.supports_computed_columns.return_value = True
        si.vendor_queries.supports_check_constraints.return_value = True
        si.vendor_queries.supports_materialized_views.return_value = True
        si.vendor_queries.supports_partitions.return_value = True

        result = introspect_schema(si, "public")

        assert result["schema"] == "public"
        assert result["table_count"] == 1
        assert result["total_columns"] == 1
        assert result["view_count"] == 1
        assert result["materialized_view_count"] == 1
        assert result["sequence_count"] == 1
        assert result["trigger_count"] == 1
        assert result["event_count"] == 1
        assert result["procedure_count"] == 1
        assert result["function_count"] == 1
        assert result["package_count"] == 1
        assert result["synonym_count"] == 1
        assert result["user_defined_type_count"] == 1
        assert result["extension_count"] == 1
        assert result["total_indexes"] == 1
        assert result["total_partitions"] == 1
        assert result["indexes"]["t1"] == ["idx1"]
        assert result["partitions"]["t1"] == ["part1"]

        si.enrich_columns_with_computed.assert_called_once()
        si.enrich_columns_with_identity.assert_called_once()
        si.enrich_table_with_partition_scheme.assert_called_once()
        si.log.info.assert_called_once()
        si.log.debug.assert_called()

    def test_export_partitions_set_on_table_when_attribute_present(self):
        si = _make_si()
        table = _make_table("t1")
        si.get_tables.return_value = [table]
        si.vendor_queries.supports_partitions.return_value = True
        si.get_table_partitions.return_value = ["part1"]

        result = introspect_schema(si, "public")

        assert table.export_partitions == ["part1"]
        assert result["partitions"]["t1"] == ["part1"]
        assert result["total_partitions"] == 1


class TestIntrospectSchemaNoVendorQueries:
    def test_no_vendor_queries_skips_optional_enrichment(self):
        si = _make_si(vendor_queries=None)

        result = introspect_schema(si, "public")

        si.enrich_columns_with_computed.assert_not_called()
        si.enrich_columns_with_identity.assert_not_called()
        si.enrich_table_with_partition_scheme.assert_not_called()
        si.get_table_partitions.assert_not_called()
        assert result["materialized_view_count"] == 0
        assert result["packages"] == []
        assert result["package_count"] == 0


class TestIntrospectSchemaIncludeFlags:
    def test_all_optional_sections_disabled(self):
        si = _make_si()

        result = introspect_schema(
            si,
            "public",
            include_views=False,
            include_sequences=False,
            include_triggers=False,
            include_procedures=False,
            include_functions=False,
        )

        si.get_views.assert_not_called()
        si.get_sequences.assert_not_called()
        si.get_triggers.assert_not_called()
        si.get_procedures.assert_not_called()
        si.get_functions.assert_not_called()
        assert result["views"] == []
        assert result["sequences"] == []
        assert result["triggers"] == []
        assert result["procedures"] == []
        assert result["functions"] == []


class TestCheckConstraintDeduplication:
    def test_skips_duplicate_check_constraint_by_name(self):
        existing = SqlConstraint(
            constraint_type=ConstraintType.CHECK,
            name="CHK_AGE",
            check_expression="age > 0",
        )
        table = _make_table("t1", constraints=[existing])
        si = _make_si()
        si.get_tables.return_value = [table]
        si.vendor_queries.supports_check_constraints.return_value = True

        duplicate = SqlConstraint(
            constraint_type=ConstraintType.CHECK,
            name="chk_age",
            check_expression="age > 0",
        )
        si.get_check_constraints.return_value = [duplicate]

        introspect_schema(si, "public")

        assert table.constraints == [existing]
        debug_calls = [str(c) for c in si.log.debug.call_args_list]
        assert any("Skipping duplicate check constraint" in c for c in debug_calls)

    def test_adds_new_check_constraint_when_not_duplicate(self):
        existing = SqlConstraint(
            constraint_type=ConstraintType.CHECK,
            name="CHK_AGE",
            check_expression="age > 0",
        )
        table = _make_table("t1", constraints=[existing])
        si = _make_si()
        si.get_tables.return_value = [table]
        si.vendor_queries.supports_check_constraints.return_value = True

        new_constraint = SqlConstraint(
            constraint_type=ConstraintType.CHECK,
            name="CHK_NAME",
            check_expression="name IS NOT NULL",
        )
        si.get_check_constraints.return_value = [new_constraint]

        introspect_schema(si, "public")

        assert table.constraints == [existing, new_constraint]

    def test_no_check_constraints_returned(self):
        table = _make_table("t1")
        si = _make_si()
        si.get_tables.return_value = [table]
        si.vendor_queries.supports_check_constraints.return_value = True
        si.get_check_constraints.return_value = []

        introspect_schema(si, "public")

        assert table.constraints == []


class TestEventsErrorHandling:
    def test_get_events_exception_results_in_empty_events(self):
        si = _make_si()
        si.get_events.side_effect = RuntimeError("events not supported")

        result = introspect_schema(si, "public")

        assert result["events"] == []
        assert result["event_count"] == 0
        debug_calls = [str(c) for c in si.log.debug.call_args_list]
        assert any("Failed to fetch events" in c for c in debug_calls)


class TestPackagesErrorHandling:
    def test_get_packages_exception_results_in_empty_packages(self):
        si = _make_si()
        si.get_packages.side_effect = RuntimeError("packages not supported")

        result = introspect_schema(si, "public")

        assert result["packages"] == []
        assert result["package_count"] == 0
        debug_calls = [str(c) for c in si.log.debug.call_args_list]
        assert any("Could not fetch packages" in c for c in debug_calls)


class TestIntrospectSchemaErrorPropagation:
    def test_exception_during_introspection_is_logged_and_reraised(self):
        si = _make_si()
        si.get_tables.side_effect = RuntimeError("boom")

        with pytest.raises(RuntimeError, match="boom"):
            introspect_schema(si, "public")

        si.log.error.assert_called_once()
