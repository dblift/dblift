"""PostgreSQL index extraction helpers."""

from unittest.mock import MagicMock

import pytest

from dblift.core.introspection.extractors.index_extractor import (
    IndexExtractor,
    normalize_postgresql_index_predicate,
)

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
