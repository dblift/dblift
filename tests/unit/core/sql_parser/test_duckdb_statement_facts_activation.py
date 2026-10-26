"""DuckDB facts activate consumers without replacing the engine script scanner."""

import subprocess
import sys

import pytest

from dblift.core.exceptions import UnsafeStatementSplitError, UnsupportedMetaCommandError
from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.db.dml_analysis import analyze_dml, statement_dml_table, updates_restore_key
from dblift.db.plugins.duckdb.quirks import DuckDBQuirks
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser

_quirks = ProviderRegistry.get_quirks

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


@pytest.mark.parametrize(
    ("sql", "action", "target"),
    [
        ("SET schema 's'", "SELECT_NAMESPACE", "s"),
        ("SET schema='s'", "SELECT_NAMESPACE", "s"),
        ("SET schema='a.s'", "SELECT_NAMESPACE", "a.s"),
        ("SET schema 'a.s'", "SELECT_NAMESPACE", "a.s"),
        ("SET schema=a.s", "SELECT_NAMESPACE", "a.s"),
        ("SET schema=s", "SELECT_NAMESPACE", "s"),
        ('SET schema="s"', "SELECT_NAMESPACE", '"s"'),
        ("USE s", "SELECT_NAMESPACE", "s"),
        ('USE "s"', "SELECT_NAMESPACE", '"s"'),
        ("USE memory.s", "SELECT_NAMESPACE", "memory.s"),
        ('USE "memory"."s"', "SELECT_NAMESPACE", '"memory"."s"'),
        ("USE s . b", "SELECT_NAMESPACE", "s . b"),
        ('USE "s" . "b"', "SELECT_NAMESPACE", '"s" . "b"'),
        ("SET search_path=s", "SELECT_NAMESPACE", "s"),
        ("SET search_path='s'", "SELECT_NAMESPACE", "s"),
        ("SET search_path='a.s'", "SELECT_NAMESPACE", "a.s"),
        ('SET search_path="s"', "SELECT_NAMESPACE", '"s"'),
        ("RESET schema", "RESET_NAMESPACE", None),
        ("RESET search_path", "RESET_NAMESPACE", None),
    ],
)
def test_plain_namespace_selection_has_a_session_fact(sql, action, target):
    facts = DuckDBQuirks().statement_facts(sql)

    assert not facts.opaque
    assert facts.action == action
    assert facts.target == target


@pytest.mark.parametrize(
    "sql",
    [
        "SET search_path='s,main'",
        "SET schema='s' extra",
        "SET schema='a.b.c'",
        "USE a.b.c",
        "SET schema current_schema()",
    ],
)
def test_unresolved_schema_selection_stays_opaque(sql):
    assert DuckDBQuirks().statement_facts(sql).opaque


@pytest.mark.parametrize(
    "sql",
    [
        "SET schema s",
        'SET schema "s"',
        "SET search_path s",
        "SET search_path 's'",
        'SET search_path "s"',
        'SET schema="s,main"',
        'SET schema="a""b"',
    ],
)
def test_native_rejected_namespace_forms_are_not_claimed(sql):
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA s")
        with pytest.raises(duckdb.ParserException):
            connection.execute(sql)
    finally:
        connection.close()

    assert DuckDBQuirks().statement_facts(sql).opaque


def test_native_multi_entry_quoted_search_path_is_not_one_selected_namespace():
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA s")
        connection.execute("CREATE SCHEMA b")
        connection.execute('SET search_path="s,b"')
        current = connection.execute("SELECT current_schema()").fetchone()[0]
    finally:
        connection.close()

    assert current == "s"
    assert DuckDBQuirks().statement_facts('SET search_path="s,b"').opaque


@pytest.mark.parametrize(
    ("sql", "target"),
    [
        ('USE "s"', '"s"'),
        ("USE memory.s", "memory.s"),
        ('USE "memory"."s"', '"memory"."s"'),
    ],
)
def test_native_use_preserves_the_written_namespace(sql, target):
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA s")
        connection.execute(sql)
        current = connection.execute("SELECT current_catalog(), current_schema()").fetchone()
    finally:
        connection.close()

    facts = DuckDBQuirks().statement_facts(sql)
    assert not facts.opaque
    assert (facts.action, facts.target) == ("SELECT_NAMESPACE", target)
    assert current == ("memory", "s")


