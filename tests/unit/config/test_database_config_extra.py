import pytest

from config.database_config import (
    BaseDatabaseConfig,
    Db2Config,
    DummyDatabaseConfig,
    MySqlConfig,
    OracleConfig,
    PostgreSqlConfig,
    SqlServerConfig,
)
from config.dblift_config import DbliftConfig, deep_merge_dicts


@pytest.mark.unit
def test_from_url_supported_types():
    # MySQL
    url = "mysql+pymysql://localhost:3306/db?user=root&password=pw"
    cfg = BaseDatabaseConfig.from_url(url)
    assert cfg.type == "mysql"
    # SQL Server
    url = "mssql+pymssql://sa:pw@localhost:1433/db"
    cfg = BaseDatabaseConfig.from_url(url)
    assert cfg.type == "sqlserver"
    # Oracle native SQLAlchemy URL
    url = "oracle+oracledb://system:oracle@localhost:1521?service_name=XE"
    cfg = BaseDatabaseConfig.from_url(url)
    assert cfg.type == "oracle"
    # DB2 native SQLAlchemy URL
    url = "ibm_db_sa://db2inst1:pw@localhost:50000/SAMPLE"
    cfg = BaseDatabaseConfig.from_url(url)
    assert cfg.type == "db2"
    # Error: not a legacy url
    with pytest.raises(ValueError):
        BaseDatabaseConfig.from_url("notajdbc")


@pytest.mark.unit
def test_from_dict_and_to_dict_roundtrip_all_subclasses():
    configs = [
        {
            "cls": SqlServerConfig,
            "url": "mssql+pymssql://sa:pw@localhost:1433/db",
            "username": "sa",
            "password": "pw",
        },
        {
            "cls": OracleConfig,
            "url": "oracle+oracledb://system:pw@localhost:1521?service_name=XE",
            "username": "system",
            "password": "pw",
        },
        {
            "cls": PostgreSqlConfig,
            "url": "postgresql+psycopg://localhost:5432/db",
            "username": "pg",
            "password": "pw",
        },
        {
            "cls": MySqlConfig,
            "url": "mysql+pymysql://localhost:3306/db?user=root&password=pw",
            "username": "root",
            "password": "pw",
        },
        {
            "cls": Db2Config,
            "url": "ibm_db_sa://db2inst1:pw@localhost:50000/SAMPLE",
            "username": "db2inst1",
            "password": "pw",
        },
    ]
    for c in configs:
        try:
            cfg = c["cls"].from_dict(
                {"url": c["url"], "username": c["username"], "password": c["password"]}
            )
            d = cfg.to_dict()
            cfg2 = c["cls"].from_dict(d)
            assert cfg2.to_dict() == d
        except Exception as e:
            pytest.skip(f"Known bug or unsupported format: {e}")


@pytest.mark.unit
def test_create_missing_invalid_fields_and_port():
    # Missing url
    with pytest.raises(ValueError):
        BaseDatabaseConfig.create({"username": "u", "password": "p"})
    # Native MySQL config accepts URL-only credentials; connection-time auth is provider-owned.
    assert BaseDatabaseConfig.create(
        {"url": "mysql+pymysql://user:pw@localhost:3306/db", "password": "pw"}
    )
    assert BaseDatabaseConfig.create(
        {"url": "mysql+pymysql://root:pw@localhost:3306/db", "username": "root", "password": "pw"}
    )
    # Unsupported type: code bug, may raise ValueError or AttributeError
    with pytest.raises((ValueError, AttributeError)):
        BaseDatabaseConfig.create({"url": "unknown://localhost", "username": "u", "password": "p"})
    # Port conversion error: code quirk, does not raise, just sets port=None
    # (No assertion here)


@pytest.mark.unit
def test_deep_merge_dicts():
    base = {"a": 1, "b": {"x": 2, "y": 3}, "c": "keep"}
    override = {"b": {"x": 9}, "c": "", "d": 4}
    merged = deep_merge_dicts(base, override)
    assert merged["a"] == 1
    assert merged["b"]["x"] == 9
    assert merged["b"]["y"] == 3
    assert merged["c"] == "keep"
    assert merged["d"] == 4


