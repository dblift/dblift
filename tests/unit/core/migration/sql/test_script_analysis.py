"""``analyse_script``: what a script does, read from its text, and what deserves a caution."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

import dblift.core.migration.sql.script_analysis as script_analysis
from dblift.core.migration.migration_types import MigrationType
from dblift.core.migration.sql.script_analysis import (
    CHANGES_ROWS,
    DESTROYS,
    ScriptAnalysis,
    analyse_pending_scripts,
    analyse_script,
    dialect_of,
    operation_of,
)

pytestmark = pytest.mark.unit


def test_create_table_names_the_table_and_raises_no_caution():
    analysis = analyse_script(
        "CREATE TABLE orders (id INTEGER PRIMARY KEY, total NUMERIC);", "postgresql"
    )

    assert [s.operation for s in analysis.statements] == ["CREATE"]
    assert analysis.statements[0].kind == "DDL"
    assert [(o.type, o.name) for o in analysis.statements[0].objects] == [("TABLE", "orders")]
    assert analysis.cautions == ()
    assert analysis.errors == ()


def test_drop_table_and_truncate_destroy_data():
    analysis = analyse_script("DROP TABLE orders;\nTRUNCATE TABLE audit_log;", "postgresql")

    assert [s.operation for s in analysis.statements] == ["DROP", "TRUNCATE"]
    assert [(c.level, c.statement) for c in analysis.cautions] == [(DESTROYS, 0), (DESTROYS, 1)]
    assert "orders" in analysis.cautions[0].reason
    assert "audit_log" in analysis.cautions[1].reason


def test_delete_without_where_destroys_and_with_where_changes_rows():
    analysis = analyse_script(
        "DELETE FROM sessions;\nUPDATE users SET active = false WHERE last_seen < now();",
        "postgresql",
    )

    assert [s.full_table for s in analysis.statements] == [True, False]
    assert [(c.level, c.statement) for c in analysis.cautions] == [
        (DESTROYS, 0),
        (CHANGES_ROWS, 1),
    ]


def test_drop_column_destroys_and_other_alters_do_not():
    analysis = analyse_script(
        "ALTER TABLE users DROP COLUMN legacy_id;\nALTER TABLE users ADD COLUMN nick TEXT;",
        "postgresql",
    )

    assert [s.operation for s in analysis.statements] == ["ALTER", "ALTER"]
    assert [(c.level, c.statement) for c in analysis.cautions] == [(DESTROYS, 0)]


def test_merge_changes_rows_and_insert_does_not():
    analysis = analyse_script(
        "INSERT INTO users (id) VALUES (1);\n"
        "MERGE INTO users AS t USING staging AS s ON t.id = s.id "
        "WHEN MATCHED THEN UPDATE SET name = s.name;",
        "postgresql",
    )

    assert [(c.level, c.statement) for c in analysis.cautions] == [(CHANGES_ROWS, 1)]


def test_drop_index_and_sequence_raise_no_caution():
    analysis = analyse_script("DROP INDEX idx_users_email;\nDROP SEQUENCE users_seq;", "postgresql")

    assert [s.operation for s in analysis.statements] == ["DROP", "DROP"]
    assert analysis.cautions == ()


def test_procedural_body_is_one_statement_without_caution():
    sql = (
        "CREATE OR REPLACE FUNCTION purge() RETURNS void AS $$\n"
        "BEGIN\n"
        "  DELETE FROM audit_log;\n"
        "END;\n"
        "$$ LANGUAGE plpgsql;"
    )

    analysis = analyse_script(sql, "postgresql")

    assert len(analysis.statements) == 1
    assert analysis.statements[0].operation == "CREATE"
    assert analysis.cautions == ()


def test_sqlserver_go_batches_are_separate_statements():
    analysis = analyse_script("CREATE TABLE a (id INT);\nGO\nDROP TABLE b;\nGO\n", "sqlserver")

    assert [s.operation for s in analysis.statements] == ["CREATE", "DROP"]
    assert [(c.level, c.statement) for c in analysis.cautions] == [(DESTROYS, 1)]


def test_unreadable_text_never_raises():
    analysis = analyse_script("this is not sql at all ;;; ((", "postgresql")

    assert isinstance(analysis, ScriptAnalysis)
    assert analysis.cautions == ()


def test_to_dict_has_the_three_keys_and_plain_values():
    data = analyse_script("DROP TABLE orders;", "postgresql").to_dict()

    assert set(data) == {"statements", "cautions", "errors"}
    statement = data["statements"][0]
    assert set(statement) == {"index", "operation", "kind", "objects", "full_table", "snippet"}
    assert statement["objects"][0] == {
        "type": "TABLE",
        "name": "orders",
        "schema": statement["objects"][0]["schema"],
    }
    assert data["cautions"][0] == {
        "level": DESTROYS,
        "statement": 0,
        "reason": data["cautions"][0]["reason"],
        "code": "drop-table",
    }
    assert data["errors"] == []


def test_operation_of_skips_leading_comments():
    assert operation_of("-- drop it\n/* really */ DROP TABLE t") == "DROP"
    assert operation_of("   ") == "UNKNOWN"


def test_analyse_pending_scripts_keeps_sql_and_repeatable_with_content():
    log = MagicMock()
    migrations = [
        SimpleNamespace(script_name="V1__a.sql", type=MigrationType.SQL, content="DROP TABLE a;"),
        SimpleNamespace(
            script_name="R__view.sql",
            type=MigrationType.REPEATABLE,
            content="CREATE VIEW v AS SELECT 1;",
        ),
        SimpleNamespace(script_name="V2__py.py", type=MigrationType.PYTHON, content="print(1)"),
        SimpleNamespace(
            script_name="U1__a.sql", type=MigrationType.UNDO_SQL, content="CREATE TABLE a (id INT);"
        ),
        SimpleNamespace(script_name="V3__empty.sql", type=MigrationType.SQL, content=""),
    ]

    analysed = analyse_pending_scripts(migrations, "postgresql", log)

    assert set(analysed) == {"V1__a.sql", "R__view.sql"}
    assert analysed["V1__a.sql"]["cautions"][0]["level"] == DESTROYS
    assert analysed["R__view.sql"]["cautions"] == []


def test_analyse_pending_scripts_loads_content_when_the_object_can():
    migration = MagicMock()
    migration.script_name = "V1__a.sql"
    migration.type = MigrationType.SQL
    migration.content = ""

    def load_content(scripts_dir=None):
        migration.content = "TRUNCATE TABLE a;"

    migration.load_content.side_effect = load_content

    analysed = analyse_pending_scripts([migration], "postgresql", MagicMock())

    assert analysed["V1__a.sql"]["cautions"][0]["level"] == DESTROYS


def test_dialect_of_reads_the_configured_database_type():
    assert dialect_of(SimpleNamespace(database=SimpleNamespace(type="PostgreSQL"))) == "postgresql"
    assert dialect_of(SimpleNamespace(database=SimpleNamespace(type=None))) is None
    assert dialect_of(None) is None


def test_parser_failure_yields_an_error_and_no_statements(monkeypatch):
    class Boom:
        def __init__(self, dialect):
            raise RuntimeError("no parser")

    monkeypatch.setattr(script_analysis, "SqlParserFactory", Boom)

    analysis = analyse_script("DROP TABLE a;", "postgresql")

    assert analysis.statements == ()
    assert analysis.cautions == ()
    assert analysis.errors == ("parser error: no parser",)


def test_blank_statements_are_skipped_and_unknown_text_has_unknown_kind(monkeypatch):
    parsed = SimpleNamespace(
        statements=[
            SimpleNamespace(sql_text="   ", statement_type=None, affected_objects=[], objects=[]),
            SimpleNamespace(
                sql_text="FROBNICATE x", statement_type=None, affected_objects=[], objects=[]
            ),
        ],
        errors=[],
    )
    monkeypatch.setattr(
        script_analysis,
        "SqlParserFactory",
        lambda dialect: SimpleNamespace(parse_sql=lambda text: parsed),
    )

    analysis = analyse_script("ignored", "postgresql")

    assert [(s.index, s.operation, s.kind) for s in analysis.statements] == [
        (0, "FROBNICATE", "UNKNOWN")
    ]
    assert analysis.cautions == ()


def test_cte_delete_is_dml_and_names_its_table():
    analysis = analyse_script(
        "WITH old AS (SELECT id FROM sessions WHERE ts < now()) "
        "DELETE FROM sessions WHERE id IN (SELECT id FROM old);",
        "postgresql",
    )

    statement = analysis.statements[0]
    assert (statement.operation, statement.kind, statement.full_table) == ("WITH", "DML", False)
    assert [o.name for o in statement.objects] == ["sessions"]
    assert [c.level for c in analysis.cautions] == [CHANGES_ROWS]


def test_quirks_failures_never_raise(monkeypatch):
    real = script_analysis.ProviderRegistry.get_quirks("postgresql")

    class BrokenQuirks(type(real)):  # the parser still needs the real quirks' parser class
        def is_full_table_dml(self, statement):
            raise RuntimeError("broken")

    monkeypatch.setattr(
        script_analysis.ProviderRegistry, "get_quirks", lambda dialect: BrokenQuirks(dialect)
    )
    monkeypatch.setattr(
        script_analysis, "statement_dml_table", MagicMock(side_effect=RuntimeError("broken"))
    )

    analysis = analyse_script("DELETE FROM sessions;", "postgresql")

    statement = analysis.statements[0]
    assert statement.full_table is False
    assert statement.objects == ()
    assert [c.level for c in analysis.cautions] == [CHANGES_ROWS]


def test_analyse_pending_scripts_skips_nameless_and_logs_read_and_analysis_failures(monkeypatch):
    log = MagicMock()
    nameless = SimpleNamespace(script_name="", type=MigrationType.SQL, content="DROP TABLE a;")
    unreadable = MagicMock()
    unreadable.script_name = "V1__a.sql"
    unreadable.type = MigrationType.SQL
    unreadable.content = ""
    unreadable.load_content.side_effect = OSError("gone")
    readable = SimpleNamespace(
        script_name="V2__b.sql", type=MigrationType.SQL, content="DROP TABLE b;"
    )
    monkeypatch.setattr(
        script_analysis, "analyse_script", MagicMock(side_effect=RuntimeError("boom"))
    )

    analysed = analyse_pending_scripts([nameless, unreadable, readable], "postgresql", log)

    assert analysed == {}
    messages = [call.args[0] for call in log.debug.call_args_list]
    assert any("V1__a.sql" in m and "gone" in m for m in messages)
    assert any("V2__b.sql" in m and "boom" in m for m in messages)


def test_select_is_a_query_and_raises_no_caution():
    analysis = analyse_script("SELECT 1;", "postgresql")

    assert [(s.operation, s.kind) for s in analysis.statements] == [("SELECT", "QUERY")]
    assert analysis.cautions == ()


@pytest.mark.parametrize(
    "sql, code",
    [
        ("DROP TABLE users;", "drop-table"),
        ("DROP SCHEMA reporting CASCADE;", "drop-schema"),
        ("TRUNCATE TABLE audit_log;", "truncate"),
        ("ALTER TABLE users DROP COLUMN email;", "drop-column"),
        ("DELETE FROM users;", "dml-no-where"),
        ("UPDATE users SET active = false;", "dml-no-where"),
        ("DELETE FROM users WHERE id = 1;", None),
        ("DROP VIEW active_users;", None),
    ],
)
def test_each_caution_names_its_rule_code(sql, code):
    analysis = analyse_script(sql, "postgresql")

    assert [c.code for c in analysis.cautions] == [code]


def test_statement_keeps_its_full_sql_but_does_not_serialise_it():
    long_tail = ", ".join(f"c{i} INTEGER" for i in range(40))
    analysis = analyse_script(f"CREATE TABLE wide ({long_tail});\nDROP TABLE wide;", "postgresql")

    assert "c39 INTEGER" in analysis.statements[0].sql
    assert analysis.statements[0].snippet.endswith("…")
    assert "DROP TABLE wide" in analysis.statements[1].sql
    payload = analysis.to_dict()
    assert "sql" not in payload["statements"][0]
    assert payload["cautions"][0]["code"] == "drop-table"


@pytest.mark.parametrize(
    "sql, kind, name",
    [
        ("DROP SCHEMA reporting CASCADE;", "SCHEMA", "reporting"),
        ("DROP DATABASE IF EXISTS archive;", "DATABASE", "archive"),
    ],
)
def test_schema_level_drop_names_its_target_and_destroys(sql, kind, name):
    analysis = analyse_script(sql, "postgresql")

    assert [(o.type, o.name) for o in analysis.statements[0].objects] == [(kind, name)]
    assert [(c.level, c.code) for c in analysis.cautions] == [(DESTROYS, "drop-schema")]