@pytest.mark.parametrize("sql", ['SET schema="s"', 'SET search_path="s"'])
def test_native_quoted_set_selector_keeps_the_quotes(sql):
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA s")
        connection.execute(sql)
        current = connection.execute("SELECT current_catalog(), current_schema()").fetchone()
    finally:
        connection.close()

    facts = DuckDBQuirks().statement_facts(sql)
    assert not facts.opaque
    assert (facts.action, facts.target) == ("SELECT_NAMESPACE", '"s"')
    assert current == ("memory", "s")


@pytest.mark.parametrize("sql", ["USE s . b", 'USE "s" . "b"'])
def test_native_use_with_space_around_dot_keeps_raw_target(sql):
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("ATTACH ':memory:' AS s")
        connection.execute("CREATE SCHEMA s.b")
        connection.execute(sql)
        current = connection.execute("SELECT current_catalog(), current_schema()").fetchone()
    finally:
        connection.close()

    facts = DuckDBQuirks().statement_facts(sql)
    assert not facts.opaque
    assert (facts.action, facts.target) == ("SELECT_NAMESPACE", sql.removeprefix("USE "))
    assert current == ("s", "b")


def test_null_table_comment_keeps_target_and_removal_value():
    facts = DuckDBQuirks().statement_facts("COMMENT ON TABLE main.t IS NULL")

    assert not facts.opaque
    assert facts.operation == "COMMENT"
    assert [(obj.name, obj.schema, obj.role) for obj in facts.objects] == [("t", "main", "altered")]
    assert facts.table_comment is None


def test_catalog_qualified_null_table_comment_keeps_the_full_target():
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE main.t(id INT)")
        connection.execute("COMMENT ON TABLE main.t IS 'old'")
        connection.execute("COMMENT ON TABLE memory.main.t IS NULL")
        removed = connection.execute(
            "SELECT comment FROM duckdb_tables() WHERE schema_name = 'main' AND table_name = 't'"
        ).fetchone()[0]
    finally:
        connection.close()

    facts = DuckDBQuirks().statement_facts("COMMENT ON TABLE memory.main.t IS NULL")
    assert not facts.opaque
    assert [(obj.name, obj.schema) for obj in facts.objects] == [("t", "memory.main")]
    assert facts.table_comment is None
    assert removed is None


def test_quoted_catalog_qualified_null_comment_keeps_raw_target():
    facts = DuckDBQuirks().statement_facts('COMMENT ON TABLE "memory"."main"."t" IS NULL')

    assert not facts.opaque
    assert [(obj.name, obj.schema, obj.name_quoted) for obj in facts.objects] == [
        ("t", "memory.main", True)
    ]
    assert facts.target_sql == '"memory"."main"."t"'
    assert facts.objects[0].catalog == "memory"


@pytest.mark.parametrize(
    "sql, catalog",
    [
        ('COMMENT ON TABLE a."b.c".t IS NULL', "a"),
        ('COMMENT ON TABLE "a.b".c.t IS NULL', "a.b"),
    ],
)
def test_null_comment_keeps_dotted_catalog_boundary(sql, catalog):
    facts = DuckDBQuirks().statement_facts(sql)

    assert not facts.opaque
    assert facts.objects[0].schema == "a.b.c"
    assert facts.objects[0].catalog == catalog


@pytest.mark.parametrize(
    ("sql", "expected"),
    [
        ("COMMENT ON TABLE t IS 'O''Brien'", "O'Brien"),
        ("COMMENT ON TABLE t IS ''", ""),
    ],
)
def test_table_comment_facts_carry_literal_value(sql, expected):
    facts = DuckDBQuirks().statement_facts(sql)

    assert not facts.opaque
    assert facts.table_comment == expected


def test_selected_schema_does_not_resolve_an_unqualified_comment_target():
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE SCHEMA s")
        connection.execute("CREATE TABLE main.t(id INT)")
        connection.execute("SET schema 's'")
        connection.execute("COMMENT ON TABLE t IS 'main table'")
        rows = connection.execute(
            "SELECT schema_name, comment FROM duckdb_tables() WHERE table_name = 't'"
        ).fetchall()
    finally:
        connection.close()

    selection = DuckDBQuirks().statement_facts("SET schema 's'")
    comment = DuckDBQuirks().statement_facts("COMMENT ON TABLE t IS 'main table'")
    assert selection.target == "s"
    assert comment.objects[0].schema is None
    assert rows == [("main", "main table")]


