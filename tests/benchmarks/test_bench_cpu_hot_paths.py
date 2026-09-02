"""Benchmarks for CPU-bound hot paths — no DB, no JVM.

Each test is a single ``benchmark()`` call that pytest-benchmark times.
Group names are used by ``pytest-benchmark compare`` to bucket related
measurements; keep them stable.

The committed ``tests/benchmarks/baseline.json`` was generated with
these exact test identifiers; renaming a test breaks the comparison.
"""

from __future__ import annotations

import pytest

# ---------------------------------------------------------------------------
# checksum (CRC32 per line)
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def small_migration_content() -> str:
    return """-- V1__create_users.sql
CREATE TABLE users (
    id INTEGER PRIMARY KEY,
    name VARCHAR(100) NOT NULL,
    email VARCHAR(255) UNIQUE
);
CREATE INDEX idx_users_email ON users(email);
"""


@pytest.fixture(scope="module")
def large_migration_content() -> str:
    """A realistic migration: ~100 DDL statements."""
    stmts = []
    for i in range(100):
        stmts.append(
            f"CREATE TABLE t_{i} (\n"
            f"    id INTEGER PRIMARY KEY,\n"
            f"    col_a VARCHAR(100),\n"
            f"    col_b INTEGER DEFAULT 0,\n"
            f"    col_c TIMESTAMP\n"
            f");"
        )
        stmts.append(f"CREATE INDEX idx_t_{i}_col_a ON t_{i}(col_a);")
    return "\n".join(stmts)


class TestChecksum:
    def test_small_content(self, benchmark, small_migration_content):
        from dblift.core.migration.migration import calculate_migration_script_checksum

        result = benchmark(calculate_migration_script_checksum, small_migration_content)
        assert isinstance(result, int)

    def test_large_content(self, benchmark, large_migration_content):
        from dblift.core.migration.migration import calculate_migration_script_checksum

        result = benchmark(calculate_migration_script_checksum, large_migration_content)
        assert isinstance(result, int)


# ---------------------------------------------------------------------------
# filename parsing (regex-heavy)
# ---------------------------------------------------------------------------


class TestFilenameParsing:
    @pytest.fixture(scope="class")
    def script_manager(self):
        from dblift.core.logger import NullLog
        from dblift.core.migration.scripting.migration_script_manager import MigrationScriptManager

        return MigrationScriptManager(NullLog(), "utf-8")

    def test_versioned_filename(self, benchmark, script_manager):
        benchmark(script_manager.parse_filename, "V1.2.3__create_users_table.sql")

    def test_repeatable_filename(self, benchmark, script_manager):
        benchmark(script_manager.parse_filename, "R__refresh_materialized_views.sql")

    def test_undo_filename(self, benchmark, script_manager):
        benchmark(script_manager.parse_filename, "U1.2.3__drop_users_table.sql")

    def test_tagged_filename(self, benchmark, script_manager):
        benchmark(
            script_manager.parse_filename,
            "V2.0.0__add_billing[billing,feature].sql",
        )


# ---------------------------------------------------------------------------
# placeholder substitution (pre-tokenisation)
# ---------------------------------------------------------------------------


class TestPlaceholderSubstitution:
    @pytest.fixture(scope="class")
    def placeholder_service(self):
        from dblift.core.logger import NullLog
        from dblift.core.migration.placeholders.placeholder_service import PlaceholderService

        return PlaceholderService(
            placeholders={"schema": "app", "user": "dblift", "env": "prod"},
            logger=NullLog(),
        )

    def test_no_placeholders(self, benchmark, placeholder_service):
        content = "CREATE TABLE users (id INTEGER);"
        benchmark(placeholder_service.replace_placeholders, content)

    def test_few_placeholders(self, benchmark, placeholder_service):
        content = "CREATE TABLE ${schema}.${user}_data (id INTEGER); COMMENT ON TABLE ${schema}.${user}_data IS 'env=${env}';"
        benchmark(placeholder_service.replace_placeholders, content)

    def test_many_placeholders(self, benchmark, placeholder_service):
        content = "\n".join(
            f"INSERT INTO ${{schema}}.log VALUES ({i}, '${{user}}', '${{env}}');"
            for i in range(200)
        )
        benchmark(placeholder_service.replace_placeholders, content)


# ---------------------------------------------------------------------------
# MigrationType matching helpers
# ---------------------------------------------------------------------------


class TestTypeMatchHelpers:
    def test_is_versioned_enum(self, benchmark):
        from dblift.core.migration import MigrationType, is_versioned

        benchmark(is_versioned, MigrationType.SQL)

    def test_is_versioned_str(self, benchmark):
        from dblift.core.migration import is_versioned

        benchmark(is_versioned, "SQL")

    def test_is_migration_type_enum_vs_enum(self, benchmark):
        from dblift.core.migration import MigrationType, is_migration_type

        benchmark(is_migration_type, MigrationType.UNDO_SQL, MigrationType.UNDO_SQL)

    def test_is_migration_type_str_vs_str(self, benchmark):
        from dblift.core.migration import is_migration_type

        benchmark(is_migration_type, "UNDO_SQL", "UNDO_SQL")

    def test_migration_type_name_enum(self, benchmark):
        from dblift.core.migration import MigrationType, migration_type_name

        benchmark(migration_type_name, MigrationType.SQL)


# ---------------------------------------------------------------------------
# dialect capability lookup
# ---------------------------------------------------------------------------


class TestDialectCapabilities:
    @pytest.mark.parametrize(
        "dialect",
        ["postgresql", "oracle", "mysql", "sqlserver", "db2", "sqlite", "cosmosdb"],
    )
    def test_get_dialect_capabilities(self, benchmark, dialect):
        from dblift.core.sql_model.dialect import get_dialect_capabilities

        caps = benchmark(get_dialect_capabilities, dialect)
        assert caps is not None

    def test_unknown_dialect_fallback(self, benchmark):
        from dblift.core.sql_model.dialect import get_dialect_capabilities

        benchmark(get_dialect_capabilities, "not-a-dialect")


# ---------------------------------------------------------------------------
# SQL statement splitting (dialect-aware)
# ---------------------------------------------------------------------------


class TestStatementSplitting:
    @pytest.fixture(scope="class")
    def content_with_n_statements(self):
        def _build(n):
            return ";\n".join(f"SELECT {i}" for i in range(n)) + ";"

        return _build

    def test_split_10_statements_postgresql(self, benchmark, content_with_n_statements):
        from dblift.core.migration.migration import Migration

        m = Migration(
            script_name="V1__test.sql",
            content=content_with_n_statements(10),
            version="1",
            description="test",
            dialect="postgresql",
        )
        result = benchmark(m.parse_sql_statements, "postgresql")
        assert len(result) == 10

    def test_split_100_statements_postgresql(self, benchmark, content_with_n_statements):
        from dblift.core.migration.migration import Migration

        m = Migration(
            script_name="V1__test.sql",
            content=content_with_n_statements(100),
            version="1",
            description="test",
            dialect="postgresql",
        )
        result = benchmark(m.parse_sql_statements, "postgresql")
        assert len(result) == 100
