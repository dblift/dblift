"""SQLite statement facts: lazy sqlglot, qualified indexes, refusals, references, CTE writes."""

import subprocess
import sys
import textwrap

import pytest

from dblift.core.migration.sql.script_analysis import analyse_script
from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.db.dml_analysis import analyze_dml, is_full_table_dml, statement_dml_table
from dblift.db.plugins.sqlite.parser.lexical_spec import SQLITE_SPEC
from dblift.db.plugins.sqlite.parser.sqlite_facts_parser import SQLiteFactsParser

READER = SqlglotStatementFactsReader("sqlite", SQLITE_SPEC)
PARSER = SQLiteFactsParser()


def _objects(facts):
    return [(o.type, o.name, o.schema, o.role) for o in facts.objects]


# --- execution-only splitting must not pay for sqlglot ------------------------------


def test_execution_splitting_does_not_import_sqlglot():
    code = textwrap.dedent("""
        import sys
        import dblift.core.migration.executor.execution_engine
        from dblift.core.migration.sql.execution_statement import execution_units
        from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
        from dblift.core.sql_parser.parser_factory import SqlParserFactory
        from dblift.db.plugins.sqlite.parser import SQLiteFactsParser
        from dblift.db.provider_registry import ProviderRegistry

        script = "CREATE TABLE a(x); INSERT INTO a VALUES(1);"
        expected = ["CREATE TABLE a(x)", "INSERT INTO a VALUES(1)"]
        ProviderRegistry.get_quirks("sqlite")
        assert SqlParserFactory("sqlite").split_statements(script) == expected
        assert SQLiteFactsParser().split_statements(script) == expected
        assert SqlAnalyzer("sqlite").split_statements(script) == expected
        assert len(execution_units(script, "sqlite")) == 2
        assert "sqlglot" not in sys.modules, "sqlglot imported while only splitting"
        """)
    result = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True)
    assert result.returncode == 0, result.stderr


# --- schema-qualified indexes -------------------------------------------------------


@pytest.mark.parametrize(
    "sql, schema",
    [
        ("CREATE INDEX main.ix ON t(c)", "main"),
        ("CREATE UNIQUE INDEX IF NOT EXISTS s.ix ON t(c)", "s"),
        ('CREATE INDEX "s"."ix" ON "t"("c")', "s"),
        ("CREATE INDEX ix ON t(c)", None),
    ],
)
def test_create_index_facts_carry_schema_on_the_index_not_the_table(sql, schema):
    facts = READER.read(sql)

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert _objects(facts) == [
        (SqlObjectType.INDEX, "ix", schema, "created"),
        (SqlObjectType.TABLE, "t", None, "referenced"),
    ]
    assert facts.indexed_table == "t"
    assert facts.indexed_columns == ("c",)
    assert not facts.opaque


@pytest.mark.parametrize(
    "sql", ["CREATE INDEX main.ix ON t(c)", "CREATE UNIQUE INDEX IF NOT EXISTS s.ix ON t(c)"]
)
def test_qualified_create_index_is_extracted_by_the_public_entry_points(sql):
    expected_schema = "main" if "main." in sql else "s"

    extracted = PARSER.extract_objects(sql)
    assert [(o.object_type, o.name, o.schema) for o in extracted] == [
        (SqlObjectType.INDEX, "ix", expected_schema)
    ]
    result = PARSER.parse_sql(sql)
    assert result.success
    assert [(o.name, o.schema) for o in result.statements[0].objects] == [("ix", expected_schema)]


@pytest.mark.parametrize(
    "sql", ["CREATE INDEX s.ix ON t(c DESC)", "CREATE INDEX s.ix ON t(c) WHERE c > 0"]
)
def test_qualified_index_forms_sqlglot_cannot_read_still_name_the_index(sql):
    facts = READER.read(sql)

    assert [(o.type, o.name, o.schema) for o in facts.affected_objects] == [
        (SqlObjectType.INDEX, "ix", "s")
    ]
    assert PARSER.extract_objects(sql)[0].name == "ix"


def test_drop_index_with_schema_names_the_index():
    facts = READER.read("DROP INDEX s.ix")

    assert _objects(facts) == [(SqlObjectType.INDEX, "ix", "s", "dropped")]
    assert [(o.name, o.schema) for o in PARSER.extract_objects("DROP INDEX s.ix")] == [("ix", "s")]


# --- analysis and extraction report a refused script ---------------------------------

REFUSED = [
    ".read x.sql\nSELECT 1;",
    "SELECT 1; /* open",
    "SELECT 6\n/\n2;",
]


@pytest.mark.parametrize("script", REFUSED)
def test_parse_sql_reports_the_refusal_as_an_error(script):
    result = PARSER.parse_sql(script)

    assert result.success is False
    assert result.statements == []
    assert len(result.errors) == 1
    assert result.errors[0].startswith("Error splitting SQL: ")


@pytest.mark.parametrize("script", REFUSED)
def test_extract_objects_returns_nothing_for_a_refused_script(script):
    assert PARSER.extract_objects(script) == []


@pytest.mark.parametrize("script", REFUSED)
def test_validate_sql_reports_the_refusal(script):
    verdict = PARSER.validate_sql(script)

    assert verdict["valid"] is False
    assert verdict["statements_found"] == 0
    assert len(verdict["errors"]) == 1


@pytest.mark.parametrize("script", REFUSED)
def test_script_analysis_reports_the_refusal(script):
    analysis = analyse_script(script, "sqlite")

    assert analysis.statements == ()
    assert len(analysis.errors) == 1
    assert analysis.errors[0].startswith("Error splitting SQL: ")


