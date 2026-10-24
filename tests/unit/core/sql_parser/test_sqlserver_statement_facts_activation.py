"""SQL Server statement facts reach the public parser and analyzer paths."""

import pytest

from dblift.core.migration.sql.statement_reader import StatementReader
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import SqlglotStatementFactsReader
from dblift.core.sql_parser.statement_facts_parser import StatementFactsParser
from dblift.db.provider_registry import ProviderRegistry
from tests.support.facts_parser import facts_parser


def test_plugin_reads_statement_facts():
    quirks = ProviderRegistry.get_quirks("sqlserver")

    assert quirks.supports_statement_facts
    assert isinstance(quirks.statement_facts_reader(), SqlglotStatementFactsReader)
    facts = quirks.statement_facts("CREATE TABLE [MiXeD].[a]]b] (id INT)")
    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert [(obj.name, obj.schema, obj.role) for obj in facts.affected_objects] == [
        ("a]b", "MiXeD", "created")
    ]


def test_the_facts_parser_keeps_go_batches_lexical():
    factory = facts_parser("sqlserver")
    parser = factory

    assert isinstance(parser, StatementFactsParser)
    script = "CREATE TABLE [MiXeD].[a]]b] (id INT)\nGO\nDROP TABLE [MiXeD].[a]]b]"
    assert factory.split_statements(script) == [
        "CREATE TABLE [MiXeD].[a]]b] (id INT)",
        "DROP TABLE [MiXeD].[a]]b]",
    ]
    assert [(obj.name, obj.schema) for obj in factory.extract_objects(script)] == [
        ("a]b", "MiXeD"),
        ("a]b", "MiXeD"),
    ]


def test_analyzer_extracts_objects_from_facts():
    analyzer = StatementReader("sqlserver")

    sql = "UPDATE [MiXeD].[a]]b] SET id = 2 WHERE id = 1"

    assert analyzer.extract_objects(sql) == [{"object_type": "TABLE", "object_name": "MiXeD.a]b"}]
    assert analyzer.analyze_statement(sql)["parsed_with"] == "facts"


@pytest.mark.parametrize(
    ("sql", "operation", "kind", "name", "schema", "role"),
    [
        ("CREATE TABLE [a]]b] (id INT)", "CREATE", "DDL", "a]b", None, "created"),
        (
            "CREATE TABLE [MiXeD].[a]]b] (id INT)",
            "CREATE",
            "DDL",
            "a]b",
            "MiXeD",
            "created",
        ),
        (
            "CREATE TABLE [DbOne].[MiXeD].[a]]b] (id INT)",
            "CREATE",
            "DDL",
            "a]b",
            "DbOne.MiXeD",
            "created",
        ),
        (
            "UPDATE [MiXeD].[a]]b] SET id = 2 WHERE id = 1",
            "UPDATE",
            "DML",
            "a]b",
            "MiXeD",
            "altered",
        ),
    ],
)
def test_raw_reader_preserves_written_names(sql, operation, kind, name, schema, role):
    facts = read_statement_facts(sql, dialect="tsql")

    assert (facts.operation, facts.kind) == (operation, kind)
    assert [(obj.name, obj.schema, obj.role) for obj in facts.affected_objects] == [
        (name, schema, role)
    ]
    assert facts.diagnostic is None


def test_unread_xml_index_stays_opaque():
    facts = read_statement_facts("CREATE XML INDEX [ix] ON [MiXeD].[t] ([doc])", dialect="tsql")

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.objects == ()
    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None


def test_unread_update_top_does_not_invent_a_target():
    facts = read_statement_facts(
        "UPDATE TOP (1) dbo.t SET x=2 OUTPUT inserted.x WHERE id=1", dialect="tsql"
    )

    assert (facts.operation, facts.kind) == ("UPDATE", "DML")
    assert facts.target is None
    assert facts.affected_objects == ()
    assert facts.diagnostic


@pytest.mark.parametrize(
    ("sql", "operation", "kind"),
    [
        ("DROP INDEX real_one.idx1;", "DROP", "DDL"),
        ("DROP INDEX dbo.real_one.idx1;", "DROP", "DDL"),
        ("CREATE XML INDEX idx1 ON real_one (xml_col);", "CREATE", "DDL"),
        ("CREATE PRIMARY XML INDEX idx1 ON real_one (xml_col);", "CREATE", "DDL"),
        ("DELETE TOP (5) [Cap Probe] WHERE id = 1", "DELETE", "DML"),
        ("DELETE TOP (SELECT 5) PERCENT [s].[t] WHERE id = 1", "DELETE", "DML"),
        ("UPDATE TOP (10) [Cap Probe] SET b = 1", "UPDATE", "DML"),
        ("INSERT TOP (5) INTO [Cap Probe] (a) SELECT 1", "INSERT", "DML"),
    ],
)
def test_legacy_unread_forms_keep_explicit_no_object_facts(sql, operation, kind):
    """The old extractor named these forms, but the T-SQL facts reader cannot prove them."""
    facts = read_statement_facts(sql, dialect="tsql")

    assert (facts.operation, facts.kind) == (operation, kind)
    assert facts.objects == ()
    assert facts.target is None
    assert facts.events is None
    assert facts.opaque
    assert facts.diagnostic
    assert facts.error is None


