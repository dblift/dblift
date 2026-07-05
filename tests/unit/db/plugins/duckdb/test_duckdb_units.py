"""Focused unit coverage for the DuckDB plugin: config, URL builder,
quirks, parser config/regex, and provider helper methods."""

from __future__ import annotations

import tempfile
from pathlib import Path

import pytest

pytest.importorskip("duckdb", reason="duckdb driver not installed")
pytest.importorskip("duckdb_engine", reason="duckdb_engine dialect not installed")


# --- config ------------------------------------------------------------
@pytest.mark.unit
class TestDuckDBConfig:
    def test_path_from_url_file(self):
        from db.plugins.duckdb.config import DuckDBConfig

        cfg = DuckDBConfig(type="duckdb", url="duckdb:////tmp/x.duckdb")
        assert cfg.path == "/tmp/x.duckdb"
        assert cfg.schema == "main"
        assert cfg.username == "" and cfg.password == ""

    def test_path_from_url_memory(self):
        from db.plugins.duckdb.config import DuckDBConfig

        assert DuckDBConfig(type="duckdb", url="duckdb:///:memory:").path == ":memory:"

    def test_path_from_url_relative_vs_absolute(self):
        from db.plugins.duckdb.config import DuckDBConfig

        # 3-slash → relative (duckdb_engine convention); 4-slash → absolute.
        assert DuckDBConfig(type="duckdb", url="duckdb:///app.db").path == "app.db"
        assert DuckDBConfig(type="duckdb", url="duckdb:///sub/app.db").path == "sub/app.db"
        assert DuckDBConfig(type="duckdb", url="duckdb:////abs/app.db").path == "/abs/app.db"

    def test_path_from_database_field(self):
        from db.plugins.duckdb.config import DuckDBConfig

        cfg = DuckDBConfig(type="duckdb", database="/data/w.duckdb")
        assert cfg.path == "/data/w.duckdb"

    def test_missing_path_raises(self):
        from db.plugins.duckdb.config import DuckDBConfig

        with pytest.raises(ValueError, match="path is required"):
            DuckDBConfig(type="duckdb")

    def test_to_dict_and_conn_props(self):
        from db.plugins.duckdb.config import DuckDBConfig

        cfg = DuckDBConfig(type="duckdb", path="/tmp/x.duckdb")
        assert cfg.to_dict()["path"] == "/tmp/x.duckdb"
        assert cfg.get_connection_props() == {"path": "/tmp/x.duckdb"}
        assert cfg.build_connection_string() == "/tmp/x.duckdb"


# --- sqlalchemy url ----------------------------------------------------
@pytest.mark.unit
class TestSqlAlchemyUrl:
    def test_build_from_path(self):
        from db.plugins.duckdb.config import DuckDBConfig
        from db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url

        assert build_sqlalchemy_url(DuckDBConfig(type="duckdb", path="/tmp/x.duckdb")) == (
            "duckdb:////tmp/x.duckdb"
        )

    def test_build_memory(self):
        from db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url

        class _C:
            url = None
            path = ":memory:"
            database = None

        assert build_sqlalchemy_url(_C()) == "duckdb:///:memory:"

    def test_raw_url_passthrough(self):
        from db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url

        class _C:
            url = "duckdb:///abc.duckdb"

        assert build_sqlalchemy_url(_C()) == "duckdb:///abc.duckdb"

    def test_bad_url_raises(self):
        from db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url

        class _C:
            url = "postgresql://x"

        with pytest.raises(ValueError, match="duckdb"):
            build_sqlalchemy_url(_C())


# --- quirks ------------------------------------------------------------
@pytest.mark.unit
class TestDuckDBQuirks:
    def test_type_maps(self):
        from db.plugins.duckdb.quirks import DuckDBQuirks

        q = DuckDBQuirks()
        assert q.type_equivalents()["INT8"] == "BIGINT"
        assert q.type_equivalents()["BOOL"] == "BOOLEAN"
        assert q.type_preferences()["VARCHAR"] == "VARCHAR"

    def test_parser_class_dispatch(self):
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser
        from db.plugins.duckdb.quirks import DuckDBQuirks

        q = DuckDBQuirks()
        assert q.parser_class("regex") is DuckDBRegexParser
        assert q.parser_class("hybrid").__name__ == "HybridParser"
        assert q.parser_class("sqlglot").__name__ == "SqlGlotParser"
        assert q.parser_class("other") is None


