"""Extended coverage tests for IndexExtractor.

Targets the many uncovered branches in index_extractor.py:
- normalize_postgresql_index_predicate (replace_cast inner function)
- get_indexes() — vendor path and exception path
- get_all_indexes() — vendor bulk query path, grouping by table
- _get_indexes_from_vendor_queries()
- _parse_vendor_rows() — all branch variants
- _build_index_objects() — all kwarg branches
- _supports_sort_direction() — all index types
- OracleQuirks.is_index_hidden_column() (was _is_oracle_hidden_column)
- OracleQuirks.should_skip_index() (was _sanitize_index_name)
- _add_dialect_specific_properties() — all dialects
"""

from unittest.mock import MagicMock, call, patch

import pytest

from core.introspection.extractors.index_extractor import (
    IndexExtractor,
    normalize_postgresql_index_predicate,
)

pytestmark = [pytest.mark.unit]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_extractor(dialect="postgresql", vendor_queries=None):
    """Create a fully mocked IndexExtractor ready for unit testing."""
    provider = MagicMock()
    provider.query_executor = MagicMock()
    ext = IndexExtractor(
        provider=provider,
        dialect=dialect,
        vendor_queries=vendor_queries,
        connection=MagicMock(),
        metadata=MagicMock(),
    )
    ext.ensure_metadata = MagicMock()
    ext.log = MagicMock()
    return ext


def _make_vendor_queries(rows=None, bulk_rows=None):
    """Build a minimal vendor_queries mock."""
    vq = MagicMock()
    vq.get_indexes_query.return_value = ("SELECT 1", [])
    vq.get_all_indexes_query.return_value = ("SELECT ALL", ["schema_arg"])
    if rows is not None:
        pass  # caller will configure provider.query_executor
    if bulk_rows is not None:
        pass  # caller will configure provider.query_executor
    return vq


# ---------------------------------------------------------------------------
# normalize_postgresql_index_predicate — inner replace_cast function
# ---------------------------------------------------------------------------


class TestNormalizePostgresqlIndexPredicate:
    def test_returns_none_for_none(self):
        assert normalize_postgresql_index_predicate(None) is None

    def test_strips_cast_function_form(self):
        result = normalize_postgresql_index_predicate("CAST(col AS TEXT) = 'x'")
        assert result == "col = 'x'"

    def test_strips_double_colon_cast(self):
        result = normalize_postgresql_index_predicate("col::TEXT = 'x'")
        assert result == "col = 'x'"

    def test_strips_quoted_column_cast(self):
        result = normalize_postgresql_index_predicate("CAST(\"MyCol\" AS TEXT) = 'v'")
        assert result == "\"MyCol\" = 'v'"

    def test_strips_schema_qualified_cast(self):
        predicate = 'CAST("s"."t"."c" AS TEXT) = \'v\''
        result = normalize_postgresql_index_predicate(predicate)
        # Dot-spaces should be removed in schema-qualified names
        assert '"s"."t"."c"' in result

    def test_strips_both_cast_forms_in_equality(self):
        predicate = "CAST(a AS TEXT) = CAST('b' AS TEXT)"
        result = normalize_postgresql_index_predicate(predicate)
        assert result == "a = 'b'"

    def test_leaves_complex_expression_untouched(self):
        # lower() call inside CAST is not a simple operand
        predicate = "CAST(lower(col) AS TEXT) = 'x'"
        result = normalize_postgresql_index_predicate(predicate)
        # The outer CAST wrapping lower() should remain because lower() is complex
        assert "lower(col)" in result

    def test_passthrough_when_no_cast(self):
        predicate = "status = 'active'"
        assert normalize_postgresql_index_predicate(predicate) == predicate

    def test_strips_colon_cast_with_quoted_column(self):
        result = normalize_postgresql_index_predicate("\"col\"::TEXT = 'v'")
        assert '"col"' in result
        assert "::TEXT" not in result


# ---------------------------------------------------------------------------
# get_indexes — main entry point
# ---------------------------------------------------------------------------