def test_unsupported_trigger_command_does_not_invent_an_object():
    facts = read_statement_facts(
        "CREATE TRIGGER [tr] ON [dbo].[t] AFTER INSERT AS SELECT 1", dialect="tsql"
    )

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.affected_objects == ()
    assert facts.diagnostic


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE PROCEDURE dbo.p AS BEGIN UPDATE dbo.t SET id=1; END",
        "CREATE FUNCTION dbo.f() RETURNS INT AS BEGIN RETURN 1 END",
    ],
)
def test_program_body_does_not_claim_partially_parsed_effects(sql):
    facts = read_statement_facts(sql, dialect="tsql")

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.objects == ()
    assert facts.diagnostic


def test_four_part_reference_does_not_drop_a_name_component():
    facts = read_statement_facts("SELECT * FROM [Srv].[Db].[dbo].[MiXeD]", dialect="tsql")

    assert (facts.operation, facts.kind) == ("SELECT", "QUERY")
    if facts.objects:
        assert [(obj.schema, obj.name, obj.role) for obj in facts.objects] == [
            ("Srv.Db.dbo", "MiXeD", "referenced")
        ]
    else:
        assert facts.diagnostic


def test_omitted_schema_does_not_become_another_identity():
    facts = read_statement_facts("SELECT * FROM [Db]..[tbl]", dialect="tsql")

    assert (facts.operation, facts.kind) == ("SELECT", "QUERY")
    assert facts.objects == ()
    assert facts.diagnostic


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLE #tmp (id INT)",
        "CREATE TABLE ##tmp (id INT)",
        "SELECT * INTO #tmp FROM dbo.Source",
    ],
)
def test_temp_table_prefix_is_never_silently_lost(sql):
    facts = read_statement_facts(sql, dialect="tsql")

    if sql.startswith("SELECT"):
        assert (facts.operation, facts.kind) == ("SELECT", "DML")
    assert facts.objects == ()
    assert facts.diagnostic


def test_unmodelled_merge_keeps_its_dml_kind_without_guessed_effects():
    facts = read_statement_facts(
        "MERGE dbo.dst AS d USING dbo.src AS s ON d.id=s.id "
        "WHEN MATCHED THEN UPDATE SET d.v=s.v",
        dialect="tsql",
    )

    assert (facts.operation, facts.kind) == ("MERGE", "DML")
    assert facts.objects == ()
    assert facts.events is None
    assert facts.diagnostic


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE a SET x=1 FROM dbo.actual AS a WHERE a.id=1",
        "DELETE a FROM dbo.actual AS a WHERE a.id=1",
    ],
)
def test_alias_write_does_not_name_the_alias_as_a_source(sql):
    facts = read_statement_facts(sql, dialect="tsql")

    assert [(obj.schema, obj.name, obj.role) for obj in facts.objects] == [
        ("dbo", "actual", "altered")
    ]


def test_create_or_alter_program_has_no_unproven_action_or_body_effects():
    facts = read_statement_facts("CREATE OR ALTER PROCEDURE dbo.p AS SELECT 1", dialect="tsql")

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.objects == ()
    assert facts.diagnostic


@pytest.mark.parametrize(
    ("sql", "role"),
    [
        ("CREATE INDEX ix ON dbo.t(x)", "created"),
        ("DROP INDEX ix ON dbo.t", "dropped"),
    ],
)
def test_index_relation_keeps_owning_table(sql, role):
    facts = read_statement_facts(sql, dialect="tsql")

    assert [(obj.schema, obj.name, obj.role) for obj in facts.objects] == [
        ("dbo", "ix", role),
        ("dbo", "t", "referenced"),
    ]
    assert facts.indexed_table == "dbo.t"


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE CLUSTERED INDEX ix ON dbo.t(x)",
        "CREATE UNIQUE NONCLUSTERED INDEX ix ON dbo.t(x)",
    ],
)
def test_clustered_index_is_an_index(sql):
    facts = read_statement_facts(sql, dialect="tsql")

    assert [(obj.type.value, obj.name, obj.schema, obj.role) for obj in facts.affected_objects] == [
        ("INDEX", "ix", "dbo", "created")
    ]
    assert facts.indexed_table == "dbo.t"


def test_qualified_index_name_misparse_is_opaque():
    facts = read_statement_facts('CREATE INDEX "S"."Ix" ON "T" (a)', dialect="tsql")

    assert (facts.operation, facts.kind) == ("CREATE", "DDL")
    assert facts.objects == ()
    assert facts.diagnostic


@pytest.mark.parametrize(
    "sql",
    [
        "UPDATE OR IGNORE t SET a=1",
        "UPDATE OR REPLACE t SET a=1",
        "INSERT OR REPLACE INTO t VALUES (1)",
    ],
)
def test_foreign_dml_modifier_does_not_create_a_tsql_target(sql):
    facts = read_statement_facts(sql, dialect="tsql")

    assert facts.objects == ()
    assert facts.target is None
    assert facts.diagnostic


