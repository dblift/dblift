"""
Test SQLite SQL parsing integration.

These tests verify that the SQLite parser correctly handles
SQLite-specific SQL including:
- Basic DDL statements
- Triggers with BEGIN/END blocks
- Views
- Indexes with various options
- Comments and unusual formatting

Unlike other database parsers, SQLite tests don't require Docker
since SQLite is a file-based database using Python's built-in sqlite3.

Tests are organized into two categories:
1. Direct parser tests (TestSQLiteParser) - Test parser functionality directly
2. CLI-based tests (TestSQLiteParserCLI) - Test through CLI like other databases
"""

import os
import sqlite3
import tempfile
from pathlib import Path

import pytest

from tests.integration.helpers.cli_runner_direct import DBLiftCLIDirect as DBLiftCLI
from tests.integration.helpers.migration_helper import create_config, create_migration


@pytest.fixture
def sqlite_db():
    """Create a temporary SQLite database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".sqlite", delete=False) as f:
        db_path = f.name

    conn = sqlite3.connect(db_path)
    yield {"path": db_path, "connection": conn, "type": "sqlite", "schema": "main"}

    conn.close()
    if os.path.exists(db_path):
        os.unlink(db_path)


@pytest.fixture
def sqlite_container(tmp_path):
    """
    Create a SQLite 'container' configuration (file-based, no Docker needed).

    This fixture mimics the pattern used by other database containers
    but uses a temporary SQLite file instead of Docker.
    """
    db_path = tmp_path / "test_database.sqlite"

    yield {
        "type": "sqlite",
        "path": str(db_path),
        "schema": "main",
    }

    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def sqlite_config(sqlite_db, tmp_path):
    """Create SQLite configuration for testing."""
    from dblift.config import DbliftConfig

    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir(parents=True, exist_ok=True)

    config_dict = {
        "database": {
            "type": "sqlite",
            "path": sqlite_db["path"],
        },
        "migrations": {
            "directory": str(migrations_dir),
            "table": "dblift_schema_history",
        },
        "logging": {
            "level": "DEBUG",
        },
    }

    return DbliftConfig.from_dict(config_dict)


@pytest.mark.integration
class TestSQLiteParser:
    """Test SQLite parsing through direct execution."""

    def test_basic_table_creation(self, sqlite_db):
        """Test parsing and executing basic CREATE TABLE."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        
        CREATE TABLE posts (
            id INTEGER PRIMARY KEY,
            user_id INTEGER NOT NULL,
            title TEXT NOT NULL,
            content TEXT,
            FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
        );
        """

        statements = parser.split_statements(sql_script)
        assert len(statements) == 2

        conn = sqlite_db["connection"]
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()

        # Verify tables were created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table' ORDER BY name")
        tables = [row[0] for row in cursor.fetchall()]
        assert "users" in tables
        assert "posts" in tables

    def test_trigger_with_begin_end(self, sqlite_db):
        """Test parsing and executing trigger with BEGIN/END block."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        CREATE TABLE logs (
            id INTEGER PRIMARY KEY,
            action TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        
        CREATE TABLE users (
            id INTEGER PRIMARY KEY,
            name TEXT,
            updated_at TEXT
        );
        
        CREATE TRIGGER update_user_timestamp
        AFTER UPDATE ON users
        BEGIN
            INSERT INTO logs (action) VALUES ('User updated: ' || NEW.name);
            UPDATE users SET updated_at = datetime('now') WHERE id = NEW.id;
        END;
        """

        statements = parser.split_statements(sql_script)
        # Should have: CREATE TABLE logs, CREATE TABLE users, CREATE TRIGGER
        assert len(statements) == 3

        conn = sqlite_db["connection"]
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()

        # Verify trigger was created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='trigger'")
        triggers = [row[0] for row in cursor.fetchall()]
        assert "update_user_timestamp" in triggers

    def test_view_creation(self, sqlite_db):
        """Test parsing and executing CREATE VIEW."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            price REAL,
            active INTEGER DEFAULT 1
        );
        
        CREATE VIEW active_products AS
        SELECT id, name, price
        FROM products
        WHERE active = 1;
        
        CREATE VIEW expensive_products AS
        SELECT * FROM products WHERE price > 100;
        """

        statements = parser.split_statements(sql_script)
        assert len(statements) == 3

        conn = sqlite_db["connection"]
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()

        # Verify views were created
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='view' ORDER BY name")
        views = [row[0] for row in cursor.fetchall()]
        assert "active_products" in views
        assert "expensive_products" in views

    def test_index_creation(self, sqlite_db):
        """Test parsing and executing CREATE INDEX statements."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            order_date TEXT,
            status TEXT,
            total REAL
        );
        
        CREATE INDEX idx_orders_customer ON orders(customer_id);
        CREATE UNIQUE INDEX idx_orders_date_customer ON orders(order_date, customer_id);
        CREATE INDEX idx_orders_status ON orders(status) WHERE status != 'completed';
        """

        statements = parser.split_statements(sql_script)
        assert len(statements) == 4

        conn = sqlite_db["connection"]
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()

        # Verify indexes were created
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%' ORDER BY name"
        )
        indexes = [row[0] for row in cursor.fetchall()]
        assert "idx_orders_customer" in indexes
        assert "idx_orders_date_customer" in indexes
        assert "idx_orders_status" in indexes

    def test_comments_handling(self, sqlite_db):
        """Test parsing SQL with various comment styles."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        -- This is a line comment
        CREATE TABLE config (
            key TEXT PRIMARY KEY,  -- inline comment
            value TEXT
        );
        
        /* This is a 
           block comment */
        INSERT INTO config (key, value) VALUES ('version', '1.0');
        
        -- Another comment
        SELECT * FROM config;
        """

        statements = parser.split_statements(sql_script)
        assert len(statements) == 3

        conn = sqlite_db["connection"]
        # Execute CREATE TABLE and INSERT
        conn.execute(statements[0])
        conn.execute(statements[1])
        conn.commit()

        # Verify data
        cursor = conn.execute("SELECT value FROM config WHERE key = 'version'")
        row = cursor.fetchone()
        assert row[0] == "1.0"

    def test_string_with_semicolons(self, sqlite_db):
        """Test parsing SQL with semicolons inside string literals."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        CREATE TABLE messages (
            id INTEGER PRIMARY KEY,
            content TEXT
        );
        
        INSERT INTO messages (content) VALUES ('Hello; World; Test');
        INSERT INTO messages (content) VALUES ('Line1;
        Line2;
        Line3');
        """

        statements = parser.split_statements(sql_script)
        assert len(statements) == 3

        conn = sqlite_db["connection"]
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()

        # Verify data preserved semicolons
        cursor = conn.execute("SELECT content FROM messages ORDER BY id")
        rows = cursor.fetchall()
        assert "Hello; World; Test" in rows[0][0]
        assert "Line1;" in rows[1][0]

    def test_complex_trigger(self, sqlite_db):
        """Test complex trigger with multiple statements in body."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        CREATE TABLE inventory (
            product_id INTEGER PRIMARY KEY,
            quantity INTEGER DEFAULT 0
        );
        
        CREATE TABLE inventory_log (
            id INTEGER PRIMARY KEY,
            product_id INTEGER,
            old_qty INTEGER,
            new_qty INTEGER,
            change_date TEXT
        );
        
        CREATE TRIGGER log_inventory_changes
        AFTER UPDATE OF quantity ON inventory
        WHEN OLD.quantity != NEW.quantity
        BEGIN
            INSERT INTO inventory_log (product_id, old_qty, new_qty, change_date)
            VALUES (NEW.product_id, OLD.quantity, NEW.quantity, datetime('now'));
        END;
        
        INSERT INTO inventory (product_id, quantity) VALUES (1, 100);
        """

        statements = parser.split_statements(sql_script)
        assert len(statements) == 4

        conn = sqlite_db["connection"]
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()

        # Update inventory to trigger the log
        conn.execute("UPDATE inventory SET quantity = 90 WHERE product_id = 1")
        conn.commit()

        # Verify trigger executed
        cursor = conn.execute("SELECT old_qty, new_qty FROM inventory_log WHERE product_id = 1")
        row = cursor.fetchone()
        assert row[0] == 100
        assert row[1] == 90

    def test_cte_with_recursive(self, sqlite_db):
        """Test parsing Common Table Expression with RECURSIVE."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT,
            parent_id INTEGER
        );
        
        INSERT INTO categories VALUES (1, 'Root', NULL);
        INSERT INTO categories VALUES (2, 'Child1', 1);
        INSERT INTO categories VALUES (3, 'Child2', 1);
        INSERT INTO categories VALUES (4, 'Grandchild', 2);
        
        -- CTE query to get hierarchy
        WITH RECURSIVE category_tree AS (
            SELECT id, name, parent_id, 0 as level
            FROM categories
            WHERE parent_id IS NULL
            UNION ALL
            SELECT c.id, c.name, c.parent_id, ct.level + 1
            FROM categories c
            JOIN category_tree ct ON c.parent_id = ct.id
        )
        SELECT * FROM category_tree ORDER BY level, name;
        """

        statements = parser.split_statements(sql_script)
        # CREATE TABLE + 4 INSERTs + 1 CTE query
        assert len(statements) == 6

        conn = sqlite_db["connection"]
        for stmt in statements[:-1]:  # Execute all except the CTE query
            conn.execute(stmt)
        conn.commit()

        # Execute CTE query
        cursor = conn.execute(statements[-1])
        rows = cursor.fetchall()
        assert len(rows) == 4  # Root, Child1, Child2, Grandchild

    def test_on_conflict_clause(self, sqlite_db):
        """Test parsing INSERT with ON CONFLICT clause."""
        from dblift.db.plugins.sqlite.parser.sqlite_regex_parser import SQLiteRegexParser

        parser = SQLiteRegexParser()

        sql_script = """
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        
        INSERT INTO settings (key, value, updated_at) 
        VALUES ('theme', 'dark', datetime('now'))
        ON CONFLICT(key) DO UPDATE SET 
            value = excluded.value,
            updated_at = datetime('now');
        
        INSERT OR REPLACE INTO settings (key, value, updated_at)
        VALUES ('language', 'en', datetime('now'));
        """

        statements = parser.split_statements(sql_script)
        assert len(statements) == 3

        conn = sqlite_db["connection"]
        for stmt in statements:
            conn.execute(stmt)
        conn.commit()

        # Verify settings
        cursor = conn.execute("SELECT COUNT(*) FROM settings")
        count = cursor.fetchone()[0]
        assert count == 2


def verify_sqlite_table_exists(db_path: str, table_name: str) -> bool:
    """Verify a table exists in the SQLite database."""
    conn = sqlite3.connect(db_path)
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name=?", (table_name,)
        )
        return cursor.fetchone() is not None
    finally:
        conn.close()


@pytest.mark.integration
class TestSQLiteParserCLI:
    """
    Test SQLite SQL parsing through CLI.

    These tests follow the same pattern as other database parser tests
    (MySQL, Oracle, SQL Server) - using the CLI to run migrations.
    """

    def test_basic_table_migration(self, sqlite_container, tmp_path):
        """Test basic table creation through CLI migration."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        sql_script = """
        CREATE TABLE users (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            username TEXT NOT NULL UNIQUE,
            email TEXT,
            created_at TEXT DEFAULT (datetime('now'))
        );
        
        INSERT INTO users (username, email) VALUES ('admin', 'admin@test.com');
        INSERT INTO users (username, email) VALUES ('user1', 'user1@test.com');
        """

        create_migration(migrations_dir, "V1_0_0__create_users.sql", sql_script)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"
        assert verify_sqlite_table_exists(sqlite_container["path"], "users")

    def test_trigger_migration(self, sqlite_container, tmp_path):
        """Test trigger creation through CLI migration."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        sql_script = """
        CREATE TABLE audit_log (
            id INTEGER PRIMARY KEY,
            action TEXT,
            timestamp TEXT DEFAULT (datetime('now'))
        );
        
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            name TEXT,
            price REAL
        );
        
        CREATE TRIGGER log_product_insert
        AFTER INSERT ON products
        BEGIN
            INSERT INTO audit_log (action) VALUES ('Product added: ' || NEW.name);
        END;
        """

        create_migration(migrations_dir, "V1_0_0__trigger.sql", sql_script)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"
        assert verify_sqlite_table_exists(sqlite_container["path"], "products")
        assert verify_sqlite_table_exists(sqlite_container["path"], "audit_log")

    def test_view_migration(self, sqlite_container, tmp_path):
        """Test view creation through CLI migration."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        sql_script = """
        CREATE TABLE orders (
            id INTEGER PRIMARY KEY,
            customer_id INTEGER,
            total REAL,
            status TEXT DEFAULT 'pending'
        );
        
        CREATE VIEW pending_orders AS
        SELECT id, customer_id, total
        FROM orders
        WHERE status = 'pending';
        
        CREATE VIEW high_value_orders AS
        SELECT * FROM orders WHERE total > 1000;
        """

        create_migration(migrations_dir, "V1_0_0__views.sql", sql_script)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"

    def test_index_migration(self, sqlite_container, tmp_path):
        """Test index creation through CLI migration."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        sql_script = """
        CREATE TABLE customers (
            id INTEGER PRIMARY KEY,
            email TEXT UNIQUE,
            name TEXT,
            country TEXT
        );
        
        CREATE INDEX idx_customers_name ON customers(name);
        CREATE INDEX idx_customers_country ON customers(country);
        CREATE UNIQUE INDEX idx_customers_email ON customers(email);
        """

        create_migration(migrations_dir, "V1_0_0__indexes.sql", sql_script)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"
        assert verify_sqlite_table_exists(sqlite_container["path"], "customers")

    def test_foreign_key_migration(self, sqlite_container, tmp_path):
        """Test foreign key constraints through CLI migration."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        sql_script = """
        CREATE TABLE departments (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL
        );
        
        CREATE TABLE employees (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL,
            department_id INTEGER,
            FOREIGN KEY (department_id) REFERENCES departments(id) ON DELETE SET NULL
        );
        
        INSERT INTO departments (id, name) VALUES (1, 'Engineering');
        INSERT INTO departments (id, name) VALUES (2, 'Sales');
        INSERT INTO employees (name, department_id) VALUES ('John', 1);
        """

        create_migration(migrations_dir, "V1_0_0__foreign_keys.sql", sql_script)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"
        assert verify_sqlite_table_exists(sqlite_container["path"], "departments")
        assert verify_sqlite_table_exists(sqlite_container["path"], "employees")

    def test_complex_trigger_migration(self, sqlite_container, tmp_path):
        """Test complex trigger with multiple statements through CLI."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        sql_script = """
        CREATE TABLE inventory (
            product_id INTEGER PRIMARY KEY,
            quantity INTEGER DEFAULT 0,
            last_updated TEXT
        );
        
        CREATE TABLE inventory_changes (
            id INTEGER PRIMARY KEY,
            product_id INTEGER,
            old_quantity INTEGER,
            new_quantity INTEGER,
            changed_at TEXT
        );
        
        CREATE TRIGGER track_inventory_changes
        AFTER UPDATE OF quantity ON inventory
        WHEN OLD.quantity != NEW.quantity
        BEGIN
            INSERT INTO inventory_changes (product_id, old_quantity, new_quantity, changed_at)
            VALUES (NEW.product_id, OLD.quantity, NEW.quantity, datetime('now'));
            UPDATE inventory SET last_updated = datetime('now') WHERE product_id = NEW.product_id;
        END;
        """

        create_migration(migrations_dir, "V1_0_0__complex_trigger.sql", sql_script)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"

    def test_multiple_migrations(self, sqlite_container, tmp_path):
        """Test running multiple migrations in sequence through CLI."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        # First migration - create tables
        create_migration(
            migrations_dir,
            "V1_0_0__initial.sql",
            """
        CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT);
        CREATE TABLE posts (id INTEGER PRIMARY KEY, user_id INTEGER, title TEXT);
        """,
        )

        # Second migration - add indexes
        create_migration(
            migrations_dir,
            "V1_0_1__add_indexes.sql",
            """
        CREATE INDEX idx_posts_user ON posts(user_id);
        """,
        )

        # Third migration - add view
        create_migration(
            migrations_dir,
            "V1_0_2__add_view.sql",
            """
        CREATE VIEW user_posts AS
        SELECT u.name, p.title
        FROM users u
        JOIN posts p ON u.id = p.user_id;
        """,
        )

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"
        assert "V1_0_0__initial.sql" in result.output
        assert "V1_0_1__add_indexes.sql" in result.output
        assert "V1_0_2__add_view.sql" in result.output

    def test_cte_migration(self, sqlite_container, tmp_path):
        """Test Common Table Expression (WITH clause) through CLI."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        sql_script = """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT,
            parent_id INTEGER
        );
        
        INSERT INTO categories VALUES (1, 'Root', NULL);
        INSERT INTO categories VALUES (2, 'Electronics', 1);
        INSERT INTO categories VALUES (3, 'Computers', 2);
        INSERT INTO categories VALUES (4, 'Laptops', 3);
        
        -- Create a view using recursive CTE
        CREATE VIEW category_paths AS
        WITH RECURSIVE cat_path AS (
            SELECT id, name, parent_id, name as path
            FROM categories
            WHERE parent_id IS NULL
            UNION ALL
            SELECT c.id, c.name, c.parent_id, cp.path || ' > ' || c.name
            FROM categories c
            JOIN cat_path cp ON c.parent_id = cp.id
        )
        SELECT * FROM cat_path;
        """

        create_migration(migrations_dir, "V1_0_0__cte.sql", sql_script)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"

    def test_on_conflict_migration(self, sqlite_container, tmp_path):
        """Test ON CONFLICT clause (UPSERT) through CLI."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()

        config_file = create_config(tmp_path, sqlite_container, migrations_dir=migrations_dir)

        sql_script = """
        CREATE TABLE settings (
            key TEXT PRIMARY KEY,
            value TEXT,
            updated_at TEXT
        );
        
        INSERT INTO settings (key, value) VALUES ('theme', 'light');
        
        -- UPSERT pattern
        INSERT INTO settings (key, value, updated_at)
        VALUES ('theme', 'dark', datetime('now'))
        ON CONFLICT(key) DO UPDATE SET
            value = excluded.value,
            updated_at = datetime('now');
        """

        create_migration(migrations_dir, "V1_0_0__on_conflict.sql", sql_script)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"
