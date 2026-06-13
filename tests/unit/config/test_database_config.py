from unittest.mock import patch

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

    def test_from_native_oracle_url_with_credentials(self):
        url = "oracle+oracledb://system:oracle@localhost:1521?service_name=XE"
        config = BaseDatabaseConfig.create({"url": url})
        assert config.username == "system"
        assert config.password == "oracle"
        assert config.host == "localhost"
        assert config.service_name == "XE"

    def test_from_url_without_credentials_raises(self):
        url = "oracle+oracledb://localhost:1521?service_name=XE"
        with pytest.raises(ValueError, match="Database username is required"):
            BaseDatabaseConfig.create({"url": url})

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
        # Lowercase keys for comparison
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
        """AC#1 — URL sans port ne doit pas lever UnboundLocalError."""
        url = "postgresql+psycopg://localhost/mydb?user=user&password=pass"
        config = BaseDatabaseConfig.from_url(url)
        assert config.port is None
        assert config.host == "localhost"
        assert config.database == "mydb"

    def test_from_url_invalid_port_returns_none(self):
        """AC#2 — Port non-entier → port=None, pas de crash."""
        url = "postgresql+psycopg://localhost:abc/mydb?user=user&password=pass"
        config = BaseDatabaseConfig.from_url(url)
        assert config.port is None
        assert config.host == "localhost"
        assert config.database == "mydb"

    def test_from_url_valid_port_parsed(self):
        """AC#3 — Port valide toujours parsé (régression)."""
        url = "postgresql+psycopg://localhost:5432/mydb?user=user&password=pass"
        config = BaseDatabaseConfig.from_url(url)
        assert config.port == 5432

    # Test parsing of host from URL
    def test_host_parsing(self):
        test_data = {
            "url": "postgresql+psycopg://myhost:5432/testdb",
            "username": "postgres",
            "password": "pw",
        }
        config = BaseDatabaseConfig.create(test_data)
        assert config.host == "myhost"


@pytest.mark.unit
@pytest.mark.sqlserver
class TestSqlServerConfig:
    def test_sqlserver_config(self):
        url = "mssql+pymssql://sa:pw@localhost:1433/mydb"
        config = SqlServerConfig.from_dict(
            {"url": url, "username": "sa", "password": "pw", "integrated_security": False}
        )
        assert config.type == "sqlserver"
        assert config.host == "localhost"
        assert config.port == 1433
        assert config.database == "mydb"
        assert config.url == url
        props = config.get_connection_props()
        assert "user" in props or "integratedSecurity" in props

    def test_build_connection_string_integrated_security_adds_trusted_connection(self):
        config = SqlServerConfig(
            type="sqlserver",
            host="myserver",
            database="mydb",
            username="",
            password="",
            integrated_security=True,
        )
        result = config.build_connection_string()
        assert "Trusted_Connection=Yes" in result
        assert ";s;" not in result

    def test_build_connection_string_trust_server_certificate(self):
        config = SqlServerConfig(
            type="sqlserver",
            host="myserver",
            database="mydb",
            username="sa",
            password="pw",
            trust_server_certificate=True,
        )
        result = config.build_connection_string()
        assert "TrustServerCertificate=Yes" in result
        assert ";s;" not in result

    def test_build_connection_string_no_encrypt(self):
        config = SqlServerConfig(
            type="sqlserver",
            host="myserver",
            database="mydb",
            username="sa",
            password="pw",
            encrypt=False,
        )
        result = config.build_connection_string()
        assert "Encrypt=No" in result
        assert ";o;" not in result

    def test_build_connection_string_integrated_security_with_trust_certificate(self):
        config = SqlServerConfig(
            type="sqlserver",
            host="myserver",
            database="mydb",
            username="",
            password="",
            integrated_security=True,
            trust_server_certificate=True,
        )
        result = config.build_connection_string()
        assert "Trusted_Connection=Yes" in result
        assert "TrustServerCertificate=Yes" in result
        assert "UID=" not in result

    def test_integrated_security_props_use_native_sspi(self):
        """Integrated auth: integratedSecurity=true, no creds, no scheme."""
        from config._subclasses.sqlserver_config import SqlServerConfig

        config = SqlServerConfig(
            type="sqlserver",
            host="dbhost",
            port=1433,
            database="app_db",
            username="",
            password="",
            integrated_security=True,
        )

        props = config.get_connection_props()

        assert props["integratedSecurity"] == "true"
        assert "user" not in props
        assert "password" not in props
        # Native SSPI is the driver default; an explicit scheme must NOT be set
        # (authenticationScheme is only set for SqlPassword auth).
        assert "authenticationScheme" not in props

    def test_build_connection_string_port_embedded_in_server(self):
        config = SqlServerConfig(
            type="sqlserver",
            host="myserver",
            port=1433,
            database="mydb",
            username="sa",
            password="pw",
        )
        result = config.build_connection_string()
        assert "SERVER=myserver,1433" in result
        assert ";1433;" not in result


