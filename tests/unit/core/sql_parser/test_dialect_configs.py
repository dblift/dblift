"""Unit tests for SQL parser dialect configuration modules."""

import re

import pytest

from tests.support.facts_parser import facts_parser


@pytest.mark.unit
class TestDialectConfigBase:
    """Test base DialectConfig class."""


@pytest.mark.unit
class TestDB2Config:
    """Test DB2Config class."""

    @pytest.mark.parametrize(
        "sql",
        [
            "CREATE PROCEDURE test_proc BEGIN SELECT 1; END;",
            "BEGIN ATOMIC SELECT 1; END;",
            "CREATE TRIGGER test_trigger BEGIN ATOMIC SELECT 1; END;",
            "CREATE FUNCTION test() RETURNS INT BEGIN RETURN 1; END;",
        ],
    )
    def test_procedural_units_use_public_scanner(self, sql):
        assert facts_parser("db2").split_statements(sql) == [sql.rstrip(";")]

    def test_module_and_simple_statements_use_public_scanner(self):
        parser = facts_parser("db2")
        assert parser.split_statements(
            "CREATE MODULE test_module END MODULE;\nCREATE TABLE t1 (id INT);"
        ) == ["CREATE MODULE test_module END MODULE", "CREATE TABLE t1 (id INT)"]
        assert parser.split_statements(
            "INSERT INTO t1 VALUES ('test;value');\nSELECT * FROM t1;"
        ) == ["INSERT INTO t1 VALUES ('test;value')", "SELECT * FROM t1"]
        assert parser.split_statements("EXEC SQL SELECT 1 END-EXEC") == [
            "EXEC SQL SELECT 1 END-EXEC"
        ]
        assert parser.split_statements("") == []


@pytest.mark.unit
class TestMySqlConfig:
    """Test MySqlConfig class."""

    def test_custom_delimiter_uses_public_scanner(self):
        sql = "DELIMITER //\nCREATE PROCEDURE test() BEGIN SELECT 1; END//\nDELIMITER ;"
        assert facts_parser("mysql").split_statements(sql) == [
            "CREATE PROCEDURE test() BEGIN SELECT 1; END"
        ]


@pytest.mark.unit
class TestSqlServerConfig:
    """Test SqlServerConfig class."""


@pytest.mark.unit
class TestPostgreSqlConfig:
    """Test PostgreSQL dialect configuration."""
