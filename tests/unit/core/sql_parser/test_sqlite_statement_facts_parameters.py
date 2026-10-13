"""Valid SQLite the grammar cannot read still names its write target; undo text is plain."""

import pytest

from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.db.dml_analysis import analyze_dml, is_full_table_dml
from dblift.db.plugins.sqlite.quirks import SqliteQuirks

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
