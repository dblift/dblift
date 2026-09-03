"""Tests for unified regex parser."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType
from dblift.core.sql_parser.unified_regex_parser import DialectConfig, RegexParser
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig


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
        parser = RegexParser(config)
        assert parser is not None
        assert parser.dialect_name == "mysql"

    def test_dialect_name_property(self):
        """Test dialect_name property."""
        config = MySqlConfig()
        parser = RegexParser(config)
        assert parser.dialect_name == "mysql"

    def test_parse_sql_simple(self):
        """Test parse_sql with simple SQL."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT PRIMARY KEY);"
        result = parser.parse_sql(sql)

        assert isinstance(result, ParseResult)
        assert result.success
        assert len(result.statements) >= 1

    def test_parse_sql_with_errors(self):
        """Test parse_sql error handling."""
        config = MySqlConfig()
        parser = RegexParser(config)

        # Mock _classify_statement to raise exception
        with patch.object(parser, "_classify_statement", side_effect=Exception("Error")):
            sql = "CREATE TABLE test (id INT);"
            result = parser.parse_sql(sql)
            assert isinstance(result, ParseResult)
            assert len(result.errors) > 0 or len(result.statements) > 0

    def test_parse_sql_splitting_error(self):
        """Test parse_sql with splitting error."""
        config = MySqlConfig()
        parser = RegexParser(config)

        # Mock split_statements to raise exception
        with patch.object(parser, "split_statements", side_effect=Exception("Error")):
            sql = "CREATE TABLE test (id INT);"
            result = parser.parse_sql(sql)
            assert isinstance(result, ParseResult)
            assert len(result.errors) > 0

    def test_split_statements_empty(self):
        """Test split_statements with empty string."""
        config = MySqlConfig()
        parser = RegexParser(config)
        assert parser.split_statements("") == []
        assert parser.split_statements("   ") == []

    def test_split_statements_simple(self):
        """Test split_statements with simple SQL."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT); SELECT 1;"
        statements = parser.split_statements(sql)
        assert len(statements) >= 2

    def test_split_statements_with_batch_separators(self):
        """Test split_statements with batch separators."""
        from dblift.db.plugins.sqlserver.parser.parser_config import SqlServerConfig

        config = SqlServerConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT); GO SELECT 1;"
        statements = parser.split_statements(sql)
        assert len(statements) >= 1

    def test_split_statements_with_block_statements(self):
        """Test split_statements with block statements."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = """
        CREATE PROCEDURE test()
        BEGIN
            SELECT 1;
        END;
        """
        statements = parser.split_statements(sql)
        assert len(statements) >= 1

    def test_validate_sql_valid(self):
        """Test validate_sql with valid SQL."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT PRIMARY KEY);"
        result = parser.validate_sql(sql)
        assert result["valid"] is True
        assert result["statements_found"] > 0

    def test_validate_sql_invalid(self):
        """Test validate_sql with invalid SQL."""
        config = MySqlConfig()
        parser = RegexParser(config)

        # Mock split_statements to raise exception
        with patch.object(parser, "split_statements", side_effect=Exception("Error")):
            sql = "INVALID SQL"
            result = parser.validate_sql(sql)
            assert result["valid"] is False
            assert len(result["errors"]) > 0

    def test_extract_objects_empty(self):
        """Test extract_objects with empty SQL."""
        config = MySqlConfig()
        parser = RegexParser(config)

        objects = parser.extract_objects("")
        assert len(objects) == 0

    def test_extract_objects_with_table(self):
        """Test extract_objects with CREATE TABLE."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT PRIMARY KEY);"
        objects = parser.extract_objects(sql)
        assert len(objects) >= 1

    def test_extract_objects_with_schema(self):
        """Test extract_objects with schema."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE myschema.test (id INT);"
        objects = parser.extract_objects(sql, default_schema="public")
        assert len(objects) >= 1

    def test_compile_patterns(self):
        """Test pattern compilation."""
        config = MySqlConfig()
        parser = RegexParser(config)

        patterns = parser._compiled_patterns
        assert "ddl_patterns" in patterns
        assert "dml_patterns" in patterns

    def test_clean_sql(self):
        """Test SQL cleaning."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "  CREATE TABLE test (id INT);  "
        cleaned = parser._clean_sql(sql)
        assert "CREATE TABLE" in cleaned

    def test_has_batch_separators(self):
        """Test batch separator detection."""
        from dblift.db.plugins.sqlserver.parser.parser_config import SqlServerConfig

        config = SqlServerConfig()
        parser = RegexParser(config)

        # SQL Server uses GO as batch separator, but it needs to match the pattern
        assert parser._has_batch_separators("CREATE TABLE test (id INT);\nGO") is True
        assert parser._has_batch_separators("CREATE TABLE test (id INT);") is False

    def test_has_block_statements(self):
        """Test block statement detection."""
        config = MySqlConfig()
        parser = RegexParser(config)

        assert parser._has_block_statements("CREATE PROCEDURE test() BEGIN END;") is True
        assert parser._has_block_statements("CREATE TABLE test (id INT);") is False

    def test_split_with_batch_separators(self):
        """Test splitting with batch separators."""
        from dblift.db.plugins.sqlserver.parser.parser_config import SqlServerConfig

        config = SqlServerConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT); GO SELECT 1;"
        statements = parser._split_with_batch_separators(sql)
        assert len(statements) >= 1

    def test_split_with_batch_separators_no_separator(self):
        """Test splitting with batch separators when none exist."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT);"
        statements = parser._split_with_batch_separators(sql)
        assert len(statements) >= 1

    def test_split_with_block_awareness(self):
        """Test splitting with block awareness."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT); SELECT 1;"
        statements = parser._split_with_block_awareness(sql)
        assert len(statements) >= 1

    def test_split_by_semicolon_simple(self):
        """Test semicolon splitting."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "SELECT 1; SELECT 2;"
        statements = parser._split_by_semicolon(sql)
        assert len(statements) == 2

    def test_split_by_semicolon_with_strings(self):
        """Test semicolon splitting with strings."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "SELECT 'value;test' FROM test; SELECT 1;"
        statements = parser._split_by_semicolon(sql)
        assert len(statements) == 2

    def test_split_by_semicolon_with_comments(self):
        """Test semicolon splitting with comments."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "SELECT 1; -- comment with ; semicolon\nSELECT 2;"
        statements = parser._split_by_semicolon(sql)
        assert len(statements) == 2

    def test_split_by_semicolon_with_block_comments(self):
        """Test semicolon splitting with block comments."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "SELECT 1; /* comment with ; semicolon */ SELECT 2;"
        statements = parser._split_by_semicolon(sql)
        assert len(statements) == 2

    def test_extract_next_statement_empty(self):
        """Test extract_next_statement with empty text."""
        config = MySqlConfig()
        parser = RegexParser(config)

        statement, pos = parser._extract_next_statement("", 0)
        assert statement == ""
        assert pos == 0

    def test_extract_next_statement_at_end(self):
        """Test extract_next_statement at end of text."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT);"
        statement, pos = parser._extract_next_statement(sql, len(sql))
        assert statement == ""
        assert pos == len(sql)

    def test_starts_with_block_keyword(self):
        """Test block keyword detection."""
        config = MySqlConfig()
        parser = RegexParser(config)

        assert parser._starts_with_block_keyword("BEGIN SELECT 1; END;") is True
        assert parser._starts_with_block_keyword("SELECT 1;") is False

    def test_extract_block_statement(self):
        """Test block statement extraction."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "BEGIN SELECT 1; END;"
        statement, pos = parser._extract_block_statement(sql, 0)
        assert len(statement) > 0

    def test_extract_regular_statement(self):
        """Test regular statement extraction."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT);"
        statement, pos = parser._extract_regular_statement(sql, 0)
        assert len(statement) > 0
        assert "CREATE TABLE" in statement

    def test_is_empty_or_comment(self):
        """Test empty or comment detection."""
        config = MySqlConfig()
        parser = RegexParser(config)

        assert parser._is_empty_or_comment("") is True
        assert parser._is_empty_or_comment("   ") is True
        assert parser._is_empty_or_comment("-- comment") is True
        assert parser._is_empty_or_comment("CREATE TABLE test (id INT);") is False

    def test_classify_statement_ddl(self):
        """Test statement classification for DDL."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "CREATE TABLE test (id INT);"
        stmt_type = parser._classify_statement(sql)
        assert stmt_type == SqlStatementType.DDL

    def test_classify_statement_dml(self):
        """Test statement classification for DML."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "INSERT INTO test VALUES (1);"
        stmt_type = parser._classify_statement(sql)
        assert stmt_type == SqlStatementType.DML

    def test_classify_statement_query(self):
        """Test statement classification for query."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "SELECT * FROM test;"
        stmt_type = parser._classify_statement(sql)
        assert stmt_type == SqlStatementType.QUERY

    def test_classify_statement_unknown(self):
        """Test statement classification for unknown."""
        config = MySqlConfig()
        parser = RegexParser(config)

        sql = "UNKNOWN STATEMENT;"
        stmt_type = parser._classify_statement(sql)
        assert stmt_type == SqlStatementType.UNKNOWN

    def test_create_object_from_match_table(self):
        """Test object creation from match for table."""
        config = MySqlConfig()
        parser = RegexParser(config)

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
        parser = RegexParser(config)

        import re

        pattern = re.compile(r"UNKNOWN\s+(\w+)", re.IGNORECASE)
        match = pattern.search("UNKNOWN test;")
        if match:
            obj = parser._create_object_from_match(match, "unknown_pattern", "public")
            assert obj is None
