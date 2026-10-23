"""Statements the facts reader cannot model are classified, never reported as errors."""

import shutil
import subprocess
import sys
from pathlib import Path
from unittest.mock import Mock

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.lint import lint_script
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.migration.sql.sql_execution_service import SqlExecutionService
from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.dml_analysis import analyze_dml, is_full_table_dml
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser
from dblift.db.plugins.sqlite.quirks import SqliteQuirks
from dblift.db.provider_registry import ProviderRegistry
from tests.unit._migration_factory import make_migration

_quirks = ProviderRegistry.get_quirks

READER = SqlglotStatementFactsReader("sqlite", SQLITE_SPEC)
PARSER = SQLiteFactsParser()

TRIGGER = "CREATE TRIGGER tr BEFORE INSERT ON t BEGIN SELECT RAISE(ABORT, 'x'); END"

# Valid SQLite that sqlglot cannot read or the facts reader does not model.
VALID = [
    TRIGGER,
    "CREATE TRIGGER IF NOT EXISTS s.tr AFTER DELETE ON t BEGIN DELETE FROM u; END",
    "CREATE TEMP TRIGGER tr AFTER DELETE ON t BEGIN DELETE FROM u; END",
    "DROP TRIGGER IF EXISTS s.tr",
    "PRAGMA foreign_keys=ON",
    "PRAGMA journal_mode=WAL;",
    "BEGIN",
    "COMMIT",
    "SAVEPOINT x",
    "VACUUM",
    "ANALYZE",
    "REINDEX",
    "ATTACH DATABASE 'x.db' AS x",
    "DETACH DATABASE x",
    "EXPLAIN SELECT 1",
    "VALUES (1)",
    "CREATE TABLE t(a INT PRIMARY KEY) WITHOUT ROWID",
    "CREATE TABLE t(a INT) STRICT",
    "CREATE TABLE t(a INT, b INT AS (a+1) STORED)",
    "CREATE VIRTUAL TABLE t USING fts5(a)",
    "CREATE VIRTUAL TABLE IF NOT EXISTS s.t USING rtree(id,a,b)",
    "CREATE INDEX ix ON t(lower(c))",
    "CREATE INDEX s.ix ON t(c DESC)",
    "REPLACE INTO t(a) VALUES (1)",
    "UPDATE OR REPLACE t SET a=1 WHERE b=2",
    "UPDATE OR IGNORE t SET a=1",
    "INSERT INTO t VALUES (X'00ff', ?1)",
]


@pytest.mark.parametrize("sql", VALID)
def test_valid_statements_are_not_errors(sql):
    result = PARSER.parse_sql(sql)
    verdict = PARSER.validate_sql(sql)

    assert result.success, result.errors
    assert result.errors == []
    assert verdict["valid"] is True
    assert verdict["errors"] == []
    assert analyse_script(sql, "sqlite").errors == ()
    assert READER.read(sql).error is None


# (operation, kind, [(type, name, schema, role)]): what the leading words alone give.
HEAD_CLASSES = [
    (
        TRIGGER,
        "CREATE",
        "DDL",
        [(SqlObjectType.TRIGGER, "tr", None, "created")],
    ),
    (
        "CREATE TRIGGER IF NOT EXISTS s.tr AFTER DELETE ON t BEGIN DELETE FROM u; END",
        "CREATE",
        "DDL",
        [(SqlObjectType.TRIGGER, "tr", "s", "created")],
    ),
    ("DROP TRIGGER IF EXISTS s.tr", "DROP", "DDL", [(SqlObjectType.TRIGGER, "tr", "s", "dropped")]),
    ("PRAGMA foreign_keys=ON", "PRAGMA", "DDL", []),
    ("VACUUM", "VACUUM", "DDL", []),
    ("ANALYZE", "ANALYZE", "DDL", []),
    ("REINDEX", "REINDEX", "DDL", []),
    ("ATTACH DATABASE 'x.db' AS x", "ATTACH", "DDL", []),
    ("DETACH DATABASE x", "DETACH", "DDL", []),
    ("BEGIN", "BEGIN", "UNKNOWN", []),
    ("COMMIT", "COMMIT", "UNKNOWN", []),
    ("SAVEPOINT x", "SAVEPOINT", "UNKNOWN", []),
    ("EXPLAIN SELECT 1", "EXPLAIN", "QUERY", []),
    ("VALUES (1)", "VALUES", "QUERY", []),
    (
        "CREATE VIRTUAL TABLE IF NOT EXISTS s.t USING rtree(id,a,b)",
        "CREATE",
        "DDL",
        [(SqlObjectType.VIRTUAL_TABLE, "t", "s", "created")],
    ),
    (
        "REPLACE INTO t(a) VALUES (1)",
        "REPLACE",
        "DML",
        [(SqlObjectType.TABLE, "t", None, "altered")],
    ),
]


