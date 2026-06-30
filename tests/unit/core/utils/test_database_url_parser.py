"""Unit tests for core.utils.database_url_parser module."""

import pytest

from core.utils.database_url_parser import DatabaseUrlParser


@pytest.mark.unit
class TestDatabaseUrlParser:
    """Test DatabaseUrlParser class."""

    def test_parse_username_none_url(self):
        """Test parsing username from None URL."""
        result = DatabaseUrlParser.parse_username(None)
        assert result is None

    def test_parse_username_empty_url(self):
        """Test parsing username from empty URL."""
        result = DatabaseUrlParser.parse_username("")
        assert result is None

    def test_parse_username_url_parameter_user(self):
        """Test parsing username from URL parameter 'user'."""
        url = "postgresql+psycopg://host:5432/db?user=myuser"
        result = DatabaseUrlParser.parse_username(url)
        assert result == "myuser"

    def test_parse_username_url_parameter_username(self):
        """Test parsing username from URL parameter 'username'."""
        url = "postgresql+psycopg://host:5432/db?username=myuser"
        result = DatabaseUrlParser.parse_username(url)
        assert result == "myuser"

    def test_parse_username_url_parameter_with_ampersand(self):
        """Test parsing username from URL parameter with ampersand."""
        url = "postgresql+psycopg://host:5432/db?param=value&user=myuser"
        result = DatabaseUrlParser.parse_username(url)
        assert result == "myuser"

    def test_parse_username_url_parameter_url_encoded(self):
        """Test parsing URL-encoded username."""
        url = "postgresql+psycopg://host:5432/db?user=my%20user"
        result = DatabaseUrlParser.parse_username(url)
        assert result == "my user"

    def test_parse_username_oracle_thin_format(self):
        """Test parsing username from Oracle SQLAlchemy URL format."""
        url = "oracle+oracledb://myuser:mypass@host:1521/?service_name=db"
        result = DatabaseUrlParser.parse_username(url)
        assert result == "myuser"

    def test_parse_username_oracle_thin_url_encoded(self):
        """Test parsing URL-encoded username from Oracle SQLAlchemy URL format."""
        url = "oracle+oracledb://my%20user:mypass@host:1521/?service_name=db"
        result = DatabaseUrlParser.parse_username(url)
        assert result == "my user"

    def test_parse_username_rejects_legacy_database_url(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;User ID=myuser"
        result = DatabaseUrlParser.parse_username(url)
        assert result is None

    def test_parse_username_rejects_legacy_database_url_case_insensitive(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;user id=myuser"
        result = DatabaseUrlParser.parse_username(url)
        assert result is None

    def test_parse_username_not_found(self):
        """Test parsing username when not found."""
        url = "postgresql+psycopg://host:5432/db"
        result = DatabaseUrlParser.parse_username(url)
        assert result is None

    def test_parse_password_none_url(self):
        """Test parsing password from None URL."""
        result = DatabaseUrlParser.parse_password(None)
        assert result is None

    def test_parse_password_empty_url(self):
        """Test parsing password from empty URL."""
        result = DatabaseUrlParser.parse_password("")
        assert result is None

    def test_parse_password_url_parameter_password(self):
        """Test parsing password from URL parameter 'password'."""
        url = "postgresql+psycopg://host:5432/db?password=mypass"
        result = DatabaseUrlParser.parse_password(url)
        assert result == "mypass"

    def test_parse_password_url_parameter_pwd(self):
        """Test parsing password from URL parameter 'pwd'."""
        url = "postgresql+psycopg://host:5432/db?pwd=mypass"
        result = DatabaseUrlParser.parse_password(url)
        assert result == "mypass"

    def test_parse_password_url_parameter_url_encoded(self):
        """Test parsing URL-encoded password."""
        url = "postgresql+psycopg://host:5432/db?password=my%20pass"
        result = DatabaseUrlParser.parse_password(url)
        assert result == "my pass"

    def test_parse_password_oracle_thin_format(self):
        """Test parsing password from Oracle SQLAlchemy URL format."""
        url = "oracle+oracledb://myuser:mypass@host:1521/?service_name=db"
        result = DatabaseUrlParser.parse_password(url)
        assert result == "mypass"

    def test_parse_password_oracle_thin_url_encoded(self):
        """Test parsing URL-encoded password from Oracle SQLAlchemy URL format."""
        url = "oracle+oracledb://myuser:my%20pass@host:1521/?service_name=db"
        result = DatabaseUrlParser.parse_password(url)
        assert result == "my pass"

    def test_parse_password_rejects_legacy_database_url(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;Password=mypass"
        result = DatabaseUrlParser.parse_password(url)
        assert result is None

    def test_parse_password_rejects_legacy_database_url_case_insensitive(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;password=mypass"
        result = DatabaseUrlParser.parse_password(url)
        assert result is None

    def test_parse_password_rejects_legacy_database_url_with_semicolon(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;Password=mypass;Other=value"
        result = DatabaseUrlParser.parse_password(url)
        assert result is None

    def test_parse_password_rejects_legacy_database_url_uppercase_only(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;Password=testpass123"
        result = DatabaseUrlParser.parse_password(url)
        assert result is None

    def test_parse_password_not_found(self):
        """Test parsing password when not found."""
        url = "postgresql+psycopg://host:5432/db"
        result = DatabaseUrlParser.parse_password(url)
        assert result is None

    def test_parse_database_name_none_url(self):
        """Test parsing database name from None URL."""
        result = DatabaseUrlParser.parse_database_name(None)
        assert result is None

    def test_parse_database_name_empty_url(self):
        """Test parsing database name from empty URL."""
        result = DatabaseUrlParser.parse_database_name("")
        assert result is None

    def test_parse_database_name_rejects_legacy_database_url(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;databaseName=mydb"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result is None

    def test_parse_database_name_rejects_legacy_database_url_case_insensitive(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;databasename=mydb"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result is None

    def test_parse_database_name_rejects_legacy_database_url_url_encoded(self):
        """Legacy legacy URLs are not parsed for compatibility."""
        url = "jdbc:sqlserver://host:1433;databaseName=my%20db"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result is None

    def test_parse_database_name_postgresql(self):
        """Test parsing database name from PostgreSQL URL."""
        url = "postgresql+psycopg://host:5432/mydb"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "mydb"

    def test_parse_database_name_postgresql_with_params(self):
        """Test parsing database name from PostgreSQL URL with parameters."""
        url = "postgresql+psycopg://host:5432/mydb?param=value"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "mydb"

    def test_parse_database_name_postgresql_no_database(self):
        """Test parsing database name from PostgreSQL URL without database."""
        url = "postgresql+psycopg://host:5432/"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result is None

    def test_parse_database_name_postgresql_url_encoded(self):
        """Test parsing URL-encoded database name from PostgreSQL."""
        url = "postgresql+psycopg://host:5432/my%20db"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "my db"

    def test_parse_database_name_mysql(self):
        """Test parsing database name from MySQL URL."""
        url = "mysql+pymysql://host:3306/mydb"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "mydb"

    def test_parse_database_name_mysql_with_params(self):
        """Test parsing database name from MySQL URL with parameters."""
        url = "mysql+pymysql://host:3306/mydb?param=value"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "mydb"

    def test_parse_database_name_mysql_url_encoded(self):
        """Test parsing URL-encoded database name from MySQL."""
        url = "mysql+pymysql://host:3306/my%20db"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "my db"

    def test_parse_database_name_oracle(self):
        """Test parsing database name from Oracle URL."""
        url = "oracle+oracledb://host:1521/mydb"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "mydb"

    def test_parse_database_name_oracle_with_user(self):
        """Test parsing database name from Oracle URL with user."""
        url = "oracle+oracledb://user:pass@host:1521/mydb"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "mydb"

    def test_parse_database_name_oracle_url_encoded(self):
        """Test parsing URL-encoded database name from Oracle."""
        url = "oracle+oracledb://host:1521/my%20db"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "my db"

    def test_parse_database_name_db2(self):
        """Test parsing database name from DB2 URL."""
        url = "ibm_db_sa://host:50000/mydb"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "mydb"

    def test_parse_database_name_db2_with_params(self):
        """Test parsing database name from DB2 URL with parameters."""
        url = "ibm_db_sa://host:50000/mydb?param=value"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "mydb"

    def test_parse_database_name_db2_url_encoded(self):
        """Test parsing URL-encoded database name from DB2."""
        url = "ibm_db_sa://host:50000/my%20db"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result == "my db"

    def test_parse_database_name_not_found(self):
        """Test parsing database name when not found."""
        url = "postgresql+psycopg://host:5432"
        result = DatabaseUrlParser.parse_database_name(url)
        assert result is None

    @pytest.mark.parametrize(
        "url, expected",
        [
            # Parity: schemes accepted by the previous hardcoded set.
            ("postgresql://host/db", "db"),
            ("postgres://host/db", "db"),
            ("mysql://host/db", "db"),
            ("mariadb://host/db", "db"),
            ("oracle://host/db", "db"),
            ("mssql://host/db", "db"),
            # +driver suffix is stripped before scheme resolution.
            ("postgresql+psycopg://host/db", "db"),
            # Upper-case scheme: ``.lower()`` is load-bearing — urlparse does
            # not lowercase a scheme that carries a ``+driver`` suffix.
            ("POSTGRESQL+PSYCOPG://host/db", "db"),
            ("MSSQL://host/db", "db"),
            # Improvement: native schemes the old hardcoded set omitted.
            ("sqlserver://host/db", "db"),
            ("db2://host/db", "db"),
            ("cosmosdb://host/db", "db"),
            ("sqlite:///app.db", "app.db"),
        ],
    )
    def test_parse_database_name_native_schemes(self, url, expected):
        """Native schemes derived from the plugin registry carry the DB in the path."""
        assert DatabaseUrlParser.parse_database_name(url) == expected

    @pytest.mark.parametrize(
        "url",
        [
            "jdbc:sqlserver://host:1433;databaseName=mydb",
            "weirddb://host/db",
            "https://host/db",
        ],
    )
    def test_parse_database_name_unknown_scheme_returns_none(self, url):
        """Unknown / non-native schemes return None."""
        assert DatabaseUrlParser.parse_database_name(url) is None

    @pytest.mark.parametrize(
        "url",
        [
            "postgresql://host/",
            "sqlserver://host/",
            "db2://host/",
            "cosmosdb://host/",
        ],
    )
    def test_parse_database_name_native_scheme_no_path_returns_none(self, url):
        """Native scheme with no path component returns None."""
        assert DatabaseUrlParser.parse_database_name(url) is None
