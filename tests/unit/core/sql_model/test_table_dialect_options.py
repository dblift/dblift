"""Tests for the Tier-3 ``Table.dialect_options`` plugin-isolation scaffold."""

from pathlib import Path

import pytest

from core.sql_model.base import SqlColumn
from core.sql_model.table import Table

pytestmark = [pytest.mark.unit]


class TestDialectOptionsScaffold:
    def test_defaults_to_empty_dict(self):
        t = Table(name="t")
        assert t.dialect_options == {}

    def test_set_then_get(self):
        t = Table(name="t")
        t.set_dialect_option("snowflake", "cluster_by", ["created_at"])
        assert t.get_dialect_option("snowflake", "cluster_by") == ["created_at"]

    def test_get_returns_default_when_missing(self):
        t = Table(name="t")
        assert t.get_dialect_option("snowflake", "cluster_by") is None
        assert t.get_dialect_option("snowflake", "cluster_by", default=[]) == []

    def test_set_creates_namespace(self):
        t = Table(name="t")
        t.set_dialect_option("bigquery", "partition_by", "DATE(created_at)")
        assert t.dialect_options == {"bigquery": {"partition_by": "DATE(created_at)"}}

    def test_set_none_records_explicit_null(self):
        t = Table(name="t")
        t.set_dialect_option("ns", "k", None)
        assert "k" in t.dialect_options["ns"]
        assert t.get_dialect_option("ns", "k", default="fallback") is None

    def test_namespaces_isolated(self):
        t = Table(name="t")
        t.set_dialect_option("snowflake", "cluster_by", ["a"])
        t.set_dialect_option("bigquery", "cluster_by", ["b"])
        assert t.get_dialect_option("snowflake", "cluster_by") == ["a"]
        assert t.get_dialect_option("bigquery", "cluster_by") == ["b"]

    def test_round_trip_via_dict(self):
        t = Table(name="t", dialect="snowflake")
        t.set_dialect_option("snowflake", "cluster_by", ["created_at"])
        t.set_dialect_option("snowflake", "data_retention_days", 30)

        restored = Table.from_dict(t.to_dict())

        assert restored.get_dialect_option("snowflake", "cluster_by") == ["created_at"]
        assert restored.get_dialect_option("snowflake", "data_retention_days") == 30

    def test_equality_considers_dialect_options(self):
        a = Table(name="t", dialect="snowflake")
        b = Table(name="t", dialect="snowflake")
        assert a == b

        a.set_dialect_option("snowflake", "cluster_by", ["x"])
        assert a != b

        b.set_dialect_option("snowflake", "cluster_by", ["x"])
        assert a == b