@pytest.mark.parametrize("sql, operation, kind, objects", HEAD_CLASSES)
def test_unreadable_statements_are_classified_from_their_leading_words(
    sql, operation, kind, objects
):
    facts = READER.read(sql)

    assert (facts.operation, facts.kind) == (operation, kind)
    assert [(o.type, o.name, o.schema, o.role) for o in facts.objects] == objects
    assert facts.error is None


@pytest.mark.parametrize("sql", [TRIGGER, "PRAGMA foreign_keys=ON", "REPLACE INTO t VALUES (1)"])
def test_an_unmodelled_construct_is_named_by_an_information_diagnostic(sql):
    facts = READER.read(sql)

    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None


def test_script_analysis_kind_and_objects_follow_the_head_classification():
    pragma, vacuum, begin, replace, trigger = (
        analyse_script(sql, "sqlite").statements[0]
        for sql in (
            "PRAGMA foreign_keys=ON",
            "VACUUM",
            "BEGIN",
            "REPLACE INTO t VALUES (1)",
            TRIGGER,
        )
    )

    assert [(s.operation, s.kind) for s in (pragma, vacuum, begin, replace, trigger)] == [
        ("PRAGMA", "DDL"),
        ("VACUUM", "DDL"),
        ("BEGIN", "UNKNOWN"),
        ("REPLACE", "DML"),
        ("CREATE", "DDL"),
    ]
    assert [(o.type, o.name) for o in trigger.objects] == [("TRIGGER", "tr")]


# --- the validate-sql verdict ----------------------------------------------------------


@pytest.mark.parametrize("opener", ["PRAGMA foreign_keys=ON", "VACUUM"])
def test_lint_still_refuses_a_script_mixing_transaction_modes(opener):
    lint = lint_script(f"{opener}; CREATE TABLE t(a);", "sqlite")

    assert lint.verdict == "UNSAFE"
    assert [f.code for f in lint.findings] == ["mixed-transaction-modes"]
    assert lint.errors == ()


def test_lint_of_a_trigger_migration_is_safe():
    lint = lint_script(f"CREATE TABLE t(a);\n{TRIGGER};\n", "sqlite")

    assert lint.verdict == "SAFE"
    assert lint.findings == ()


def test_lint_of_a_trigger_beside_a_pragma_is_unsafe():
    lint = lint_script(f"{TRIGGER}; PRAGMA foreign_keys=ON;", "sqlite")

    assert lint.verdict == "UNSAFE"


def test_validate_sql_cli_gives_unsafe_for_a_mixed_script(tmp_path):
    cli = Path(sys.executable).parent / "dblift"
    if not cli.exists():
        cli = shutil.which("dblift")
    if not cli:
        pytest.skip("dblift console script is not installed")
    script = tmp_path / "p.sql"
    script.write_text("PRAGMA foreign_keys=ON; CREATE TABLE t(a);\n")

    done = subprocess.run(
        [str(cli), "validate-sql", "--dialect", "sqlite", "--files", str(script)],
        capture_output=True,
        text=True,
        cwd=tmp_path,
    )

    output = done.stdout + done.stderr
    assert "UNSAFE" in output and "mixed-transaction-modes" in output
    assert done.returncode != 0


# --- errors are reserved for refusals and text that does not tokenize ----------------


def test_an_unterminated_string_is_an_error_that_does_not_echo_the_sql():
    script = "INSERT INTO accounts VALUES ('hunter2"
    result = PARSER.parse_sql(script)
    verdict = PARSER.validate_sql(script)
    analysis = analyse_script(script, "sqlite")
    facts = READER.read(script)

    assert result.success is False
    assert verdict["valid"] is False
    assert analysis.errors
    assert facts.error
    for message in [*result.errors, *verdict["errors"], *analysis.errors, facts.error]:
        assert "hunter2" not in message
        assert "accounts" not in message


