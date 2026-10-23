"""Focused unit coverage for the DuckDB plugin: config, URL builder,
quirks, parser config/regex, and provider helper methods."""

from __future__ import annotations

import pytest

pytest.importorskip("duckdb", reason="duckdb driver not installed")
pytest.importorskip("duckdb_engine", reason="duckdb_engine dialect not installed")


# --- config ------------------------------------------------------------
@pytest.mark.unit
class TestDuckDBConfig:
    def test_path_from_url_file(self):
        from dblift.db.plugins.duckdb.config import DuckDBConfig

        cfg = DuckDBConfig(type="duckdb", url="duckdb:////tmp/x.duckdb")
        assert cfg.path == "/tmp/x.duckdb"
        assert cfg.schema == "main"
        assert cfg.username == "" and cfg.password == ""

    def test_path_from_url_memory(self):
        from dblift.db.plugins.duckdb.config import DuckDBConfig

        assert DuckDBConfig(type="duckdb", url="duckdb:///:memory:").path == ":memory:"

    def test_path_from_url_relative_vs_absolute(self):
        from dblift.db.plugins.duckdb.config import DuckDBConfig

        # 3-slash → relative (duckdb_engine convention); 4-slash → absolute.
        assert DuckDBConfig(type="duckdb", url="duckdb:///app.db").path == "app.db"
        assert DuckDBConfig(type="duckdb", url="duckdb:///sub/app.db").path == "sub/app.db"
        assert DuckDBConfig(type="duckdb", url="duckdb:////abs/app.db").path == "/abs/app.db"

    def test_path_from_database_field(self):
        from dblift.db.plugins.duckdb.config import DuckDBConfig

        cfg = DuckDBConfig(type="duckdb", database="/data/w.duckdb")
        assert cfg.path == "/data/w.duckdb"

    def test_missing_path_raises(self):
        from dblift.db.plugins.duckdb.config import DuckDBConfig

        with pytest.raises(ValueError, match="path is required"):
            DuckDBConfig(type="duckdb")

    def test_to_dict_and_conn_props(self):
        from dblift.db.plugins.duckdb.config import DuckDBConfig

        cfg = DuckDBConfig(type="duckdb", path="/tmp/x.duckdb")
        assert cfg.to_dict()["path"] == "/tmp/x.duckdb"
        assert cfg.get_connection_props() == {"path": "/tmp/x.duckdb"}
        assert cfg.build_connection_string() == "/tmp/x.duckdb"


# --- sqlalchemy url ----------------------------------------------------
@pytest.mark.unit
class TestSqlAlchemyUrl:
    def test_build_from_path(self):
        from dblift.db.plugins.duckdb.config import DuckDBConfig
        from dblift.db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url

        assert build_sqlalchemy_url(DuckDBConfig(type="duckdb", path="/tmp/x.duckdb")) == (
            "duckdb:////tmp/x.duckdb"
        )

    def test_build_memory(self):
        from dblift.db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url

        class _C:
            url = None
            path = ":memory:"
            database = None

        assert build_sqlalchemy_url(_C()) == "duckdb:///:memory:"

    def test_raw_url_passthrough(self):
        from dblift.db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url

        class _C:
            url = "duckdb:///abc.duckdb"

        assert build_sqlalchemy_url(_C()) == "duckdb:///abc.duckdb"

    def test_bad_url_raises(self):
        from dblift.db.plugins.duckdb.sqlalchemy_url import build_sqlalchemy_url

        class _C:
            url = "postgresql://x"

        with pytest.raises(ValueError, match="duckdb"):
            build_sqlalchemy_url(_C())


# --- quirks ------------------------------------------------------------
@pytest.mark.unit
class TestDuckDBQuirks:
    def test_type_maps(self):
        from dblift.db.plugins.duckdb.quirks import DuckDBQuirks

        q = DuckDBQuirks()
        assert q.type_equivalents()["INT8"] == "BIGINT"
        assert q.type_equivalents()["BOOL"] == "BOOLEAN"
