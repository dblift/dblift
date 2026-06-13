"""PostgreSQL index extraction helpers."""

from unittest.mock import MagicMock

import pytest

from core.introspection.extractors.index_extractor import (
    IndexExtractor,
    normalize_postgresql_index_predicate,
)
from db.plugins.postgresql.generator.ddl_generator import PostgreSQLSqlGenerator

pytestmark = [pytest.mark.unit]


@pytest.mark.parametrize(
    ("predicate", "expected"),
    [
        ("CAST(status AS TEXT) = CAST('pending' AS TEXT)", "status = 'pending'"),
        ("CAST(\"status\" AS TEXT) = CAST('pending' AS TEXT)", "\"status\" = 'pending'"),
        (
            'CAST("dblift_test"."orders"."status" AS TEXT) = CAST(\'pending\' AS TEXT)',
            '"dblift_test"."orders"."status" = \'pending\'',
        ),
        ("status::text = 'pending'::text", "status = 'pending'"),
    ],
)
def test_normalize_postgresql_index_predicate_strips_simple_text_casts(predicate, expected):
    assert normalize_postgresql_index_predicate(predicate) == expected


def test_normalize_postgresql_index_predicate_leaves_complex_casts_alone():
    predicate = "CAST(lower(status) AS TEXT) = CAST('pending' AS TEXT)"

    assert (
        normalize_postgresql_index_predicate(predicate) == "CAST(lower(status) AS TEXT) = 'pending'"
    )


def test_normalize_postgresql_index_predicate_handles_none():
    assert normalize_postgresql_index_predicate(None) is None


def test_postgresql_vendor_rows_store_normalized_partial_index_predicate():
    extractor = IndexExtractor(provider=MagicMock(), dialect="postgresql")
    rows = [
        {
            "index_name": "idx_orders_partial",
            "column_name": "status",
            "ordinal_position": 1,
            "is_unique": False,
            "index_type": "btree",
            "filter_condition": "CAST(status AS TEXT) = CAST('pending' AS TEXT)",
            "is_descending": False,
        }
    ]

    indexes_data = extractor._parse_vendor_rows("orders", rows)
    indexes = extractor._build_index_objects("dblift_test", "orders", indexes_data)

    assert indexes[0].condition == "status = 'pending'"

    statement = PostgreSQLSqlGenerator()._generate_index_create_statement(indexes[0])
    assert "WHERE status = 'pending'" in statement
