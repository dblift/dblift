"""Unit tests for core.sql_model.database_link module."""

import pytest

from core.sql_model.database_link import DatabaseLink


@pytest.mark.unit
class TestDatabaseLink:
    """Test DatabaseLink class."""

    def test_init_basic(self):
        """Test basic initialization."""
        link = DatabaseLink("remote_db", dialect="oracle")
        assert link.name == "remote_db"
        assert link.host is None
        assert link.username is None
        assert link.connect_string is None
        assert link.public is False
        assert link.dialect == "oracle"

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters."""
        link = DatabaseLink(
            name="remote_db",
            host="remote.example.com",
            username="user1",
            connect_string="tns_name",
            public=True,
            schema="public",
            dialect="oracle",
        )
        assert link.name == "remote_db"
        assert link.host == "remote.example.com"
        assert link.username == "user1"
        assert link.connect_string == "tns_name"
        assert link.public is True
        assert link.schema == "public"
        assert link.dialect == "oracle"

    def test_init_public_link(self):
        """Test initialization of public database link."""
        link = DatabaseLink("public_link", public=True)
        assert link.public is True

    def test_init_private_link(self):
        """Test initialization of private database link."""
        link = DatabaseLink("private_link", public=False)
        assert link.public is False

    def test_create_statement_private_minimal(self):
        """Test create statement for private link without credentials."""
        link = DatabaseLink("test_link")
        result = link.create_statement
        assert "CREATE DATABASE LINK" in result
        assert "PUBLIC" not in result
        assert "test_link" in result

    def test_create_statement_public_minimal(self):
        """Test create statement for public link without credentials."""
        link = DatabaseLink("test_link", public=True)
        result = link.create_statement
        assert "CREATE PUBLIC DATABASE LINK" in result
        assert "test_link" in result

    def test_create_statement_with_username(self):
        """Test create statement with username."""
        link = DatabaseLink("test_link", username="user1")
        result = link.create_statement
        assert "CREATE DATABASE LINK" in result
        assert "CONNECT TO user1" in result
        assert "IDENTIFIED BY <password>" in result

    def test_create_statement_with_connect_string(self):
        """Test create statement with connect string."""
        link = DatabaseLink("test_link", connect_string="tns_name")
        result = link.create_statement
        assert "CREATE DATABASE LINK" in result
        assert "USING 'tns_name'" in result

    def test_create_statement_complete(self):
        """Test create statement with all components."""
        link = DatabaseLink(
            "test_link",
            username="user1",
            connect_string="tns_name",
            public=True,
        )
        result = link.create_statement
        assert "CREATE PUBLIC DATABASE LINK" in result
        assert "CONNECT TO user1" in result
        assert "USING 'tns_name'" in result

    def test_drop_statement_private(self):
        """Test drop statement for private link."""
        link = DatabaseLink("test_link", dialect="oracle")
        result = link.drop_statement
        assert result == 'DROP DATABASE LINK "test_link"'
        assert "PUBLIC" not in result

    def test_drop_statement_public(self):
        """Test drop statement for public link."""
        link = DatabaseLink("test_link", public=True, dialect="oracle")
        result = link.drop_statement
        assert result == 'DROP PUBLIC DATABASE LINK "test_link"'

    def test_str_representation_basic(self):
        """Test string representation without connection info."""
        link = DatabaseLink("test_link")
        result = str(link)
        assert "DATABASE LINK test_link" in result
        assert "PUBLIC" not in result

    def test_str_representation_public(self):
        """Test string representation for public link."""
        link = DatabaseLink("test_link", public=True)
        result = str(link)
        assert "PUBLIC DATABASE LINK test_link" in result

    def test_str_representation_with_host(self):
        """Test string representation with host."""
        link = DatabaseLink("test_link", host="remote.example.com")
        result = str(link)
        assert "DATABASE LINK test_link" in result
        assert "-> remote.example.com" in result

    def test_str_representation_with_connect_string(self):
        """Test string representation with connect string."""
        link = DatabaseLink("test_link", connect_string="tns_name")
        result = str(link)
        assert "DATABASE LINK test_link" in result
        assert "-> tns_name" in result

    def test_str_representation_with_username(self):
        """Test string representation with username."""
        link = DatabaseLink("test_link", username="user1")
        result = str(link)
        assert "DATABASE LINK test_link" in result
        assert "(user: user1)" in result

    def test_str_representation_complete(self):
        """Test string representation with all components."""
        link = DatabaseLink(
            "test_link",
            host="remote.example.com",
            username="user1",
            public=True,
        )
        result = str(link)
        assert "PUBLIC DATABASE LINK test_link" in result
        assert "-> remote.example.com" in result
        assert "(user: user1)" in result

    def test_eq_same_link(self):
        """Test equality with same link."""
        link1 = DatabaseLink(
            "test_link", host="host1", username="user1", connect_string="conn1", public=True
        )
        link2 = DatabaseLink(
            "test_link", host="host1", username="user1", connect_string="conn1", public=True
        )
        assert link1 == link2

    def test_eq_different_type(self):
        """Test equality with different type."""
        link = DatabaseLink("test_link")
        assert link != "not_a_link"

    def test_eq_different_host(self):
        """Test equality with different host."""
        link1 = DatabaseLink("test_link", host="host1")
        link2 = DatabaseLink("test_link", host="host2")
        assert link1 != link2

    def test_eq_different_username(self):
        """Test equality with different username."""
        link1 = DatabaseLink("test_link", username="user1")
        link2 = DatabaseLink("test_link", username="user2")
        assert link1 != link2

    def test_eq_different_connect_string(self):
        """Test equality with different connect string."""
        link1 = DatabaseLink("test_link", connect_string="conn1")
        link2 = DatabaseLink("test_link", connect_string="conn2")
        assert link1 != link2

    def test_eq_different_public_flag(self):
        """Test equality with different public flag."""
        link1 = DatabaseLink("test_link", public=True)
        link2 = DatabaseLink("test_link", public=False)
        assert link1 != link2

    def test_eq_case_insensitive(self):
        """Test equality is case-insensitive."""
        link1 = DatabaseLink("test_link", host="Host1", username="User1")
        link2 = DatabaseLink("test_link", host="host1", username="user1")
        assert link1 == link2

    def test_eq_none_values(self):
        """Test equality with None values."""
        link1 = DatabaseLink("test_link")
        link2 = DatabaseLink("test_link")
        assert link1 == link2

    def test_hash(self):
        """Test hash generation."""
        link1 = DatabaseLink("test_link", host="host1", public=True, schema="public")
        link2 = DatabaseLink("test_link", host="host1", public=True, schema="public")
        assert hash(link1) == hash(link2)

    def test_hash_different_host(self):
        """Test hash differs with different host."""
        link1 = DatabaseLink("test_link", host="host1")
        link2 = DatabaseLink("test_link", host="host2")
        assert hash(link1) != hash(link2)

    def test_hash_different_public_flag(self):
        """Test hash differs with different public flag."""
        link1 = DatabaseLink("test_link", public=True)
        link2 = DatabaseLink("test_link", public=False)
        assert hash(link1) != hash(link2)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        link = DatabaseLink(
            "test_link",
            host="remote.example.com",
            username="user1",
            connect_string="tns_name",
            public=True,
            schema="public",
            dialect="oracle",
        )
        result = link.to_dict()
        assert result == {
            "name": "test_link",
            "schema": "public",
            "dialect": "oracle",
            "host": "remote.example.com",
            "username": "user1",
            "connect_string": "tns_name",
            "public": True,
        }

    def test_to_dict_minimal(self):
        """Test serialization with minimal link."""
        link = DatabaseLink("test_link")
        result = link.to_dict()
        assert result["name"] == "test_link"
        assert result["host"] is None
        assert result["username"] is None
        assert result["connect_string"] is None
        assert result["public"] is False

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "test_link",
            "host": "remote.example.com",
            "username": "user1",
            "connect_string": "tns_name",
            "public": True,
            "schema": "public",
            "dialect": "oracle",
        }
        link = DatabaseLink.from_dict(data)
        assert link.name == "test_link"
        assert link.host == "remote.example.com"
        assert link.username == "user1"
        assert link.connect_string == "tns_name"
        assert link.public is True
        assert link.schema == "public"
        assert link.dialect == "oracle"

    def test_from_dict_minimal(self):
        """Test deserialization with minimal data."""
        data = {"name": "test_link"}
        link = DatabaseLink.from_dict(data)
        assert link.name == "test_link"
        assert link.host is None
        assert link.username is None
        assert link.connect_string is None
        assert link.public is False

    def test_from_dict_empty_name(self):
        """Test deserialization with empty name."""
        data = {}
        link = DatabaseLink.from_dict(data)
        assert link.name == ""
