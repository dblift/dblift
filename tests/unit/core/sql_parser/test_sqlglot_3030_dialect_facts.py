"""SQLGlot 30.30 parses PostgreSQL-only clauses on every dialect; the facts follow the engine.

PostgreSQL and Oracle accept ``CREATE INDEX … TABLESPACE`` and PostgreSQL names the trigger's table
in ``DROP TRIGGER … ON``, so their facts gain detail. The other engines reject those forms, so
their facts stay opaque and name nothing, as they did while the grammar held the statement as a
command. DuckDB has no triggers at all.
"""

import pytest
from sqlglot import exp, parse_one

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import _head_facts, read_statement_facts
from dblift.db.plugins.duckdb.parser.duckdb_facts_parser import DuckDBStatementFactsReader

T = SqlObjectType

# sqlglot 30.23 holds a PostgreSQL TABLESPACE clause as a command; 30.30 parses it.
PARSES_TABLESPACE = isinstance(
    parse_one("CREATE INDEX i ON m (a) TABLESPACE ts", read="postgres"), exp.Create
)
NO_INDEX_TABLESPACE = ["mysql", "tsql", "sqlite", "duckdb", "snowflake"]
NO_DROP_TRIGGER_ON = ["mysql", "tsql", "oracle", "sqlite", "snowflake", "redshift"]


def _objects(facts):
    return [(o.name, o.type, o.role) for o in facts.objects]


@pytest.mark.parametrize("dialect", NO_INDEX_TABLESPACE)
@pytest.mark.parametrize(
    "sql",
    ['CREATE INDEX "Ix" ON "T" (a) TABLESPACE ts', "CREATE UNIQUE INDEX i ON m (a) TABLESPACE ts"],
)
def test_an_index_tablespace_clause_the_engine_rejects_names_nothing(dialect, sql):
    facts = read_statement_facts(sql, dialect=dialect)

    assert (facts.operation, facts.kind, facts.objects) == ("CREATE", "DDL", ())
    assert facts.indexed_table is None and facts.indexed_columns is None
    assert facts.diagnostic.endswith(f"{dialect} TABLESPACE clause is not supported")


@pytest.mark.parametrize("dialect", NO_INDEX_TABLESPACE)
def test_an_index_on_a_table_named_tablespace_keeps_its_objects(dialect):
    facts = read_statement_facts("CREATE INDEX i ON tablespace (a)", dialect=dialect)

    assert ("I" if dialect == "snowflake" else "i", T.INDEX, "created") in _objects(facts)
    assert not (facts.diagnostic or "").endswith(f"{dialect} TABLESPACE clause is not supported")


def test_a_mysql_table_tablespace_option_is_not_the_index_clause():
    """MySQL accepts TABLESPACE as a CREATE TABLE option: the table stays named."""
    facts = read_statement_facts("CREATE TABLE m (a int) TABLESPACE ts", dialect="mysql")

    assert _objects(facts) == [("m", T.TABLE, "created")]


@pytest.mark.parametrize("dialect", ["postgres", "oracle"])
def test_an_index_tablespace_clause_the_engine_accepts_keeps_the_index_and_its_table(dialect):
    facts = read_statement_facts("CREATE INDEX i ON m (a) TABLESPACE ts", dialect=dialect)

    index, table = ("I", "M") if dialect == "oracle" else ("i", "m")
    assert (index, T.INDEX, "created") in _objects(facts)
    if PARSES_TABLESPACE:
        assert _objects(facts) == [(index, T.INDEX, "created"), (table, T.TABLE, "referenced")]
        assert facts.indexed_table == table
        assert facts.indexed_columns == ("a",) and not facts.opaque
    else:  # the head names the index, and Oracle's head its table as well
        assert facts.opaque


