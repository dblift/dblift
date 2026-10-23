"""Tests for PostgreSQL SQL parser."""

import pytest

from tests.support.facts_parser import facts_parser


@pytest.mark.unit
class TestPostgreSqlParser:
    """Test suite for PostgreSQL SQL parser."""

    def test_parser_creation(self):
        """Test parser can be created."""
        parser = facts_parser("postgresql")
        assert parser is not None
        assert parser._dialect == "postgresql"

    def test_parse_sql_simple(self):
        """Test parsing simple SQL."""
        parser = facts_parser("postgresql")
        sql = "CREATE TABLE test (id SERIAL PRIMARY KEY);"

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True
        assert len(result.statements) >= 1

    def test_parse_sql_multiple_statements(self):
        """Test parsing multiple SQL statements."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE TABLE test1 (id SERIAL PRIMARY KEY);
        CREATE TABLE test2 (id SERIAL PRIMARY KEY);
        INSERT INTO test1 VALUES (DEFAULT);
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_postgresql_specific(self):
        """Test parsing PostgreSQL-specific syntax."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE TABLE test (
            id SERIAL PRIMARY KEY,
            name VARCHAR(255) NOT NULL,
            data JSONB,
            created_at TIMESTAMP DEFAULT NOW()
        );
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_plpgsql_function(self):
        """Test parsing PL/pgSQL function."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE OR REPLACE FUNCTION test_func()
        RETURNS INTEGER AS $$
        BEGIN
            RETURN 42;
        END;
        $$ LANGUAGE plpgsql;
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_trigger(self):
        """Test parsing PostgreSQL trigger."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE OR REPLACE FUNCTION test_trigger_func()
        RETURNS TRIGGER AS $$
        BEGIN
            NEW.updated_at = NOW();
            RETURN NEW;
        END;
        $$ LANGUAGE plpgsql;
        
        CREATE TRIGGER test_trigger
        BEFORE UPDATE ON test
        FOR EACH ROW
        EXECUTE FUNCTION test_trigger_func();
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_with_arrays(self):
        """Test parsing PostgreSQL arrays."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE TABLE test (
            tags TEXT[],
            numbers INTEGER[]
        );
        INSERT INTO test VALUES (ARRAY['tag1', 'tag2'], ARRAY[1, 2, 3]);
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_with_json(self):
        """Test parsing PostgreSQL JSON operations."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE TABLE test (data JSONB);
        INSERT INTO test VALUES ('{"key": "value"}');
        SELECT data->>'key' FROM test;
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_with_extensions(self):
        """Test parsing PostgreSQL extensions."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE EXTENSION IF NOT EXISTS "uuid-ossp";
        CREATE TABLE test (id UUID DEFAULT uuid_generate_v4());
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_with_comments(self):
        """Test parsing SQL with comments."""
        parser = facts_parser("postgresql")
        sql = """
        -- This is a comment
        CREATE TABLE test (id SERIAL PRIMARY KEY);
        /* Multi-line
           comment */
        INSERT INTO test VALUES (DEFAULT);
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_empty(self):
        """Test parsing empty SQL."""
        parser = facts_parser("postgresql")

        result = parser.parse_sql("")

        assert result is not None
        assert result.success is True
        assert len(result.statements) == 0

    def test_split_statements_postgresql_specific(self):
        """Test statement splitting with PostgreSQL-specific syntax."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE TABLE test (id SERIAL PRIMARY KEY);
        INSERT INTO test VALUES (DEFAULT);
        UPDATE test SET id = id + 1 WHERE id > 0;
        """

        statements = parser.split_statements(sql)

        assert len(statements) >= 3

    def test_parse_sql_with_dollar_quoting(self):
        """Test parsing PostgreSQL dollar-quoted strings."""
        parser = facts_parser("postgresql")
        sql = """
        CREATE OR REPLACE FUNCTION test_func()
        RETURNS TEXT AS $function$
        BEGIN
            RETURN 'Hello World';
        END;
        $function$ LANGUAGE plpgsql;
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_parse_sql_with_cte(self):
        """Test parsing PostgreSQL Common Table Expressions."""
        parser = facts_parser("postgresql")
        sql = """
        WITH recursive_cte AS (
            SELECT 1 as n
            UNION ALL
            SELECT n + 1 FROM recursive_cte WHERE n < 10
        )
        SELECT * FROM recursive_cte;
        """

        result = parser.parse_sql(sql)

        assert result is not None
        assert result.success is True

    def test_postgresql_parser_inheritance(self):
        """Test that PostgreSQL parser inherits from base parser correctly."""
        parser = facts_parser("postgresql")

        # Should have methods from base parser
        assert hasattr(parser, "parse_sql")
        assert hasattr(parser, "split_statements")

    def test_parser_configuration(self):
        """Test parser configuration and setup."""
        parser = facts_parser("postgresql")

        # Verify dialect is set correctly
        assert parser._dialect == "postgresql"

        # Should be able to create without errors
        assert parser is not None
