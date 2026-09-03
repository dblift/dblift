"""Regression tests for Flyway/Dblift schema history compatibility checks."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from dblift.core.sql_validator.migration_validator import MigrationValidator


def _make_validator(provider: MagicMock) -> MigrationValidator:
    validator = MigrationValidator.__new__(MigrationValidator)
    validator.log = MagicMock()
    validator.history_manager = SimpleNamespace(
        provider=provider,
        schema="public",
        history_table="dblift_schema_history",
        normalized_history_table="dblift_schema_history",
    )
    validator._flyway_compatibility_cache = None
    return validator


def _row(
    version: str = "1",
    script: str = "V1__init.sql",
    checksum: int = 123,
) -> dict[str, object]:
    return {
        "version": version,
        "description": "init",
        "type": "SQL",
        "script": script,
        "checksum": checksum,
        "installed_by": "tester",
        "installed_rank": 1,
        "success": True,
    }


@pytest.mark.unit
class TestFlywayCompatibilityCache:
    def test_first_call_computes_instead_of_returning_empty_cache(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], []]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["flyway_exists"] is True
        assert result["Dblift_exists"] is True
        assert result["compatible"] is False
        assert result["flyway_count"] == 1
        assert result["Dblift_count"] == 0
        assert "Flyway has 1 migrations" in str(result["error_message"])
        assert provider.execute_query.call_count == 2

    def test_computed_result_is_cached_after_first_check(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], [_row()]]
        validator = _make_validator(provider)

        first = validator.validate_flyway_compatibility()
        second = validator.validate_flyway_compatibility()

        assert first is second
        assert first["compatible"] is True
        assert provider.table_exists.call_count == 2
        assert provider.execute_query.call_count == 2


@pytest.mark.unit
class TestFlywayCompatibilityHistoryColumns:
    def test_dblift_query_uses_script_column(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], [_row()]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is True
        dblift_query = provider.execute_query.call_args_list[1].args[0]
        assert "script_name" not in dblift_query
        assert "script," in dblift_query
        assert "checksum" in dblift_query

    def test_checksum_mismatch_is_incompatible(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row(checksum=123)], [_row(checksum=456)]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is False
        assert "checksum mismatch" in str(result["error_message"])

    def test_unsigned_and_signed_crc32_values_match(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [
            [_row(checksum=3272252829)],
            [_row(checksum=-1022714467)],
        ]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is True

    def test_check_flyway_history_table_propagates_incompatibility(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True, True, True]
        provider.execute_query.side_effect = [[_row()], []]

        result = _make_validator(provider).check_flyway_history_table()

        assert result.success is False
        assert "Flyway has 1 migrations" in result.error_message


@pytest.mark.unit
class TestFlywayCompatibilityAcceptedTypes:
    """The two sides of the type gate accept different vocabularies.

    A dblift history legitimately contains ``PYTHON`` rows — that is what a
    versioned ``.py`` migration is stored as. Flyway has no such type and never
    writes one, so widening both sides would weaken a real check.
    """

    def test_dblift_python_row_is_compatible(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], [{**_row(), "type": "PYTHON"}]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is True, result["error_message"]

    def test_flyway_python_row_is_still_rejected(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[{**_row(), "type": "PYTHON"}], [_row()]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is False
        assert "Unsupported migration type" in str(result["error_message"])

    def test_dblift_unknown_row_is_still_rejected(self):
        provider = MagicMock()
        provider.table_exists.side_effect = [True, True]
        provider.execute_query.side_effect = [[_row()], [{**_row(), "type": "NONSENSE"}]]

        result = _make_validator(provider).validate_flyway_compatibility()

        assert result["compatible"] is False
        assert "Migration type mismatch" in str(result["error_message"])