@pytest.mark.skipif(not PARSES_TABLESPACE, reason="sqlglot 30.23 holds the clause as a command")
def test_postgres_reads_the_columns_of_a_table_created_in_a_tablespace():
    """dblift/dblift#666: PostgreSQL accepts both forms (measured on 16: 42704, not 42601)."""
    for sql in (
        "CREATE TABLE m (a int, b text) WITH (fillfactor=70) TABLESPACE ts",
        "CREATE TABLE m (a int, b text) TABLESPACE ts",
    ):
        facts = read_statement_facts(sql, dialect="postgres")

        assert _objects(facts) == [("m", T.TABLE, "created")]
        assert facts.declared_columns == ("a", "b")
        assert not facts.opaque


@pytest.mark.parametrize("dialect", NO_DROP_TRIGGER_ON)
@pytest.mark.parametrize("sql", ["DROP TRIGGER trg ON t", "DROP TRIGGER IF EXISTS trg ON s.t"])
def test_a_drop_trigger_on_clause_outside_postgres_names_nothing(dialect, sql):
    facts = read_statement_facts(sql, dialect=dialect)

    assert (facts.operation, facts.kind, facts.objects) == ("DROP", "DDL", ())
    assert facts.diagnostic.endswith(f"{dialect} DROP TRIGGER ON clause is not supported")


@pytest.mark.parametrize("dialect", NO_DROP_TRIGGER_ON)
def test_a_plain_drop_trigger_is_not_the_on_clause(dialect):
    facts = read_statement_facts("DROP TRIGGER trg", dialect=dialect)

    assert not (facts.diagnostic or "").endswith(
        f"{dialect} DROP TRIGGER ON clause is not supported"
    )
    assert ("TRG" if dialect in {"oracle", "snowflake"} else "trg", T.TRIGGER, "dropped") in (
        _objects(facts)
    )


@pytest.mark.parametrize("sql", ["DROP TRIGGER trg ON DATABASE", "DROP TRIGGER trg ON ALL SERVER"])
def test_a_tsql_ddl_trigger_scope_is_not_the_on_clause(sql):
    facts = read_statement_facts(sql, dialect="tsql")

    assert not (facts.diagnostic or "").endswith("tsql DROP TRIGGER ON clause is not supported")


def test_postgres_drop_trigger_on_keeps_its_trigger():
    facts = read_statement_facts("DROP TRIGGER IF EXISTS trg ON s.t", dialect="postgres")

    assert _objects(facts) == [("trg", T.TRIGGER, "dropped")]


@pytest.mark.parametrize(
    "sql, operation",
    [
        ('CREATE TRIGGER "Tg" AFTER INSERT ON "T" FOR EACH ROW EXECUTE FUNCTION f()', "CREATE"),
        (
            "CREATE TRIGGER trg1 BEFORE INSERT ON app.orders FOR EACH ROW SET NEW.a = NOW()",
            "CREATE",
        ),
        (
            "CREATE OR REPLACE TRIGGER t AFTER DELETE ON x FOR EACH ROW EXECUTE FUNCTION f()",
            "CREATE",
        ),
        ("DROP TRIGGER IF EXISTS my_trigger ON myschema.my_table", "DROP"),
        ("DROP TRIGGER trg", "DROP"),
        ("ALTER TRIGGER trg ON t RENAME TO trg2", "ALTER"),
    ],
)
def test_duckdb_has_no_triggers(sql, operation):
    facts = DuckDBStatementFactsReader("duckdb").read(sql)

    assert (facts.operation, facts.kind, facts.objects) == (operation, "DDL", ())
    assert facts.diagnostic == "duckdb does not support triggers"


def test_duckdb_still_reads_a_table_that_mentions_triggers():
    facts = DuckDBStatementFactsReader("duckdb").read("CREATE TABLE trigger_log (a int)")

    assert _objects(facts) == [("trigger_log", T.TABLE, "created")]
    assert not facts.opaque


@pytest.mark.parametrize("dialect", ["sqlite", "snowflake", "redshift", "duckdb"])
def test_a_head_read_predicate_drops_its_where_keyword(dialect):
    """The parsed path returns the condition alone; the head path returns the same shape."""
    facts = _head_facts("UPDATE t SET v = 1 WHERE id = 1 RETURNING id", "unread", dialect=dialect)

    assert facts.operation == "UPDATE"
    assert facts.predicate == "id = 1 RETURNING id"
