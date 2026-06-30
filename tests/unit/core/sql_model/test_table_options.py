"""Unit tests for ``core.sql_model.table_options.TableOptions`` and the
``Table.from_options`` / ``Table.to_options`` classmethods (SIMP-48).

These tests verify the typed dialect-specific options surface. Since
``Table.__init__`` only accepts base/structural parameters, all
dialect-specific properties must round-trip through
``TableOptions`` -> ``Table.from_options`` -> ``Table.to_options``.
"""

from __future__ import annotations

import dataclasses

import pytest

from core.sql_model.base import SqlColumn
from core.sql_model.table import Table
from core.sql_model.table_options import (
    MySqlTableOptions,
    OracleStorageOptions,
    PostgresTableOptions,
    SqlServerTableOptions,
    TableOptions,
)

# ---------------------------------------------------------------------------
# Dataclass immutability and defaults
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestTableOptionsImmutability:
    def test_empty_options_has_default_subgroups(self):
        opts = TableOptions()
        assert isinstance(opts.mysql, MySqlTableOptions)
        assert isinstance(opts.sqlserver, SqlServerTableOptions)
        assert isinstance(opts.postgres, PostgresTableOptions)
        assert isinstance(opts.oracle_storage, OracleStorageOptions)
        assert opts.derived_from is None
        assert opts.raw_ddl is None

    def test_options_are_frozen(self):
        opts = TableOptions()
        with pytest.raises(dataclasses.FrozenInstanceError):
            opts.derived_from = "CTAS"  # type: ignore[misc]

    def test_subgroups_are_frozen(self):
        ms = MySqlTableOptions(storage_engine="InnoDB")
        with pytest.raises(dataclasses.FrozenInstanceError):
            ms.storage_engine = "MyISAM"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# Table.from_options equivalence with legacy constructor
# ---------------------------------------------------------------------------


def _basic_columns():
    return [SqlColumn("id", "INT"), SqlColumn("name", "VARCHAR(50)")]


@pytest.mark.unit
class TestFromOptionsEquivalence:
    def test_minimal_construction(self):
        legacy = Table(name="t", columns=_basic_columns(), dialect="mysql")
        typed = Table.from_options(
            name="t", columns=_basic_columns(), dialect="mysql", options=TableOptions()
        )

        assert typed.name == legacy.name
        assert typed.dialect == legacy.dialect
        assert [c.name for c in typed.columns] == [c.name for c in legacy.columns]
        assert typed.get_dialect_option("mysql", "storage_engine") is None
        assert typed.get_dialect_option("sqlserver", "memory_optimized", default=False) is False
        assert typed.get_dialect_option("postgresql", "policies", default=[]) == []
        assert typed.get_dialect_option("postgresql", "inherits", default=[]) == []

    def test_mysql_options_propagate_to_attributes(self):
        opts = TableOptions(
            mysql=MySqlTableOptions(
                storage_engine="InnoDB",
                row_format="DYNAMIC",
                table_collation="utf8mb4_unicode_ci",
                next_auto_increment=42,
                create_options="ROW_FORMAT=DYNAMIC",
            )
        )
        t = Table.from_options(name="t", columns=_basic_columns(), options=opts, dialect="mysql")

        assert t.get_dialect_option("mysql", "storage_engine") == "InnoDB"
        assert t.get_dialect_option("mysql", "row_format") == "DYNAMIC"
        assert t.get_dialect_option("mysql", "table_collation") == "utf8mb4_unicode_ci"
        assert t.get_dialect_option("mysql", "next_auto_increment") == 42
        assert t.get_dialect_option("mysql", "create_options") == "ROW_FORMAT=DYNAMIC"

    def test_sqlserver_options_propagate_and_mark_explicit(self):
        opts = TableOptions(
            sqlserver=SqlServerTableOptions(
                filegroup="PRIMARY",
                memory_optimized=True,
                system_versioned=True,
                history_table="t_history",
                history_schema="hist",
                period_start_column="valid_from",
                period_end_column="valid_to",
            )
        )
        t = Table.from_options(
            name="t", columns=_basic_columns(), options=opts, dialect="sqlserver"
        )

        assert t.get_dialect_option("sqlserver", "filegroup") == "PRIMARY"
        assert t.get_dialect_option("sqlserver", "memory_optimized") is True
        assert t.get_dialect_option("sqlserver", "system_versioned") is True
        assert t.get_dialect_option("sqlserver", "history_table") == "t_history"
        # mark_property_explicit hooks must still fire — same as legacy ctor
        assert t.is_property_explicit("filegroup")
        assert t.is_property_explicit("memory_optimized")
        assert t.is_property_explicit("history_table")

    def test_postgres_options_propagate(self):
        opts = TableOptions(
            postgres=PostgresTableOptions(
                row_security=True,
                force_row_security=True,
                policies=[{"name": "p1", "for": "ALL"}],
                inherits=["parent_a", "parent_b"],
            )
        )
        t = Table.from_options(
            name="t", columns=_basic_columns(), options=opts, dialect="postgresql"
        )

        assert t.get_dialect_option("postgresql", "row_security") is True
        assert t.get_dialect_option("postgresql", "force_row_security") is True
        assert t.get_dialect_option("postgresql", "policies") == [{"name": "p1", "for": "ALL"}]
        assert t.get_dialect_option("postgresql", "inherits") == ["parent_a", "parent_b"]

    def test_oracle_storage_options_propagate(self):
        opts = TableOptions(
            oracle_storage=OracleStorageOptions(pctfree=10, pctused=40, initial=1024, next=2048)
        )
        t = Table.from_options(name="t", columns=_basic_columns(), options=opts, dialect="oracle")

        assert t.get_dialect_option("oracle", "pctfree") == 10
        assert t.get_dialect_option("oracle", "pctused") == 40
        assert t.get_dialect_option("oracle", "initial") == 1024
        assert t.get_dialect_option("oracle", "next") == 2048


# ---------------------------------------------------------------------------
# Table.to_options round-trip
# ---------------------------------------------------------------------------


@pytest.mark.unit
class TestToOptionsRoundTrip:
    def test_empty_table_round_trip(self):
        t = Table(name="t", columns=_basic_columns(), dialect="postgresql")
        opts = t.to_options()
        assert opts == TableOptions()

    def test_full_round_trip_preserves_fields(self):
        original = TableOptions(
            mysql=MySqlTableOptions(storage_engine="InnoDB", next_auto_increment=7),
            sqlserver=SqlServerTableOptions(memory_optimized=True, history_table="h"),
            postgres=PostgresTableOptions(row_security=True, inherits=["parent"]),
            oracle_storage=OracleStorageOptions(pctfree=5),
            derived_from="CTAS",
            raw_ddl="CREATE TABLE t AS SELECT 1",
        )
        t = Table.from_options(
            name="t", columns=_basic_columns(), options=original, dialect="mysql"
        )

        rebuilt = t.to_options()
        assert rebuilt == original
