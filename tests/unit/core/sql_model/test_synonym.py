"""Unit tests for core.sql_model.synonym module."""

from unittest.mock import Mock, patch

import pytest

from core.sql_model.synonym import Synonym


@pytest.mark.unit
class TestSynonym:
    """Test Synonym class."""

    def test_init_basic(self):
        """Test basic initialization."""
        synonym = Synonym("synonym_name", "target_table")
        assert synonym.name == "synonym_name"
        assert synonym.target_object == "target_table"
        assert synonym.target_schema is None
        assert synonym.target_database is None
        assert synonym.db_link is None
        assert synonym.schema is None

    def test_init_with_all_parameters(self):
        """Test initialization with all parameters."""
        synonym = Synonym(
            name="synonym_name",
            target_object="target_table",
            schema="public",
            target_schema="remote_schema",
            target_database="remote_db",
            db_link="remote_link",
            dialect="oracle",
        )
        assert synonym.name == "synonym_name"
        assert synonym.target_object == "target_table"
        assert synonym.schema == "public"
        assert synonym.target_schema == "remote_schema"
        assert synonym.target_database == "remote_db"
        assert synonym.db_link == "remote_link"
        assert synonym.dialect == "oracle"

    def test_target_full_name_basic(self):
        """Test target_full_name with just object name."""
        synonym = Synonym("synonym_name", "target_table")
        result = synonym.target_full_name
        assert result == "target_table"  # format_identifier may not quote for default dialect

    def test_target_full_name_with_target_schema(self):
        """Test target_full_name with target schema."""
        synonym = Synonym("synonym_name", "target_table", target_schema="remote_schema")
        result = synonym.target_full_name
        assert "remote_schema" in result
        assert "target_table" in result
        assert "." in result

    def test_target_full_name_with_target_database(self):
        """Test target_full_name with target database (SQL Server)."""
        synonym = Synonym(
            "synonym_name", "target_table", target_database="remote_db", dialect="sqlserver"
        )
        result = synonym.target_full_name
        assert "remote_db" in result
        assert "target_table" in result
        assert "." in result

    def test_target_full_name_with_target_database_and_schema(self):
        """Test target_full_name with target database and schema."""
        synonym = Synonym(
            "synonym_name",
            "target_table",
            target_database="remote_db",
            target_schema="remote_schema",
            dialect="sqlserver",
        )
        result = synonym.target_full_name
        assert "remote_db" in result
        assert "remote_schema" in result
        assert "target_table" in result
        assert result.count(".") >= 2

    def test_target_full_name_with_db_link(self):
        """Test target_full_name with database link (Oracle)."""
        synonym = Synonym("synonym_name", "target_table", db_link="remote_link", dialect="oracle")
        result = synonym.target_full_name
        assert "target_table" in result
        assert "@remote_link" in result or '@"remote_link"' in result

    def test_target_full_name_complete(self):
        """Test target_full_name with all components."""
        synonym = Synonym(
            "synonym_name",
            "target_table",
            target_database="remote_db",
            target_schema="remote_schema",
            db_link="remote_link",
            dialect="oracle",
        )
        result = synonym.target_full_name
        assert "remote_db" in result
        assert "remote_schema" in result
        assert "target_table" in result
        assert "@" in result
        assert "remote_link" in result

    def test_create_statement_with_generator(self):
        """Test create_statement using generator."""
        synonym = Synonym("synonym_name", "target_table", schema="public")
        mock_generator = Mock()
        mock_generator.generate_create_statement = Mock(return_value="CREATE SYNONYM synonym_name;")

        with patch(
            "core.sql_generator.generator_factory.SqlGeneratorFactory.create",
            return_value=mock_generator,
        ):
            result = synonym.create_statement
            assert result == "CREATE SYNONYM synonym_name;"
            mock_generator.generate_create_statement.assert_called_once_with(synonym)

    def test_create_statement_fallback_no_generator_method(self):
        """Test create_statement fallback when generator lacks method."""
        synonym = Synonym("synonym_name", "target_table", schema="public")
        mock_generator = Mock()
        del mock_generator.generate_create_statement  # Simulate missing method

        with patch(
            "core.sql_generator.generator_factory.SqlGeneratorFactory.create",
            return_value=mock_generator,
        ):
            result = synonym.create_statement
            assert "CREATE SYNONYM" in result
            assert "FOR" in result

    def test_create_statement_fallback_exception(self):
        """Test create_statement fallback on exception."""
        synonym = Synonym("synonym_name", "target_table")

        with patch(
            "core.sql_generator.generator_factory.SqlGeneratorFactory.create",
            side_effect=ValueError("Error"),
        ):
            result = synonym.create_statement
            assert "CREATE SYNONYM" in result
            assert "FOR" in result

    def test_generate_basic_create_statement_oracle(self):
        """Test basic create statement for Oracle."""
        synonym = Synonym("synonym_name", "target_table", schema="public", dialect="oracle")
        result = synonym._generate_basic_create_statement()
        assert "CREATE OR REPLACE SYNONYM" in result
        assert '"public"."synonym_name"' in result
        assert "FOR" in result

    def test_generate_basic_create_statement_sqlserver(self):
        """Test basic create statement for SQL Server."""
        synonym = Synonym("synonym_name", "target_table", schema="dbo", dialect="sqlserver")
        result = synonym._generate_basic_create_statement()
        assert "CREATE SYNONYM" in result
        assert "dbo" in result
        assert "synonym_name" in result
        assert "FOR" in result

    def test_generate_basic_create_statement_db2(self):
        """Test basic create statement for DB2."""
        synonym = Synonym("synonym_name", "target_table", dialect="db2")
        result = synonym._generate_basic_create_statement()
        assert "CREATE ALIAS" in result
        assert '"synonym_name"' in result
        assert "FOR" in result

    def test_generate_basic_create_statement_generic(self):
        """Test basic create statement for generic dialect."""
        synonym = Synonym("synonym_name", "target_table", dialect="postgresql")
        result = synonym._generate_basic_create_statement()
        assert "CREATE SYNONYM" in result
        assert '"synonym_name"' in result
        assert "FOR" in result

    def test_generate_basic_create_statement_no_schema(self):
        """Test basic create statement without schema."""
        synonym = Synonym("synonym_name", "target_table")
        result = synonym._generate_basic_create_statement()
        assert "CREATE SYNONYM" in result
        assert "synonym_name" in result
        assert "FOR" in result

    def test_drop_statement_db2(self):
        """Test drop statement for DB2."""
        synonym = Synonym("synonym_name", "target_table", dialect="db2")
        result = synonym.drop_statement
        assert result == 'DROP ALIAS "synonym_name"'

    def test_drop_statement_other_dialects(self):
        """Test drop statement for other dialects."""
        synonym = Synonym("synonym_name", "target_table", dialect="oracle")
        result = synonym.drop_statement
        assert result == 'DROP SYNONYM "synonym_name"'

    def test_drop_statement_with_schema(self):
        """Test drop statement with schema."""
        synonym = Synonym("synonym_name", "target_table", schema="public", dialect="oracle")
        result = synonym.drop_statement
        assert result == 'DROP SYNONYM "public"."synonym_name"'

    def test_str_representation(self):
        """Test string representation."""
        synonym = Synonym("synonym_name", "target_table", target_schema="remote_schema")
        result = str(synonym)
        assert "SYNONYM synonym_name" in result
        assert "->" in result
        assert "remote_schema" in result

    def test_eq_same_synonym(self):
        """Test equality with same synonym."""
        synonym1 = Synonym(
            "synonym_name",
            "target_table",
            target_schema="remote_schema",
            target_database="remote_db",
            db_link="remote_link",
        )
        synonym2 = Synonym(
            "synonym_name",
            "target_table",
            target_schema="remote_schema",
            target_database="remote_db",
            db_link="remote_link",
        )
        assert synonym1 == synonym2

    def test_eq_different_type(self):
        """Test equality with different type."""
        synonym = Synonym("synonym_name", "target_table")
        assert synonym != "not_a_synonym"

    def test_eq_different_target_object(self):
        """Test equality with different target object."""
        synonym1 = Synonym("synonym_name", "target1")
        synonym2 = Synonym("synonym_name", "target2")
        assert synonym1 != synonym2

    def test_eq_different_target_schema(self):
        """Test equality with different target schema."""
        synonym1 = Synonym("synonym_name", "target_table", target_schema="schema1")
        synonym2 = Synonym("synonym_name", "target_table", target_schema="schema2")
        assert synonym1 != synonym2

    def test_eq_different_target_database(self):
        """Test equality with different target database."""
        synonym1 = Synonym("synonym_name", "target_table", target_database="db1")
        synonym2 = Synonym("synonym_name", "target_table", target_database="db2")
        assert synonym1 != synonym2

    def test_eq_different_db_link(self):
        """Test equality with different database link."""
        synonym1 = Synonym("synonym_name", "target_table", db_link="link1")
        synonym2 = Synonym("synonym_name", "target_table", db_link="link2")
        assert synonym1 != synonym2

    def test_eq_case_insensitive(self):
        """Test equality is case-insensitive."""
        synonym1 = Synonym("synonym_name", "Target", target_schema="Schema")
        synonym2 = Synonym("synonym_name", "target", target_schema="schema")
        assert synonym1 == synonym2

    def test_eq_none_values(self):
        """Test equality with None values."""
        synonym1 = Synonym("synonym_name", "target_table")
        synonym2 = Synonym("synonym_name", "target_table")
        assert synonym1 == synonym2

    def test_hash(self):
        """Test hash generation."""
        synonym1 = Synonym(
            "synonym_name", "target_table", target_schema="remote_schema", schema="public"
        )
        synonym2 = Synonym(
            "synonym_name", "target_table", target_schema="remote_schema", schema="public"
        )
        assert hash(synonym1) == hash(synonym2)

    def test_hash_different_target_object(self):
        """Test hash differs with different target object."""
        synonym1 = Synonym("synonym_name", "target1")
        synonym2 = Synonym("synonym_name", "target2")
        assert hash(synonym1) != hash(synonym2)

    def test_hash_different_target_schema(self):
        """Test hash differs with different target schema."""
        synonym1 = Synonym("synonym_name", "target_table", target_schema="schema1")
        synonym2 = Synonym("synonym_name", "target_table", target_schema="schema2")
        assert hash(synonym1) != hash(synonym2)

    def test_to_dict(self):
        """Test serialization to dictionary."""
        synonym = Synonym(
            "synonym_name",
            "target_table",
            schema="public",
            target_schema="remote_schema",
            target_database="remote_db",
            db_link="remote_link",
            dialect="oracle",
        )
        result = synonym.to_dict()
        assert result == {
            "name": "synonym_name",
            "schema": "public",
            "dialect": "oracle",
            "target_object": "target_table",
            "target_schema": "remote_schema",
            "target_database": "remote_db",
            "db_link": "remote_link",
        }

    def test_to_dict_minimal(self):
        """Test serialization with minimal synonym."""
        synonym = Synonym("synonym_name", "target_table")
        result = synonym.to_dict()
        assert result["name"] == "synonym_name"
        assert result["target_object"] == "target_table"
        assert result["schema"] is None
        assert result["target_schema"] is None
        assert result["target_database"] is None
        assert result["db_link"] is None

    def test_from_dict(self):
        """Test deserialization from dictionary."""
        data = {
            "name": "synonym_name",
            "target_object": "target_table",
            "schema": "public",
            "target_schema": "remote_schema",
            "target_database": "remote_db",
            "db_link": "remote_link",
            "dialect": "oracle",
        }
        synonym = Synonym.from_dict(data)
        assert synonym.name == "synonym_name"
        assert synonym.target_object == "target_table"
        assert synonym.schema == "public"
        assert synonym.target_schema == "remote_schema"
        assert synonym.target_database == "remote_db"
        assert synonym.db_link == "remote_link"
        assert synonym.dialect == "oracle"

    def test_from_dict_minimal(self):
        """Test deserialization with minimal data."""
        data = {"name": "synonym_name", "target_object": "target_table"}
        synonym = Synonym.from_dict(data)
        assert synonym.name == "synonym_name"
        assert synonym.target_object == "target_table"
        assert synonym.schema is None
        assert synonym.target_schema is None
        assert synonym.target_database is None
        assert synonym.db_link is None

    def test_from_dict_empty_name(self):
        """Test deserialization with empty name."""
        data = {}
        synonym = Synonym.from_dict(data)
        assert synonym.name == ""
        assert synonym.target_object == ""
