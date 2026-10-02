"""CockroachDB type normalization follows the engine's default integer widths."""

import pytest

from dblift.core.normalization.type_normalizer import DataTypeNormalizer


@pytest.mark.unit
@pytest.mark.parametrize(
    "data_type,expected",
    [
        ("INT", "BIGINT"),
        ("INTEGER", "BIGINT"),
        ("INT8", "BIGINT"),
        ("INT4", "INTEGER"),
        ("INT2", "SMALLINT"),
    ],
)
def test_normalize_cockroachdb_integer_widths(data_type, expected):
    assert DataTypeNormalizer().normalize(data_type, "cockroachdb") == expected


@pytest.mark.unit
@pytest.mark.parametrize("data_type,expected", [("INT", True), ("INT4", False)])
def test_cockroachdb_bigint_equivalence_respects_integer_width(data_type, expected):
    assert (
        DataTypeNormalizer().are_equivalent(data_type, "BIGINT", "cockroachdb", "cockroachdb")
        is expected
    )


@pytest.mark.unit
@pytest.mark.parametrize(
    "data_type", ["SERIAL", "SERIAL2", "SERIAL4", "SERIAL8", "SMALLSERIAL", "BIGSERIAL"]
)
def test_normalize_cockroachdb_serial_uses_rowid_width(data_type):
    assert DataTypeNormalizer().normalize(data_type, "cockroachdb") == "BIGINT"


@pytest.mark.unit
@pytest.mark.parametrize("data_type", ["INT", "INTEGER", "SERIAL"])
def test_normalize_postgresql_keeps_32_bit_integer_defaults(data_type):
    assert DataTypeNormalizer().normalize(data_type, "postgresql") == "INTEGER"