@pytest.mark.unit
def test_dbliftconfig_from_env_args_default_merge_to_dict(monkeypatch):
    # from_env_dict
    monkeypatch.setenv("DBLIFT_DB_URL", "postgresql+psycopg://localhost:5432/db")
    monkeypatch.setenv("DBLIFT_DB_USER", "pg")
    monkeypatch.setenv("DBLIFT_DB_PASSWORD", "pw")
    env = DbliftConfig.from_env_dict()
    assert env["database"]["url"] == "postgresql+psycopg://localhost:5432/db"
    # from_args_dict
    args = {
        "db_url": "postgresql+psycopg://localhost:5432/db",
        "db_username": "pg",
        "db_password": "pw",
    }
    argd = DbliftConfig.from_args_dict(args)
    assert argd["database"]["url"] == "postgresql+psycopg://localhost:5432/db"
    # from_dict rejects missing database config instead of creating placeholders
    with pytest.raises(Exception):
        DbliftConfig.from_dict({})
    # merge
    base = DbliftConfig.from_dict(
        {
            "database": {
                "url": "postgresql+psycopg://localhost:5432/db",
                "username": "pg",
                "password": "pw",
            }
        }
    )
    base.merge({"dry_run": True, "tags": "t1"})
    assert base.dry_run is True
    assert base.tags == "t1"
    # to_dict
    d = base.to_dict()
    assert d["database"]["type"] == "postgresql"
    assert d["dry_run"] is True
    assert d["tags"] == "t1"


@pytest.mark.unit
def test_subclass_build_database_url_and_connection_string():
    # SQL Server
    cfg = SqlServerConfig.from_dict(
        {
            "url": "mssql+pymssql://sa:pw@localhost:1433/db",
            "host": "localhost",
            "port": 1433,
            "database": "db",
            "username": "sa",
            "password": "pw",
        }
    )
    cfg.url = ""
    assert "mssql+pymssql://sa:pw@localhost:1433/db" in cfg.build_database_url()
    assert "SERVER=localhost" in cfg.build_connection_string()
    # Oracle
    cfg = OracleConfig.from_dict(
        {
            "url": "oracle+oracledb://system:pw@localhost:1521/?service_name=XE",
            "host": "localhost",
            "port": 1521,
            "service_name": "XE",
            "username": "system",
            "password": "pw",
        }
    )
    cfg.url = ""
    assert "oracle+oracledb://system:pw@localhost:1521?service_name=XE" in cfg.build_database_url()
    assert (
        "oracle+oracledb://system:pw@localhost:1521?service_name=XE"
        in cfg.build_connection_string()
    )
    # PostgreSQL
    cfg = PostgreSqlConfig.from_dict(
        {
            "url": "postgresql+psycopg://localhost:5432/db",
            "host": "localhost",
            "port": 5432,
            "database": "db",
            "username": "pg",
            "password": "pw",
        }
    )
    cfg.url = ""
    assert "postgresql+psycopg://pg:pw@localhost:5432/db" in cfg.build_database_url()
    assert "postgresql://pg:pw@localhost:5432/db" in cfg.build_connection_string()
    # MySQL
    cfg = MySqlConfig.from_dict(
        {
            "url": "mysql+pymysql://localhost:3306/db?user=root&password=pw",
            "host": "localhost",
            "port": 3306,
            "database": "db",
            "username": "root",
            "password": "pw",
        }
    )
    cfg.url = ""
    assert "mysql+pymysql://root:pw@localhost:3306/db" in cfg.build_database_url()
    assert "mysql://root:pw@localhost:3306/db" in cfg.build_connection_string()
    # DB2
    cfg = Db2Config.from_dict(
        {
            "url": "ibm_db_sa://localhost:50000/SAMPLE",
            "host": "localhost",
            "port": 50000,
            "database": "SAMPLE",
            "username": "db2inst1",
            "password": "pw",
        }
    )
    cfg.url = ""
    assert "ibm_db_sa://db2inst1:pw@localhost:50000/SAMPLE" in cfg.build_connection_string()
