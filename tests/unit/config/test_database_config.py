from unittest.mock import patch

import pytest

from config.database_config import (
    BaseDatabaseConfig,
    DummyDatabaseConfig,
    MySqlConfig,
    PostgreSqlConfig,
    SQLiteConfig,
)


@pytest.mark.unit
class TestBaseDatabaseConfig:
    def test_create_and_to_dict(self):
        url = "postgresql+psycopg://localhost:5432/testdb"
        config = BaseDatabaseConfig.create({"url": url, "username": "postgres", "password": "pw"})
        d = config.to_dict()
        assert d["type"] == "postgresql"
        assert d["host"] == "localhost"
        assert d["port"] == 5432
        assert d["database"] == "testdb"
        assert d["username"] == "postgres"
        assert d["password"] == "pw"

    def test_postgresql_url_search_path_sets_schema(self):
        url = "postgresql+psycopg://postgres:pw@localhost:5432/testdb?search_path=tenant_a"

        config = BaseDatabaseConfig.create({"url": url})

        assert config.schema == "tenant_a"
        assert config.extra_params["search_path"] == "tenant_a"

    def test_missing_url_raises(self):
        with pytest.raises(ValueError):
            BaseDatabaseConfig.create({"username": "postgres", "password": "pw"})

    def test_native_config_missing_connection_identifier_raises(self):
        with pytest.raises(ValueError, match="PostgreSQL connection requires"):
            BaseDatabaseConfig.create(
                {"type": "postgresql", "username": "postgres", "password": "pw"}
            )

    def test_missing_username_raises(self):
        url = "postgresql+psycopg://localhost:5432/testdb"
        with pytest.raises(ValueError, match="Database username is required"):
            BaseDatabaseConfig.create({"url": url, "password": "pw"})

    def test_missing_password_raises(self):
        url = "postgresql+psycopg://localhost:5432/testdb"
        with pytest.raises(ValueError, match="Database password is required"):
            BaseDatabaseConfig.create({"url": url, "username": "postgres"})

    def test_invalid_url_raises(self):
        with pytest.raises(ValueError):
            BaseDatabaseConfig.create({"url": "notajdbc", "username": "postgres", "password": "pw"})

    def test_extra_params_and_properties(self):
        url = "postgresql+psycopg://localhost:5432/testdb?sslmode=require&applicationName=myapp"
        config = BaseDatabaseConfig.create({"url": url, "username": "postgres", "password": "pw"})
        assert isinstance(config.extra_params, dict)
        keys = {k.lower() for k in config.extra_params.keys()}
        assert "sslmode" in keys
        assert "applicationname" in keys
        assert config.extra_params.get("sslmode") == "require"
        assert (
            config.extra_params.get("applicationName") == "myapp"
            or config.extra_params.get("applicationname") == "myapp"
        )

    def test_build_database_url(self):
        url = "postgresql+psycopg://localhost:5432/testdb"
        config = BaseDatabaseConfig.create({"url": url, "username": "postgres", "password": "pw"})
        built = config.build_database_url()
        assert built.startswith("postgresql+psycopg://postgres:pw@localhost:5432/testdb")

    def test_to_dict_roundtrip(self):
        url = "postgresql+psycopg://localhost:5432/testdb"
        config = BaseDatabaseConfig.create({"url": url, "username": "postgres", "password": "pw"})
        d = config.to_dict()
        config2 = BaseDatabaseConfig.create(d)
        assert config2.to_dict() == d

    def test_from_url_no_port_returns_none(self):
        url = "postgresql+psycopg://localhost/mydb?user=user&password=pass"
        config = BaseDatabaseConfig.from_url(url)
        assert config.port is None
        assert config.host == "localhost"
        assert config.database == "mydb"

    def test_from_url_invalid_port_returns_none(self):
        url = "postgresql+psycopg://localhost:abc/mydb?user=user&password=pass"
        config = BaseDatabaseConfig.from_url(url)
        assert config.port is None
        assert config.host == "localhost"
        assert config.database == "mydb"

    def test_from_url_valid_port_parsed(self):
        url = "postgresql+psycopg://localhost:5432/mydb?user=user&password=pass"
        config = BaseDatabaseConfig.from_url(url)
        assert config.port == 5432

    def test_host_parsing(self):
        test_data = {
            "url": "postgresql+psycopg://myhost:5432/testdb",
            "username": "postgres",
            "password": "pw",
        }
        config = BaseDatabaseConfig.create(test_data)
        assert config.host == "myhost"


@pytest.mark.unit
class TestPostgreSqlConfig:
    def test_postgresql_config(self):
        url = "postgresql+psycopg://localhost:5432/testdb"
        config = PostgreSqlConfig.from_dict({"url": url, "username": "postgres", "password": "pw"})
        assert config.type == "postgresql"
        assert config.host == "localhost"
        assert config.port == 5432
        assert config.database == "testdb"
        assert config.build_database_url().startswith(
            "postgresql+psycopg://postgres:pw@localhost:5432/"
        )


@pytest.mark.unit
class TestMySqlConfig:
    def test_mysql_config(self):
        url = "mysql+pymysql://localhost:3306/testdb"
        config = MySqlConfig.from_dict({"url": url, "username": "root", "password": "pw"})
        assert config.type == "mysql"
        assert config.host == "localhost"
        assert config.port in (None, 3306)
        assert config.database in (None, "testdb")
        assert config.build_database_url().startswith("mysql+pymysql://root:pw@localhost")

    def test_build_connection_string_ssl_enabled_mysql(self):
        config = MySqlConfig(
            type="mysql",
            host="myserver",
            port=3306,
            database="mydb",
            username="root",
            password="pw",
            ssl_enabled=True,
        )
        result = config.build_connection_string()
        assert "useSSL=true" in result
        assert "?e" not in result and "&e" not in result


