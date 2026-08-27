"""Tests for PostgreSQL dialect quirks."""

from unittest.mock import MagicMock

import pytest

from core.sql_model.table import Table
from core.sql_model.user_defined_type import UserDefinedType
from db.plugins.postgresql.quirks import PostgresqlQuirks


@pytest.mark.unit
def test_filter_user_defined_types_excludes_relation_row_types():
    query_executor = MagicMock()
    query_executor.execute_query.return_value = [{"relname": "mv_parent_probe"}]
    extractor = MagicMock()
    extractor.provider.query_executor = query_executor
    extractor.connection = object()

    relation_type = UserDefinedType(
        name="mv_parent_probe",
        type_category="C",
        dialect="postgresql",
    )
    explicit_type = UserDefinedType(
        name="address_type",
        type_category="C",
        dialect="postgresql",
    )

    result = PostgresqlQuirks().filter_user_defined_types(
        extractor,
        "TEST_SCHEMA",
        [relation_type, explicit_type],
        lambda schema, include_views=False: [Table(name="parent_probe", schema=schema)],
    )

    assert result == [explicit_type]
    query_executor.execute_query.assert_called_once()


def _sequence_row(name, **extra):
    row = {
        "sequence_name": name,
        "start_value": "1",
        "increment": "1",
        "minimum_value": "1",
        "maximum_value": "9223372036854775807",
        "cycle_option": "NO",
        "cache_size": "1",
    }
    row.update(extra)
    return row


@pytest.mark.unit
def test_identity_owned_sequence_names_uses_pg_depend_deptype_i():
    """Identity backing sequences are those with an internal pg_depend row."""
    query_executor = MagicMock()
    query_executor.execute_query.return_value = [
        {"identity_sequence_name": "app_users_legacy_id_seq"},
    ]
    extractor = MagicMock()
    extractor.provider.query_executor = query_executor
    extractor.connection = object()

    names = PostgresqlQuirks().identity_owned_sequence_names(extractor, "public")

    assert names == {"app_users_legacy_id_seq"}
    sql = query_executor.execute_query.call_args.args[1]
    assert "pg_depend" in sql
    assert "deptype = 'i'" in sql
    assert "attidentity" in sql
    assert query_executor.execute_query.call_args.args[2] == ["public"]


@pytest.mark.unit
def test_identity_owned_sequence_names_ignores_sequence_name_only_rows():
    """A mocked sequences catalog must not be treated as identity-owned."""
    query_executor = MagicMock()
    query_executor.execute_query.return_value = [_sequence_row("order_seq")]
    extractor = MagicMock()
    extractor.provider.query_executor = query_executor
    extractor.connection = object()

    names = PostgresqlQuirks().identity_owned_sequence_names(extractor, "public")

    assert names == set()


@pytest.mark.unit
def test_identity_owned_sequence_names_returns_empty_when_catalog_read_fails():
    query_executor = MagicMock()
    query_executor.execute_query.side_effect = RuntimeError("undefined table")
    extractor = MagicMock()
    extractor.provider.query_executor = query_executor
    extractor.connection = object()

    names = PostgresqlQuirks().identity_owned_sequence_names(extractor, "public")

    assert names == set()