# --- parser config -----------------------------------------------------
@pytest.mark.unit
class TestParserConfig:
    def test_classification_and_getters(self):
        from db.plugins.duckdb.parser.parser_config import DuckDBParserConfig

        cfg = DuckDBParserConfig()
        assert cfg.is_ddl_statement("CREATE SEQUENCE s START 1")
        assert cfg.is_dml_statement("INSERT INTO t VALUES (1)")
        assert cfg.is_query_statement("SELECT 1")
        assert not cfg.is_ddl_statement("")
        assert cfg.get_batch_separator() == ";"
        assert cfg.supports_block_comments() and cfg.supports_line_comments()
        assert cfg.get_block_keywords_for_splitting() == set()
        assert "CREATE" in cfg.get_ddl_keywords()
        assert "INSERT" in cfg.get_dml_keywords()
        assert "SELECT" in cfg.get_query_keywords()
        assert "COMMIT" in cfg.get_transaction_keywords()

    def test_identifier_normalization_and_properties(self):
        from db.plugins.duckdb.parser.parser_config import DuckDBParserConfig

        cfg = DuckDBParserConfig()
        assert cfg.normalize_identifier('"Mixed"') == "Mixed"
        assert cfg.normalize_identifier("plain") == "plain"
        assert cfg.normalize_identifier("") == ""
        assert cfg.name == "duckdb"
        assert cfg.batch_separators and cfg.quoted_identifiers and cfg.comment_patterns
        assert cfg.block_keywords and cfg.ddl_patterns and cfg.dml_patterns
        assert cfg.query_patterns and cfg.object_patterns
        assert cfg.get_identifier_pattern().match("foo")
        assert cfg.get_qualified_identifier_pattern().match("s.foo")
        assert cfg.get_string_literal_pattern().match("'x'")
        assert cfg.get_comment_pattern().search("-- c")
        assert cfg.get_statement_separator_pattern().search(";")


# --- regex parser ------------------------------------------------------
@pytest.mark.unit
class TestRegexParser:
    def test_classify_variants(self):
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        p = DuckDBRegexParser()
        assert p.classify_statement("INSERT INTO t VALUES (1)") == "DML"
        assert p.classify_statement("SELECT 1") == "QUERY"
        assert p.classify_statement("BEGIN") == "TCL"
        assert p.classify_statement("FLOOMP") == "UNKNOWN"
        assert p.classify_statement("") == "UNKNOWN"

    def test_split_empty_and_block_comment(self):
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        p = DuckDBRegexParser()
        assert p.split_statements("") == []
        stmts = p.split_statements("/* c; */ SELECT 1; SELECT 2;")
        assert len(stmts) == 2

    def test_split_respects_quoted_identifiers(self):
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        p = DuckDBRegexParser()
        # ';' and '--' inside a double-quoted identifier are literal.
        stmts = p.split_statements('CREATE TABLE "weird;name" (a INT); SELECT 1;')
        assert len(stmts) == 2
        assert '"weird;name"' in stmts[0]
        stmts2 = p.split_statements('CREATE TABLE "a--b" (x INT);\nSELECT 2;')
        assert len(stmts2) == 2

    def test_extract_variants(self):
        from db.plugins.duckdb.parser.duckdb_regex_parser import DuckDBRegexParser

        p = DuckDBRegexParser()
        assert p.extract_objects("") == []
        assert p.extract_objects("CREATE SEQUENCE s")[0].object_type.value == "SEQUENCE"
        assert p.extract_objects("CREATE VIEW v AS SELECT 1")[0].name == "v"


# --- provider helper methods ------------------------------------------
@pytest.fixture()
def provider():
    from config import DbliftConfig
    from db.plugins.duckdb.config import DuckDBConfig
    from db.plugins.duckdb.provider import DuckDBProvider

    tmp = Path(tempfile.mkdtemp())
    p = DuckDBProvider(
        DbliftConfig(
            database=DuckDBConfig(type="duckdb", path=str(tmp / "p.duckdb"), schema="main")
        )
    )
    p.create_connection()
    yield p
    p.close()


@pytest.mark.unit
class TestProviderHelpers:
    def test_version_schema_transactions(self, provider):
        assert "duck" in provider.get_database_version().lower() or provider.get_database_version()
        provider.create_schema_if_not_exists("main")  # idempotent, exists
        provider.create_schema_if_not_exists("extra")
        provider.set_current_schema("main")
        provider.begin_transaction()
        provider.execute_statement("CREATE TABLE t (a INTEGER)")
        provider.commit_transaction()
        assert provider.table_exists("main", "t")
        provider.begin_transaction()
        provider.execute_statement("CREATE TABLE t2 (a INTEGER)")
        provider.rollback_transaction()
        assert not provider.table_exists("main", "t2")

    def test_lock_acquire_release(self, provider):
        assert provider.acquire_migration_lock("main") is True
        assert provider.release_migration_lock("main") is True

    def test_record_undo_and_repair(self, provider):
        provider.record_migration(
            "main",
            {
                "version": "1",
                "description": "d",
                "script": "V1.sql",
                "checksum": "abc",
                "execution_time": 1,
            },
        )
        assert provider.record_undo("main", "1", script_name="UNDO_1.sql") is True
        assert provider.repair_migration_history("main", "V1.sql", "def") is True
        assert (
            provider.repair_migration_history("main", "missing.sql", "x", table_name="nope")
            is False
        )

    def test_get_schema_qualified_name(self, provider):
        assert provider.get_schema_qualified_name("main", "t") == '"main"."t"'
