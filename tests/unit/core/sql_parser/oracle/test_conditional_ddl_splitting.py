"""Oracle conditional DDL must not open a procedural IF block."""

import pytest

from dblift.db.plugins.oracle.parser.oracle_parser import OracleParser

pytestmark = pytest.mark.unit


@pytest.mark.parametrize(
    "ddl",
    [
        "CREATE TABLE IF NOT EXISTS probe(id NUMBER)",
        "CREATE INDEX IF NOT EXISTS ix_probe ON probe(id)",
        "DROP TABLE IF EXISTS probe",
        "CREATE TABLE IF /* comment */ NOT\nEXISTS probe(id NUMBER)",
    ],
)
def test_conditional_ddl_does_not_swallow_following_statement(ddl):
    statements = OracleParser().split_statements(
        ddl + ";\nINSERT INTO probe VALUES(1);", strict_tokenizer=True
    )
    assert len(statements) == 2
    assert "INSERT" not in statements[0]
    assert statements[1].rstrip(";") == "INSERT INTO probe VALUES(1)"


def test_conditional_procedure_header_preserves_nested_if_and_following_sql():
    sql = """
    CREATE PROCEDURE IF NOT EXISTS probe_proc AS
    BEGIN
        IF 1 = 1 THEN
            IF 2 = 2 THEN
                NULL;
            END IF;
        END IF;
    END;
    /
    INSERT INTO probe VALUES(1);
    """
    statements = OracleParser().split_statements(sql, strict_tokenizer=True)
    assert len(statements) == 2
    assert statements[0].count("END IF") == 2
    assert "INSERT" not in statements[0]
    assert statements[1].rstrip(";") == "INSERT INTO probe VALUES(1)"


def test_anonymous_if_and_sql_case_keep_their_own_boundaries():
    sql = """
    BEGIN
        IF 1 = 1 THEN
            NULL;
        END IF;
    END;
    /
    SELECT CASE WHEN 1 = 1 THEN 2 ELSE 3 END FROM dual;
    INSERT INTO probe VALUES(1);
    """
    statements = OracleParser().split_statements(sql, strict_tokenizer=True)
    assert len(statements) == 3
    assert "END IF" in statements[0]
    assert "CASE WHEN" in statements[1]
    assert statements[2].rstrip(";") == "INSERT INTO probe VALUES(1)"