def test_namespace_selector_can_name_an_attached_catalog():
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("ATTACH ':memory:' AS other")
        connection.execute("SET schema 'other'")
        current = connection.execute("SELECT current_catalog(), current_schema()").fetchone()
    finally:
        connection.close()

    facts = DuckDBQuirks().statement_facts("SET schema 'other'")
    assert (facts.action, facts.target) == ("SELECT_NAMESPACE", "other")
    assert current == ("other", "main")


@pytest.mark.parametrize(
    "sql",
    ["SET schema='a.s'", "SET schema 'a.s'", "SET schema=a.s", "SET search_path='a.s'"],
)
def test_dotted_namespace_selector_can_name_an_attached_schema(sql):
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("ATTACH ':memory:' AS a")
        connection.execute("CREATE SCHEMA a.s")
        connection.execute(sql)
        current = connection.execute("SELECT current_catalog(), current_schema()").fetchone()
    finally:
        connection.close()

    facts = DuckDBQuirks().statement_facts(sql)
    assert (facts.action, facts.target) == ("SELECT_NAMESPACE", "a.s")
    assert current == ("a", "s")


def test_null_table_comment_really_removes_the_comment():
    duckdb = pytest.importorskip("duckdb")
    connection = duckdb.connect(":memory:")
    try:
        connection.execute("CREATE TABLE t(id INT)")
        connection.execute("COMMENT ON TABLE t IS 'documented'")
        connection.execute("COMMENT ON TABLE t IS NULL")
        comment = connection.execute(
            "SELECT comment FROM duckdb_tables() WHERE schema_name = 'main' AND table_name = 't'"
        ).fetchone()[0]
    finally:
        connection.close()

    assert comment is None


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_factory_preserves_mutation_target_in_each_supported_mode(mode, sql):
    result = facts_parser("duckdb").parse_sql(sql)

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
def test_comment_only_script_is_successful_and_has_no_statements(mode):
    factory = facts_parser("duckdb")
    result = factory.parse_sql("/* outer /* inner */ tail */")

    assert result.success, result.errors
    assert result.statements == []
    assert factory.split_statements("/* outer /* inner */ tail */") == []


@pytest.mark.parametrize(
    ("sql", "error"),
    [
        ("CREATE TABLE child(id INT);\n.mode csv\nSELECT 1;", UnsupportedMetaCommandError),
        ("CREATE TABLE child(id INT);\x00DROP TABLE child;", UnsafeStatementSplitError),
    ],
)
def test_refused_script_has_no_partial_analysis(sql, error):
    analysis = analyse_script(sql, "duckdb")
    assert analysis.statements == ()
    assert analysis.errors
    for mode in ("regex", "hybrid", "sqlglot"):
        factory = facts_parser("duckdb")
        with pytest.raises(error):
            factory.split_statements(sql)
        parsed = factory.parse_sql(sql)
        assert not parsed.success
        assert parsed.statements == []


@pytest.mark.parametrize("sql", ["CREATE TYPE mood AS ENUM ('ok')", "DROP TYPE mood"])
def test_opaque_type_keeps_ddl_classification_without_guessing_an_object(sql):
    facts = DuckDBQuirks().statement_facts(sql)
    analysis = analyse_script(sql, "duckdb")

    assert facts.kind == "DDL" and facts.opaque and facts.objects == ()
    assert [statement.kind for statement in analysis.statements] == ["DDL"]
    assert analysis.statements[0].objects == ()


@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_full_analyzer_classifies_mutations(sql):
    assert StatementReader("duckdb", analysis_mode="full").get_statement_type(sql) == "DML"