class TestDialectOptionsSerializationContract:
    """Characterization tests pinning the ``to_dict`` serialization contract
    after ADR-26 E story 26-5 removed the four ``_NS_X`` dialect-name literals
    (and the per-dialect convenience properties) from ``table.py``.

    Built-in table options (storage_engine/filegroup/pctfree/row_security/...)
    live exclusively *inside* ``dialect_options`` under their canonical dialect
    namespace — the same public extension point third-party plugins use. The
    serialized dict no longer re-emits redundant top-level built-in keys; the
    ``dialect_options`` value is the single source of truth and round-trips
    byte-identically. Framework consumers read built-ins via
    ``get_dialect_option(<canonical-dialect>, "<option>")`` rather than named
    convenience properties, so ``table.py`` holds no dialect-name string
    literals.
    """

    def _populated(self) -> Table:
        t = Table(
            name="orders",
            schema="app",
            columns=[SqlColumn(name="id", data_type="INT")],
            dialect="mysql",
        )
        t.set_dialect_option("mysql", "storage_engine", "InnoDB")
        t.set_dialect_option("sqlserver", "filegroup", "PRIMARY")
        t.set_dialect_option("oracle", "pctfree", 10)
        t.set_dialect_option("postgresql", "row_security", True)
        t.set_dialect_option("thirdparty", "custom_key", "custom_value")
        return t

    def test_table_py_has_no_dialect_name_literals(self):
        """``table.py`` must hold zero dialect-name string literals — the four
        ``_NS_X`` constants are eliminated for ADR-26 E story 26-5."""
        import ast

        from core.sql_model import table as table_module

        source = Path(table_module.__file__).read_text(encoding="utf-8")
        tree = ast.parse(source)
        dialect_names = {
            "postgresql",
            "postgres",
            "oracle",
            "mysql",
            "mariadb",
            "sqlserver",
            "mssql",
            "db2",
            "sqlite",
            "cosmosdb",
        }
        offenders = [
            node.value
            for node in ast.walk(tree)
            if isinstance(node, ast.Constant)
            and isinstance(node.value, str)
            and node.value.lower() in dialect_names
        ]
        assert offenders == [], f"table.py still names dialects: {offenders}"

    def test_to_dict_serializes_builtins_under_dialect_namespaces(self):
        """Built-in table options are persisted *inside* ``dialect_options``
        keyed by canonical dialect name — the shape any snapshot reader sees."""
        d = self._populated().to_dict()
        assert d["dialect_options"] == {
            "mysql": {"storage_engine": "InnoDB"},
            "sqlserver": {"filegroup": "PRIMARY"},
            "oracle": {"pctfree": 10},
            "postgresql": {"row_security": True},
            "thirdparty": {"custom_key": "custom_value"},
        }

    def test_to_dict_does_not_emit_redundant_top_level_builtin_keys(self):
        """``to_dict`` no longer mirrors built-in options as top-level keys;
        ``dialect_options`` is the single source of truth."""
        d = self._populated().to_dict()
        for redundant in (
            "storage_engine",
            "row_format",
            "table_collation",
            "next_auto_increment",
            "create_options",
            "filegroup",
            "memory_optimized",
            "system_versioned",
            "history_table",
            "history_schema",
            "period_start_column",
            "period_end_column",
            "row_security",
            "force_row_security",
            "policies",
            "pctfree",
            "pctused",
            "initial",
            "next",
            "inherits",
        ):
            assert redundant not in d, f"{redundant!r} should not be a top-level key"

    def test_reconstructed_object_round_trips_identically(self):
        """``Table.from_dict(t.to_dict()) == t`` for a table populated with
        mysql/oracle/postgres/sqlserver built-ins plus a third-party namespace."""
        t = self._populated()
        assert Table.from_dict(t.to_dict()) == t

    def test_dialect_options_key_round_trips_byte_identical(self):
        """The ``dialect_options`` value survives a from_dict/to_dict round-trip
        unchanged — confirming it is a stable persisted-JSON contract."""
        d1 = self._populated().to_dict()
        d2 = Table.from_dict(d1).to_dict()
        assert d1["dialect_options"] == d2["dialect_options"]

    def test_dialect_options_key_is_load_bearing_for_third_party(self):
        """Dropping the ``dialect_options`` key from the serialized dict loses
        third-party namespaces on round-trip, so ``to_dict`` cannot stop
        emitting it — pinning the public serialization contract."""
        t = Table(name="t", dialect="snowflake")
        t.set_dialect_option("snowflake", "cluster_by", ["created_at"])
        d = t.to_dict()
        d.pop("dialect_options")
        restored = Table.from_dict(d)
        assert restored.get_dialect_option("snowflake", "cluster_by") is None

    def test_legacy_snapshot_with_builtins_only_in_dialect_options_reads_back(self):
        """A snapshot that carries a built-in option only under
        ``dialect_options[<dialect>]`` must hydrate it back via
        ``get_dialect_option`` — proving readers depend on the namespaced shape."""
        legacy = {
            "name": "t",
            "schema": "app",
            "dialect": "mysql",
            "object_type": "TABLE",
            "columns": [],
            "constraints": [],
            "dialect_options": {"mysql": {"storage_engine": "MyISAM"}},
        }
        restored = Table.from_dict(legacy)
        assert restored.get_dialect_option("mysql", "storage_engine") == "MyISAM"

    def test_legacy_snapshot_with_top_level_builtin_key_still_hydrates(self):
        """Snapshots written before story 26-5 carry built-ins as *top-level*
        keys; ``from_dict`` must still hydrate them into ``dialect_options``."""
        legacy = {
            "name": "t",
            "schema": "app",
            "dialect": "mysql",
            "object_type": "TABLE",
            "columns": [],
            "constraints": [],
            "storage_engine": "MyISAM",
            "filegroup": "FG1",
            "pctfree": 20,
            "row_security": True,
        }
        restored = Table.from_dict(legacy)
        assert restored.get_dialect_option("mysql", "storage_engine") == "MyISAM"
        assert restored.get_dialect_option("sqlserver", "filegroup") == "FG1"
        assert restored.get_dialect_option("oracle", "pctfree") == 20
        assert restored.get_dialect_option("postgresql", "row_security") is True