@pytest.mark.unit
class TestDummyDatabaseConfig:
    def test_dummy_config(self):
        config = DummyDatabaseConfig(
            type="dummy", url="dummy+driver://localhost", username="u", password="p"
        )
        assert config.type == "dummy"
        assert config.url == "dummy+driver://localhost"
        assert config.username == "u"
        assert config.password == "p"


@pytest.mark.unit
class TestFromUrl:
    """Tests for native URL construction."""

    def test_from_url_postgresql(self):
        url = "postgresql+psycopg://myhost:5432/mydb?user=pg&password=pw"
        config = BaseDatabaseConfig.from_url(url)
        assert config.host == "myhost"
        assert config.port == 5432
        assert config.database == "mydb"
        assert config.type == "postgresql"

    def test_from_url_mysql(self):
        url = "mysql+pymysql://myhost:3306/mydb?user=root&password=pw"
        config = BaseDatabaseConfig.from_url(url)
        assert config.host == "myhost"
        assert config.port == 3306
        assert config.database == "mydb"
        assert config.type == "mysql"

    def test_from_url_oracle_jdbc_is_rejected(self):
        url = "jdbc:oracle:thin:system/oracle@myhost:1521:XE"
        with pytest.raises(ValueError, match="Legacy database URLs are no longer supported"):
            BaseDatabaseConfig.from_url(url)

    def test_from_url_db2_jdbc_is_rejected(self):
        url = "jdbc:db2://myhost:50000/SAMPLE:user=db2inst1;password=pw;"
        with pytest.raises(ValueError, match="Legacy database URLs are no longer supported"):
            BaseDatabaseConfig.from_url(url)

    def test_from_url_no_port_url_returns_none_port(self):
        url = "postgresql+psycopg://myhost/mydb?user=user&password=pass"
        config = BaseDatabaseConfig.from_url(url)
        assert config.port is None
        assert config.host == "myhost"
        assert config.database == "mydb"

    def test_from_url_invalid_prefix_raises(self):
        with pytest.raises(ValueError, match="Unsupported database type"):
            BaseDatabaseConfig.from_url("notajdbc://host/db")

    def test_from_url_unknown_db_type_raises(self):
        with pytest.raises(ValueError, match="Legacy database URLs are no longer supported"):
            BaseDatabaseConfig.from_url("jdbc:unknowndb://host/db")


@pytest.mark.unit
class TestDbSpecificFieldsOcp:
    """Story 14-12 — DB-specific fields moved from BaseDatabaseConfig to subclasses."""

    OSS_SPECIFIC_FIELDS = [
        "ssl_mode",
        "ssl_enabled",
    ]

    def test_base_config_has_no_db_specific_fields(self):
        db_specific_fields = [
            "instance",
            "encrypt",
            "trust_server_certificate",
            "integrated_security",
            "service_name",
            "collection",
        ]
        base_fields = set(BaseDatabaseConfig.__dataclass_fields__.keys())
        for field_name in db_specific_fields:
            assert (
                field_name not in base_fields
            ), f"'{field_name}' should not be in BaseDatabaseConfig"

    def test_postgresql_to_dict_includes_specific_fields(self):
        config = PostgreSqlConfig(
            type="postgresql",
            url="postgresql+psycopg://host/db",
            username="u",
            password="p",
            ssl_mode="require",
        )
        d = config.to_dict()
        assert d["ssl_mode"] == "require"

    def test_mysql_to_dict_includes_specific_fields(self):
        config = MySqlConfig(
            type="mysql",
            url="mysql+pymysql://host/db",
            username="u",
            password="p",
            ssl_enabled=True,
        )
        d = config.to_dict()
        assert d["ssl_enabled"] is True

    def test_roundtrip_postgresql(self):
        original = PostgreSqlConfig(
            type="postgresql",
            url="postgresql+psycopg://host/db",
            username="u",
            password="p",
            ssl_mode="verify-full",
        )
        rebuilt = BaseDatabaseConfig.create(original.to_dict())
        assert isinstance(rebuilt, PostgreSqlConfig)
        assert rebuilt.ssl_mode == "verify-full"

    def test_roundtrip_mysql(self):
        original = MySqlConfig(
            type="mysql",
            url="mysql+pymysql://host/db",
            username="u",
            password="p",
            ssl_enabled=True,
        )
        rebuilt = BaseDatabaseConfig.create(original.to_dict())
        assert isinstance(rebuilt, MySqlConfig)
        assert rebuilt.ssl_enabled is True


@pytest.mark.unit
class TestBug09SqliteNonJdbcProvider:
    """SQLite URL handling."""

    def test_sqlite_with_explicit_type_and_jdbc_style_url(self):
        with pytest.raises(ValueError, match="Legacy database URLs are no longer supported"):
            BaseDatabaseConfig.create({"type": "sqlite", "url": "jdbc:sqlite:/tmp/dblift.db"})

    def test_sqlite_type_inferred_from_url(self):
        config = BaseDatabaseConfig.create({"url": "sqlite:///tmp/dblift_test.db"})
        assert config.type == "sqlite"

    def test_sqlite_plain_url_also_inferred(self):
        config = BaseDatabaseConfig.create({"url": "sqlite:///tmp/dblift_test.db"})
        assert config.type == "sqlite"
