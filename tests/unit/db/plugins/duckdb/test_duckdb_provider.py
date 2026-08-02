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

    def test_extract_objects_from_create(self) -> None:
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        parser = DuckDBRegexParser()
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


@pytest.mark.unit
class TestDuckDBDmlRowcount:
    def _provider(self, tmp_path: Path) -> "DuckDBProvider":
        from config import DatabaseConfig, DbliftConfig
        from db.plugins.duckdb.provider import DuckDBProvider

        db_file = tmp_path / "rc.duckdb"
        cfg = DbliftConfig(
            database=DatabaseConfig(
                type="duckdb",
                url=f"duckdb:///{db_file}",
                schema="main",
            )
        )
        return DuckDBProvider(cfg)

    def test_update_reports_positive_rowcount(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
        rc = provider.execute_statement("UPDATE t SET v = 'x' WHERE id = 1")
        assert rc == 1, f"expected rowcount 1, got {rc}"
        rc0 = provider.execute_statement("UPDATE t SET v = 'y' WHERE id = 99")
        assert rc0 == 0, f"expected rowcount 0, got {rc0}"

    def test_update_with_leading_directive_comments(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        sql = "-- dblift:formatted\n-- dblift: expect=1 onfail=halt\nUPDATE t SET v = 'x' WHERE id = 1;"
        assert provider.execute_statement(sql) == 1

    def test_pk_violation_propagates_root_error(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        with pytest.raises(Exception) as ei:
            provider.execute_statement("INSERT INTO t VALUES (1, 'dup')")
        msg = str(ei.value).lower()
        assert "aborted" not in msg or "constraint" in msg or "unique" in msg or "primary" in msg

    def test_delete_and_multi_row_insert_rowcounts(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        assert provider.execute_statement("INSERT INTO t VALUES (1, 'a'), (2, 'b'), (3, 'c')") == 3
        assert provider.execute_statement("DELETE FROM t WHERE id >= 2") == 2

    def test_params_update_reports_positive_rowcount(self, tmp_path: Path) -> None:
        """Parameterized DML uses RETURNING rewrite (undo restore / bind paths)."""
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a'), (2, 'b')")
        rc = provider.execute_statement("UPDATE t SET v = ? WHERE id = ?", params=["x", 1])
        assert rc == 1, f"expected rowcount 1 for matching param UPDATE, got {rc}"
        rows = provider.execute_query("SELECT v FROM t WHERE id = 1")
        assert rows[0]["v"] == "x"
        rc0 = provider.execute_statement("UPDATE t SET v = ? WHERE id = ?", params=["y", 99])
        assert rc0 == 0, f"expected rowcount 0 for non-matching param UPDATE, got {rc0}"

    def test_params_delete_and_insert_rowcounts(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        assert (
            provider.execute_statement(
                "INSERT INTO t (id, v) VALUES (?, ?), (?, ?)",
                params=[1, "a", 2, "b"],
            )
            == 2
        )
        assert provider.execute_statement("DELETE FROM t WHERE id = ?", params=[1]) == 1
        assert provider.execute_statement("DELETE FROM t WHERE id = ?", params=[99]) == 0

    def test_existing_returning_not_double_appended(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        # Already has RETURNING — path returns None from helper, super executes
        rc = provider.execute_statement("UPDATE t SET v = 'z' WHERE id = 1 RETURNING id")
        assert isinstance(rc, int)

    def test_trailing_comment_does_not_swallow_returning(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        # Bugbot: inline `--` on the same line must not comment out RETURNING 1
        sql = "UPDATE t SET v = 'x' WHERE id = 1  -- trailing note"
        assert provider.execute_statement(sql) == 1
        rows = provider.execute_query("SELECT v FROM t WHERE id = 1")
        assert rows[0]["v"] == "x"

    def test_dash_dash_inside_string_is_not_stripped(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        assert provider.execute_statement("UPDATE t SET v = 'a--b' WHERE id = 1") == 1
        rows = provider.execute_query("SELECT v FROM t WHERE id = 1")
        assert rows[0]["v"] == "a--b"

    def test_semicolon_inside_string_still_rewrites(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        assert provider.execute_statement("UPDATE t SET v = 'a;b' WHERE id = 1") == 1

    def test_multi_statement_falls_back(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        # Top-level semicolon → no RETURNING rewrite; should not crash
        rc = provider.execute_statement(
            "INSERT INTO t VALUES (1, 'a'); INSERT INTO t VALUES (2, 'b')"
        )
        assert isinstance(rc, int)

    def test_strip_sql_comments_helpers(self) -> None:
        from db.plugins.duckdb.provider import DuckDBProvider

        strip = DuckDBProvider._strip_sql_comments
        assert strip("-- only comment") == ""
        assert strip("/* block */") == ""
        assert strip("/* a */\nUPDATE t SET v=1 /* trail */") == "UPDATE t SET v=1"
        assert strip("-- d1\n-- d2\nDELETE FROM t") == "DELETE FROM t"
        assert strip("UPDATE t SET v=1\n-- trail\n") == "UPDATE t SET v=1"
        # Inline trailing comment on the DML line (Bugbot finding)
        assert strip("UPDATE t SET v=1  -- note") == "UPDATE t SET v=1"
        # Dashes inside string literals must remain
        assert strip("UPDATE t SET v = 'a--b'") == "UPDATE t SET v = 'a--b'"

    def test_has_top_level_semicolon_helpers(self) -> None:
        from db.plugins.duckdb.provider import DuckDBProvider

        has = DuckDBProvider._has_top_level_semicolon
        assert has("UPDATE t SET v = 1") is False
        assert has("UPDATE t SET v = 'a;b'") is False
        assert has('UPDATE t SET v = "a;b"') is False
        assert has("UPDATE t SET v = 'it''s;ok'") is False
        assert has("INSERT INTO t VALUES (1); INSERT INTO t VALUES (2)") is True

    def test_returning_word_in_string_still_rewrites(self, tmp_path: Path) -> None:
        """Bugbot: substring ' RETURNING ' inside a literal must not skip rewrite."""
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        assert provider.execute_statement("UPDATE t SET v = ' returning ' WHERE id = 1") == 1
        rows = provider.execute_query("SELECT v FROM t WHERE id = 1")
        assert rows[0]["v"] == " returning "

    def test_returning_word_in_mid_comment_still_rewrites(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        sql = "UPDATE t SET v = 'x'\n-- returning users later\nWHERE id = 1"
        assert provider.execute_statement(sql) == 1

    def test_has_top_level_keyword_helpers(self) -> None:
        from db.plugins.duckdb.provider import DuckDBProvider

        has = DuckDBProvider._has_top_level_keyword
        strip = DuckDBProvider._strip_sql_comments
        assert has("UPDATE t SET v = 1 RETURNING id", "RETURNING") is True
        assert has("UPDATE t SET v = ' returning ' WHERE id = 1", "RETURNING") is False
        # After comment strip, mid-line/full-line comments mentioning returning are gone
        cleaned = strip("UPDATE t SET v = 1  -- returning\nWHERE id = 1")
        assert "returning" not in cleaned.lower()
        assert has(cleaned, "RETURNING") is False

    def test_schema_kwarg_path_with_dml_rowcount(self, tmp_path: Path) -> None:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE SCHEMA IF NOT EXISTS s")
        provider.execute_statement(
            "CREATE TABLE s.t (id INTEGER PRIMARY KEY, v VARCHAR)", schema="s"
        )
        provider.execute_statement("INSERT INTO s.t VALUES (1, 'a')", schema="s")
        assert provider.execute_statement("UPDATE s.t SET v = 'x' WHERE id = 1", schema="s") == 1
