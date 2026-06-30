"""Unit tests for core.sql_model.linked_server module."""

import pytest

from core.sql_model.linked_server import LinkedServer


@pytest.mark.unit
class TestLinkedServer:
    """Test LinkedServer class."""

    def test_init_basic(self):
        """Test basic initialization."""
        server = LinkedServer("remote_server", dialect="sqlserver")
        assert server.name == "remote_server"
        assert server.product is None
        assert server.provider is None
        assert server.data_source is None
        assert server.catalog is None
        assert server.username is None
        assert server.dialect == "sqlserver"

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters."""
        server = LinkedServer(
            name="remote_server",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="remote.example.com",
            catalog="remote_db",
            username="user1",
            schema="dbo",
            dialect="sqlserver",
        )
        assert server.name == "remote_server"
        assert server.product == "SQL Server"
        assert server.provider == "SQLNCLI"
        assert server.data_source == "remote.example.com"
        assert server.catalog == "remote_db"
        assert server.username == "user1"
        assert server.schema == "dbo"
        assert server.dialect == "sqlserver"

    def test_create_statement_minimal(self):
        """Test create statement with minimal parameters."""
        server = LinkedServer("test_server", dialect="sqlserver")
        result = server.create_statement
        assert "EXEC sp_addlinkedserver" in result
        assert "@server = [test_server]" in result

    def test_create_statement_with_product(self):
        """Test create statement with product."""
        server = LinkedServer("test_server", product="SQL Server")
        result = server.create_statement
        assert "@srvproduct = 'SQL Server'" in result

    def test_create_statement_with_provider(self):
        """Test create statement with provider."""
        server = LinkedServer("test_server", provider="SQLNCLI")
        result = server.create_statement
        assert "@provider = 'SQLNCLI'" in result

    def test_create_statement_with_data_source(self):
        """Test create statement with data source."""
        server = LinkedServer("test_server", data_source="remote.example.com")
        result = server.create_statement
        assert "@datasrc = 'remote.example.com'" in result

    def test_create_statement_with_catalog(self):
        """Test create statement with catalog."""
        server = LinkedServer("test_server", catalog="remote_db")
        result = server.create_statement
        assert "@catalog = 'remote_db'" in result

    def test_create_statement_with_username(self):
        """Test create statement with username (includes login mapping comment)."""
        server = LinkedServer("test_server", username="user1")
        result = server.create_statement
        assert "EXEC sp_addlinkedserver" in result
        assert "Configure login mapping" in result
        assert "@rmtuser = 'user1'" in result

    def test_create_statement_complete(self):
        """Test create statement with all components."""
        server = LinkedServer(
            "test_server",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="remote.example.com",
            catalog="remote_db",
            username="user1",
            dialect="sqlserver",
        )
        result = server.create_statement
        assert "EXEC sp_addlinkedserver" in result
        assert "@server = [test_server]" in result
        assert "@srvproduct = 'SQL Server'" in result
        assert "@provider = 'SQLNCLI'" in result
        assert "@datasrc = 'remote.example.com'" in result
        assert "@catalog = 'remote_db'" in result
        assert "Configure login mapping" in result

    def test_drop_statement(self):
        """Test drop statement generation."""
        server = LinkedServer("test_server", dialect="sqlserver")
        result = server.drop_statement
        assert result == "EXEC sp_dropserver @server = [test_server], @droplogins = 'droplogins';"

    def test_str_representation_basic(self):
        """Test string representation without details."""
        server = LinkedServer("test_server")
        result = str(server)
        assert "LINKED SERVER test_server" in result

    def test_str_representation_with_product(self):
        """Test string representation with product."""
        server = LinkedServer("test_server", product="SQL Server")
        result = str(server)
        assert "LINKED SERVER test_server" in result
        assert "(SQL Server)" in result

    def test_str_representation_with_data_source(self):
        """Test string representation with data source."""
        server = LinkedServer("test_server", data_source="remote.example.com")
        result = str(server)
        assert "LINKED SERVER test_server" in result
        assert "-> remote.example.com" in result

    def test_str_representation_with_catalog(self):
        """Test string representation with catalog."""
        server = LinkedServer("test_server", data_source="remote.example.com", catalog="remote_db")
        result = str(server)
        assert "LINKED SERVER test_server" in result
        assert "-> remote.example.com" in result
        assert ".remote_db" in result

    def test_str_representation_with_username(self):
        """Test string representation with username."""
        server = LinkedServer("test_server", username="user1")
        result = str(server)
        assert "LINKED SERVER test_server" in result
        assert "(user: user1)" in result

    def test_str_representation_complete(self):
        """Test string representation with all components."""
        server = LinkedServer(
            "test_server",
            product="SQL Server",
            data_source="remote.example.com",
            catalog="remote_db",
            username="user1",
        )
        result = str(server)
        assert "LINKED SERVER test_server" in result
        assert "(SQL Server)" in result
        assert "-> remote.example.com" in result
        assert ".remote_db" in result
        assert "(user: user1)" in result

    def test_eq_same_server(self):
        """Test equality with same server."""
        server1 = LinkedServer(
            "test_server",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="remote.example.com",
            catalog="remote_db",
            username="user1",
        )
        server2 = LinkedServer(
            "test_server",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="remote.example.com",
            catalog="remote_db",
            username="user1",
        )
        assert server1 == server2

    def test_eq_different_type(self):
        """Test equality with different type."""
        server = LinkedServer("test_server")
        assert server != "not_a_server"

    def test_eq_different_product(self):
        """Test equality with different product."""
        server1 = LinkedServer("test_server", product="SQL Server")
        server2 = LinkedServer("test_server", product="Oracle")
        assert server1 != server2

    def test_eq_different_provider(self):
        """Test equality with different provider."""
        server1 = LinkedServer("test_server", provider="SQLNCLI")
        server2 = LinkedServer("test_server", provider="OraOLEDB.Oracle")
        assert server1 != server2

    def test_eq_different_data_source(self):
        """Test equality with different data source."""
        server1 = LinkedServer("test_server", data_source="host1")
        server2 = LinkedServer("test_server", data_source="host2")
        assert server1 != server2

    def test_eq_different_catalog(self):
        """Test equality with different catalog."""
        server1 = LinkedServer("test_server", catalog="db1")
        server2 = LinkedServer("test_server", catalog="db2")
        assert server1 != server2

    def test_eq_different_username(self):
        """Test equality with different username."""
        server1 = LinkedServer("test_server", username="user1")
        server2 = LinkedServer("test_server", username="user2")
        assert server1 != server2

    def test_eq_case_insensitive(self):
        """Test equality is case-insensitive."""
        server1 = LinkedServer("test_server", product="SQL Server", data_source="Host1")
        server2 = LinkedServer("test_server", product="sql server", data_source="host1")
        assert server1 == server2

    def test_eq_none_values(self):
        """Test equality with None values."""
        server1 = LinkedServer("test_server")
        server2 = LinkedServer("test_server")
        assert server1 == server2

    def test_hash(self):
        """Test hash generation."""
        server1 = LinkedServer("test_server", data_source="remote.example.com", schema="dbo")
        server2 = LinkedServer("test_server", data_source="remote.example.com", schema="dbo")
        assert hash(server1) == hash(server2)

    def test_hash_different_data_source(self):
        """Test hash differs with different data source."""
        server1 = LinkedServer("test_server", data_source="host1")
        server2 = LinkedServer("test_server", data_source="host2")
        assert hash(server1) != hash(server2)

    def test_to_dict(self):
        """Test to_dict serializes all fields."""
        server = LinkedServer(
            name="remote",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="remote.host.com",
            catalog="db",
            username="sa",
            schema="dbo",
            dialect="sqlserver",
        )
        d = server.to_dict()
        assert d["name"] == "remote"
        assert d["product"] == "SQL Server"
        assert d["provider"] == "SQLNCLI"
        assert d["data_source"] == "remote.host.com"
        assert d["catalog"] == "db"
        assert d["username"] == "sa"
        assert d["schema"] == "dbo"
        assert d["dialect"] == "sqlserver"

    def test_from_dict(self):
        """Test from_dict round-trip."""
        server = LinkedServer(
            name="remote",
            product="SQL Server",
            provider="SQLNCLI",
            data_source="remote.host.com",
            catalog="db",
            username="sa",
            schema="dbo",
        )
        assert LinkedServer.from_dict(server.to_dict()) == server

    def test_from_dict_minimal(self):
        """Test from_dict with minimal fields."""
        d = {"name": "srv"}
        server = LinkedServer.from_dict(d)
        assert server.name == "srv"
        assert server.product is None
        assert server.data_source is None
