"""Unit tests for undo script generator."""

from pathlib import Path
from tempfile import TemporaryDirectory

import pytest

from core.logger import LogFactory
from core.migration.migration import Migration
from core.migration.scripting.undo_script_generator import (
    UndoScriptGenerator,
    UndoStatement,
)


class TestUndoScriptGenerator:
    """Test cases for undo script generator."""

    def test_dialect_is_required(self):
        """ADR-26 E: ``dialect`` has no default — the sole production caller
        (api/_client_operations) always passes ``client.dialect``, so the
        literal default was removed."""
        with pytest.raises(TypeError):
            UndoScriptGenerator()

    @pytest.fixture
    def generator(self):
        """Create an undo script generator instance."""
        logger = LogFactory.get_log("test")
        return UndoScriptGenerator(dialect="postgresql", logger=logger)

    def test_generate_undo_script_create_table(self, generator):
        """Test generating undo script for CREATE TABLE."""
        migration_sql = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL,
            email VARCHAR(255) UNIQUE
        );
        """

        migration = Migration(
            script_name="V1_0_1__Create_users_table.sql",
            content=migration_sql,
            version="1_0_1",
            description="Create_users_table",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        assert len(undo_statements) == 1
        assert undo_statements[0].sql.strip().startswith("DROP TABLE")
        assert "users" in undo_statements[0].sql
        assert undo_statements[0].operation_type == "CREATE"

    def test_generate_undo_script_create_index(self, generator):
        """Test generating undo script for CREATE INDEX."""
        migration_sql = """
        CREATE INDEX idx_users_email ON users(email);
        CREATE INDEX idx_users_name ON users(name);
        """

        migration = Migration(
            script_name="V1_0_2__Add_indexes.sql",
            content=migration_sql,
            version="1_0_2",
            description="Add_indexes",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        assert len(undo_statements) == 2
        assert all("DROP INDEX" in stmt.sql for stmt in undo_statements)
        assert any("idx_users_email" in stmt.sql for stmt in undo_statements)
        assert any("idx_users_name" in stmt.sql for stmt in undo_statements)

    def test_generate_undo_script_create_table_with_indexes_filtered(self, generator):
        """Test that DROP INDEX is filtered when table is dropped."""
        migration_sql = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        );
        CREATE INDEX idx_users_name ON users(name);
        CREATE INDEX idx_users_email ON users(email);
        """

        migration = Migration(
            script_name="V1_0_1__Create_users_table.sql",
            content=migration_sql,
            version="1_0_1",
            description="Create_users_table",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # Should only have DROP TABLE, indexes filtered out
        drop_table_statements = [stmt for stmt in undo_statements if "DROP TABLE" in stmt.sql]
        drop_index_statements = [stmt for stmt in undo_statements if "DROP INDEX" in stmt.sql]

        assert len(drop_table_statements) == 1
        assert len(drop_index_statements) == 0  # Filtered out

    def test_generate_undo_script_create_table_with_comment_filtered(self, generator):
        """Test that COMMENT ON TABLE is filtered when table is dropped."""
        migration_sql = """
        CREATE TABLE users (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        );
        COMMENT ON TABLE users IS 'User accounts table';
        """

        migration = Migration(
            script_name="V1_0_1__Create_users_table.sql",
            content=migration_sql,
            version="1_0_1",
            description="Create_users_table",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # Should only have DROP TABLE, comment filtered out
        drop_table_statements = [stmt for stmt in undo_statements if "DROP TABLE" in stmt.sql]
        comment_statements = [stmt for stmt in undo_statements if "COMMENT ON TABLE" in stmt.sql]

        assert len(drop_table_statements) == 1
        assert len(comment_statements) == 0  # Filtered out

    def test_generate_undo_script_insert_with_table_drop_filtered(self, generator):
        """Test that INSERT reversal is filtered when table is dropped."""
        migration_sql = """
        CREATE TABLE products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100) NOT NULL
        );
        INSERT INTO products (name) VALUES ('Product A'), ('Product B');
        """

        migration = Migration(
            script_name="V1_0_1__Create_products_table.sql",
            content=migration_sql,
            version="1_0_1",
            description="Create_products_table",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # Should only have DROP TABLE, INSERT reversal filtered out
        drop_table_statements = [stmt for stmt in undo_statements if "DROP TABLE" in stmt.sql]
        delete_statements = [stmt for stmt in undo_statements if "DELETE FROM" in stmt.sql]

        assert len(drop_table_statements) == 1
        assert len(delete_statements) == 0  # Filtered out

    def test_generate_undo_script_insert_without_table_drop(self, generator):
        """Test that INSERT reversal generates DELETE when table is not dropped."""
        migration_sql = """
        INSERT INTO products (name, price) VALUES
        ('Product A', 19.99),
        ('Product B', 29.99);
        """

        migration = Migration(
            script_name="V1_0_2__Add_products.sql",
            content=migration_sql,
            version="1_0_2",
            description="Add_products",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # Should have DELETE statement
        delete_statements = [stmt for stmt in undo_statements if "DELETE FROM" in stmt.sql]

        assert len(delete_statements) == 1
        assert "products" in delete_statements[0].sql
        assert "WHERE" in delete_statements[0].sql
        assert delete_statements[0].requires_manual_review is True

    def test_generate_undo_script_alter_table_add_column(self, generator):
        """Test generating undo script for ALTER TABLE ADD COLUMN."""
        migration_sql = """
        ALTER TABLE users ADD COLUMN email VARCHAR(255);
        ALTER TABLE users ADD COLUMN age INTEGER;
        """

        migration = Migration(
            script_name="V1_0_3__Add_columns.sql",
            content=migration_sql,
            version="1_0_3",
            description="Add_columns",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        assert len(undo_statements) == 2
        assert all("DROP COLUMN" in stmt.sql for stmt in undo_statements)
        assert any("email" in stmt.sql for stmt in undo_statements)
        assert any("age" in stmt.sql for stmt in undo_statements)

    def test_generate_undo_script_alter_table_add_constraint(self, generator):
        """Test generating undo script for ALTER TABLE ADD CONSTRAINT."""
        migration_sql = """
        ALTER TABLE users ADD CONSTRAINT uk_users_email UNIQUE (email);
        ALTER TABLE users ADD PRIMARY KEY (id);
        """

        migration = Migration(
            script_name="V1_0_4__Add_constraints.sql",
            content=migration_sql,
            version="1_0_4",
            description="Add_constraints",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # Should have at least one DROP CONSTRAINT or DROP PRIMARY KEY
        # (PRIMARY KEY might not be reversible if table already has it)
        assert len(undo_statements) >= 1
        # Should have DROP CONSTRAINT or DROP PRIMARY KEY
        assert any(
            "DROP CONSTRAINT" in stmt.sql or "DROP PRIMARY KEY" in stmt.sql
            for stmt in undo_statements
        )

    def test_generate_undo_script_create_view(self, generator):
        """Test generating undo script for CREATE VIEW."""
        migration_sql = """
        CREATE VIEW active_users AS
        SELECT * FROM users WHERE active = true;
        """

        migration = Migration(
            script_name="V1_0_5__Create_view.sql",
            content=migration_sql,
            version="1_0_5",
            description="Create_view",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        assert len(undo_statements) == 1
        assert "DROP VIEW" in undo_statements[0].sql
        assert "active_users" in undo_statements[0].sql

    def test_generate_undo_script_create_sequence(self, generator):
        """Test generating undo script for CREATE SEQUENCE."""
        migration_sql = """
        CREATE SEQUENCE user_id_seq;
        CREATE SEQUENCE order_id_seq;
        """

        migration = Migration(
            script_name="V1_0_6__Create_sequences.sql",
            content=migration_sql,
            version="1_0_6",
            description="Create_sequences",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        assert len(undo_statements) == 2
        assert all("DROP SEQUENCE" in stmt.sql for stmt in undo_statements)
        assert any("user_id_seq" in stmt.sql for stmt in undo_statements)
        assert any("order_id_seq" in stmt.sql for stmt in undo_statements)

    def test_generate_undo_script_complex_migration(self, generator):
        """Test generating undo script for complex migration with multiple objects."""
        migration_sql = """
        CREATE TABLE orders (
            id SERIAL PRIMARY KEY,
            user_id INTEGER,
            total DECIMAL(10,2)
        );
        
        CREATE INDEX idx_orders_user_id ON orders(user_id);
        CREATE INDEX idx_orders_total ON orders(total);
        
        COMMENT ON TABLE orders IS 'Customer orders';
        
        INSERT INTO orders (user_id, total) VALUES (1, 100.00);
        """

        migration = Migration(
            script_name="V1_0_7__Create_orders.sql",
            content=migration_sql,
            version="1_0_7",
            description="Create_orders",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # Should only have DROP TABLE (indexes, comment, insert filtered)
        drop_table_statements = [stmt for stmt in undo_statements if "DROP TABLE" in stmt.sql]

        assert len(drop_table_statements) == 1
        assert "orders" in drop_table_statements[0].sql

        # Verify filtered statements are not present
        assert not any("DROP INDEX" in stmt.sql for stmt in undo_statements)
        assert not any("COMMENT ON TABLE" in stmt.sql for stmt in undo_statements)
        assert not any("DELETE FROM" in stmt.sql for stmt in undo_statements)

    def test_generate_undo_script_mixed_operations(self, generator):
        """Test generating undo script for mixed operations."""
        migration_sql = """
        -- Create table
        CREATE TABLE products (
            id SERIAL PRIMARY KEY,
            name VARCHAR(100)
        );
        
        -- Add index (table exists, so index should be in undo)
        CREATE INDEX idx_products_name ON products(name);
        
        -- Add comment (table exists, so comment should be in undo)
        COMMENT ON TABLE products IS 'Product catalog';
        
        -- Insert data (table exists, so DELETE should be in undo)
        INSERT INTO products (name) VALUES ('Product A');
        """

        migration = Migration(
            script_name="V1_0_8__Add_products.sql",
            content=migration_sql,
            version="1_0_8",
            description="Add_products",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # When table is dropped, index, comment, and delete are filtered
        # So only DROP TABLE should be present
        assert len(undo_statements) == 1

        # Check that only DROP TABLE is present
        has_drop_table = any("DROP TABLE" in stmt.sql for stmt in undo_statements)
        has_drop_index = any("DROP INDEX" in stmt.sql for stmt in undo_statements)
        has_comment = any("COMMENT ON TABLE" in stmt.sql for stmt in undo_statements)
        has_delete = any("DELETE FROM" in stmt.sql for stmt in undo_statements)

        assert has_drop_table
        # These should be filtered because table is dropped
        assert not has_drop_index
        assert not has_comment
        assert not has_delete

    def test_generate_undo_script_insert_multiple_rows(self, generator):
        """Test generating undo script for INSERT with multiple rows."""
        migration_sql = """
        INSERT INTO products (name, price, category) VALUES
        ('Widget A', 19.99, 'widgets'),
        ('Gadget B', 49.99, 'gadgets'),
        ('Tool C', 99.99, 'tools');
        """

        migration = Migration(
            script_name="V1_0_9__Add_products.sql",
            content=migration_sql,
            version="1_0_9",
            description="Add_products",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # Should have DELETE statement (uses first row for WHERE clause)
        delete_statements = [stmt for stmt in undo_statements if "DELETE FROM" in stmt.sql]

        assert len(delete_statements) == 1
        assert "products" in delete_statements[0].sql
        assert "WHERE" in delete_statements[0].sql
        # Should have conditions for all columns
        assert "name" in delete_statements[0].sql.lower()
        assert "price" in delete_statements[0].sql.lower()
        assert "category" in delete_statements[0].sql.lower()

    def test_generate_undo_script_version_preservation(self, generator, tmp_path):
        """Test that version format is preserved (underscores vs dots)."""
        migration_path = tmp_path / "V1_0_1__Test_migration.sql"
        migration_path.write_text("CREATE TABLE test (id INTEGER);")

        undo_path = generator.generate_undo_script(migration_path, overwrite=True)

        # Check that version uses underscores (1_0_1) not dots (1.0.1)
        assert "U1_0_1" in undo_path.name
        assert "U1.0.1" not in undo_path.name

    def test_generate_undo_script_file_creation(self, generator, tmp_path):
        """Test that undo script file is created correctly."""
        migration_path = tmp_path / "V1_0_1__Create_table.sql"
        migration_path.write_text("CREATE TABLE users (id INTEGER);")

        undo_path = generator.generate_undo_script(migration_path, overwrite=True)

        assert undo_path.exists()
        assert undo_path.name.startswith("U1_0_1")
        assert undo_path.suffix == ".sql"

        content = undo_path.read_text()
        assert "Undo script" in content
        assert "DROP TABLE" in content

    def test_generate_undo_script_overwrite_flag(self, generator, tmp_path):
        """Test that overwrite flag works correctly."""
        migration_path = tmp_path / "V1_0_1__Create_table.sql"
        migration_path.write_text("CREATE TABLE users (id INTEGER);")

        # Generate first time
        undo_path1 = generator.generate_undo_script(migration_path, overwrite=True)
        assert undo_path1.exists()

        # Generate again with overwrite=True (should succeed)
        undo_path2 = generator.generate_undo_script(migration_path, overwrite=True)
        assert undo_path2 == undo_path1

        # Generate again with overwrite=False (should raise error)
        with pytest.raises(FileExistsError):
            generator.generate_undo_script(migration_path, overwrite=False)

    def test_generate_undo_script_invalid_migration_type(self, generator, tmp_path):
        """Test that non-versioned migrations raise error."""
        migration_path = tmp_path / "R1__Repeatable_migration.sql"
        migration_path.write_text("CREATE TABLE test (id INTEGER);")

        with pytest.raises(ValueError, match="not a versioned migration"):
            generator.generate_undo_script(migration_path)

    def test_generate_undo_script_python_migration_rejected(self, generator, tmp_path):
        """Versioned .py files are not passed to SQL undo generation."""
        migration_path = tmp_path / "V1_0_0__seed.py"
        migration_path.write_text("def upgrade():\n    pass\n")

        with pytest.raises(ValueError, match="only SQL versioned"):
            generator.generate_undo_script(migration_path)

    def test_reverse_statement_unknown_type(self, generator):
        """Test that unknown statement types are handled gracefully."""
        migration_sql = """
        -- Some comment
        SELECT * FROM users;
        """

        migration = Migration(
            script_name="V1_0_1__Test.sql",
            content=migration_sql,
            version="1_0_1",
            description="Test",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # SELECT statements should not generate undo statements
        # (or generate warnings)
        assert len(undo_statements) == 0 or all("WARNING" in stmt.sql for stmt in undo_statements)

    def test_reverse_insert_complex_values(self, generator):
        """Test reversing INSERT with complex value types."""
        migration_sql = """
        INSERT INTO products (name, price, active, created_at) VALUES
        ('Product A', 19.99, true, CURRENT_TIMESTAMP);
        """

        migration = Migration(
            script_name="V1_0_1__Add_product.sql",
            content=migration_sql,
            version="1_0_1",
            description="Add_product",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # Should attempt to generate DELETE (may have warnings for complex values)
        delete_statements = [stmt for stmt in undo_statements if "DELETE FROM" in stmt.sql]

        # May generate DELETE or warning depending on complexity
        assert len(undo_statements) > 0

    def test_generate_undo_script_reverse_order(self, generator):
        """Test that undo statements are in reverse order."""
        migration_sql = """
        CREATE TABLE users (id INTEGER);
        CREATE INDEX idx_users_id ON users(id);
        CREATE VIEW user_view AS SELECT * FROM users;
        """

        migration = Migration(
            script_name="V1_0_1__Create_objects.sql",
            content=migration_sql,
            version="1_0_1",
            description="Create_objects",
            logger=generator.logger,
        )

        undo_statements = generator._generate_undo_statements(migration)

        # INDEX is filtered because table is dropped
        # So should have VIEW and TABLE only
        assert len(undo_statements) == 2

        # Find positions
        view_pos = next(i for i, stmt in enumerate(undo_statements) if "DROP VIEW" in stmt.sql)
        table_pos = next(i for i, stmt in enumerate(undo_statements) if "DROP TABLE" in stmt.sql)

        # VIEW should come before TABLE (reverse order)
        assert view_pos < table_pos
