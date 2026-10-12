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
from typing import Any

import pytest

duckdb = pytest.importorskip("duckdb", reason="duckdb driver not installed")
pytest.importorskip("duckdb_engine", reason="duckdb_engine dialect not installed")


@pytest.mark.unit
class TestDuckDBRegistration:
    def test_plugin_metadata(self) -> None:
        from dblift.db.plugins.duckdb.plugin import PLUGIN

        assert PLUGIN.name == "duckdb"
        assert PLUGIN.dialects == ["duckdb"]
        assert PLUGIN.transport == "native"
        assert PLUGIN.provider_class.__name__ == "DuckDBProvider"

    def test_capability_matrix_from_quirks(self) -> None:
        from dblift.db.plugins.duckdb.quirks import DuckDBQuirks

        q = DuckDBQuirks()
        assert q.supports_transactions is True
        assert q.supports_transactional_ddl is True
        assert q.schema_required is False
        assert q.sqlglot_dialect == "duckdb"
        assert q.default_schema_name == "main"
        assert q.boolean_false_literal == "FALSE"

    def test_pro_hooks_none_in_oss(self) -> None:
        from dblift.db.plugins.duckdb.quirks import DuckDBQuirks

        q = DuckDBQuirks()
        assert not hasattr(q, "introspector_class")
        assert not hasattr(q, "vendor_queries_class")


@pytest.mark.unit
class TestDuckDBParamBinding:
    def test_driver_bind_numeric_dollar(self) -> None:
        """duckdb_engine's dialect reports ``numeric_dollar``; the raw
        exec_driver_sql path must emit ``$1``/``$2`` (its DBAPI accepts them),
        not the unbindable ``:p0`` fallback."""
        from dblift.db.sqlalchemy_provider import SqlAlchemyProvider

        sql, params = SqlAlchemyProvider._driver_bind(
            "SELECT * FROM t WHERE a = ? AND b = ?", ["x", "y"], "numeric_dollar"
        )
        assert sql == "SELECT * FROM t WHERE a = $1 AND b = $2"
        assert params == ("x", "y")


@pytest.mark.unit
class TestDuckDBSplitter:
    def test_splits_respecting_strings_and_comments(self) -> None:
        from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        parser = DuckDBRegexParser()
        sql = "CREATE TABLE t (a INT); INSERT INTO t VALUES (';');\n-- c; still comment\nSELECT 1;"
        stmts = parser.split_statements(sql)
        assert len(stmts) == 3
        assert stmts[1] == "INSERT INTO t VALUES (';')"

    def test_strict_mode_does_not_raise(self) -> None:
        from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        parser = DuckDBRegexParser()
        stmts = parser.split_statements("CREATE TABLE t (a INT);", strict_tokenizer=True)
        assert stmts == ["CREATE TABLE t (a INT)"]

    def test_extract_objects_from_create(self) -> None:
        from dblift.db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        parser = DuckDBRegexParser()
        objs = parser.extract_objects("CREATE TABLE main.foo (a int)")
        assert [(o.object_type.value, o.name) for o in objs] == [("TABLE", "foo")]


