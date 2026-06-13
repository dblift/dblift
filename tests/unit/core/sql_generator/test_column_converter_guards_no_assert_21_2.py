"""Tests for ColumnConverter dialect-via-quirks refactor (story 21-2 / Epic 27).

Old story 21-2 tested private handler functions (_nullable_postgresql etc.)
that have since moved into dialect Quirks classes.  These tests cover the
same acceptance criteria through the public API.
"""

import inspect

import pytest

from core.comparison.diff_models import ColumnDiff
from core.sql_generator.diff_converters.column_converter import ColumnConverter
from core.sql_generator.sql_statement import GenerationOptions

pytestmark = [pytest.mark.unit]


def _make_column_diff(**kwargs) -> ColumnDiff:
    return ColumnDiff(
        object_name=kwargs.pop("object_name", "col"),
        column_name=kwargs.pop("column_name", "col"),
        **kwargs,
    )


def _make_options(dialect: str = "postgresql") -> GenerationOptions:
    return GenerationOptions(dialect=dialect)


# ---------------------------------------------------------------------------
# AC#1 — No assert statement in the column_converter module
# ---------------------------------------------------------------------------


class TestNoAssertInModule:
    def test_no_assert_keyword_in_source(self):
        import core.sql_generator.diff_converters.column_converter as mod

        source = inspect.getsource(mod)
        assert_lines = [line for line in source.splitlines() if line.strip().startswith("assert ")]
        assert assert_lines == [], f"Found assert lines: {assert_lines}"


# ---------------------------------------------------------------------------
# AC#3/AC#4 — Nullable changes via quirks
# ---------------------------------------------------------------------------


class TestNullableViaQuirks:
    def test_postgresql_set_not_null(self):
        conv = ColumnConverter(dialect="postgresql")
        diff = _make_column_diff(nullable_diff=(False, True))
        stmts = conv.convert(diff, "public.t", _make_options())
        assert any("SET NOT NULL" in s.sql for s in stmts)

    def test_postgresql_drop_not_null(self):
        conv = ColumnConverter(dialect="postgresql")
        diff = _make_column_diff(nullable_diff=(True, False))
        stmts = conv.convert(diff, "public.t", _make_options())
        assert any("DROP NOT NULL" in s.sql for s in stmts)

    def test_oracle_set_not_null_uses_modify(self):
        conv = ColumnConverter(dialect="oracle")
        diff = _make_column_diff(nullable_diff=(False, True))
        stmts = conv.convert(diff, "SCHEMA.T", _make_options("oracle"))
        assert any("MODIFY" in s.sql and "NOT NULL" in s.sql for s in stmts)

    def test_sqlserver_set_not_null(self):
        conv = ColumnConverter(dialect="sqlserver")
        diff = _make_column_diff(nullable_diff=(False, True))
        stmts = conv.convert(diff, "dbo.t", _make_options("sqlserver"))
        assert any("NOT NULL" in s.sql for s in stmts)

    def test_no_nullable_diff_produces_no_nullable_stmt(self):
        conv = ColumnConverter(dialect="postgresql")
        diff = _make_column_diff(nullable_diff=None)
        stmts = conv.convert(diff, "public.t", _make_options())
        assert not any("NOT NULL" in s.sql or "NULL" in s.sql for s in stmts)


# ---------------------------------------------------------------------------
# AC#3/AC#4 — Default changes via quirks
# ---------------------------------------------------------------------------


class TestDefaultViaQuirks:
    def test_postgresql_set_default(self):
        conv = ColumnConverter(dialect="postgresql")
        diff = _make_column_diff(default_diff=("0", None))
        stmts = conv.convert(diff, "public.t", _make_options())
        assert any("SET DEFAULT" in s.sql for s in stmts)

    def test_postgresql_drop_default(self):
        conv = ColumnConverter(dialect="postgresql")
        diff = _make_column_diff(default_diff=(None, "old"))
        stmts = conv.convert(diff, "public.t", _make_options())
        assert any("DROP DEFAULT" in s.sql for s in stmts)

    def test_oracle_set_default_uses_modify(self):
        conv = ColumnConverter(dialect="oracle")
        diff = _make_column_diff(default_diff=("0", None))
        stmts = conv.convert(diff, "SCHEMA.T", _make_options("oracle"))
        assert any("MODIFY" in s.sql and "DEFAULT 0" in s.sql for s in stmts)


# ---------------------------------------------------------------------------
# AC#3/AC#4 — Type changes via quirks
# ---------------------------------------------------------------------------


class TestTypeViaQuirks:
    def test_postgresql_type_change(self):
        conv = ColumnConverter(dialect="postgresql")
        diff = _make_column_diff(data_type_diff=("TEXT", "VARCHAR(50)"))
        stmts = conv.convert(diff, "public.t", _make_options())
        assert any("TYPE TEXT" in s.sql for s in stmts)

    def test_oracle_type_change_uses_modify(self):
        conv = ColumnConverter(dialect="oracle")
        diff = _make_column_diff(data_type_diff=("CLOB", "VARCHAR2(100)"))
        stmts = conv.convert(diff, "SCHEMA.T", _make_options("oracle"))
        assert any("MODIFY" in s.sql and "CLOB" in s.sql for s in stmts)

    def test_sqlserver_type_change(self):
        conv = ColumnConverter(dialect="sqlserver")
        diff = _make_column_diff(data_type_diff=("NVARCHAR(100)", "VARCHAR(50)"))
        stmts = conv.convert(diff, "dbo.t", _make_options("sqlserver"))
        assert any("NVARCHAR(100)" in s.sql for s in stmts)

    def test_mysql_type_change_uses_modify(self):
        conv = ColumnConverter(dialect="mysql")
        diff = _make_column_diff(data_type_diff=("TEXT", "VARCHAR(255)"))
        stmts = conv.convert(diff, "t", _make_options("mysql"))
        assert any("MODIFY" in s.sql and "TEXT" in s.sql for s in stmts)

    def test_cosmosdb_type_change_returns_comment(self):
        conv = ColumnConverter(dialect="cosmosdb")
        diff = _make_column_diff(data_type_diff=("STRING", "INT"))
        stmts = conv.convert(diff, "t", _make_options("cosmosdb"))
        assert any("schema-less" in s.sql.lower() or s.statement_type == "COMMENT" for s in stmts)


# ---------------------------------------------------------------------------
# AC#3/AC#4 — Collation changes via quirks
# ---------------------------------------------------------------------------


class TestCollationViaQuirks:
    def test_postgresql_collation_change(self):
        conv = ColumnConverter(dialect="postgresql")
        diff = _make_column_diff(collation_diff=("en_US", "fr_FR"))
        stmts = conv.convert(diff, "public.t", _make_options())
        assert any("SET COLLATION en_US" in s.sql for s in stmts)

    def test_unknown_dialect_logs_warning_returns_empty(self, caplog):
        import logging

        conv = ColumnConverter(dialect="nonexistent")
        diff = _make_column_diff(nullable_diff=(False, True))
        with caplog.at_level(logging.WARNING):
            stmts = conv.convert(diff, "t", _make_options("nonexistent"))
        assert stmts == []
        assert any("Unsupported dialect" in r.message for r in caplog.records)
