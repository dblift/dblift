"""Unit tests for core.sql_model.foreign_server module."""

from unittest.mock import Mock, patch

import pytest

from core.sql_model.foreign_server import ForeignServer


@pytest.mark.unit
class TestForeignServer:
    """Test ForeignServer class."""

    def test_init_basic(self):
        """Test basic initialization."""
        server = ForeignServer("remote_server", "postgres_fdw", dialect="postgresql")
        assert server.name == "remote_server"
        assert server.fdw_name == "postgres_fdw"
        assert server.host is None
        assert server.port is None
        assert server.dbname is None
        assert server.options == {}
        assert server.dialect == "postgresql"

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters."""
        options = {"option1": "value1"}
        server = ForeignServer(
            name="remote_server",
            fdw_name="postgres_fdw",
            host="remote.example.com",
            port=5432,
            dbname="remote_db",
            options=options,
            schema="public",
            dialect="postgresql",
        )
        assert server.name == "remote_server"
        assert server.fdw_name == "postgres_fdw"
        assert server.host == "remote.example.com"
        assert server.port == 5432
        assert server.dbname == "remote_db"
        assert server.options == {
            "option1": "value1",
            "host": "remote.example.com",
            "port": "5432",
            "dbname": "remote_db",
        }
        assert server.schema == "public"
        assert server.dialect == "postgresql"

    def test_init_options_copy(self):
        """Test that options dictionary is copied."""
        original_options = {"key": "value"}
        server = ForeignServer("test_server", "test_fdw", options=original_options)
        server.options["new_key"] = "new_value"
        assert "new_key" not in original_options

    def test_init_host_added_to_options(self):
        """Test that host is added to options."""
        server = ForeignServer("test_server", "test_fdw", host="remote.example.com")
        assert server.options["host"] == "remote.example.com"

    def test_init_port_added_to_options(self):
        """Test that port is added to options."""
        server = ForeignServer("test_server", "test_fdw", port=5432)
        assert server.options["port"] == "5432"

    def test_init_dbname_added_to_options(self):
        """Test that dbname is added to options."""
        server = ForeignServer("test_server", "test_fdw", dbname="remote_db")
        assert server.options["dbname"] == "remote_db"

    def test_init_all_connection_params_added_to_options(self):
        """Test that host, port, and dbname are all added to options."""
        server = ForeignServer(
            "test_server", "test_fdw", host="remote.example.com", port=5432, dbname="remote_db"
        )
        assert server.options["host"] == "remote.example.com"
        assert server.options["port"] == "5432"
        assert server.options["dbname"] == "remote_db"

    def test_drop_statement(self):
        """Test drop statement generation."""
        server = ForeignServer("test_server", "test_fdw", dialect="postgresql")
        result = server.drop_statement
        assert result == 'DROP SERVER IF EXISTS "test_server" CASCADE;'

    def test_str_representation_basic(self):
        """Test string representation without connection info."""
        server = ForeignServer("test_server", "test_fdw")
        result = str(server)
        assert "FOREIGN SERVER test_server" in result
        assert "(FDW: test_fdw)" in result

    def test_str_representation_with_host(self):
        """Test string representation with host."""
        server = ForeignServer("test_server", "test_fdw", host="remote.example.com")
        result = str(server)
        assert "FOREIGN SERVER test_server" in result
        assert "-> remote.example.com" in result

    def test_str_representation_with_host_and_port(self):
        """Test string representation with host and port."""
        server = ForeignServer("test_server", "test_fdw", host="remote.example.com", port=5432)
        result = str(server)
        assert "FOREIGN SERVER test_server" in result
        assert "-> remote.example.com:5432" in result

    def test_str_representation_with_host_port_and_dbname(self):
        """Test string representation with host, port, and dbname."""
        server = ForeignServer(
            "test_server", "test_fdw", host="remote.example.com", port=5432, dbname="remote_db"
        )
        result = str(server)
        assert "FOREIGN SERVER test_server" in result
        assert "-> remote.example.com:5432" in result
        assert "/remote_db" in result

    def test_eq_same_server(self):
        """Test equality with same server."""
        server1 = ForeignServer(
            "test_server",
            "test_fdw",
            host="remote.example.com",
            port=5432,
            dbname="remote_db",
            options={"k": "v"},
        )
        server2 = ForeignServer(
            "test_server",
            "test_fdw",
            host="remote.example.com",
            port=5432,
            dbname="remote_db",
            options={"k": "v"},
        )
        assert server1 == server2

    def test_eq_different_type(self):
        """Test equality with different type."""
        server = ForeignServer("test_server", "test_fdw")
        assert server != "not_a_server"

    def test_eq_different_fdw_name(self):
        """Test equality with different FDW name."""
        server1 = ForeignServer("test_server", "fdw1")
        server2 = ForeignServer("test_server", "fdw2")
        assert server1 != server2

    def test_eq_different_host(self):
        """Test equality with different host."""
        server1 = ForeignServer("test_server", "test_fdw", host="host1")
        server2 = ForeignServer("test_server", "test_fdw", host="host2")
        assert server1 != server2

    def test_eq_different_port(self):
        """Test equality with different port."""
        server1 = ForeignServer("test_server", "test_fdw", port=5432)
        server2 = ForeignServer("test_server", "test_fdw", port=5433)
        assert server1 != server2

    def test_eq_different_dbname(self):
        """Test equality with different dbname."""
        server1 = ForeignServer("test_server", "test_fdw", dbname="db1")
        server2 = ForeignServer("test_server", "test_fdw", dbname="db2")
        assert server1 != server2

    def test_eq_different_options(self):
        """Test equality with different options."""
        server1 = ForeignServer("test_server", "test_fdw", options={"k1": "v1"})
        server2 = ForeignServer("test_server", "test_fdw", options={"k2": "v2"})
        assert server1 != server2

    def test_eq_case_insensitive(self):
        """Test equality is case-insensitive."""
        # Note: host values in options dict are compared directly, not case-insensitively
        # But fdw_name comparison is case-insensitive
        server1 = ForeignServer("test_server", "Fdw")
        server2 = ForeignServer("test_server", "fdw")
        assert server1 == server2

    def test_eq_none_values(self):
        """Test equality with None values."""
        server1 = ForeignServer("test_server", "test_fdw")
        server2 = ForeignServer("test_server", "test_fdw")
        assert server1 == server2

    def test_hash(self):
        """Test hash generation."""
        server1 = ForeignServer(
            "test_server", "test_fdw", host="remote.example.com", schema="public"
        )
        server2 = ForeignServer(
            "test_server", "test_fdw", host="remote.example.com", schema="public"
        )
        assert hash(server1) == hash(server2)

    def test_hash_different_fdw_name(self):
        """Test hash differs with different FDW name."""
        server1 = ForeignServer("test_server", "fdw1")
        server2 = ForeignServer("test_server", "fdw2")
        assert hash(server1) != hash(server2)

    def test_hash_different_host(self):
        """Test hash differs with different host."""
        server1 = ForeignServer("test_server", "test_fdw", host="host1")
        server2 = ForeignServer("test_server", "test_fdw", host="host2")
        assert hash(server1) != hash(server2)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        server = ForeignServer(
            "test_server",
            "postgres_fdw",
            host="remote.example.com",
            port=5432,
            dbname="remote_db",
            options={"key": "value"},
            schema="public",
            dialect="postgresql",
        )
        result = server.to_dict()
        assert result == {
            "name": "test_server",
            "schema": "public",
            "dialect": "postgresql",
            "fdw_name": "postgres_fdw",
            "host": "remote.example.com",
            "port": 5432,
            "dbname": "remote_db",
            "options": {
                "key": "value",
                "host": "remote.example.com",
                "port": "5432",
                "dbname": "remote_db",
            },
        }

    def test_to_dict_minimal(self):
        """Test serialization with minimal server."""
        server = ForeignServer("test_server", "test_fdw")
        result = server.to_dict()
        assert result["name"] == "test_server"
        assert result["fdw_name"] == "test_fdw"
        assert result["host"] is None
        assert result["port"] is None
        assert result["dbname"] is None
        assert result["options"] == {}

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "test_server",
            "fdw_name": "postgres_fdw",
            "host": "remote.example.com",
            "port": 5432,
            "dbname": "remote_db",
            "options": {"key": "value"},
            "schema": "public",
            "dialect": "postgresql",
        }
        server = ForeignServer.from_dict(data)
        assert server.name == "test_server"
        assert server.fdw_name == "postgres_fdw"
        assert server.host == "remote.example.com"
        assert server.port == 5432
        assert server.dbname == "remote_db"
        # Note: host, port, dbname are merged into options during initialization
        assert "host" in server.options
        assert "port" in server.options
        assert "dbname" in server.options
        assert server.options["key"] == "value"
        assert server.schema == "public"
        assert server.dialect == "postgresql"

    def test_from_dict_minimal(self):
        """Test deserialization with minimal data."""
        data = {"name": "test_server", "fdw_name": "test_fdw"}
        server = ForeignServer.from_dict(data)
        assert server.name == "test_server"
        assert server.fdw_name == "test_fdw"
        assert server.host is None
        assert server.port is None
        assert server.dbname is None

    def test_from_dict_empty_name(self):
        """Test deserialization with empty name."""
        data = {}
        server = ForeignServer.from_dict(data)
        assert server.name == ""
        assert server.fdw_name == ""
