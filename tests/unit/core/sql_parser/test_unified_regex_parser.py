"""Tests for unified regex parser."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType
from dblift.core.sql_parser.unified_regex_parser import DialectConfig, RegexParser
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig


class _SemanticParser(RegexParser):
    def split_statements(self, sql_content, strict_tokenizer=False):
        from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser

        return MySqlRegexParser().split_statements(sql_content, strict_tokenizer)


@pytest.mark.unit
class TestDialectConfig:
    """Test suite for DialectConfig abstract class."""

    def test_dialect_config_abstract(self):
        """Test that DialectConfig is abstract."""
        with pytest.raises(TypeError):
            DialectConfig()

    def test_dialect_config_concrete_implementation(self):
        """Test concrete DialectConfig implementation."""

        class TestConfig(DialectConfig):
            @property
            def name(self):
                return "test"

            @property
            def batch_separators(self):
                return []

            @property
            def quoted_identifiers(self):
                return []

            @property
            def comment_patterns(self):
                return []

            @property
            def block_keywords(self):
                return []

            @property
            def ddl_patterns(self):
                return {}

            @property
            def dml_patterns(self):
                return {}

            @property
            def query_patterns(self):
                return {}

            @property
            def object_patterns(self):
                return {}

        config = TestConfig()
        assert config.name == "test"
        assert config.get_default_schema() == "default_schema"
        assert config.normalize_identifier("test") == "test"


@pytest.mark.unit
class TestRegexParser:
    """Test suite for RegexParser."""

    def test_parser_creation(self):
        """Test parser can be created."""
        config = MySqlConfig()
        parser = _SemanticParser(config)
        assert parser is not None
        assert parser.dialect_name == "mysql"

    def test_dialect_name_property(self):
        """Test dialect_name property."""
        config = MySqlConfig()
        parser = _SemanticParser(config)
        assert parser.dialect_name == "mysql"

    def test_parse_sql_simple(self):
        """Test parse_sql with simple SQL."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "CREATE TABLE test (id INT PRIMARY KEY);"
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 1

    def test_parse_sql_with_errors(self):
        """Test parse_sql error handling."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        # Mock _classify_statement to raise exception
        with patch.object(parser, "_classify_statement", side_effect=Exception("Error")):
            sql = "CREATE TABLE test (id INT);"
            result = parser.parse_sql(sql)
            assert isinstance(result, ParseResult)
            assert len(result.errors) > 0 or len(result.statements) > 0

    def test_parse_sql_splitting_error(self):
        """Test parse_sql with splitting error."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        # Mock split_statements to raise exception
        with patch.object(parser, "split_statements", side_effect=Exception("Error")):
            sql = "CREATE TABLE test (id INT);"
            result = parser.parse_sql(sql)
            assert isinstance(result, ParseResult)
            assert len(result.errors) > 0

    def test_validate_sql_valid(self):
        """Test validate_sql with valid SQL."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "CREATE TABLE test (id INT PRIMARY KEY);"
        result = parser.validate_sql(sql)
        assert result["valid"] is True
        assert result["statements_found"] > 0

    def test_validate_sql_invalid(self):
        """Test validate_sql with invalid SQL."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        # Mock split_statements to raise exception
        with patch.object(parser, "split_statements", side_effect=Exception("Error")):
            sql = "INVALID SQL"
            result = parser.validate_sql(sql)
            assert result["valid"] is False
            assert len(result["errors"]) > 0

    def test_extract_objects_empty(self):
        """Test extract_objects with empty SQL."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        objects = parser.extract_objects("")
        assert len(objects) == 0

    def test_extract_objects_with_table(self):
        """Test extract_objects with CREATE TABLE."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "CREATE TABLE test (id INT PRIMARY KEY);"
        objects = parser.extract_objects(sql)
        assert len(objects) >= 1

    def test_extract_objects_with_schema(self):
        """Test extract_objects with schema."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "CREATE TABLE myschema.test (id INT);"
        objects = parser.extract_objects(sql, default_schema="public")
        assert len(objects) >= 1

    def test_compile_patterns(self):
        """Test pattern compilation."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        patterns = parser._compiled_patterns
        assert "ddl_patterns" in patterns
        assert "dml_patterns" in patterns

    def test_clean_sql(self):
        """Test SQL cleaning."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "  CREATE TABLE test (id INT);  "
        cleaned = parser._clean_sql(sql)
        assert "CREATE TABLE" in cleaned

    def test_is_empty_or_comment(self):
        """Test empty or comment detection."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        assert parser._is_empty_or_comment("") is True
        assert parser._is_empty_or_comment("   ") is True
        assert parser._is_empty_or_comment("-- comment") is True
        assert parser._is_empty_or_comment("CREATE TABLE test (id INT);") is False

    def test_classify_statement_ddl(self):
        """Test statement classification for DDL."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "CREATE TABLE test (id INT);"
        stmt_type = parser._classify_statement(sql)
        assert stmt_type == SqlStatementType.DDL

    def test_classify_statement_dml(self):
        """Test statement classification for DML."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "INSERT INTO test VALUES (1);"
        stmt_type = parser._classify_statement(sql)
        assert stmt_type == SqlStatementType.DML

    def test_classify_statement_query(self):
        """Test statement classification for query."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "SELECT * FROM test;"
        stmt_type = parser._classify_statement(sql)
        assert stmt_type == SqlStatementType.QUERY

    def test_classify_statement_unknown(self):
        """Test statement classification for unknown."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "UNKNOWN STATEMENT;"
        stmt_type = parser._classify_statement(sql)
        assert stmt_type == SqlStatementType.UNKNOWN

    def test_create_object_from_match_table(self):
        """Test object creation from match for table."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        import re

        pattern = re.compile(r"CREATE TABLE\s+(\w+)", re.IGNORECASE)
        match = pattern.search("CREATE TABLE test (id INT);")
        if match:
            obj = parser._create_object_from_match(match, "create_table", "public")
            assert obj is not None
            assert obj.object_type == SqlObjectType.TABLE

    def test_create_object_from_match_unknown(self):
        """Test object creation from match for unknown pattern."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        import re

        pattern = re.compile(r"UNKNOWN\s+(\w+)", re.IGNORECASE)
        match = pattern.search("UNKNOWN test;")
        if match:
            obj = parser._create_object_from_match(match, "unknown_pattern", "public")
            assert obj is None