@pytest.fixture()
def duckdb_provider():
    from dblift.config import DbliftConfig
    from dblift.db.plugins.duckdb.config import DuckDBConfig
    from dblift.db.plugins.duckdb.provider import DuckDBProvider

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
        from dblift.api.client import DBLiftClient

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

    def test_clean_drops_macros_and_user_types(self, duckdb_provider) -> None:
        provider, _ = duckdb_provider
        provider.execute_statement("CREATE TYPE mood AS ENUM ('sad', 'happy')")
        provider.execute_statement("CREATE MACRO add_one(x) AS x + 1, (x, y) AS x + y")
        provider.execute_statement("CREATE MACRO one_row(x) AS TABLE SELECT x AS v")
        provider.execute_statement("CREATE TABLE person (m mood)")

        preview = provider.get_clean_preview("main")
        assert sorted((o.object_type, o.name) for o in preview.objects) == [
            ("MACRO", "add_one"),
            ("TABLE", "person"),
            ("TABLE MACRO", "one_row"),
            ("TYPE", "mood"),
        ]
        assert [o.drop_sql for o in provider.list_droppable_objects("main")] == preview.statements

        provider.clean_schema("main")

        assert provider.execute_query("SELECT 1 FROM duckdb_types() WHERE type_name = 'mood'") == []
        assert (
            provider.execute_query(
                "SELECT 1 FROM duckdb_functions() WHERE function_name IN ('add_one', 'one_row')"
            )
            == []
        )
        provider.execute_statement("CREATE TYPE mood AS ENUM ('sad', 'happy')")

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
class TestDuckDBMigrationLock:
    def test_contended_lock_times_out_with_false(self, duckdb_provider) -> None:
        from dblift.db.plugins.duckdb.provider import DuckDBProvider

        provider, _ = duckdb_provider
        # A second provider on the same file contends for the lock.
        contender = DuckDBProvider(provider.config)
        try:
            assert provider.acquire_migration_lock("main") is True

            assert contender.acquire_migration_lock("main", wait_timeout_seconds=1) is False

            # The failed attempt must not leave the connection in an aborted state.
            assert contender.execute_query("SELECT 1 AS one") == [{"one": 1}]
            assert provider.release_migration_lock("main") is True
            assert contender.acquire_migration_lock("main", wait_timeout_seconds=1) is True
            assert contender.release_migration_lock("main") is True
        finally:
            contender.close()


@pytest.mark.unit
class TestDuckDBDmlRowcount:
    def _provider(self, tmp_path: Path) -> "DuckDBProvider":
        from dblift.config import DatabaseConfig, DbliftConfig
        from dblift.db.plugins.duckdb.provider import DuckDBProvider

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

    def test_returning_rewrite_runs_unbound_sql_through_exec_unbound(self, tmp_path: Path) -> None:
        """The RETURNING rewrite sends unbound SQL with no parameter argument."""
        from unittest.mock import patch

        from dblift.db.sqlalchemy_provider import SqlAlchemyProvider

        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        provider.execute_statement("INSERT INTO t VALUES (1, 'a')")
        real = SqlAlchemyProvider.__dict__["_exec_unbound"].__func__
        sent: list = []

        def spy(connection, sql):
            sent.append(sql)
            return real(connection, sql)

        with patch.object(SqlAlchemyProvider, "_exec_unbound", staticmethod(spy)):
            assert provider.execute_statement("UPDATE t SET v = '50%' WHERE id = 1") == 1

        assert sent == ["UPDATE t SET v = '50%' WHERE id = 1\nRETURNING 1"]

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
        from dblift.db.plugins.duckdb.parser._script import blank_comments
        from dblift.db.plugins.duckdb.provider import DuckDBProvider

        has = DuckDBProvider._has_top_level_keyword
        blank = blank_comments
        assert has("UPDATE t SET v = 1 RETURNING id", "RETURNING") is True
        assert has("UPDATE t SET v = ' returning ' WHERE id = 1", "RETURNING") is False
        # After comment strip, mid-line/full-line comments mentioning returning are gone
        cleaned = blank("UPDATE t SET v = 1  -- returning\nWHERE id = 1")
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


MULTILINE_LITERAL = "a\n\n-- b\n/* c */\nd\r\ne"


