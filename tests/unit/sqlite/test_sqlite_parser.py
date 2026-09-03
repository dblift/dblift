"""Unit tests for SQLite parser."""

import pytest

pytestmark = [pytest.mark.unit]


class TestSQLiteRegexParser:
    """Tests for SQLite regex parser."""

    def test_split_simple_statements(self):
        """Test splitting simple SQL statements."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql = """
        CREATE TABLE users (id INTEGER PRIMARY KEY);
        INSERT INTO users (id) VALUES (1);
        SELECT * FROM users;
        """

        statements = parser.split_statements(sql)
        assert len(statements) == 3
        assert "CREATE TABLE" in statements[0]
        assert "INSERT INTO" in statements[1]
        assert "SELECT" in statements[2]

    def test_split_trigger_with_begin_end(self):
        """Test splitting trigger with BEGIN/END block."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql = """
        CREATE TRIGGER update_timestamp
        AFTER UPDATE ON users
        BEGIN
            UPDATE users SET updated_at = datetime('now') WHERE id = NEW.id;
        END;
        
        SELECT * FROM users;
        """

        statements = parser.split_statements(sql)
        assert len(statements) == 2
        assert "CREATE TRIGGER" in statements[0]
        assert "BEGIN" in statements[0]
        assert "END" in statements[0]
        assert "SELECT" in statements[1]

    def test_extract_table_from_create(self):
        """Test extracting table object from CREATE TABLE."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        stmt = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type.value == "TABLE"
        assert objects[0].name == "users"

    def test_extract_view_from_create(self):
        """Test extracting view object from CREATE VIEW."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        stmt = "CREATE VIEW active_users AS SELECT * FROM users WHERE active = 1"
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type.value == "VIEW"
        assert objects[0].name == "active_users"

    def test_extract_index_from_create(self):
        """Test extracting index object from CREATE INDEX."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        stmt = "CREATE UNIQUE INDEX idx_users_email ON users(email)"
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type.value == "INDEX"
        assert objects[0].name == "idx_users_email"

    def test_extract_trigger_from_create(self):
        """Test extracting trigger object from CREATE TRIGGER."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        stmt = """CREATE TRIGGER update_timestamp AFTER UPDATE ON users 
                  BEGIN UPDATE users SET updated_at = datetime('now'); END"""
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type.value == "TRIGGER"
        assert objects[0].name == "update_timestamp"

    def test_extract_virtual_table_from_create(self):
        """CREATE VIRTUAL TABLE must keep VIRTUAL_TABLE type (not UNKNOWN)."""
        from dblift.core.sql_model.base import SqlObjectType
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        stmt = "CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(title, body);"
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.VIRTUAL_TABLE
        assert objects[0].name == "docs"

    def test_handle_comments(self):
        """Test handling of SQL comments."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql = """
        -- This is a comment
        CREATE TABLE users (id INTEGER); -- inline comment
        /* Block
           comment */
        SELECT * FROM users;
        """

        statements = parser.split_statements(sql)
        assert len(statements) == 2

    def test_handle_quoted_semicolons(self):
        """Test handling semicolons inside strings."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql = """
        INSERT INTO logs (message) VALUES ('Error; please retry');
        SELECT * FROM logs;
        """

        statements = parser.split_statements(sql)
        assert len(statements) == 2
        assert "Error; please retry" in statements[0]


class TestSQLiteConfig:
    """Tests for SQLite dialect configuration."""

    def test_name_property(self):
        """Test dialect name property."""
        from dblift.db.plugins.sqlite.parser.parser_config import SQLiteConfig

        config = SQLiteConfig()
        assert config.name == "sqlite"

    def test_supports_features(self):
        """Test feature support flags."""
        from dblift.db.plugins.sqlite.parser.parser_config import SQLiteConfig

        config = SQLiteConfig()

        assert config.supports_dollar_quoting is False
        assert config.supports_copy_statements is False
        assert config.supports_cte_with_recursive is True
        assert config.supports_on_conflict is True
        assert config.supports_block_comments() is True
        assert config.supports_line_comments() is True

    def test_ddl_keywords(self):
        """Test DDL keywords."""
        from dblift.db.plugins.sqlite.parser.parser_config import SQLiteConfig

        config = SQLiteConfig()
        keywords = config.get_ddl_keywords()

        assert "CREATE" in keywords
        assert "ALTER" in keywords
        assert "DROP" in keywords
        assert "VACUUM" in keywords
        assert "ANALYZE" in keywords
        assert "PRAGMA" in keywords

    def test_dml_keywords(self):
        """Test DML keywords."""
        from dblift.db.plugins.sqlite.parser.parser_config import SQLiteConfig

        config = SQLiteConfig()
        keywords = config.get_dml_keywords()

        assert "INSERT" in keywords
        assert "UPDATE" in keywords
        assert "DELETE" in keywords
        assert "REPLACE" in keywords

    def test_identifier_pattern(self):
        """Test identifier pattern."""
        import re

        from dblift.db.plugins.sqlite.parser.parser_config import SQLiteConfig

        config = SQLiteConfig()
        pattern = config.get_identifier_pattern()

        # Test unquoted identifiers
        assert pattern.match("table_name")
        assert pattern.match("_underscore")

        # Test quoted identifiers
        assert pattern.match('"quoted name"')
        assert pattern.match("[bracket_quoted]")

    def test_normalize_identifier(self):
        """Test identifier normalization."""
        from dblift.db.plugins.sqlite.parser.parser_config import SQLiteConfig

        config = SQLiteConfig()

        # Unquoted - returned as-is (SQLite doesn't fold case)
        assert config.normalize_identifier("MyTable") == "MyTable"

        # Double-quoted - preserve case
        assert config.normalize_identifier('"MyTable"') == "MyTable"

        # Bracket-quoted - preserve case
        assert config.normalize_identifier("[MyTable]") == "MyTable"
