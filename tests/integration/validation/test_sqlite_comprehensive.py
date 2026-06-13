"""
Comprehensive SQLite validation tests.

Tests that combine multiple SQLite features to ensure they work together correctly.
"""

import pytest

from core.introspection.introspector_factory import IntrospectorFactory
from core.logger import ConsoleLog
from core.validation.round_trip_tester import RoundTripTester


@pytest.fixture
def sqlite_test_db(tmp_path):
    """Create a temporary SQLite database for testing."""
    db_path = tmp_path / "test_comprehensive.sqlite"

    yield {
        "type": "sqlite",
        "path": str(db_path),
        "schema": "main",
    }

    # Cleanup
    if db_path.exists():
        db_path.unlink()


@pytest.fixture
def sqlite_provider(sqlite_test_db):
    """Create SQLite provider for testing."""
    from config import DbliftConfig
    from config.database_config import SQLiteConfig
    from core.logger import ConsoleLog
    from db.plugins.sqlite.provider import SQLiteProvider

    db_config = SQLiteConfig(
        type="sqlite",
        path=sqlite_test_db["path"],
        schema=sqlite_test_db["schema"],
    )
    config = DbliftConfig(database=db_config)
    log = ConsoleLog("sqlite_comprehensive_test", enable_debug=False)
    provider = SQLiteProvider(config, log)
    provider.create_connection()

    # Enable foreign key enforcement
    provider.execute_statement("PRAGMA foreign_keys = ON")
    provider.connection.commit()

    yield provider

    if hasattr(provider, "close"):
        provider.close()


@pytest.mark.integration
class TestSQLiteComprehensive:
    """Comprehensive SQLite feature combination tests."""

    def test_all_features_combined(self, sqlite_provider):
        """Test table with all SQLite features: PK, FK, CHECK, generated columns, indexes."""
        # Create parent table
        create_parent = """
        CREATE TABLE categories (
            id INTEGER PRIMARY KEY,
            name TEXT NOT NULL UNIQUE,
            description TEXT,
            CHECK (length(name) > 0)
        )
        """

        # Create child table with all features
        create_child = """
        CREATE TABLE products (
            id INTEGER PRIMARY KEY,
            category_id INTEGER NOT NULL,
            name TEXT NOT NULL,
            price REAL NOT NULL,
            discount REAL DEFAULT 0,
            total_price REAL GENERATED ALWAYS AS (price * (1 - discount)) STORED,
            status TEXT DEFAULT 'active',
            created_at TEXT DEFAULT (datetime('now')),
            CHECK (price > 0),
            CHECK (discount >= 0 AND discount <= 1),
            FOREIGN KEY (category_id) REFERENCES categories(id) ON DELETE CASCADE
        )
        """

        # Create indexes
        create_indexes = [
            "CREATE INDEX idx_products_category ON products(category_id)",
            "CREATE INDEX idx_products_price ON products(price) WHERE status = 'active'",
            "CREATE INDEX idx_products_name_lower ON products(LOWER(name))",
        ]

        sqlite_provider.execute_statement(create_parent)
        sqlite_provider.execute_statement(create_child)
        for idx_sql in create_indexes:
            sqlite_provider.execute_statement(idx_sql)
        sqlite_provider.connection.commit()

        # Run round-trip test
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)

        tester = RoundTripTester(
            source_provider=sqlite_provider,
            test_provider=sqlite_provider,
            source_schema="main",
            test_schema="main_test",
            introspector=introspector,
            test_object_types=["tables", "indexes"],
        )

        results = tester.run_round_trip_test()

        # Verify success
        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )
        assert results["tables"]["original_count"] == 2
        assert results["indexes"]["original_count"] == 3

    def test_complex_schema_round_trip(self, sqlite_provider):
        """Test complex schema with multiple tables, constraints, and indexes."""
        # Create schema with multiple related tables
        statements = [
            """
            CREATE TABLE users (
                id INTEGER PRIMARY KEY,
                username TEXT NOT NULL UNIQUE,
                email TEXT NOT NULL,
                age INTEGER,
                CHECK (age >= 0 AND age < 150),
                CHECK (email LIKE '%@%')
            )
            """,
            """
            CREATE TABLE posts (
                id INTEGER PRIMARY KEY,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                content TEXT,
                published INTEGER DEFAULT 0,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
            """
            CREATE TABLE comments (
                id INTEGER PRIMARY KEY,
                post_id INTEGER NOT NULL,
                user_id INTEGER NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT DEFAULT (datetime('now')),
                FOREIGN KEY (post_id) REFERENCES posts(id) ON DELETE CASCADE,
                FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
            )
            """,
            # Indexes
            "CREATE INDEX idx_posts_user ON posts(user_id)",
            "CREATE INDEX idx_posts_published ON posts(published) WHERE published = 1",
            "CREATE INDEX idx_comments_post ON comments(post_id)",
            "CREATE INDEX idx_users_email_lower ON users(LOWER(email))",
        ]

        for stmt in statements:
            sqlite_provider.execute_statement(stmt)
        sqlite_provider.connection.commit()

        # Run round-trip test
        log = ConsoleLog("test", enable_debug=False)
        introspector = IntrospectorFactory.create(sqlite_provider, log=log)

        tester = RoundTripTester(
            source_provider=sqlite_provider,
            test_provider=sqlite_provider,
            source_schema="main",
            test_schema="main_test",
            introspector=introspector,
            test_object_types=["tables", "indexes"],
        )

        results = tester.run_round_trip_test()

        assert results["success"], (
            f"Round-trip failed. Errors: {results.get('errors', [])}, "
            f"Differences: {results.get('tables', {}).get('differences', [])}"
        )
        assert results["tables"]["original_count"] == 3
        assert results["indexes"]["original_count"] == 4
