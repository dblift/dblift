import pytest

from config.dblift_config import DbliftConfig
from db.plugins.db2.config import Db2Config
from db.plugins.mysql.config import MySqlConfig
from db.plugins.oracle.config import OracleConfig
from db.plugins.postgresql.config import PostgreSqlConfig


@pytest.mark.unit
def test_build_database_url_and_connection_string_errors():
    # OracleConfig: error if service_name missing
    o = OracleConfig.from_dict(
        {
            "url": "oracle+oracledb://localhost:1521?service_name=XE",
            "username": "system",
            "password": "pw",
        }
    )
    o.service_name = None
    o.url = ""
    o.extra_params.pop("service_name", None)
    with pytest.raises(ValueError):
        o.build_connection_string()
    with pytest.raises(ValueError):
        o.build_database_url()


@pytest.mark.unit
def test_subclass_specific_fields_and_serialization():
    # PostgreSqlConfig ssl_mode
    url = "postgresql+psycopg://localhost:5432/db?user=pg&password=pw&sslmode=require"
    cfg = PostgreSqlConfig.from_dict(
        {"url": url, "username": "pg", "password": "pw", "ssl_mode": "require"}
    )
    d = cfg.to_dict()
    assert d["ssl_mode"] == "require"
    # OracleConfig service_name
    url = "oracle+oracledb://system:oracle@localhost:1521?service_name=XE"
    cfg = OracleConfig.from_dict(
        {"url": url, "username": "system", "password": "oracle", "service_name": "XE"}
    )
    d = cfg.to_dict()
    assert d["service_name"] == "XE"
    # Db2Config collection
    url = "ibm_db_sa://db2inst1:pw@localhost:50000/SAMPLE"
    cfg = Db2Config.from_dict(
        {"url": url, "username": "db2inst1", "password": "pw", "collection": "COLL"}
    )
    d = cfg.to_dict()
    assert d["collection"] == "COLL"
    # MySqlConfig ssl_enabled
    url = "mysql+pymysql://localhost:3306/db?user=root&password=pw"
    cfg = MySqlConfig.from_dict(
        {"url": url, "username": "root", "password": "pw", "ssl_enabled": True}
    )
    d = cfg.to_dict()
    assert d["ssl_enabled"] is True


@pytest.mark.unit
def test_db2_oracle_mysql_legacy_and_edge_cases():
    # DB2: missing credentials
    url = "jdbc:db2://localhost:50000/SAMPLE"
    with pytest.raises(ValueError):
        Db2Config.from_dict({"url": url})
    # Oracle: legacy regex
    url = "oracle+oracledb://legacy:legacy@localhost:1521?service_name=LEGACY"
    cfg = OracleConfig.from_dict({"url": url})
    assert cfg.username == "legacy"
    assert cfg.password == "legacy"
    # MySQL: missing db
    url = "mysql+pymysql://localhost:3306"
    cfg = MySqlConfig.from_dict({"url": url, "username": "root", "password": "pw"})
    assert cfg.database is None


@pytest.mark.unit
def test_dbliftconfig_file_loading_and_merging_errors(tmp_path):
    # Invalid YAML
    bad_file = tmp_path / "bad.yaml"
    bad_file.write_text(":not yaml:")
    with pytest.raises(Exception):
        DbliftConfig.from_file(str(bad_file))
    # File not found
    with pytest.raises(FileNotFoundError):
        DbliftConfig.from_file("/no/such/file.yaml")
    # Invalid log level
    d = {
        "database": {
            "url": "postgresql+psycopg://localhost:5432/db",
            "username": "pg",
            "password": "pw",
        },
        "logging": {"level": "BAD"},
    }
    with pytest.raises(ValueError):
        DbliftConfig.from_dict(d)
    # Merge with partial dict
    base = DbliftConfig.from_dict(
        {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/db",
                "username": "pg",
                "password": "pw",
            }
        }
    )
    base.merge({"logging": {"level": "DEBUG"}})
    assert base.logging.level == "DEBUG"
    # Round-trip with all fields
    d = {
        "database": {
            "url": "postgresql+psycopg://localhost:5432/db",
            "username": "pg",
            "password": "pw",
        },
        "migrations": {"directory": "m", "table": "t"},
        "logging": {"level": "INFO", "file": "f.log"},
        "baseline_version": "1",
        "target_version": "2",
        "dry_run": True,
        "undo": True,
        "installed_by": "me",
        "extra_params": {"foo": "bar"},
        "tags": "t1",
        "exclude_tags": "t2",
        "versions": "v1",
        "exclude_versions": "v2",
        "mark_as_executed": True,
        "placeholders": {"x": "y"},
    }
    config = DbliftConfig.from_dict(d)
    d2 = config.to_dict()
    assert d2["database"]["type"] == "postgresql"
    assert d2["migrations"]["directory"] == "./m"
    assert d2["logging"]["file"] == "./f.log"