def test_execution_analyzer_does_not_import_sqlglot():
    probe = subprocess.run(
        [
            sys.executable,
            "-c",
            "import sys; "
            "from dblift.core.migration.sql.statement_reader import StatementReader; "
            "analyzer = StatementReader('duckdb', analysis_mode='execution'); "
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


@pytest.mark.parametrize("mode", ["regex", "hybrid", "sqlglot"])
@pytest.mark.parametrize("sql", [CTE_UPDATE, COPY_FROM])
def test_factory_affected_objects_projects_facts(mode, sql):
    objects = facts_parser("duckdb").get_affected_objects(sql)
    assert [(obj.object_type.value, obj.name) for obj in objects] == [("TABLE", "child")]


@pytest.mark.parametrize(
    "sql,name,schema",
    [
        ("DROP SCHEMA s CASCADE", "s", None),
        ('DROP SCHEMA "Warehouse"."Reporting" CASCADE', "Reporting", "Warehouse"),
    ],
)
def test_drop_schema_keeps_identity_and_destructive_caution(sql, name, schema):
    analysis = analyse_script(sql, "duckdb")
    assert analysis.errors == ()
    assert [(obj.type, obj.name, obj.schema) for obj in analysis.statements[0].objects] == [
        ("SCHEMA", name, schema)
    ]
    assert [(caution.level, caution.code) for caution in analysis.cautions] == [
        ("destroys", "drop-schema")
    ]


@pytest.mark.parametrize(
    "sql,kind",
    [
        ("COMMENT ON TABLE child IS 'note'", "DDL"),
        ("SHOW TABLES", "QUERY"),
        ("DESCRIBE child", "QUERY"),
    ],
)
def test_metadata_statements_keep_full_analyzer_classification(sql, kind):
    assert StatementReader("duckdb", analysis_mode="full").get_statement_type(sql) == kind


def test_comment_on_table_preserves_script_ddl_classification():
    analysis = analyse_script("COMMENT ON TABLE child IS 'note'", "duckdb")
    assert analysis.errors == ()
    assert analysis.statements[0].kind == "DDL"
    assert [(obj.type, obj.name) for obj in analysis.statements[0].objects] == [("TABLE", "child")]


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE child AS c SET id = 2 WHERE c.id = 1",
        "UPDATE ONLY child SET id = 2",
        "DELETE FROM ONLY child WHERE id = 1",
        "DELETE FROM child AS c WHERE c.id = 1",
        "MERGE INTO child AS c USING source AS s ON c.id = s.id WHEN MATCHED THEN DELETE",
    ],
)
def test_dml_target_sql_excludes_statement_local_modifiers(sql):
    assert statement_dml_table(sql, quirks=_quirks("duckdb")) == "child"


def test_dml_target_sql_preserves_qualified_quoted_identity_without_alias():
    sql = 'UPDATE "Warehouse"."Sales"."Order Items" AS c SET id = 2 WHERE c.id = 1'
    assert statement_dml_table(sql, quirks=_quirks("duckdb")) == '"Warehouse"."Sales"."Order Items"'


@pytest.mark.parametrize(
    "sql,kind",
    [
        ("COMMENT ON COLUMN child.id IS 'note'", "DDL"),
        ("COMMENT ON VIEW v IS 'note'", "DDL"),
        ("COMMENT ON INDEX idx IS 'note'", "DDL"),
        ("COMMENT ON SEQUENCE seq IS 'note'", "DDL"),
        ("SHOW DATABASES", "QUERY"),
    ],
)
def test_opaque_metadata_preserves_high_level_classification(sql, kind):
    facts = DuckDBQuirks().statement_facts(sql)
    assert facts.kind == kind
    assert facts.opaque
    assert facts.objects == ()
    assert StatementReader("duckdb").get_statement_type(sql) == kind


@pytest.mark.parametrize(
    "sql,columns,updates_key",
    [
        ("INSERT INTO child(value) VALUES(10) ON CONFLICT(value) DO UPDATE SET id=2", ["id"], True),
        ("INSERT INTO child(id,value) VALUES(1,10)", [], False),
        (
            "INSERT INTO child(id,value) VALUES(1,10) ON CONFLICT(id) DO UPDATE SET value=20",
            ["value"],
            False,
        ),
    ],
)
@pytest.mark.parametrize("dialect", ["duckdb", "sqlite"])
def test_insert_facts_keep_update_assignments_for_restore_key_checks(
    sql, columns, updates_key, dialect
):
    assert analyze_dml(sql, quirks=_quirks(dialect)).updated_columns == columns
    assert updates_restore_key(sql, ["id"], quirks=_quirks(dialect)) is updates_key


def test_prepared_execute_keeps_dml_classification():
    facts = DuckDBQuirks().statement_facts("EXECUTE stmt")
    assert facts.kind == "DML"
    assert facts.opaque
    assert facts.objects == ()
    assert StatementReader("duckdb").get_statement_type("EXECUTE stmt") == "DML"


def test_copy_import_columns_do_not_count_as_restore_key_updates():
    sql = "COPY child(id) FROM 'x.csv'"
    facts = DuckDBQuirks().statement_facts(sql)
    assert facts.events == frozenset({"INSERT"})
    assert facts.affected_columns == ("id",)
    assert analyze_dml(sql, quirks=_quirks("duckdb")).updated_columns == []
    assert not updates_restore_key(sql, ["id"], quirks=_quirks("duckdb"))