def test_nested_block_comment_keeps_the_ast_proven_target():
    facts = read_statement_facts(
        'ALTER TABLE /* outer /* inner */ x */ "s"."orders" ADD COLUMN c INT',
        dialect="tsql",
    )

    assert (facts.operation, facts.kind) == ("ALTER", "DDL")
    assert [(obj.name, obj.schema, obj.role) for obj in facts.affected_objects] == [
        ("orders", "s", "altered")
    ]
    assert facts.action == "add-column"
    assert facts.declared_columns == ("c",)
    assert facts.diagnostic is None


def test_nested_comment_head_ignores_words_inside_the_comment():
    facts = read_statement_facts(
        "/* outer /* inner */ tail */ COPY items (id) FROM 'input.csv'", dialect="tsql"
    )
    assert (facts.operation, facts.kind) == ("COPY", "UNKNOWN")
    assert facts.objects == () and facts.target is None and facts.events is None
    assert facts.diagnostic == "tsql Copy has no statement facts mapping"


def test_unterminated_nested_comment_has_no_executable_head_or_object():
    facts = read_statement_facts("/* outer /* inner */ DROP TABLE victim", dialect="tsql")
    assert (facts.operation, facts.kind) == ("UNKNOWN", "UNKNOWN")
    assert facts.objects == () and facts.target is None and facts.events is None
    assert facts.error and "unterminated" in facts.error


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("WITH c AS (SELECT * FROM dbo.t) UPDATE c SET x=1", "UPDATE"),
        ("WITH c AS (SELECT * FROM dbo.t) DELETE FROM c", "DELETE"),
        ("WITH c AS (SELECT * FROM dbo.t) UPDATE a SET x=1 FROM c AS a", "UPDATE"),
    ],
)
def test_cte_write_alias_is_not_reported_as_base_table(sql, operation):
    facts = read_statement_facts(sql, dialect="tsql")

    assert (facts.operation, facts.kind) == (operation, "DML")
    assert facts.objects == ()
    assert facts.target is None
    assert facts.events is None
    assert facts.diagnostic


@pytest.mark.parametrize(
    "sql",
    [
        "WITH d AS (INSERT INTO t VALUES (1) RETURNING id) SELECT * FROM d",
        "WITH d AS (DELETE FROM t RETURNING id) INSERT INTO out_table SELECT id FROM d",
    ],
)
def test_cte_mutation_body_does_not_downgrade_a_write_to_a_reference(sql):
    facts = read_statement_facts(sql, dialect="tsql")

    assert facts.objects == ()
    assert facts.diagnostic


def test_select_into_records_its_created_table():
    facts = read_statement_facts("SELECT id INTO dbo.NewTable FROM dbo.Source", dialect="tsql")

    assert (facts.operation, facts.kind) == ("SELECT", "DML")
    assert [(obj.schema, obj.name, obj.role) for obj in facts.objects] == [
        ("dbo", "NewTable", "created"),
        ("dbo", "Source", "referenced"),
    ]


@pytest.mark.parametrize(
    ("sql", "operation", "role"),
    [
        ("CREATE SCHEMA [MiXeD]", "CREATE", "created"),
        ("DROP SCHEMA [MiXeD]", "DROP", "dropped"),
    ],
)
def test_schema_name_is_projected_from_sqlglot_db_slot(sql, operation, role):
    facts = read_statement_facts(sql, dialect="tsql")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert [(obj.type.value, obj.name, obj.schema, obj.role) for obj in facts.objects] == [
        ("SCHEMA", "MiXeD", None, role)
    ]


def test_truncate_records_its_qualified_target():
    facts = read_statement_facts("TRUNCATE TABLE dbo.t", dialect="tsql")

    assert (facts.operation, facts.kind) == ("TRUNCATE", "DDL")
    assert [(obj.type.value, obj.name, obj.schema, obj.role) for obj in facts.objects] == [
        ("TABLE", "t", "dbo", "altered")
    ]


def test_partition_truncate_does_not_claim_whole_table_effect():
    facts = read_statement_facts("TRUNCATE TABLE dbo.t WITH (PARTITIONS (1))", dialect="tsql")

    assert (facts.operation, facts.kind) == ("TRUNCATE", "DDL")
    assert facts.objects == ()
    assert facts.diagnostic


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        ("CREATE MATERIALIZED VIEW mv AS SELECT 1 FROM dbo.t", "CREATE"),
        ("DROP MATERIALIZED VIEW mv", "DROP"),
    ],
)
def test_materialized_view_modifier_does_not_become_ordinary_view(sql, operation):
    facts = read_statement_facts(sql, dialect="tsql")

    assert (facts.operation, facts.kind) == (operation, "DDL")
    assert facts.objects == ()
    assert facts.diagnostic


def test_select_into_unrepresented_temporary_scope_is_opaque():
    facts = read_statement_facts("SELECT * INTO TEMP t2 FROM t", dialect="tsql")

    assert (facts.operation, facts.kind) == ("SELECT", "DML")
    assert facts.objects == ()
    assert facts.diagnostic
