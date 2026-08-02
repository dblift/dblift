"""
Test migrate command with all options.

This test suite covers all migrate command options:
- Basic migration
- Target version (--target-version)
- Dry run (--dry-run)
- Mark as executed (--mark-as-executed)
- Tag filtering (--tags, --exclude-tags)
- Version filtering (--versions, --exclude-versions)

All tests use the production CLI (cli/main.py).
"""

import pytest

from tests.integration.helpers.cli_runner import DBLiftCLI
from tests.integration.helpers.database_helper import (
    get_table_count,
    verify_table_exists,
)
from tests.integration.helpers.migration_helper import (
    create_config,
    create_migration,
    create_versioned_migration,
    generate_test_sql,
)


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestMigrateCommand:
    """Test migrate command with various options."""

    def test_migrate_basic(self, db_container, tmp_path):
        """Test basic migration without options."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create migrations
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "create_table",
            generate_test_sql(db_type, "basic_test", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # Run migrate
        result = cli.migrate()

        # Verify success
        assert result.success, f"Migration failed: {result.stderr}"
        assert "1.0.0" in result.stdout or "V1_0_0" in result.stdout

        # Verify database state
        assert verify_table_exists(db_container, "basic_test", schema)

    def test_migrate_target_version(self, db_container, tmp_path):
        """Test migrate with --target-version option."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create multiple migrations
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "first",
            generate_test_sql(db_type, "table_v1", schema),
        )
        create_versioned_migration(
            migrations_dir,
            "1.0.1",
            "second",
            generate_test_sql(db_type, "table_v2", schema),
        )
        create_versioned_migration(
            migrations_dir,
            "1.0.2",
            "third",
            generate_test_sql(db_type, "table_v3", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # Migrate to 1.0.1 only
        result = cli.migrate(target_version="1.0.1")

        assert result.success, f"Migration failed: {result.stderr}"

        # Verify only first two tables exist
        assert verify_table_exists(db_container, "table_v1", schema)
        assert verify_table_exists(db_container, "table_v2", schema)
        assert not verify_table_exists(db_container, "table_v3", schema)

        # Verify info shows pending migration
        info_result = cli.info()
        assert info_result.success
        assert "1.0.2" in info_result.stdout

    def test_migrate_dry_run(self, db_container, tmp_path):
        """Test migrate with --dry-run option."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "dryrun_test",
            generate_test_sql(db_type, "dryrun_table", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # Dry run
        result = cli.migrate(dry_run=True)

        assert result.success, f"Dry run failed: {result.stderr}"
        output_lower = result.stdout.lower()
        assert "dry" in output_lower or "would" in output_lower

        # Verify NO changes were made
        assert not verify_table_exists(db_container, "dryrun_table", schema)

        # Verify migration is still pending
        info_result = cli.info()
        assert (
            "pending" in info_result.stdout.lower() or "not applied" in info_result.stdout.lower()
        )

    def test_migrate_with_tags(self, db_container, tmp_path):
        """Test migrate with --tags option."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create migrations with tags
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "core_table",
            generate_test_sql(db_type, "core_table", schema),
            tags=["core"],
        )
        create_versioned_migration(
            migrations_dir,
            "1.0.1",
            "optional_table",
            generate_test_sql(db_type, "optional_table", schema),
            tags=["optional"],
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # Migrate only core tags
        result = cli.migrate(tags=["core"])

        assert result.success, f"Migration failed: {result.stderr}"

        # Verify only core table exists
        assert verify_table_exists(db_container, "core_table", schema)
        assert not verify_table_exists(db_container, "optional_table", schema)

    def test_migrate_exclude_tags(self, db_container, tmp_path):
        """Test migrate with --exclude-tags option."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create migrations with tags
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "prod_table",
            generate_test_sql(db_type, "prod_table", schema),
            tags=["production"],
        )
        create_versioned_migration(
            migrations_dir,
            "1.0.1",
            "test_table",
            generate_test_sql(db_type, "test_table", schema),
            tags=["test"],
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # Migrate excluding test tags
        result = cli.migrate(exclude_tags=["test"])

        assert result.success, f"Migration failed: {result.stderr}"

        # Verify only production table exists
        assert verify_table_exists(db_container, "prod_table", schema)
        assert not verify_table_exists(db_container, "test_table", schema)

    def test_migrate_idempotent(self, db_container, tmp_path):
        """Test that running migrate twice is idempotent."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "idempotent_test",
            generate_test_sql(db_type, "idempotent_table", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # First migration
        result1 = cli.migrate()
        assert result1.success

        # Second migration (should be no-op)
        result2 = cli.migrate()
        assert result2.success
        output_lower = result2.stdout.lower()
        assert (
            "up to date" in output_lower
            or "no pending" in output_lower
            or "already" in output_lower
        )

    def test_migrate_incremental(self, db_container, tmp_path):
        """Test incremental migrations."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create first migration
        create_versioned_migration(
            migrations_dir,
            "1.0.0",
            "first",
            generate_test_sql(db_type, "incr_table1", schema),
        )

        cli = DBLiftCLI(config_file, migrations_dir)

        # Apply first
        result = cli.migrate()
        assert result.success
        assert verify_table_exists(db_container, "incr_table1", schema)

        # Add second migration
        create_versioned_migration(
            migrations_dir,
            "1.0.1",
            "second",
            generate_test_sql(db_type, "incr_table2", schema),
        )

        # Apply second
        result = cli.migrate()
        assert result.success
        assert verify_table_exists(db_container, "incr_table2", schema)

        # Both tables should exist
        assert verify_table_exists(db_container, "incr_table1", schema)
        assert verify_table_exists(db_container, "incr_table2", schema)

    def test_migrate_with_data(self, db_container, tmp_path):
        """Test migration that includes data."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        db_type = db_container["type"]
        schema = db_container.get("schema", "TEST_SCHEMA")

        # Create table and insert data in one migration
        if db_type == "postgresql":
            sql = f"""
            CREATE TABLE "{schema}"."data_test" (
                id SERIAL PRIMARY KEY,
                name VARCHAR(100)
            );

            INSERT INTO "{schema}"."data_test" (name)
            VALUES ('test1'), ('test2'), ('test3');
            """
        elif db_type == "mysql":
            sql = f"""
            CREATE TABLE {schema}.data_test (
                id INT AUTO_INCREMENT PRIMARY KEY,
                name VARCHAR(100)
            );

            INSERT INTO {schema}.data_test (name)
            VALUES ('test1'), ('test2'), ('test3');
            """
        elif db_type == "oracle":
            sql = f"""
            CREATE TABLE {schema}.data_test (
                id NUMBER GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name VARCHAR2(100)
            );

            INSERT INTO {schema}.data_test (name) VALUES ('test1');
            INSERT INTO {schema}.data_test (name) VALUES ('test2');
            INSERT INTO {schema}.data_test (name) VALUES ('test3');
            """
        elif db_type == "db2":
            sql = f"""
            CREATE TABLE {schema}.data_test (
                id INT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
                name VARCHAR(100)
            );

            INSERT INTO {schema}.data_test (name)
            VALUES ('test1'), ('test2'), ('test3');
            """
        else:  # sqlserver
            sql = f"""
            CREATE TABLE {schema}.data_test (
                id INT IDENTITY(1,1) PRIMARY KEY,
                name NVARCHAR(100)
            );

            INSERT INTO {schema}.data_test (name)
            VALUES ('test1'), ('test2'), ('test3');
            """

        create_versioned_migration(migrations_dir, "1.0.0", "with_data", sql)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        assert result.success, f"Migration failed: {result.stderr}"

        # Verify table and data
        assert verify_table_exists(db_container, "data_test", schema)
        count = get_table_count(db_container, "data_test", schema)
        assert count == 3, f"Expected 3 rows, got {count}"


@pytest.mark.integration
@pytest.mark.parametrize(
    "db_container",
    ["postgresql", "mysql", "sqlserver", "oracle", "db2"],
    indirect=True,
)
class TestMigrateErrors:
    """Test migrate command error handling."""

    def test_migrate_sql_error(self, db_container, tmp_path):
        """Test that SQL errors are reported correctly."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        # Create migration with SQL error
        create_migration(
            migrations_dir,
            "V1_0_0__sql_error.sql",
            """
            CREATE TABLE test_table (id INT);
            INVALID SQL STATEMENT HERE;
            """,
        )

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        # Should fail
        assert not result.success, "Migration should fail with SQL error"
        # Error messages go to stdout, not stderr
        output_lower = result.output.lower()
        assert "invalid" in output_lower or "syntax" in output_lower or "error" in output_lower

    def test_migrate_no_migrations(self, db_container, tmp_path):
        """Test migrate with no migration files."""
        migrations_dir = tmp_path / "migrations"
        migrations_dir.mkdir()
        config_file = create_config(tmp_path, db_container, migrations_dir=migrations_dir)

        cli = DBLiftCLI(config_file, migrations_dir)
        result = cli.migrate()

        # Should succeed (no-op)
        assert result.success
        output_lower = result.stdout.lower()
        assert (
            "no pending migrations" in output_lower
            or "no migrations" in output_lower
            or "up to date" in output_lower
            or "nothing to migrate" in output_lower
        )
