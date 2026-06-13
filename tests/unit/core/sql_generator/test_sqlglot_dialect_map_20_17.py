"""Tests for _SQLGLOT_DIALECT_MAP consolidation (story 20-17)."""

import inspect

import pytest

from core.sql_model.dialect import SQLGLOT_DIALECT_MAP as _SQLGLOT_DIALECT_MAP
from core.sql_model.dialect import get_sqlglot_dialect

pytestmark = [pytest.mark.unit]


class TestSqlglotDialectMapConsolidation:
    """AC#2 — Single source of truth for sqlglot dialect mapping."""

    def test_importable_from_formatter(self):
        # Trigger lazy population before inspecting raw dict
        get_sqlglot_dialect("postgresql")
        assert _SQLGLOT_DIALECT_MAP is not None
        assert len(_SQLGLOT_DIALECT_MAP) > 0

    def test_postgresql_maps_to_postgres(self):
        assert get_sqlglot_dialect("postgresql") == "postgres"

    def test_oracle_maps_to_oracle(self):
        assert get_sqlglot_dialect("oracle") == "oracle"

    def test_sqlserver_maps_to_tsql(self):
        assert get_sqlglot_dialect("sqlserver") == "tsql"

    def test_mysql_maps_to_mysql(self):
        assert get_sqlglot_dialect("mysql") == "mysql"

    def test_db2_not_supported(self):
        assert get_sqlglot_dialect("db2") is None

    def test_sqlite_maps_to_sqlite(self):
        assert get_sqlglot_dialect("sqlite") == "sqlite"

    def test_cosmosdb_not_supported(self):
        assert get_sqlglot_dialect("cosmosdb") is None


class TestNoLocalDialectMap:
    """AC#2.2 — sqlglot_parser no longer has a local DIALECT_MAP."""

    def test_sqlglot_parser_no_local_dialect_map(self):
        """Module no longer defines its own DIALECT_MAP at module level."""
        import core.sql_parser.sqlglot_parser as mod

        assert "DIALECT_MAP" not in vars(mod)

    def test_sqlglot_parser_imports_centralized_map(self):
        from core.sql_parser import sqlglot_parser as mod

        module_source = inspect.getsource(mod)
        assert "_SQLGLOT_DIALECT_MAP" in module_source