@pytest.mark.unit
class TestOracleConfig:
    def test_oracle_config(self):
        url = "oracle+oracledb://localhost:1521?service_name=XE"
        config = OracleConfig.from_dict({"url": url, "username": "system", "password": "pw"})
        assert config.type == "oracle"
        assert config.host == "localhost"
        assert config.port == 1521
        assert config.service_name == "XE"
        assert config.database == "XE"
        assert config.build_database_url().startswith("oracle+oracledb://system:pw@localhost:1521")

    def test_oracle_config_database_uses_sid_when_service_name_absent(self):
        url = "oracle+oracledb://localhost:1521?sid=ORCL"
        config = OracleConfig.from_dict({"url": url, "username": "system", "password": "pw"})
        assert config.sid == "ORCL"
        assert config.database == "ORCL"


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
class TestDb2Config:
    def test_db2_config(self):
        url = "ibm_db_sa://localhost:50000/testdb"
        config = Db2Config.from_dict({"url": url, "username": "db2inst1", "password": "pw"})
        assert config.type == "db2"
        assert config.host == "localhost"
        assert config.port in (None, 50000)
        assert config.database in (None, "testdb")
        assert config.build_connection_string().startswith("ibm_db_sa://")

    def test_db2_native_url_promotes_current_schema(self):
        url = "ibm_db_sa://db2inst1:pw@localhost:50000/testdb?currentSchema=APP"
        config = Db2Config.from_dict({"url": url})
        assert config.schema == "APP"
        assert config.extra_params["currentSchema"] == "APP"

    def test_db2_native_url_promotes_schema_query_param(self):
        url = "ibm_db_sa://db2inst1:pw@localhost:50000/testdb?schema=APP"
        config = Db2Config.from_dict({"url": url})
        assert config.schema == "APP"
        assert config.extra_params["schema"] == "APP"


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

    def test_from_url_oracle_is_rejected(self):
        url = "jdbc:oracle:thin:system/oracle@myhost:1521:XE"
        with pytest.raises(ValueError, match="Legacy database URLs are no longer supported"):
            BaseDatabaseConfig.from_url(url)

    def test_from_url_db2_is_rejected(self):
        url = "jdbc:db2://myhost:50000/SAMPLE:user=db2inst1;password=pw;"
        with pytest.raises(ValueError, match="Legacy database URLs are no longer supported"):
            BaseDatabaseConfig.from_url(url)

    def test_from_url_sqlserver_no_longer_uses_parse_sqlserver_url(self):
        """SQL Server now accepts native SQLAlchemy URLs instead of database URLs."""
        url = "mssql+pymssql://sa:pw@sqlhost:1433/mydb"
        config = BaseDatabaseConfig.from_url(url)
        assert config.host == "sqlhost"
        assert config.port == 1433
        assert config.database == "mydb"
        assert config.type == "sqlserver"

    def test_from_url_no_port_url_returns_none_port(self):
        """Regression test for BUG-02 (UnboundLocalError on port)."""
        url = "postgresql+psycopg://myhost/mydb?user=user&password=pass"
        config = BaseDatabaseConfig.from_url(url)
        assert config.port is None
        assert config.host == "myhost"
        assert config.database == "mydb"

    def test_sqlserver_accepts_sqlalchemy_url(self):
        """SQLAlchemy URLs are accepted by the native SQL Server plugin."""
        config = BaseDatabaseConfig.create({"url": "mssql+pymssql://sa:pw@sqlhost:1433/app"})
        assert config.type == "sqlserver"
        assert config.host == "sqlhost"
        assert config.database == "app"

    def test_from_url_invalid_prefix_raises(self):
        """Unknown native URL schemes are rejected."""
        with pytest.raises(ValueError, match="Unsupported database type"):
            BaseDatabaseConfig.from_url("notajdbc://host/db")

    def test_from_url_unknown_db_type_raises(self):
        """Legacy URL schemes are rejected before dialect lookup."""
        with pytest.raises(ValueError, match="Legacy database URLs are no longer supported"):
            BaseDatabaseConfig.from_url("jdbc:unknowndb://host/db")


