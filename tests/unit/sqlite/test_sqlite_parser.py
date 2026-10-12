"""Unit tests for SQLite parser."""

import pytest

pytestmark = [pytest.mark.unit]


class TestSQLiteFactsParser:
    """Tests for SQLite regex parser."""

    def test_split_simple_statements(self):
        """Test splitting simple SQL statements."""
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

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
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

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
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

        stmt = "CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT)"
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type.value == "TABLE"
        assert objects[0].name == "users"

    def test_extract_view_from_create(self):
        """Test extracting view object from CREATE VIEW."""
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

        stmt = "CREATE VIEW active_users AS SELECT * FROM users WHERE active = 1"
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type.value == "VIEW"
        assert objects[0].name == "active_users"

    def test_extract_index_from_create(self):
        """Test extracting index object from CREATE INDEX."""
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

        stmt = "CREATE UNIQUE INDEX idx_users_email ON users(email)"
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type.value == "INDEX"
        assert objects[0].name == "idx_users_email"

    def test_extract_trigger_from_create(self):
        """Test extracting trigger object from CREATE TRIGGER."""
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

        stmt = """CREATE TRIGGER update_timestamp AFTER UPDATE ON users 
                  BEGIN UPDATE users SET updated_at = datetime('now'); END"""
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type.value == "TRIGGER"
        assert objects[0].name == "update_timestamp"

    def test_extract_virtual_table_from_create(self):
        """CREATE VIRTUAL TABLE must keep VIRTUAL_TABLE type (not UNKNOWN)."""
        from dblift.core.sql_model.base import SqlObjectType
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

        stmt = "CREATE VIRTUAL TABLE IF NOT EXISTS docs USING fts5(title, body);"
        objects = parser.extract_objects(stmt)

        assert len(objects) == 1
        assert objects[0].object_type == SqlObjectType.VIRTUAL_TABLE
        assert objects[0].name == "docs"

    def test_handle_comments(self):
        """Test handling of SQL comments."""
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

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
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        parser = SQLiteFactsParser()

        sql = """
        INSERT INTO logs (message) VALUES ('Error; please retry');
        SELECT * FROM logs;
        """

        statements = parser.split_statements(sql)
        assert len(statements) == 2
        assert "Error; please retry" in statements[0]


class TestSQLiteFactsReader:
    """The removed pattern table's representative inputs remain in the facts corpus."""

    @pytest.mark.parametrize(
        "sql, expected_type, expected_name",
        [
            ('CREATE TABLE "MyTable" (id INT)', "TABLE", "MyTable"),
            ("CREATE TABLE [bracket_quoted] (id INT)", "TABLE", "bracket_quoted"),
            ("CREATE VIEW v AS SELECT 1", "VIEW", "v"),
            ("CREATE INDEX ix ON t (id)", "INDEX", "ix"),
            ("UPDATE MyTable SET id = 1", "TABLE", "MyTable"),
            ("DELETE FROM MyTable", "TABLE", "MyTable"),
        ],
    )
    def test_named_object(self, sql, expected_type, expected_name):
        from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

        objects = SQLiteFactsParser().extract_objects(sql)
        assert [(obj.object_type.value, obj.name) for obj in objects] == [
            (expected_type, expected_name)
        ]
