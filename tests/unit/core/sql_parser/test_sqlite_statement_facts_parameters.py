"""Valid SQLite the grammar cannot read still names its write target; undo text is plain."""

import pytest

from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.dml_analysis import analyze_dml, is_full_table_dml
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlite.quirks import SqliteQuirks

READER = SqlglotStatementFactsReader("sqlite", SQLITE_SPEC)

# (statement, target, writes every row)
NUMBERED = [
    ("UPDATE t SET a=?1 WHERE id=?2", "t", False),
    ("UPDATE s.t SET a=?1 WHERE id=?2", "s.t", False),
    ("UPDATE OR IGNORE t SET a=?1 WHERE x=1", "t", False),
    ("UPDATE t SET a=?1", "t", True),
    ("UPDATE t SET a=(SELECT 'where' FROM u WHERE u.id=?1)", "t", True),
    ("DELETE FROM t WHERE id=?1", "t", False),
    ("DELETE FROM t WHERE id IN (SELECT id FROM u WHERE v=?1)", "t", False),
    ("DELETE FROM t", "t", True),
    ("INSERT INTO t VALUES (?1)", "t", False),
    ("INSERT OR REPLACE INTO s.t VALUES (?1, ?2)", "s.t", False),
    ("REPLACE INTO t VALUES (?1)", "t", False),
]


@pytest.mark.parametrize("sql, target, full", NUMBERED)
def test_numbered_parameters_keep_the_target_and_the_where_verdict(sql, target, full):
    (statement,) = analyse_script(sql, "sqlite").statements

    assert [(o.schema + "." if o.schema else "") + o.name for o in statement.objects] == [target]
    assert statement.full_table is full
    assert any(c.code == "dml-no-where" for c in analyse_script(sql, "sqlite").cautions) is full
    assert SqliteQuirks().is_full_table_dml(sql) is full
    assert is_full_table_dml(sql, sqlglot_dialect="sqlite") is full
    assert analyze_dml(sql, sqlglot_dialect="sqlite").table == target


# --- undo text names no internal machinery ---------------------------------------------

UNDO_INPUTS = [
    "INSERT INTO t VALUES (1);",
    "DROP TABLE t;",
    "PRAGMA foreign_keys=ON;",
    "CREATE VIRTUAL TABLE v USING fts5(a);",
    "UPDATE t SET a = 1;",
    "ALTER TABLE t RENAME TO u;",
]


@pytest.mark.parametrize("content", UNDO_INPUTS)
def test_undo_comments_use_plain_wording(content):
    statements = UndoScriptGenerator("sqlite")._generate_undo_statements(
        Migration(script_name="V1__x.sql", content=content)
    )

    assert statements
    for undo in statements:
        text = f"{undo.sql} {undo.warning or ''}".lower()
        assert "facts" not in text
        assert "opaque" not in text
        assert "mapping" not in text
        assert "grammar" not in text
        if undo.requires_manual_review:
            assert "review" in text


# --- a write behind a WITH clause the grammar cannot read ------------------------------

CTE = "WITH c AS (SELECT id FROM u WHERE x=?1)"
CTE_WRITES = [
    (f"{CTE} UPDATE t SET a=?2", "UPDATE", "t", True),
    (f"{CTE} UPDATE t SET a=?2 WHERE id IN (SELECT id FROM c)", "UPDATE", "t", False),
    (f"{CTE} DELETE FROM t", "DELETE", "t", True),
    (f"{CTE} DELETE FROM t WHERE id IN (SELECT id FROM c)", "DELETE", "t", False),
    (f"{CTE} INSERT INTO t SELECT id FROM c", "INSERT", "t", False),
    (
        f"WITH RECURSIVE c(n) AS (SELECT ?1 UNION ALL SELECT n+1 FROM c) DELETE FROM t",
        "DELETE",
        "t",
        True,
    ),
]


@pytest.mark.parametrize("sql, operation, target, full", CTE_WRITES)
def test_unreadable_cte_write_keeps_operation_target_and_caution(sql, operation, target, full):
    analysis = analyse_script(sql, "sqlite")
    (statement,) = analysis.statements

    assert (statement.operation, statement.kind) == (operation, "DML")
    assert [o.name for o in statement.objects] == [target]
    assert statement.full_table is full
    assert any(c.code == "dml-no-where" for c in analysis.cautions) is full
    assert SqliteQuirks().is_full_table_dml(sql) is full


def test_unreadable_cte_select_is_a_query_without_objects():
    (statement,) = analyse_script("WITH c AS (SELECT ?1) SELECT * FROM c", "sqlite").statements

    assert (statement.operation, statement.kind, statement.objects) == ("SELECT", "QUERY", ())


@pytest.mark.parametrize(
    "sql", ["DELETE FROM", "INSERT INTO", "DELETE FROM WHERE", "UPDATE SET a=1"]
)
def test_truncated_dml_does_not_take_a_keyword_as_its_table(sql):
    facts = READER.read(sql)

    assert facts.objects == ()
    assert facts.target is None
    assert facts.diagnostic


def test_unreadable_cte_merge_is_not_taken_for_the_delete_inside_it():
    sql = "WITH x AS (SELECT ?1) MERGE INTO t USING x ON 1=1 WHEN MATCHED THEN DELETE"
    analysis = analyse_script(sql, "sqlite")
    (statement,) = analysis.statements

    assert statement.operation == "MERGE"
    assert statement.objects == ()
    assert statement.full_table is False
    assert "dml-no-where" not in [c.code for c in analysis.cautions]
    assert READER.read(sql).target is None