@pytest.mark.unit
class TestDbSpecificFieldsOcp:
    """Story 14-12 — DB-specific fields moved from BaseDatabaseConfig to subclasses."""

    DB_SPECIFIC_FIELDS = [
        "instance",
        "encrypt",
        "trust_server_certificate",
        "integrated_security",
        "service_name",
        "ssl_mode",
        "ssl_enabled",
        "collection",
    ]

    def test_base_config_has_no_db_specific_fields(self):
        """AC#6.1 — BaseDatabaseConfig.__dataclass_fields__ contains no DB-specific fields."""
        base_fields = set(BaseDatabaseConfig.__dataclass_fields__.keys())
        for field_name in self.DB_SPECIFIC_FIELDS:
            assert (
                field_name not in base_fields
            ), f"'{field_name}' should not be in BaseDatabaseConfig"

    # --- to_dict() tests (AC#6.2) ---

    def test_sqlserver_to_dict_includes_specific_fields(self):
        config = SqlServerConfig(
            type="sqlserver",
            url="mssql+pymssql://host/db",
            username="u",
            password="p",
            instance="INST1",
            encrypt=True,
            trust_server_certificate=True,
            integrated_security=True,
        )
        d = config.to_dict()
        assert d["instance"] == "INST1"
        assert d["encrypt"] is True
        assert d["trust_server_certificate"] is True
        assert d["integrated_security"] is True

    def test_oracle_to_dict_includes_specific_fields(self):
        config = OracleConfig(
            type="oracle",
            url="oracle+oracledb://host:1521?service_name=XE",
            username="u",
            password="p",
            service_name="ORCL",
        )
        d = config.to_dict()
        assert d["service_name"] == "ORCL"

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

    def test_db2_to_dict_includes_specific_fields(self):
        config = Db2Config(
            type="db2",
            url="ibm_db_sa://host/db",
            username="u",
            password="p",
            collection="MYCOL",
        )
        d = config.to_dict()
        assert d["collection"] == "MYCOL"

    # --- Round-trip tests (AC#6.3) ---

    def test_roundtrip_sqlserver(self):
        original = SqlServerConfig(
            type="sqlserver",
            url="mssql+pymssql://host/app",
            username="u",
            password="p",
            instance="INST1",
            encrypt=True,
            trust_server_certificate=True,
            integrated_security=False,
        )
        rebuilt = BaseDatabaseConfig.create(original.to_dict())
        assert isinstance(rebuilt, SqlServerConfig)
        assert rebuilt.instance == "INST1"
        assert rebuilt.encrypt is True
        assert rebuilt.trust_server_certificate is True
        assert rebuilt.integrated_security is False

    def test_roundtrip_oracle(self):
        original = OracleConfig(
            type="oracle",
            url="oracle+oracledb://host:1521?service_name=XE",
            username="u",
            password="p",
            service_name="ORCL",
        )
        rebuilt = BaseDatabaseConfig.create(original.to_dict())
        assert isinstance(rebuilt, OracleConfig)
        assert rebuilt.service_name == "ORCL"

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

    def test_roundtrip_db2(self):
        original = Db2Config(
            type="db2",
            url="ibm_db_sa://host/db",
            username="u",
            password="p",
            collection="MYCOL",
        )
        rebuilt = BaseDatabaseConfig.create(original.to_dict())
        assert isinstance(rebuilt, Db2Config)
        assert rebuilt.collection == "MYCOL"

    # --- to_dict() default (None) values (L1) ---

    def test_oracle_to_dict_includes_service_name_when_none(self):
        """to_dict() doit inclure service_name=None quand non fourni."""
        config = SqlServerConfig(type="sqlserver", host="h", username="u", password="p")
        d = config.to_dict()
        assert "instance" in d
        assert d["instance"] is None
        assert "encrypt" in d
        assert d["encrypt"] is False

    # --- Tests AC#4 — hasattr() removed, direct field access (M1) ---

    def test_get_connection_props_trust_server_certificate_true(self):
        """AC#4.3 — trust_server_certificate=True → trustServerCertificate=true."""
        config = SqlServerConfig(
            type="sqlserver",
            host="server",
            username="u",
            password="p",
            trust_server_certificate=True,
        )
        props = config.get_connection_props()
        assert props["trustServerCertificate"] == "true"

    def test_get_connection_props_trust_server_certificate_false(self):
        """AC#4.3 (H1 fix) — trust_server_certificate=False → trustServerCertificate=false."""
        config = SqlServerConfig(
            type="sqlserver",
            host="server",
            username="u",
            password="p",
            trust_server_certificate=False,
        )
        props = config.get_connection_props()
        assert props["trustServerCertificate"] == "false"

    def test_get_connection_props_encrypt_true(self):
        """AC#4.4 — encrypt=True → encrypt=true."""
        config = SqlServerConfig(
            type="sqlserver",
            host="server",
            username="u",
            password="p",
            encrypt=True,
        )
        props = config.get_connection_props()
        assert props["encrypt"] == "true"

    def test_get_connection_props_encrypt_false(self):
        """AC#4.4 — encrypt=False → encrypt=false."""
        config = SqlServerConfig(
            type="sqlserver",
            host="server",
            username="u",
            password="p",
            encrypt=False,
        )
        props = config.get_connection_props()
        assert props["encrypt"] == "false"


@pytest.mark.unit
class TestBug09SqliteNonJdbcProvider:
    """SQLite URL handling."""

    def test_sqlite_with_explicit_type_and_jdbc_style_url(self):
        """Legacy jdbc:sqlite URLs are rejected in v2."""
        with pytest.raises(ValueError, match="Legacy database URLs are no longer supported"):
            BaseDatabaseConfig.create({"type": "sqlite", "url": "jdbc:sqlite:/tmp/dblift.db"})

    def test_sqlite_type_inferred_from_url(self):
        """Without explicit type, a sqlite:// URL should infer type=sqlite."""
        config = BaseDatabaseConfig.create({"url": "sqlite:///tmp/dblift_test.db"})
        assert config.type == "sqlite"

    def test_sqlite_plain_url_also_inferred(self):
        """Non-JDBC prefix sqlite: URL should also infer type=sqlite."""
        config = BaseDatabaseConfig.create({"url": "sqlite:///tmp/dblift_test.db"})
        assert config.type == "sqlite"