# --- extraction preserves refusals even when valid DDL precedes them -----------------


@pytest.mark.parametrize(
    "script",
    [
        ".mode csv\nCREATE TABLE a(x)",
        "CREATE TABLE t(a);\n.read x",
        "CREATE TABLE t(a);\n/* unterminated\n",
        "CREATE TABLE t(a)\nGO\n",
        "CREATE TABLE a(x)\n/\nCREATE TABLE b(y);",
        ".read x.sql",
    ],
)
def test_extract_objects_does_not_recover_tables_from_a_refused_script(script):
    with pytest.raises((UnsafeStatementSplitError, UnsupportedMetaCommandError)):
        PARSER.extract_objects(script)


@pytest.mark.parametrize(
    "script, expected",
    [
        (
            "CREATE TABLE a(x);\x00CREATE TABLE b(y);",
            [(SqlObjectType.TABLE, "a", None)],
        ),
        (
            "CREATE TABLE a(x);\n/\nCREATE TABLE b(y);",
            [(SqlObjectType.TABLE, "a", None)],
        ),
        (
            "CREATE TABLE a(x); CREATE TABLE b(y);",
            [(SqlObjectType.TABLE, "a", None), (SqlObjectType.TABLE, "b", None)],
        ),
    ],
)
def test_extract_objects_preserves_scanner_selected_tables(script, expected):
    # NUL and slash prefixes leave the scanner's second unit without a proven CREATE head.
    assert [(o.object_type, o.name, o.schema) for o in PARSER.extract_objects(script)] == expected


# --- undo of a trigger -----------------------------------------------------------------


# --- DML ----------------------------------------------------------------------------


@pytest.mark.parametrize(
    "sql",
    [
        "INSERT INTO t VALUES (1)",
        "INSERT INTO t(a) SELECT a FROM u",
        "INSERT OR REPLACE INTO t VALUES (1)",
        "REPLACE INTO t VALUES (1)",
        "INSERT INTO t VALUES (X'00', ?1)",
    ],
)
def test_an_insert_is_never_a_full_table_dml(sql):
    assert SqliteQuirks().is_full_table_dml(sql) is False
    assert is_full_table_dml(sql, quirks=_quirks("sqlite")) is False


@pytest.mark.parametrize(
    "sql, full",
    [
        ("UPDATE OR REPLACE t SET a=1 WHERE b=2", False),
        ("UPDATE OR IGNORE t SET a=1 WHERE b=2", False),
        ("UPDATE OR IGNORE t SET a=1", True),
    ],
)
def test_update_with_a_conflict_clause_keeps_events_columns_and_full_table_result(sql, full):
    mutation = analyze_dml(sql, quirks=_quirks("sqlite"))

    assert mutation.events == {"UPDATE"}
    assert mutation.updated_columns == ["a"]
    assert SqliteQuirks().is_full_table_dml(sql) is full
    assert is_full_table_dml(sql, quirks=_quirks("sqlite")) is full
    assert analyse_script(sql, "sqlite").statements[0].kind == "DML"


def test_replace_into_keeps_its_kind_and_dml_result():
    sql = "REPLACE INTO t(a) VALUES (1)"
    mutation = analyze_dml(sql, quirks=_quirks("sqlite"))

    assert (mutation.events, mutation.updated_columns) == (None, [])
    assert SqliteQuirks().is_full_table_dml(sql) is False
    assert analyse_script(sql, "sqlite").statements[0].kind == "DML"
    assert SqlAnalyzer("sqlite").analyze_statement(sql)["type"] == "DML"


# --- execution does not warn about statements it ran ----------------------------------


def test_executing_a_trigger_does_not_log_a_warning():
    provider = Mock(spec=["execute_statement"])
    provider.execute_statement.return_value = 0
    journal = Mock(
        spec=["record_statement_start", "record_statement_complete", "record_object_changes"]
    )
    service = SqlExecutionService(
        provider, SqlAnalyzer("sqlite"), journal=journal, quirks=SqliteQuirks()
    )
    service.log = Mock()

    service.execute_statement(TRIGGER, stmt_index=0)

    assert journal.record_object_changes.call_count == 1
    service.log.warning.assert_not_called()