class TestGetIndexes:
    def test_vendor_query_path_returns_indexes(self):
        vq = MagicMock()
        vq.get_indexes_query.return_value = ("SELECT 1", [])
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "index_name": "idx_a",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_unique": "N",
                "index_type": "btree",
                "is_descending": False,
            }
        ]

        result = ext.get_indexes("myschema", "mytable")

        assert len(result) == 1
        assert result[0].name == "idx_a"

    def test_without_vendor_queries_returns_empty_list(self):
        ext = _make_extractor(dialect="mysql", vendor_queries=None)

        result = ext.get_indexes("myschema", "mytable")

        assert result == []

    def test_exception_path_returns_empty_list(self):
        vq = MagicMock()
        vq.get_indexes_query.side_effect = RuntimeError("DB error")
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)

        result = ext.get_indexes("s", "t")

        assert result == []
        ext.log.warning.assert_called_once()

    def test_without_vendor_queries_and_metadata_none_returns_empty_list(self):
        ext = _make_extractor(dialect="postgresql", vendor_queries=None)
        ext.metadata = None

        assert ext.get_indexes("s", "t") == []


# ---------------------------------------------------------------------------
# get_all_indexes — bulk vendor query path
# ---------------------------------------------------------------------------


class TestGetAllIndexesBulkVendorPath:
    def test_bulk_vendor_query_groups_rows_by_table(self):
        vq = MagicMock()
        vq.get_all_indexes_query.return_value = ("SELECT ALL", [])
        ext = _make_extractor(dialect="sqlserver", vendor_queries=vq)

        ext.provider.query_executor.execute_query.return_value = [
            {
                "table_name": "orders",
                "index_name": "idx_orders_a",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_unique": "N",
                "index_type": "NONCLUSTERED",
                "is_descending": "N",
            },
            {
                "table_name": "users",
                "index_name": "idx_users_b",
                "column_name": "col2",
                "ordinal_position": 1,
                "is_unique": "Y",
                "index_type": "CLUSTERED",
                "is_descending": "N",
            },
        ]

        all_indexes = ext.get_all_indexes("dbo")

        names = {i.name for i in all_indexes}
        assert "idx_orders_a" in names
        assert "idx_users_b" in names
        assert len(all_indexes) == 2

    def test_bulk_vendor_query_skips_rows_without_table_name(self):
        vq = MagicMock()
        vq.get_all_indexes_query.return_value = ("SELECT ALL", [])
        ext = _make_extractor(dialect="sqlserver", vendor_queries=vq)

        ext.provider.query_executor.execute_query.return_value = [
            # Row without table_name should be silently skipped
            {
                "table_name": None,
                "index_name": "idx_ghost",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_unique": "N",
                "index_type": "NONCLUSTERED",
                "is_descending": "N",
            },
            {
                "table_name": "orders",
                "index_name": "idx_orders_a",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_unique": "N",
                "index_type": "NONCLUSTERED",
                "is_descending": "N",
            },
        ]

        all_indexes = ext.get_all_indexes("dbo")
        assert len(all_indexes) == 1
        assert all_indexes[0].name == "idx_orders_a"

    def test_bulk_vendor_query_returns_empty_list_when_no_rows(self):
        vq = MagicMock()
        vq.get_all_indexes_query.return_value = ("SELECT ALL", [])
        ext = _make_extractor(dialect="sqlserver", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = []

        assert ext.get_all_indexes("dbo") == []

    def test_bulk_vendor_query_none_returns_empty_list(self):
        """When get_all_indexes_query returns None, native introspection has no fallback."""
        vq = MagicMock()
        vq.get_all_indexes_query.return_value = None
        ext = _make_extractor(dialect="mysql", vendor_queries=vq)

        assert ext.get_all_indexes("myschema") == []

    def test_no_vendor_queries_returns_empty_list(self):
        ext = _make_extractor(dialect="mysql", vendor_queries=None)

        assert ext.get_all_indexes("myschema") == []

    def test_TABLE_NAME_uppercase_key_is_accepted(self):
        """Rows using uppercase TABLE_NAME key should be grouped correctly."""
        vq = MagicMock()
        vq.get_all_indexes_query.return_value = ("SELECT ALL", [])
        ext = _make_extractor(dialect="oracle", vendor_queries=vq)

        ext.provider.query_executor.execute_query.return_value = [
            {
                "TABLE_NAME": "EMP",
                "index_name": "IDX_EMP_ID",
                "column_name": "EMP_ID",
                "ordinal_position": 1,
                "is_unique": "N",
                "index_type": "NORMAL",
                "is_descending": "N",
            }
        ]

        all_indexes = ext.get_all_indexes("HR")
        assert len(all_indexes) == 1
        assert all_indexes[0].name == "IDX_EMP_ID"


# ---------------------------------------------------------------------------
# _parse_vendor_rows — comprehensive branch coverage
# ---------------------------------------------------------------------------


class TestParseVendorRows:
    def _make_oracle_extractor(self):
        return _make_extractor(dialect="oracle")

    def test_skips_rows_with_no_index_name(self):
        ext = _make_extractor()
        rows = [{"index_name": None, "column_name": "col1"}]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result == {}

    def test_is_unique_string_y(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "is_unique": "Y",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": "N",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["unique"] is True

    def test_is_unique_string_yes(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "is_unique": "YES",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": "N",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["unique"] is True

    def test_is_unique_bool_true(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "is_unique": True,
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": "N",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["unique"] is True

    def test_is_unique_false_by_default(self):
        ext = _make_extractor()
        rows = [
            {"index_name": "idx1", "column_name": "c1", "ordinal_position": 1, "is_descending": "N"}
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["unique"] is False

    def test_index_type_uppercased(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "index_type": "btree",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": "N",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["type"] == "BTREE"

    def test_index_type_defaults_to_btree_when_missing(self):
        ext = _make_extractor()
        rows = [
            {"index_name": "idx1", "column_name": "c1", "ordinal_position": 1, "is_descending": "N"}
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["type"] == "BTREE"

    def test_filter_condition_set(self):
        ext = _make_extractor(dialect="mysql")  # non-pg → no normalization
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": "N",
                "filter_condition": "status = 'active'",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["condition"] == "status = 'active'"

    def test_postgresql_filter_condition_normalized(self):
        ext = _make_extractor(dialect="postgresql")
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
                "filter_condition": "CAST(status AS TEXT) = 'active'",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["condition"] == "status = 'active'"

    def test_concurrent_string_true(self):
        ext = _make_extractor(dialect="postgresql")
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
                "is_concurrent": "YES",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["concurrently"] is True

    def test_concurrent_bool_true(self):
        ext = _make_extractor(dialect="postgresql")
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
                "is_concurrent": True,
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["concurrently"] is True

    def test_concurrent_false_by_default(self):
        ext = _make_extractor(dialect="postgresql")
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["concurrently"] is False

    def test_locality_local(self):
        ext = _make_extractor(dialect="oracle")
        rows = [
            {
                "index_name": "IDX1",
                "column_name": "C1",
                "ordinal_position": 1,
                "is_descending": "N",
                "is_unique": "N",
                "locality": "LOCAL",
            }
        ]
        result = ext._parse_vendor_rows("TBL", rows)
        assert result["IDX1"]["is_local"] is True

    def test_locality_global(self):
        ext = _make_extractor(dialect="oracle")
        rows = [
            {
                "index_name": "IDX1",
                "column_name": "C1",
                "ordinal_position": 1,
                "is_descending": "N",
                "is_unique": "N",
                "locality": "GLOBAL",
            }
        ]
        result = ext._parse_vendor_rows("TBL", rows)
        assert result["IDX1"]["is_local"] is False

    def test_locality_absent_is_none(self):
        ext = _make_extractor(dialect="oracle")
        rows = [
            {"index_name": "IDX1", "column_name": "C1", "ordinal_position": 1, "is_descending": "N"}
        ]
        result = ext._parse_vendor_rows("TBL", rows)
        assert result["IDX1"]["is_local"] is None

    def test_fillfactor_parsed_as_int(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
                "fillfactor": "80",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["fillfactor"] == 80

    def test_fillfactor_none_when_absent(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["fillfactor"] is None

    def test_compression_and_comment_stored(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
                "compression": "LZ4",
                "comment": "my note",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["compression"] == "LZ4"
        assert result["idx1"]["comment"] == "my note"

    def test_is_descending_bool_true(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": True,
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["columns"][0]["order"] == "DESC"

    def test_is_descending_string_y(self):
        ext = _make_extractor()
        rows = [
            {"index_name": "idx1", "column_name": "c1", "ordinal_position": 1, "is_descending": "Y"}
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["columns"][0]["order"] == "DESC"

    def test_is_descending_string_desc(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": "DESC",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["columns"][0]["order"] == "DESC"

    def test_is_descending_false_gives_asc(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["columns"][0]["order"] == "ASC"

    def test_include_columns_json_array_string(self):
        """SQL Server include_columns as JSON string."""
        ext = _make_extractor(dialect="sqlserver")
        ext.parse_json_array = MagicMock(return_value=["email", "phone"])
        rows = [
            {
                "index_name": "idx1",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_descending": "N",
                "include_columns": '["email","phone"]',
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["include_columns"] == ["email", "phone"]

    def test_include_columns_dict_entries(self):
        """include_columns rows as list of dicts (e.g. {name: col})."""
        ext = _make_extractor(dialect="sqlserver")
        ext.parse_json_array = MagicMock(return_value=[{"name": "email"}, {"name": "phone"}])
        rows = [
            {
                "index_name": "idx1",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_descending": "N",
                "include_columns": '[{"name":"email"},{"name":"phone"}]',
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["include_columns"] == ["email", "phone"]

    def test_include_columns_dict_no_name_key_uses_first_value(self):
        """Dict entry without 'name' key: use first value."""
        ext = _make_extractor(dialect="sqlserver")
        ext.parse_json_array = MagicMock(return_value=[{"col": "email"}])
        rows = [
            {
                "index_name": "idx1",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_descending": "N",
                "include_columns": '[{"col":"email"}]',
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["include_columns"] == ["email"]

    def test_include_columns_none_skipped(self):
        """None entries in include_columns list are skipped."""
        ext = _make_extractor(dialect="sqlserver")
        ext.parse_json_array = MagicMock(return_value=[None, "email"])
        rows = [
            {
                "index_name": "idx1",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_descending": "N",
                "include_columns": '[null, "email"]',
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["include_columns"] == ["email"]

    def test_is_included_column_flag_skips_column_from_main_list(self):
        ext = _make_extractor(dialect="sqlserver")
        rows = [
            {
                "index_name": "idx1",
                "column_name": "key_col",
                "ordinal_position": 1,
                "is_descending": "N",
                "is_included": "N",
            },
            {
                "index_name": "idx1",
                "column_name": "incl_col",
                "ordinal_position": 2,
                "is_descending": "N",
                "is_included": "Y",
            },
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        cols = [c["column"] for c in result["idx1"]["columns"]]
        assert "key_col" in cols
        assert "incl_col" not in cols

    def test_is_included_bool_true_skips_column(self):
        ext = _make_extractor(dialect="sqlserver")
        rows = [
            {
                "index_name": "idx1",
                "column_name": "incl_col",
                "ordinal_position": 1,
                "is_descending": "N",
                "is_included": True,
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["columns"] == []

    def test_index_expression_used_when_column_name_missing(self):
        ext = _make_extractor(dialect="mysql")
        rows = [
            {
                "index_name": "idx1",
                "column_name": None,
                "index_expression": "lower(email)",
                "ordinal_position": 1,
                "is_descending": False,
                "is_expression": True,
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["columns"][0]["column"] == "lower(email)"
        assert result["idx1"]["columns"][0]["is_expression"] is True

    def test_index_expression_stripped_of_whitespace(self):
        ext = _make_extractor(dialect="mysql")
        rows = [
            {
                "index_name": "idx1",
                "column_name": None,
                "index_expression": "  lower(email)  ",
                "ordinal_position": 1,
                "is_descending": False,
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["columns"][0]["column"] == "lower(email)"

    def test_oracle_hidden_column_replaced_by_expression(self):
        ext = _make_extractor(dialect="oracle")
        rows = [
            {
                "index_name": "IDX1",
                "column_name": "SYS_NC00001$",
                "index_expression": "UPPER(NAME)",
                "ordinal_position": 1,
                "is_descending": "N",
            }
        ]
        result = ext._parse_vendor_rows("TBL", rows)
        assert result["IDX1"]["columns"][0]["column"] == "UPPER(NAME)"

    def test_oracle_sys_index_name_filtered_out(self):
        ext = _make_extractor(dialect="oracle")
        rows = [
            {
                "index_name": "SYS_C00123",
                "column_name": "ID",
                "ordinal_position": 1,
                "is_descending": "N",
            }
        ]
        result = ext._parse_vendor_rows("TBL", rows)
        assert result == {}

    def test_multiple_rows_same_index_builds_multi_column(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "column_name": "c1",
                "ordinal_position": 1,
                "is_descending": False,
            },
            {
                "index_name": "idx1",
                "column_name": "c2",
                "ordinal_position": 2,
                "is_descending": True,
            },
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        cols = [c["column"] for c in sorted(result["idx1"]["columns"], key=lambda x: x["position"])]
        assert cols == ["c1", "c2"]

    def test_is_expression_string_yes(self):
        ext = _make_extractor()
        rows = [
            {
                "index_name": "idx1",
                "column_name": "col1",
                "ordinal_position": 1,
                "is_descending": False,
                "is_expression": "YES",
            }
        ]
        result = ext._parse_vendor_rows("tbl", rows)
        assert result["idx1"]["columns"][0]["is_expression"] is True

    def test_definition_stored(self):
        ext = _make_extractor(dialect="oracle")
        rows = [
            {
                "index_name": "IDX_DOMAIN",
                "column_name": "COL1",
                "ordinal_position": 1,
                "is_descending": "N",
                "is_unique": "N",
                "index_type": "DOMAIN",
                "DEFINITION": "CREATE INDEX IDX_DOMAIN ON T(COL1) INDEXTYPE IS CTXSYS.CONTEXT",
            }
        ]
        result = ext._parse_vendor_rows("T", rows)
        assert result["IDX_DOMAIN"]["definition"] is not None


# ---------------------------------------------------------------------------
# _build_index_objects — kwarg branches
# ---------------------------------------------------------------------------


class TestBuildIndexObjects:
    def _minimal_data(self, name="idx1", columns=None, **extra):
        data = {
            "name": name,
            "unique": False,
            "table": "tbl",
            "type": "BTREE",
            "condition": None,
            "concurrently": False,
            "tablespace": None,
            "is_local": None,
            "fillfactor": None,
            "compression": None,
            "comment": None,
            "definition": None,
            "columns": columns
            or [{"column": "c1", "position": 1, "order": "ASC", "is_expression": False}],
            "sort_directions": [],
        }
        data.update(extra)
        return {name: data}

    def test_basic_index_created(self):
        ext = _make_extractor()
        result = ext._build_index_objects("s", "tbl", self._minimal_data())
        assert len(result) == 1
        assert result[0].name == "idx1"

    def test_sort_direction_added_for_btree(self):
        ext = _make_extractor()
        data = self._minimal_data()
        data["idx1"]["columns"][0]["order"] = "DESC"
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].sort_directions == ["DESC"]

    def test_sort_direction_not_added_for_gin(self):
        ext = _make_extractor(dialect="postgresql")
        data = self._minimal_data()
        data["idx1"]["type"] = "GIN"
        data["idx1"]["columns"][0]["order"] = "DESC"
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].sort_directions == []

    def test_sort_direction_not_added_for_gist(self):
        ext = _make_extractor(dialect="postgresql")
        data = self._minimal_data()
        data["idx1"]["type"] = "GIST"
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].sort_directions == []

    def test_sort_direction_not_added_for_brin(self):
        ext = _make_extractor(dialect="postgresql")
        data = self._minimal_data()
        data["idx1"]["type"] = "BRIN"
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].sort_directions == []

    def test_sort_direction_not_added_for_hash(self):
        ext = _make_extractor(dialect="postgresql")
        data = self._minimal_data()
        data["idx1"]["type"] = "HASH"
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].sort_directions == []

    def test_sort_direction_not_added_for_spgist(self):
        ext = _make_extractor(dialect="postgresql")
        data = self._minimal_data()
        data["idx1"]["type"] = "SPGIST"
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].sort_directions == []

    def test_sort_direction_boolean_order_val(self):
        """When col['order'] is a bool True, should produce DESC."""
        ext = _make_extractor(dialect="mysql")
        data = self._minimal_data()
        data["idx1"]["columns"][0]["order"] = True
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].sort_directions == ["DESC"]

    def test_sort_direction_normalization_d_to_desc(self):
        """Catalog abbreviation 'D' should be normalized to 'DESC'."""
        ext = _make_extractor(dialect="mysql")
        data = self._minimal_data()
        data["idx1"]["columns"][0]["order"] = "D"
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].sort_directions == ["DESC"]

    def test_condition_added_to_kwargs(self):
        ext = _make_extractor()
        data = self._minimal_data(condition="status = 'active'")
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].condition == "status = 'active'"

    def test_include_columns_added_to_kwargs(self):
        ext = _make_extractor(dialect="sqlserver")
        data = self._minimal_data()
        data["idx1"]["include_columns"] = ["email", "phone"]
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].include_columns == ["email", "phone"]

    def test_fillfactor_added_to_kwargs(self):
        ext = _make_extractor(dialect="postgresql")
        data = self._minimal_data(fillfactor=90)
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].fillfactor == 90

    def test_compression_added_to_kwargs(self):
        ext = _make_extractor()
        data = self._minimal_data(compression="LZ4")
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].compression == "LZ4"

    def test_comment_added_to_kwargs(self):
        ext = _make_extractor()
        data = self._minimal_data(comment="my note")
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].comment == "my note"

    def test_definition_added_to_kwargs(self):
        ext = _make_extractor(dialect="oracle")
        ddl = "CREATE INDEX IDX ON T(C) INDEXTYPE IS CTXSYS.CONTEXT"
        data = self._minimal_data(definition=ddl)
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].definition == ddl

    def test_columns_sorted_by_position(self):
        ext = _make_extractor()
        data = self._minimal_data(
            columns=[
                {"column": "c2", "position": 2, "order": "ASC", "is_expression": False},
                {"column": "c1", "position": 1, "order": "ASC", "is_expression": False},
            ]
        )
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].columns == ["c1", "c2"]

    def test_expression_flags_included(self):
        ext = _make_extractor()
        data = self._minimal_data(
            columns=[
                {"column": "lower(email)", "position": 1, "order": "ASC", "is_expression": True}
            ]
        )
        result = ext._build_index_objects("s", "tbl", data)
        assert result[0].expression_flags == [True]

    def test_empty_indexes_data_returns_empty_list(self):
        ext = _make_extractor()
        result = ext._build_index_objects("s", "tbl", {})
        assert result == []


# ---------------------------------------------------------------------------
# _supports_sort_direction
# ---------------------------------------------------------------------------


class TestSupportsSortDirection:
    def test_btree_postgresql_returns_true(self):
        ext = _make_extractor(dialect="postgresql")
        assert ext._supports_sort_direction("BTREE") is True

    def test_gin_postgresql_returns_false(self):
        ext = _make_extractor(dialect="postgresql")
        assert ext._supports_sort_direction("GIN") is False

    def test_gist_postgresql_returns_false(self):
        ext = _make_extractor(dialect="postgresql")
        assert ext._supports_sort_direction("GIST") is False

    def test_brin_postgresql_returns_false(self):
        ext = _make_extractor(dialect="postgresql")
        assert ext._supports_sort_direction("BRIN") is False

    def test_hash_postgresql_returns_false(self):
        ext = _make_extractor(dialect="postgresql")
        assert ext._supports_sort_direction("HASH") is False

    def test_spgist_postgresql_returns_false(self):
        ext = _make_extractor(dialect="postgresql")
        assert ext._supports_sort_direction("SPGIST") is False

    def test_gin_mysql_returns_true(self):
        """Non-PostgreSQL dialects always support sort directions."""
        ext = _make_extractor(dialect="mysql")
        assert ext._supports_sort_direction("GIN") is True

    def test_no_dialect_returns_true(self):
        ext = _make_extractor(dialect="unknown")
        assert ext._supports_sort_direction("BTREE") is True

    def test_postgres_alias_dialect(self):
        """'postgres' alias should behave like 'postgresql'."""
        ext = _make_extractor(dialect="postgres")
        assert ext._supports_sort_direction("GIN") is False

    def test_function_based_returns_true_for_oracle(self):
        ext = _make_extractor(dialect="oracle")
        assert ext._supports_sort_direction("FUNCTION-BASED NORMAL") is True


# ---------------------------------------------------------------------------
# OracleQuirks.is_index_hidden_column (was _is_oracle_hidden_column)
# ---------------------------------------------------------------------------


class TestIsOracleHiddenColumn:
    @staticmethod
    def _quirks():
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.get_quirks("oracle")

    def test_empty_string_returns_false(self):
        assert self._quirks().is_index_hidden_column("") is False

    def test_sys_underscore_prefix_returns_true(self):
        assert self._quirks().is_index_hidden_column("SYS_NC00001$") is True

    def test_sys_dollar_prefix_returns_true(self):
        assert self._quirks().is_index_hidden_column("SYS$ROWID") is True

    def test_lowercase_sys_prefix_returns_true(self):
        assert self._quirks().is_index_hidden_column("sys_NC00001$") is True

    def test_normal_column_returns_false(self):
        assert self._quirks().is_index_hidden_column("EMPLOYEE_ID") is False

    def test_sys_without_underscore_returns_false(self):
        """SYS alone is not a hidden column name."""
        assert self._quirks().is_index_hidden_column("SYSDATE") is False


# ---------------------------------------------------------------------------
# OracleQuirks.should_skip_index (was _sanitize_index_name)
# ---------------------------------------------------------------------------


class TestSanitizeIndexName:
    @staticmethod
    def _quirks(dialect: str):
        from db.provider_registry import ProviderRegistry

        return ProviderRegistry.get_quirks(dialect)

    def test_empty_string_returns_false(self):
        assert self._quirks("oracle").should_skip_index("") is False

    def test_sys_underscore_returns_true(self):
        assert self._quirks("oracle").should_skip_index("SYS_C00123") is True

    def test_sys_dollar_returns_true(self):
        assert self._quirks("oracle").should_skip_index("SYS$XYZ") is True

    def test_normal_name_preserved(self):
        assert self._quirks("oracle").should_skip_index("IDX_ORDERS") is False

    def test_lowercase_sys_returns_true(self):
        assert self._quirks("oracle").should_skip_index("sys_c00001") is True

    def test_non_oracle_dialect_never_skips(self):
        """Non-Oracle dialects don't filter SYS_ names."""
        assert self._quirks("mysql").should_skip_index("SYS_C00123") is False

    def test_whitespace_stripped_before_check(self):
        assert self._quirks("oracle").should_skip_index("  SYS_C00123  ") is True


# ---------------------------------------------------------------------------
# _add_dialect_specific_properties
# ---------------------------------------------------------------------------


class TestAddDialectSpecificProperties:
    def test_postgresql_concurrently_set_when_true(self):
        ext = _make_extractor(dialect="postgresql")
        idx_data = {"concurrently": True, "type": "BTREE", "tablespace": None}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs.get("concurrently") is True

    def test_postgresql_concurrently_not_set_when_false(self):
        ext = _make_extractor(dialect="postgresql")
        idx_data = {"concurrently": False, "type": "BTREE", "tablespace": None}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert "concurrently" not in kwargs

    def test_postgresql_tablespace_set(self):
        ext = _make_extractor(dialect="postgresql")
        idx_data = {"concurrently": False, "type": "BTREE", "tablespace": "pg_default"}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs.get("tablespace") == "pg_default"

    def test_mysql_fulltext_type_preserved(self):
        ext = _make_extractor(dialect="mysql")
        idx_data = {"type": "FULLTEXT"}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs.get("type") == "FULLTEXT"

    def test_mysql_spatial_type_preserved(self):
        ext = _make_extractor(dialect="mysql")
        idx_data = {"type": "SPATIAL"}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs.get("type") == "SPATIAL"

    def test_mysql_btree_not_overwritten(self):
        """Regular BTREE type for MySQL: no special override."""
        ext = _make_extractor(dialect="mysql")
        idx_data = {"type": "BTREE"}
        kwargs = {"type": "BTREE"}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        # BTREE is not FULLTEXT/SPATIAL so no change from this method
        assert kwargs.get("type") == "BTREE"

    def test_oracle_bitmap_type_set(self):
        ext = _make_extractor(dialect="oracle")
        idx_data = {"type": "BITMAP", "tablespace": None, "is_local": None}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs.get("type") == "BITMAP"

    def test_oracle_tablespace_set(self):
        ext = _make_extractor(dialect="oracle")
        idx_data = {"type": "NORMAL", "tablespace": "USERS", "is_local": None}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs.get("tablespace") == "USERS"

    def test_oracle_is_local_true(self):
        ext = _make_extractor(dialect="oracle")
        idx_data = {"type": None, "tablespace": None, "is_local": True}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs.get("is_local") is True

    def test_oracle_is_local_false(self):
        ext = _make_extractor(dialect="oracle")
        idx_data = {"type": None, "tablespace": None, "is_local": False}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs.get("is_local") is False

    def test_oracle_is_local_none_not_set(self):
        ext = _make_extractor(dialect="oracle")
        idx_data = {"type": None, "tablespace": None, "is_local": None}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert "is_local" not in kwargs

    def test_non_special_dialect_noop(self):
        ext = _make_extractor(dialect="db2")
        idx_data = {"concurrently": True, "type": "FULLTEXT", "tablespace": "ts1", "is_local": True}
        kwargs = {}
        ext._add_dialect_specific_properties(idx_data, kwargs)
        assert kwargs == {}


# ---------------------------------------------------------------------------
# _get_indexes_from_vendor_queries
# ---------------------------------------------------------------------------


class TestGetIndexesFromVendorQueries:
    def test_calls_vendor_query_and_parses_rows(self):
        vq = MagicMock()
        vq.get_indexes_query.return_value = ("SELECT 1", ["arg"])
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = [
            {
                "index_name": "idx_pg",
                "column_name": "status",
                "ordinal_position": 1,
                "is_unique": False,
                "index_type": "btree",
                "is_descending": False,
            }
        ]

        result = ext._get_indexes_from_vendor_queries("myschema", "orders")

        vq.get_indexes_query.assert_called_once_with("myschema", "orders")
        ext.provider.query_executor.execute_query.assert_called_once_with(
            ext.connection, "SELECT 1", ["arg"]
        )
        assert "idx_pg" in result

    def test_empty_rows_returns_empty_dict(self):
        vq = MagicMock()
        vq.get_indexes_query.return_value = ("SELECT 1", [])
        ext = _make_extractor(dialect="postgresql", vendor_queries=vq)
        ext.provider.query_executor.execute_query.return_value = []

        result = ext._get_indexes_from_vendor_queries("s", "t")

        assert result == {}
