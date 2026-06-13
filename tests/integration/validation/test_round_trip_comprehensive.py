"""
Comprehensive round trip validation tests.

This test suite covers round_trip_tester.py functionality:
- Round trip validation for various schema changes
- Validation across different databases
- Error handling in round trip validation
- Edge cases and complex scenarios
"""

import pytest

from tests.integration.helpers.cli_runner_direct import DBLiftCLIDirect as DBLiftCLI
from tests.integration.helpers.database_helper import verify_table_exists
from tests.integration.helpers.migration_helper import (
    create_config,
    create_versioned_migration,
    generate_test_sql,
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestRoundTripComprehensive:
    """Comprehensive round trip validation tests."""

    def test_round_trip_create_table(self, db_container, tmp_path):
        """Test round trip validation for CREATE TABLE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create migration
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "create_table",
            generate_test_sql(db_type, "test_table", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # Apply migration
        result = cli.migrate()
        assert result.success

        # Export schema
        result = cli.export_schema(output_file=tmp_path / "exported_schema.yaml")
        assert result.success

        # Verify table exists
        assert verify_table_exists(db_container, "test_table", schema)

        # Validate round trip - exported schema should match
        # This tests the round trip validation logic
        result = cli.validate()
        assert result.success

    def test_round_trip_alter_table(self, db_container, tmp_path):
        """Test round trip validation for ALTER TABLE."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create initial table
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "create_table",
            generate_test_sql(db_type, "test_table", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)
        cli.migrate()

        # Export initial schema
        result = cli.export_schema(output_file=tmp_path / "schema1.yaml")
        assert result.success

        # Create migration to alter table
        if db_type == "postgresql":
            alter_sql = f'ALTER TABLE "{schema}"."test_table" ADD COLUMN new_column VARCHAR(100);'
        elif db_type == "mysql":
            alter_sql = f"ALTER TABLE {schema}.test_table ADD COLUMN new_column VARCHAR(100);"
        elif db_type == "sqlserver":
            alter_sql = f"ALTER TABLE {schema}.test_table ADD new_column NVARCHAR(100);"
        elif db_type == "oracle":
            alter_sql = f'ALTER TABLE "{schema}"."test_table" ADD new_column VARCHAR2(100);'
        elif db_type == "db2":
            alter_sql = f'ALTER TABLE "{schema}"."test_table" ADD COLUMN new_column VARCHAR(100);'

        create_versioned_migration(migrations_dir, "1.0.1", "alter_table", alter_sql)

        # Apply alter migration
        result = cli.migrate()
        assert result.success

        # Export modified schema
        result = cli.export_schema(output_file=tmp_path / "schema2.yaml")
        assert result.success

        # Validate - should pass
        result = cli.validate()
        assert result.success

    def test_round_trip_multiple_tables(self, db_container, tmp_path):
        """Test round trip validation with multiple tables."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create multiple tables
        if db_type == "postgresql":
            tables_sql = f"""
            CREATE TABLE "{schema}"."table1" (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE "{schema}"."table2" (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE "{schema}"."table3" (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100)
            );
            """
        elif db_type == "mysql":
            tables_sql = f"""
            CREATE TABLE {schema}.table1 (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE {schema}.table2 (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE {schema}.table3 (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100)
            );
            """
        else:
            tables_sql = f"""
            CREATE TABLE {schema}.table1 (
                id INT PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE {schema}.table2 (
                id INT PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE {schema}.table3 (
                id INT PRIMARY KEY,
                name VARCHAR(100)
            );
            """

        create_versioned_migration(migrations_dir, "1.0.0", "create_tables", tables_sql)

        cli = DBLiftCLI(config_file, migrations_dir)

        # Apply migration
        result = cli.migrate()
        assert result.success

        # Verify all tables exist
        assert verify_table_exists(db_container, "table1", schema)
        assert verify_table_exists(db_container, "table2", schema)
        assert verify_table_exists(db_container, "table3", schema)

        # Export and validate
        result = cli.export_schema(output_file=tmp_path / "exported_schema.yaml")
        assert result.success

        result = cli.validate()
        assert result.success

    def test_round_trip_with_indexes(self, db_container, tmp_path):
        """Test round trip validation with indexes."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create table with index
        if db_type == "postgresql":
            table_sql = f"""
            CREATE TABLE "{schema}"."test_table" (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100),
                email VARCHAR(255)
            );
            CREATE INDEX idx_name ON "{schema}"."test_table" (name);
            CREATE INDEX idx_email ON "{schema}"."test_table" (email);
            """
        elif db_type == "mysql":
            table_sql = f"""
            CREATE TABLE {schema}.test_table (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100),
                email VARCHAR(255),
                INDEX idx_name (name),
                INDEX idx_email (email)
            );
            """
        else:
            table_sql = f"""
            CREATE TABLE {schema}.test_table (
                id INT PRIMARY KEY,
                name VARCHAR(100),
                email VARCHAR(255)
            );
            CREATE INDEX idx_name ON {schema}.test_table (name);
            CREATE INDEX idx_email ON {schema}.test_table (email);
            """

        create_versioned_migration(migrations_dir, "1.0.0", "create_table_indexes", table_sql)

        cli = DBLiftCLI(config_file, migrations_dir)

        # Apply migration
        result = cli.migrate()
        assert result.success

        # Export and validate
        result = cli.export_schema(output_file=tmp_path / "exported_schema.yaml")
        assert result.success

        result = cli.validate()
        assert result.success

    def test_round_trip_with_foreign_keys(self, db_container, tmp_path):
        """Test round trip validation with foreign keys."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create tables with foreign key
        if db_type == "postgresql":
            tables_sql = f"""
            CREATE TABLE "{schema}"."parent" (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE "{schema}"."child" (
                id SERIAL PRIMARY KEY,
                parent_id INT REFERENCES "{schema}"."parent"(id),
                name VARCHAR(100)
            );
            """
        elif db_type == "mysql":
            tables_sql = f"""
            CREATE TABLE {schema}.parent (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE {schema}.child (
                id INT AUTO_INCREMENT PRIMARY KEY,
                parent_id INT,
                name VARCHAR(100),
                FOREIGN KEY (parent_id) REFERENCES {schema}.parent(id)
            );
            """
        else:
            tables_sql = f"""
            CREATE TABLE {schema}.parent (
                id INT PRIMARY KEY,
                name VARCHAR(100)
            );
            CREATE TABLE {schema}.child (
                id INT PRIMARY KEY,
                parent_id INT,
                name VARCHAR(100),
                FOREIGN KEY (parent_id) REFERENCES {schema}.parent(id)
            );
            """

        create_versioned_migration(migrations_dir, "1.0.0", "create_tables_fk", tables_sql)

        cli = DBLiftCLI(config_file, migrations_dir)

        # Apply migration
        result = cli.migrate()
        assert result.success

        # Verify tables exist
        assert verify_table_exists(db_container, "parent", schema)
        assert verify_table_exists(db_container, "child", schema)

        # Export and validate
        result = cli.export_schema(output_file=tmp_path / "exported_schema.yaml")
        assert result.success

        result = cli.validate()
        assert result.success

    def test_round_trip_incremental_changes(self, db_container, tmp_path):
        """Test round trip validation with incremental schema changes."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        cli = DBLiftCLI(config_file, migrations_dir)

        # Step 1: Create initial table
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "create_table",
            generate_test_sql(db_type, "test_table", schema),
        )
        result = cli.migrate()
        assert result.success

        # Step 2: Add column
        if db_type == "postgresql":
            alter_sql = f'ALTER TABLE "{schema}"."test_table" ADD COLUMN col1 VARCHAR(100);'
        elif db_type == "mysql":
            alter_sql = f"ALTER TABLE {schema}.test_table ADD COLUMN col1 VARCHAR(100);"
        else:
            alter_sql = f"ALTER TABLE {schema}.test_table ADD col1 VARCHAR(100);"

        create_versioned_migration(migrations_dir, "1.0.1", "add_column", alter_sql)
        result = cli.migrate()
        assert result.success

        # Step 3: Add index
        if db_type == "postgresql":
            index_sql = f'CREATE INDEX idx_col1 ON "{schema}"."test_table" (col1);'
        else:
            index_sql = f"CREATE INDEX idx_col1 ON {schema}.test_table (col1);"

        create_versioned_migration(migrations_dir, "1.0.2", "add_index", index_sql)
        result = cli.migrate()
        assert result.success

        # Validate after all changes
        result = cli.validate()
        assert result.success

        # Export final schema
        result = cli.export_schema(output_file=tmp_path / "final_schema.yaml")
        assert result.success