def test_facts_of_unsplit_text_holding_a_shell_command_do_not_raise():
    facts = READER.read("SELECT 1;\n.read x.sql\n")

    assert facts.opaque
    assert facts.error is None


# --- recognised statements never drop references or constraints silently --------------


def test_column_and_table_check_constraints_are_returned():
    column = READER.read("CREATE TABLE c(q INT CHECK (q > 0))")
    table = READER.read("CREATE TABLE c(q INT, CONSTRAINT ck CHECK (q > 0))")

    assert [(k.kind, k.columns, k.name) for k in column.declared_constraints] == [
        ("CHECK", ("q",), None)
    ]
    assert [(k.kind, k.columns, k.name) for k in table.declared_constraints] == [
        ("CHECK", ("q",), "ck")
    ]


def test_unique_table_constraints_are_returned():
    facts = READER.read("CREATE TABLE c(a INT, b INT, UNIQUE (a, b), CONSTRAINT un UNIQUE (b))")

    assert [(k.kind, k.columns, k.name) for k in facts.declared_constraints] == [
        ("UNIQUE", ("a", "b"), None),
        ("UNIQUE", ("b",), "un"),
    ]


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE c(p INT REFERENCES main.parent(id))",
        "CREATE TABLE c(p INT, FOREIGN KEY (p) REFERENCES main.parent(id))",
    ],
)
def test_foreign_key_targets_are_returned_as_referenced_tables_with_schema(sql):
    facts = READER.read(sql)

    assert (SqlObjectType.TABLE, "parent", "main", "referenced") in _objects(facts)
    assert [k.referenced_table for k in facts.declared_constraints] == ["parent"]


def test_added_column_reference_is_returned():
    facts = READER.read("ALTER TABLE t ADD COLUMN p INT REFERENCES parent(id)")

    assert [(k.kind, k.columns, k.referenced_table) for k in facts.declared_constraints] == [
        ("FOREIGN_KEY", ("p",), "parent")
    ]
    assert (SqlObjectType.TABLE, "parent", None, "referenced") in _objects(facts)
    assert [o.name for o in facts.affected_objects] == ["t"]


@pytest.mark.parametrize(
    "sql, created",
    [
        ("CREATE VIEW v AS SELECT a.x FROM a JOIN b ON a.id = b.id", "v"),
        ("CREATE TABLE t AS SELECT * FROM a JOIN b ON a.id = b.id", "t"),
    ],
)
def test_source_tables_of_a_query_defined_object_are_referenced(sql, created):
    facts = READER.read(sql)

    assert [o.name for o in facts.affected_objects] == [created]
    assert [o.name for o in facts.objects if o.role == "referenced"] == ["a", "b"]


def test_insert_select_source_tables_are_referenced_not_affected():
    facts = READER.read("INSERT INTO t(a) SELECT a FROM s1 JOIN main.s2 USING (id)")

    assert [o.name for o in facts.affected_objects] == ["t"]
    assert [(o.name, o.schema) for o in facts.objects if o.role == "referenced"] == [
        ("s1", None),
        ("s2", "main"),
    ]


def test_subquery_tables_of_update_and_delete_are_referenced():
    update = READER.read("UPDATE t SET a = (SELECT max(x) FROM s)")
    delete = READER.read("DELETE FROM t WHERE id IN (SELECT id FROM s)")

    for facts in (update, delete):
        assert [o.name for o in facts.affected_objects] == ["t"]
        assert [o.name for o in facts.objects if o.role == "referenced"] == ["s"]


def test_common_table_names_are_not_reported_as_referenced_tables():
    facts = READER.read("INSERT INTO t WITH x AS (SELECT id FROM src) SELECT id FROM x")

    assert [o.name for o in facts.objects if o.role == "referenced"] == ["src"]


def test_trigger_body_and_event_table_are_reported_as_skipped():
    facts = READER.read(
        "CREATE TRIGGER trg AFTER INSERT ON child BEGIN UPDATE other SET x = 1; END"
    )

    assert facts.opaque
    assert "trigger" in facts.diagnostic


# --- a write behind a WITH clause keeps its own operation -----------------------------

CTE_WRITES = [
    ("WITH x AS (SELECT 1) UPDATE t SET a = 1 WHERE b IN (SELECT * FROM x)", "UPDATE"),
    ("WITH x AS (SELECT 1) DELETE FROM t WHERE b IN (SELECT * FROM x)", "DELETE"),
    ("WITH x AS (SELECT 1) INSERT INTO t SELECT * FROM x", "INSERT"),
]


@pytest.mark.parametrize("sql, operation", CTE_WRITES)
def test_cte_write_facts_report_the_write_operation_and_target(sql, operation):
    facts = READER.read(sql)

    assert (facts.operation, facts.kind, facts.target) == (operation, "DML", "t")


@pytest.mark.parametrize("sql, operation", CTE_WRITES)
def test_cte_write_script_analysis_reports_the_write_operation(sql, operation):
    (statement,) = analyse_script(sql, "sqlite").statements

    assert statement.operation == operation
    assert statement.kind == "DML"
    assert [o.name for o in statement.objects] == ["t"]


@pytest.mark.parametrize("sql, operation", CTE_WRITES)
def test_cte_write_dml_analysis_reports_the_write_target(sql, operation):
    mutation = analyze_dml(sql, sqlglot_dialect="sqlite")

    assert mutation.table == "t"
    assert mutation.events == {operation}
    assert statement_dml_table(sql, "sqlite") == "t"
    assert is_full_table_dml(sql, sqlglot_dialect="sqlite") is False