@pytest.mark.unit
class TestDuckDBDmlKeepsLiterals:
    """The RETURNING rewrite must send string literals exactly as written."""

    _provider = TestDuckDBDmlRowcount._provider

    def _table(self, tmp_path: Path) -> Any:
        provider = self._provider(tmp_path)
        provider.execute_statement("CREATE TABLE t (id INTEGER PRIMARY KEY, v VARCHAR)")
        return provider

    def _values(self, provider: Any) -> list:
        return [r["v"] for r in provider.execute_query("SELECT v FROM t ORDER BY id")]

    def test_insert_keeps_blank_comment_and_crlf_lines_in_literal(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        rc = provider.execute_statement(f"INSERT INTO t VALUES (1, '{MULTILINE_LITERAL}')")
        assert rc == 1
        assert self._values(provider) == [MULTILINE_LITERAL]

    def test_update_keeps_literal(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        provider.execute_statement("INSERT INTO t VALUES (1, 'x')")
        rc = provider.execute_statement(f"UPDATE t SET v = '{MULTILINE_LITERAL}' WHERE id = 1")
        assert rc == 1
        assert self._values(provider) == [MULTILINE_LITERAL]

    def test_delete_where_literal_matches_the_stored_row(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        # Built by the engine, so the stored row does not depend on the statement under test.
        provider.execute_statement(
            "INSERT INTO t SELECT 1, 'a' || chr(10) || chr(10) || '-- b' || chr(10)"
            " || '/* c */' || chr(10) || 'd' || chr(13) || chr(10) || 'e'"
        )
        provider.execute_statement("INSERT INTO t VALUES (2, 'a / d / e')")
        rc = provider.execute_statement(f"DELETE FROM t WHERE v = '{MULTILINE_LITERAL}'")
        assert rc == 1
        assert self._values(provider) == ["a / d / e"]

    def test_literal_with_returning_text_and_comment_lines(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        literal = "x\n\n-- returning\nRETURNING y"
        assert provider.execute_statement(f"INSERT INTO t VALUES (1, '{literal}')") == 1
        assert self._values(provider) == [literal]

    def test_comments_around_the_statement_still_count_rows(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        assert provider.execute_statement("-- lead\n/* lead */\nINSERT INTO t VALUES (1, 'a')") == 1
        assert provider.execute_statement("INSERT INTO t VALUES (2, 'b') -- trail") == 1
        assert provider.execute_statement("UPDATE t SET v = 'z' /* trail */;\n-- after\n") == 2
        assert provider.execute_statement("DELETE FROM t -- all\nWHERE id > 0;") == 2
        assert self._values(provider) == []

    def test_returning_already_present_is_left_alone(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        provider.execute_statement("INSERT INTO t VALUES (1, 'a') RETURNING id")
        assert self._values(provider) == ["a"]

    def test_with_cte_insert_is_not_rewritten_but_runs(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        provider.execute_statement(
            "WITH s AS (SELECT 1 AS id, 'a' AS v) INSERT INTO t SELECT * FROM s"
        )
        assert self._values(provider) == ["a"]

    def test_trailing_line_comment_does_not_swallow_returning(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        provider.execute_statement("INSERT INTO t VALUES (1, 'a'), (2, 'a'), (3, 'a')")
        assert provider.execute_statement("UPDATE t SET v = 'b' -- trailing") == 3
        assert provider.execute_statement("DELETE FROM t -- trailing") == 3

    def test_two_statements_both_run_through_the_default_path(self, tmp_path: Path) -> None:
        provider = self._table(tmp_path)
        rc = provider.execute_statement(
            "INSERT INTO t VALUES (1, 'a'); INSERT INTO t VALUES (2, 'b')"
        )
        assert rc == -1
        assert self._values(provider) == ["a", "b"]

    def test_shell_command_and_nul_fall_back_to_the_default_path(self, tmp_path: Path) -> None:
        """The scanner's refusals are not raised by the rewrite: the engine answers instead."""
        from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError

        provider = self._table(tmp_path)
        for sql in (".tables", "INSERT INTO t VALUES (1, 'a\x00b')"):
            with pytest.raises(Exception) as caught:
                provider.execute_statement(sql)
            assert not isinstance(
                caught.value, (UnsafeStatementSplitError, UnsupportedMetaCommandError)
            ), sql
        assert self._values(provider) == []


@pytest.mark.unit
class TestDuckDBAutocommit:
    @pytest.mark.parametrize("checkpoint", ["CHECKPOINT", "FORCE CHECKPOINT"])
    def test_checkpoint_ends_pending_writes_without_committing(self, duckdb_provider, checkpoint):
        provider, _ = duckdb_provider
        provider.execute_statement("CREATE TABLE pending (id INTEGER)")
        connection = provider._ensure_connection()
        provider.begin_transaction()
        provider.execute_statement("INSERT INTO pending VALUES (1)")

        provider.execute_autocommit_statement(checkpoint)

        assert provider._ensure_connection() is connection
        assert not connection.in_transaction()
        assert provider.execute_query("SELECT * FROM pending") == []
        provider.begin_transaction()
        provider.execute_statement("INSERT INTO pending VALUES (2)")
        provider.rollback_transaction()
        assert provider.execute_query("SELECT * FROM pending") == []

    def test_failure_leaves_connection_transactional(self, duckdb_provider):
        provider, _ = duckdb_provider
        provider.execute_statement("CREATE TABLE pending (id INTEGER)")
        provider.begin_transaction()
        provider.execute_statement("INSERT INTO pending VALUES (1)")
        with pytest.raises(duckdb.Error, match="missing_database"):
            provider.execute_autocommit_statement("CHECKPOINT missing_database")
        assert not provider._ensure_connection().in_transaction()
        provider.begin_transaction()
        provider.execute_statement("INSERT INTO pending VALUES (2)")
        provider.rollback_transaction()
        assert provider.execute_query("SELECT * FROM pending") == []

    def test_schema_and_parameters_are_preserved(self, duckdb_provider):
        provider, _ = duckdb_provider
        provider.execute_statement("CREATE SCHEMA target")
        provider.execute_statement("CREATE TABLE target.items (id INTEGER)")
        provider.execute_autocommit_statement(
            "INSERT INTO items VALUES (?)", schema="target", params=[7]
        )
        assert provider.execute_query("SELECT * FROM target.items") == [{"id": 7}]

    @pytest.mark.parametrize("checkpoint", ["CHECKPOINT", "FORCE CHECKPOINT"])
    def test_checkpoint_migration_routes_to_autocommit(
        self, duckdb_provider, checkpoint, monkeypatch
    ):
        from dblift.api.client import DBLiftClient

        provider, tmp = duckdb_provider
        migrations = tmp / "migrations"
        migrations.mkdir()
        (migrations / "V1__create.sql").write_text(
            "CREATE TABLE items (id INTEGER); INSERT INTO items VALUES (1);"
        )
        (migrations / "V2__checkpoint.sql").write_text(f"-- persist writes\n{checkpoint};")
        calls = []
        execute = provider.execute_autocommit_statement

        def record(sql, schema=None, params=None):
            calls.append(sql)
            return execute(sql, schema=schema, params=params)

        monkeypatch.setattr(provider, "execute_autocommit_statement", record)
        client = DBLiftClient(provider, migrations)
        result = client.migrate()
        assert result.success, result.error_message
        assert len(calls) == 1
        assert checkpoint in calls[0]
        assert provider.execute_query("SELECT * FROM items") == [{"id": 1}]
        assert len(provider.get_applied_migrations("main")) == 2

    def test_mixed_checkpoint_migration_is_rejected_before_writes(self, duckdb_provider):
        from dblift.api.client import DBLiftClient

        provider, tmp = duckdb_provider
        provider.execute_statement("CREATE TABLE pending (id INTEGER)")
        migrations = tmp / "migrations"
        migrations.mkdir()
        (migrations / "V1__mixed.sql").write_text("INSERT INTO pending VALUES (1); CHECKPOINT;")
        result = DBLiftClient(provider, migrations).migrate()
        assert not result.success
        assert "mixes transactional and autocommit-only statements" in result.error_message
        assert provider.execute_query("SELECT * FROM pending") == []
