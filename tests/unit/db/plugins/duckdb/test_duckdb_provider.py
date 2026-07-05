"""DuckDB provider tests — discovery, statement splitting, and a real
migrate/clean round-trip against an on-disk DuckDB file.

Requires the ``duckdb`` extra (``pip install dblift[duckdb]``); the
round-trip/clean tests skip when the driver is absent so the suite stays
green on driver-less CI shards. The discovery and splitter tests need no
driver and always run.
"""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb driver not installed")
pytest.importorskip("duckdb_engine", reason="duckdb_engine dialect not installed")


@pytest.mark.unit
class TestDuckDBRegistration:
    def test_plugin_metadata(self) -> None:
        from db.plugins.duckdb.plugin import PLUGIN

        assert PLUGIN.name == "duckdb"
        assert PLUGIN.dialects == ["duckdb"]
        assert PLUGIN.transport == "native"
        assert PLUGIN.provider_class.__name__ == "DuckDBProvider"

    def test_capability_matrix_from_quirks(self) -> None:
        from db.plugins.duckdb.quirks import DuckDBQuirks

        q = DuckDBQuirks()
        assert q.supports_transactions is True
        assert q.supports_transactional_ddl is True
        assert q.schema_required is False
        assert q.sqlglot_dialect == "duckdb"
        assert q.default_schema_name == "main"
        assert q.boolean_false_literal == "FALSE"

    def test_pro_hooks_none_in_oss(self) -> None:
        from db.plugins.duckdb.quirks import DuckDBQuirks

        q = DuckDBQuirks()
        assert q.ddl_generator_class() is None
        assert q.alter_generator_class() is None
        assert q.introspector_class() is None
        assert q.vendor_queries_class() is None


@pytest.mark.unit
class TestDuckDBParamBinding:
    def test_driver_bind_numeric_dollar(self) -> None:
        """duckdb_engine's dialect reports ``numeric_dollar``; the raw
        exec_driver_sql path must emit ``$1``/``$2`` (its DBAPI accepts them),
        not the unbindable ``:p0`` fallback."""
        from db.sqlalchemy_provider import SqlAlchemyProvider

        sql, params = SqlAlchemyProvider._driver_bind(
            "SELECT * FROM t WHERE a = ? AND b = ?", ["x", "y"], "numeric_dollar"
        )
        assert sql == "SELECT * FROM t WHERE a = $1 AND b = $2"
        assert params == ("x", "y")


@pytest.mark.unit
class TestDuckDBSplitter:
    def test_splits_respecting_strings_and_comments(self) -> None:
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        parser = DuckDBRegexParser()
        sql = "CREATE TABLE t (a INT); INSERT INTO t VALUES (';');\n-- c; still comment\nSELECT 1;"
        stmts = parser.split_statements(sql)
        assert len(stmts) == 3
        assert stmts[1] == "INSERT INTO t VALUES (';');"

    def test_strict_mode_does_not_raise(self) -> None:
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        parser = DuckDBRegexParser()
        stmts = parser.split_statements("CREATE TABLE t (a INT);", strict_tokenizer=True)
        assert stmts == ["CREATE TABLE t (a INT);"]

    def test_classify_and_extract(self) -> None:
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        parser = DuckDBRegexParser()
        assert parser.classify_statement("CREATE TABLE x (a int)") == "DDL"
        objs = parser.extract_objects("CREATE TABLE main.foo (a int)")
        assert [(o.object_type.value, o.name) for o in objs] == [("TABLE", "foo")]


@pytest.fixture()
def duckdb_provider():
    from config import DbliftConfig
    from db.plugins.duckdb.config import DuckDBConfig
    from db.plugins.duckdb.provider import DuckDBProvider

    tmp = Path(tempfile.mkdtemp())
    dbfile = tmp / "test.duckdb"
    config = DbliftConfig(database=DuckDBConfig(type="duckdb", path=str(dbfile), schema="main"))
    provider = DuckDBProvider(config)
    provider.create_connection()
    yield provider, tmp
    provider.close()


@pytest.mark.unit
class TestDuckDBRoundTrip:
    def test_migrate_creates_schema_and_records_history(self, duckdb_provider) -> None:
        from api.client import DBLiftClient

        provider, tmp = duckdb_provider
        migrations = tmp / "migrations"
        migrations.mkdir()
        (migrations / "V1__create.sql").write_text(
            "CREATE TABLE customers (id INTEGER PRIMARY KEY, name VARCHAR NOT NULL, "
            "active BOOLEAN DEFAULT TRUE);"
        )
        (migrations / "V2__alter.sql").write_text("ALTER TABLE customers ADD COLUMN email VARCHAR;")
        client = DBLiftClient(
            provider=provider, migrations_dir=str(migrations), config=provider.config
        )
        result = client.migrate()

        assert result.success is True
        assert provider.table_exists("main", "customers") is True
        cols = [
            r["column_name"]
            for r in provider.execute_query(
                "SELECT column_name FROM information_schema.columns "
                "WHERE table_schema='main' AND table_name='customers' ORDER BY ordinal_position"
            )
        ]
        assert cols == ["id", "name", "active", "email"]
        history = provider.get_applied_migrations("main")
        assert [h["installed_rank"] for h in history] == [1, 2]
        assert all(h["success"] for h in history)

    def test_clean_drops_tables_views_sequences(self, duckdb_provider) -> None:
        provider, _ = duckdb_provider
        provider.execute_statement("CREATE TABLE a (id INTEGER)")
        provider.execute_statement("CREATE SEQUENCE s")
        provider.execute_statement("CREATE VIEW v AS SELECT 1")

        preview = provider.get_clean_preview("main")
        assert sorted((o.object_type, o.name) for o in preview.objects) == [
            ("SEQUENCE", "s"),
            ("TABLE", "a"),
            ("VIEW", "v"),
        ]
        provider.clean_schema("main")
        assert provider.get_clean_preview("main").objects == []

    def test_clean_drops_fk_referenced_table(self, duckdb_provider) -> None:
        # DuckDB DROP TABLE CASCADE does not drop FKs held by other tables, so
        # a referenced table must be dropped after its referencing table.
        provider, _ = duckdb_provider
        provider.execute_statement("CREATE TABLE parent (id INTEGER PRIMARY KEY)")
        provider.execute_statement(
            "CREATE TABLE child (id INTEGER PRIMARY KEY, pid INTEGER REFERENCES parent(id))"
        )
        provider.clean_schema("main")
        assert provider.get_clean_preview("main").objects == []
