"""Tests for enhanced regex parser."""

from unittest.mock import MagicMock, patch

import pytest

from dblift.core.sql_model.base import ParseResult, SqlObject, SqlObjectType, SqlStatementType
from dblift.core.sql_parser.enhanced_regex_parser import EnhancedRegexParser
from dblift.db.plugins.mysql.parser.parser_config import MySqlConfig


class _SemanticParser(EnhancedRegexParser):
    def split_statements(self, sql_content, strict_tokenizer=False):
        from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser

        return MySqlRegexParser().split_statements(sql_content, strict_tokenizer)

    def split_for_extraction(self, sql_content, strict_tokenizer=False):
        from dblift.db.plugins.mysql.parser.mysql_regex_parser import MySqlRegexParser

        return MySqlRegexParser().split_for_extraction(sql_content, strict_tokenizer)


@pytest.mark.unit
class TestEnhancedRegexParser:
    """Test suite for enhanced regex parser."""

    def test_parser_creation(self):
        """Test parser can be created."""
        config = MySqlConfig()
        parser = _SemanticParser(config)
        assert parser is not None
        assert parser.dialect_name == "mysql"

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

    def test_extract_objects_error_handling(self):
        """Test extract_objects error handling."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        # Mock extract_objects to raise an exception in the loop
        # We'll test by patching the _create_object_from_match_enhanced to raise
        original_create = parser._create_object_from_match_enhanced
        parser._create_object_from_match_enhanced = MagicMock(side_effect=Exception("Error"))
        try:
            sql = "CREATE TABLE test (id INT);"
            objects = parser.extract_objects(sql)
            # Should handle gracefully and return empty list or partial results
            assert isinstance(objects, list)
        finally:
            parser._create_object_from_match_enhanced = original_create

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

        # Mock _classify_statement_enhanced to raise exception
        with patch.object(parser, "_classify_statement_enhanced", side_effect=Exception("Error")):
            sql = "CREATE TABLE test (id INT);"
            result = parser.parse_sql(sql)
            assert isinstance(result, ParseResult)
            assert len(result.errors) > 0 or len(result.statements) > 0

    def test_parse_sql_splitting_error(self):
        """Test parse_sql with splitting error."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        # Mock the authoritative extraction projection to raise exception.
        with patch.object(parser, "split_for_extraction", side_effect=Exception("Error")):
            sql = "CREATE TABLE test (id INT);"
            result = parser.parse_sql(sql)
            assert isinstance(result, ParseResult)
            assert len(result.errors) > 0

    def test_compile_string_patterns(self):
        """Test string pattern compilation."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        patterns = parser._compile_string_patterns()
        assert "single_quote" in patterns
        assert "double_quote" in patterns

    def test_compile_block_patterns(self):
        """Test block pattern compilation."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        patterns = parser._compile_block_patterns()
        assert "plsql_block" in patterns
        assert "procedure_block" in patterns

    def test_clean_sql(self):
        """Test SQL cleaning."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "  CREATE TABLE test (id INT);  "
        cleaned = parser._clean_sql(sql)
        assert cleaned == "CREATE TABLE test (id INT);"

    def test_is_empty_or_comment(self):
        """Test empty or comment detection."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        assert parser._is_empty_or_comment("") is True
        assert parser._is_empty_or_comment("   ") is True
        assert parser._is_empty_or_comment("-- comment") is True
        assert parser._is_empty_or_comment("CREATE TABLE test (id INT);") is False

    def test_classify_statement_enhanced_ddl(self):
        """Test enhanced statement classification for DDL."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "CREATE TABLE test (id INT);"
        stmt_type = parser._classify_statement_enhanced(sql)
        assert stmt_type == SqlStatementType.DDL

    def test_classify_statement_enhanced_dml(self):
        """Test enhanced statement classification for DML."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "INSERT INTO test VALUES (1);"
        stmt_type = parser._classify_statement_enhanced(sql)
        assert stmt_type == SqlStatementType.DML

    def test_classify_statement_enhanced_query(self):
        """Test enhanced statement classification for query."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "SELECT * FROM test;"
        stmt_type = parser._classify_statement_enhanced(sql)
        assert stmt_type == SqlStatementType.QUERY

    def test_classify_statement_enhanced_empty(self):
        """Test enhanced statement classification with empty SQL."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = ""
        stmt_type = parser._classify_statement_enhanced(sql)
        assert stmt_type == SqlStatementType.UNKNOWN

    def test_classify_statement_enhanced_block(self):
        """Test enhanced statement classification for block statements."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "CREATE PROCEDURE test() BEGIN END;"
        stmt_type = parser._classify_statement_enhanced(sql)
        assert stmt_type == SqlStatementType.DDL

    def test_remove_comments_enhanced(self):
        """Test enhanced comment removal."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        sql = "-- comment\nCREATE TABLE test (id INT);"
        cleaned = parser._remove_comments_enhanced(sql)
        assert "--" not in cleaned
        assert "CREATE TABLE" in cleaned

    def test_is_block_statement_enhanced(self):
        """Test enhanced block statement detection."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        assert parser._is_block_statement_enhanced("BEGIN END;") is True
        assert parser._is_block_statement_enhanced("CREATE TABLE test (id INT);") is False

    def test_create_object_from_match_enhanced_table(self):
        """Test enhanced object creation from match for table."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        import re

        # Create a mock match object
        pattern = re.compile(r"CREATE TABLE\s+(\w+)", re.IGNORECASE)
        match = pattern.search("CREATE TABLE test (id INT);")
        if match:
            obj = parser._create_object_from_match_enhanced(match, "create_table", "public")
            assert obj is not None
            assert obj.object_type == SqlObjectType.TABLE

    def test_create_object_from_match_enhanced_view(self):
        """Test enhanced object creation from match for view."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        import re

        pattern = re.compile(r"CREATE VIEW\s+(\w+)", re.IGNORECASE)
        match = pattern.search("CREATE VIEW test_view AS SELECT 1;")
        if match:
            obj = parser._create_object_from_match_enhanced(match, "create_view", "public")
            assert obj is not None
            assert obj.object_type == SqlObjectType.VIEW

    def test_create_object_from_match_enhanced_error(self):
        """Test enhanced object creation error handling."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        import re

        # Create a match that will cause an error
        pattern = re.compile(r"CREATE TABLE\s+(\w+)", re.IGNORECASE)
        match = pattern.search("CREATE TABLE test (id INT);")
        if match:
            # Mock normalize_identifier to raise exception
            with patch.object(config, "normalize_identifier", side_effect=Exception("Error")):
                obj = parser._create_object_from_match_enhanced(match, "create_table", "public")
                assert obj is None

    def test_get_object_type_from_pattern(self):
        """Test object type extraction from pattern name."""
        config = MySqlConfig()
        parser = _SemanticParser(config)

        assert parser._get_object_type_from_pattern("create_table") == SqlObjectType.TABLE
        assert parser._get_object_type_from_pattern("create_view") == SqlObjectType.VIEW
        assert parser._get_object_type_from_pattern("create_index") == SqlObjectType.INDEX
        assert parser._get_object_type_from_pattern("create_sequence") == SqlObjectType.SEQUENCE
        assert parser._get_object_type_from_pattern("create_procedure") == SqlObjectType.PROCEDURE
        assert parser._get_object_type_from_pattern("create_function") == SqlObjectType.FUNCTION
        assert parser._get_object_type_from_pattern("create_trigger") == SqlObjectType.TRIGGER
        assert parser._get_object_type_from_pattern("create_extension") == SqlObjectType.EXTENSION
        assert (
            parser._get_object_type_from_pattern("create_foreign_data_wrapper")
            == SqlObjectType.FOREIGN_DATA_WRAPPER
        )
        assert (
            parser._get_object_type_from_pattern("create_foreign_server")
            == SqlObjectType.FOREIGN_SERVER
        )
        assert parser._get_object_type_from_pattern("unknown_pattern") == SqlObjectType.UNKNOWN
