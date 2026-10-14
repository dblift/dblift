"""DuckDB facts activate consumers without replacing the engine script scanner."""

import subprocess
import sys

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.migration import Migration
from dblift.core.migration.scripting.undo_script_generator import UndoScriptGenerator
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_parser import SqlParserFactory
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks

CTE_UPDATE = "WITH x AS (SELECT 1) UPDATE child SET id = 2"
COPY_FROM = "COPY child FROM 'input.csv'"


def test_plugin_reads_facts_without_a_lexical_spec():
    facts = DuckDBQuirks().statement_facts(CTE_UPDATE)

    assert facts.operation == "UPDATE"
    assert facts.target == "child"
    assert facts.events == frozenset({"UPDATE"})


def test_plugin_comment_only_facts_have_no_diagnostic():
    facts = DuckDBQuirks().statement_facts("/* outer /* inner */ tail */")

    assert facts.operation == "UNKNOWN"
    assert facts.kind == "UNKNOWN"
    assert facts.diagnostic is None
    assert facts.error is None
    assert facts.objects == ()


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_factory_preserves_mutation_target_in_each_supported_mode(mode, sql):
    result = SqlParserFactory("duckdb", mode).parse_sql(sql)

    assert result.success, result.errors
    assert len(result.statements) == 1
    statement = result.statements[0]
    assert statement.statement_type.value == "DML"
    assert [(obj.object_type.value, obj.name) for obj in statement.affected_objects] == [
        ("TABLE", "child")
    ]


@pytest.mark.parametrize(
    ("sql", "operation", "kind", "objects"),
    [
        (CTE_UPDATE, "UPDATE", "DML", [("TABLE", "child")]),
        (COPY_FROM, "COPY", "DML", [("TABLE", "child")]),
        ("/* outer /* inner ; */ tail */ SELECT 1;", "SELECT", "QUERY", []),
        ("-- note\n", "UNKNOWN", "UNKNOWN", []),
    ],
)
def test_script_analysis_uses_facts_and_preserves_scanner_units(sql, operation, kind, objects):
    analysis = analyse_script(sql, "duckdb")

    assert analysis.errors == ()
    assert len(analysis.statements) == 1
    statement = analysis.statements[0]
    assert (statement.operation, statement.kind) == (operation, kind)
    assert [(obj.type, obj.name) for obj in statement.objects] == objects
    if sql == CTE_UPDATE:
        assert statement.full_table
        assert [caution.code for caution in analysis.cautions] == ["dml-no-where"]


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
def test_comment_only_analysis_is_successful_but_execution_has_no_statements(mode):
    factory = SqlParserFactory("duckdb", mode)
    result = factory.parse_sql("/* outer /* inner */ tail */")

    assert result.success, result.errors
    assert len(result.statements) == 1
    assert result.statements[0].statement_type.value == "UNKNOWN"
    assert factory.split_statements("/* outer /* inner */ tail */") == []


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("CREATE TABLE child(id INT);\n.mode csv\nSELECT 1;", UnsupportedMetaCommandError),
        ("CREATE TABLE child(id INT);\x00DROP TABLE child;", UnsafeStatementSplitError),
    ],
)
def test_refused_script_has_no_partial_analysis_or_undo(sql, error):
    analysis = analyse_script(sql, "duckdb")
    assert analysis.statements == ()
    assert analysis.errors
    for mode in ("regex", "hybrid", "sqlglot"):
        factory = SqlParserFactory("duckdb", mode)
        with pytest.raises(error):
            factory.split_statements(sql)
        parsed = factory.parse_sql(sql)
        assert not parsed.success
        assert parsed.statements == []
    migration = Migration(script_name="V1__child.sql", content=sql)
    with pytest.raises(error):
        UndoScriptGenerator("duckdb")._generate_undo_statements(migration)


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE OR REPLACE TABLE child(id INT)",
        "CREATE TABLE IF NOT EXISTS child(id INT)",
        "CREATE TABLE catalog.schema.items(id INT)",
    ],
)
def test_undo_requires_review_when_table_creation_cannot_be_safely_reversed(sql):
    migration = Migration(script_name="V1__child.sql", content=sql)
    undo = UndoScriptGenerator("duckdb")._generate_undo_statements(migration)

    assert len(undo) == 1
    assert undo[0].requires_manual_review
    assert undo[0].warning
    assert all(line.lstrip().startswith("--") for line in undo[0].sql.splitlines() if line.strip())


@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_full_analyzer_classifies_mutations(sql):
    assert SqlAnalyzer("duckdb", analysis_mode="full").get_statement_type(sql) == "DML"


def test_execution_analyzer_does_not_import_sqlglot():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer; "
            "analyzer = SqlAnalyzer('duckdb', analysis_mode='execution'); "
            "assert analyzer.get_statement_type('UPDATE child SET id = 2') == 'DML'; "
            "analyzer.extract_objects('UPDATE child SET id = 2'); "
            "assert analyzer.analyze_statement('UPDATE child SET id = 2')['type'] == 'DML'; "
            "assert not any(name == 'sqlglot' or name.startswith('sqlglot.') "
            "for name in sys.modules)",
        ],
        capture_output=True,
        text=True,
    )
    assert probe.returncode == 0, probe.stdout + probe.stderr


@pytest.mark.parametrize(
    "sql", ["SELECT * FROM child", "COPY child TO 'output.csv'", "/* outer /* inner */ tail */"]
)
def test_read_only_statements_and_comments_need_no_undo(sql):
    migration = Migration(script_name="V1__read.sql", content=sql)
    assert UndoScriptGenerator("duckdb")._generate_undo_statements(migration) == []


@pytest.mark.parametrize("sql", ["CREATE TABLE child(id INT)", "FUTURE COMMAND child"])
def test_mutations_and_unknown_commands_require_manual_undo(sql):
    migration = Migration(script_name="V1__child.sql", content=sql)
    undo = UndoScriptGenerator("duckdb")._generate_undo_statements(migration)
    assert len(undo) == 1
    assert undo[0].requires_manual_review
    assert undo[0].warning
    assert all(line.lstrip().startswith("--") for line in undo[0].sql.splitlines() if line.strip())


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_factory_affected_objects_projects_facts(mode, sql):
    objects = SqlParserFactory("duckdb", mode).get_affected_objects(sql)
    assert [(obj.object_type.value, obj.name) for obj in objects] == [("TABLE", "child")]
