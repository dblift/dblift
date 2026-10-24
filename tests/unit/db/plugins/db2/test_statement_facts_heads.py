"""Db2 statement facts: heads outside the named families classify and name nothing."""

import ast
from pathlib import Path

import pytest

from dblift.db.plugins.db2.parser import statement_facts as module
from dblift.db.plugins.db2.parser.lexical_spec import DB2_SPEC
from dblift.db.plugins.db2.parser.statement_facts import (
    CLIENT_COMMAND,
    DATA_CHANGE_QUERY,
    NOT_CLASSIFIED,
    SET_INTEGRITY,
    Db2StatementFactsReader,
)

READ = Db2StatementFactsReader(None).read


@pytest.mark.parametrize(
    ("sql", "operation", "kind", "opaque"),
    [
        ("COMMIT", "COMMIT", "UNKNOWN", False),
        ("ROLLBACK TO SAVEPOINT sp1", "ROLLBACK", "UNKNOWN", False),
        ("SAVEPOINT sp1 ON ROLLBACK RETAIN CURSORS", "SAVEPOINT", "UNKNOWN", False),
        ("RELEASE SAVEPOINT sp1", "RELEASE", "UNKNOWN", False),
        ("SET SCHEMA app", "SET", "UNKNOWN", False),
        ("SET CURRENT SCHEMA = 'APP'", "SET", "UNKNOWN", False),
        ("SELECT * FROM app.orders FETCH FIRST 10 ROWS ONLY", "SELECT", "QUERY", False),
        ("VALUES 1", "VALUES", "QUERY", False),
        ("WITH x AS (SELECT 1 FROM sysibm.sysdummy1) SELECT * FROM x", "WITH", "QUERY", False),
        ("SELECT * FROM FINAL TABLE (INSERT INTO t VALUES (1))", "SELECT", "QUERY", True),
        ("CONNECT TO sample", "CONNECT", "UNKNOWN", True),
        ("RUNSTATS ON TABLE app.orders", "RUNSTATS", "UNKNOWN", True),
        ("UPDATE DB CFG FOR sample USING LOGRETAIN ON", "UPDATE", "DML", True),
        ("EXECUTE IMMEDIATE 'DROP TABLE t'", "EXECUTE", "UNKNOWN", True),
        ("", "UNKNOWN", "UNKNOWN", True),
        ("-- only a comment\n/* and */", "UNKNOWN", "UNKNOWN", True),
    ],
)
def test_heads_outside_the_families_classify_and_name_nothing(sql, operation, kind, opaque):
    facts = READ(sql)
    assert (facts.operation, facts.kind, facts.objects, facts.opaque) == (
        operation,
        kind,
        (),
        opaque,
    )
    assert facts.error is None


@pytest.mark.parametrize(
    ("sql", "diagnostic"),
    [
        ("EXECUTE IMMEDIATE 'DROP TABLE t'", NOT_CLASSIFIED.format(word="EXECUTE")),
        ("CONNECT TO sample", CLIENT_COMMAND),
        ("UPDATE DB CFG FOR sample USING LOGRETAIN ON", CLIENT_COMMAND),
        ("SET INTEGRITY FOR app.t IMMEDIATE CHECKED", SET_INTEGRITY),
        ("SELECT * FROM FINAL TABLE (INSERT INTO t VALUES (1))", DATA_CHANGE_QUERY),
    ],
)
def test_opaque_heads_name_their_construct(sql, diagnostic):
    assert READ(sql).diagnostic == diagnostic


def test_reader_binds_the_db2_spec_by_default():
    assert Db2StatementFactsReader(None).spec is DB2_SPEC


def test_reader_does_not_import_re():
    tree = ast.parse(Path(module.__file__).read_text())
    imported = {
        alias.name
        for node in ast.walk(tree)
        if isinstance(node, ast.Import)
        for alias in node.names
    }
    imported |= {node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom)}
    assert "re" not in imported
