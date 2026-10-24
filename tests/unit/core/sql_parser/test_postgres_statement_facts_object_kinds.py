"""PostgreSQL statement facts name the objects of the kinds sqlglot 30.23 returns as commands:
event triggers, foreign data wrappers, servers, publications, operator classes, text search
objects and tablespaces (dblift/dblift#669).

Every expectation is built by hand from what PostgreSQL 16.14 accepts, measured 2026-10-24 with
psql 16.14 against PostgreSQL 16.14 (Debian 16.14-1.pgdg13+1). A form counts as accepted when it
succeeds or fails after the parser (42704 undefined object, 58P01 missing directory, 42710
duplicate object, 42883 undefined function); 42601 is a syntax error.
"""

import pytest

from dblift.core.sql_model.base import SqlObjectType
from dblift.core.sql_parser.sqlglot_statement_facts import read_statement_facts
from dblift.core.sql_parser.statement_facts import NamedObject

T = SqlObjectType


def _pg(sql):
    return read_statement_facts(sql, dialect="postgres")  # lint: allow-dialect-string: test


@pytest.mark.parametrize(
    "sql,operation,named",
    [
        # Measured 2026-10-24 on PostgreSQL 16.14: CREATE EVENT TRIGGER (with or without WHEN TAG
        # IN), ALTER EVENT TRIGGER ... DISABLE and ... RENAME TO and DROP EVENT TRIGGER IF EXISTS
        # succeed.
        (
            "CREATE EVENT TRIGGER et ON ddl_command_end EXECUTE FUNCTION f()",
            "CREATE",
            NamedObject("et", T.EVENT_TRIGGER, "created"),
        ),
        (
            "CREATE EVENT TRIGGER et ON ddl_command_start WHEN TAG IN ('CREATE TABLE')"
            " EXECUTE FUNCTION f()",
            "CREATE",
            NamedObject("et", T.EVENT_TRIGGER, "created"),
        ),
        ("ALTER EVENT TRIGGER et DISABLE", "ALTER", NamedObject("et", T.EVENT_TRIGGER, "altered")),
        (
            "ALTER EVENT TRIGGER et RENAME TO et2",
            "ALTER",
            NamedObject("et", T.EVENT_TRIGGER, "altered"),
        ),
        (
            "DROP EVENT TRIGGER IF EXISTS et",
            "DROP",
            NamedObject("et", T.EVENT_TRIGGER, "dropped"),
        ),
        # Measured 2026-10-24 on PostgreSQL 16.14: CREATE FOREIGN DATA WRAPPER succeeds, and with
        # HANDLER h fails with 42883 (no function h); ALTER FOREIGN DATA WRAPPER ... OPTIONS and
        # DROP FOREIGN DATA WRAPPER IF EXISTS succeed.
        (
            "CREATE FOREIGN DATA WRAPPER fdw HANDLER h",
            "CREATE",
            NamedObject("fdw", T.FOREIGN_DATA_WRAPPER, "created"),
        ),
        (
            "ALTER FOREIGN DATA WRAPPER fdw OPTIONS (ADD a 'b')",
            "ALTER",
            NamedObject("fdw", T.FOREIGN_DATA_WRAPPER, "altered"),
        ),
        (
            "DROP FOREIGN DATA WRAPPER IF EXISTS fdw",
            "DROP",
            NamedObject("fdw", T.FOREIGN_DATA_WRAPPER, "dropped"),
        ),
        # Measured 2026-10-24 on PostgreSQL 16.14: CREATE SERVER, CREATE SERVER IF NOT EXISTS,
        # ALTER SERVER ... OPTIONS and DROP SERVER IF EXISTS succeed.
        (
            "CREATE SERVER srv FOREIGN DATA WRAPPER fdw",
            "CREATE",
            NamedObject("srv", T.FOREIGN_SERVER, "created"),
        ),
        (
            "CREATE SERVER IF NOT EXISTS srv FOREIGN DATA WRAPPER fdw",
            "CREATE",
            NamedObject("srv", T.FOREIGN_SERVER, "created"),
        ),
        (
            "ALTER SERVER srv OPTIONS (ADD host 'x')",
            "ALTER",
            NamedObject("srv", T.FOREIGN_SERVER, "altered"),
        ),
        ("DROP SERVER IF EXISTS srv", "DROP", NamedObject("srv", T.FOREIGN_SERVER, "dropped")),
        # Measured 2026-10-24 on PostgreSQL 16.14: CREATE PUBLICATION, ALTER PUBLICATION ... DROP
        # TABLE and DROP PUBLICATION IF EXISTS succeed; ALTER PUBLICATION ... ADD TABLE fails with
        # 42710 (the table is already a member), after the parser.
        (
            "CREATE PUBLICATION pub FOR TABLE t",
            "CREATE",
            NamedObject("pub", T.PUBLICATION, "created"),
        ),
        (
            "ALTER PUBLICATION pub ADD TABLE t",
            "ALTER",
            NamedObject("pub", T.PUBLICATION, "altered"),
        ),
        ("DROP PUBLICATION pub", "DROP", NamedObject("pub", T.PUBLICATION, "dropped")),
        # Measured 2026-10-24 on PostgreSQL 16.14: CREATE OPERATOR CLASS and ALTER OPERATOR CLASS
        # ... USING btree RENAME TO succeed, with or without a schema; DROP OPERATOR CLASS needs
        # USING (without it: 42601) and a missing class fails with 42704.
        (
            "CREATE OPERATOR CLASS oc FOR TYPE int USING btree AS OPERATOR 1 =",
            "CREATE",
            NamedObject("oc", T.OPERATOR_CLASS, "created"),
        ),
        (
            "CREATE OPERATOR CLASS s.oc FOR TYPE int USING btree AS OPERATOR 1 =",
            "CREATE",
            NamedObject("oc", T.OPERATOR_CLASS, "created", "s"),
        ),
        (
            "ALTER OPERATOR CLASS s.oc USING btree RENAME TO oc2",
            "ALTER",
            NamedObject("oc", T.OPERATOR_CLASS, "altered", "s"),
        ),
        (
            "DROP OPERATOR CLASS IF EXISTS s.oc USING btree",
            "DROP",
            NamedObject("oc", T.OPERATOR_CLASS, "dropped", "s"),
        ),
        # Measured 2026-10-24 on PostgreSQL 16.14: the four text search kinds are schema
        # qualifiable; CREATE and ALTER DICTIONARY and CONFIGURATION succeed, CREATE PARSER and
        # TEMPLATE fail with 42883 (the support function does not exist), ALTER PARSER and
        # TEMPLATE with 42704, and DROP ... IF EXISTS succeeds, all after the parser.
        (
            "CREATE TEXT SEARCH DICTIONARY d (TEMPLATE = simple)",
            "CREATE",
            NamedObject("d", T.TEXT_SEARCH_DICTIONARY, "created"),
        ),
        (
            "ALTER TEXT SEARCH DICTIONARY s.d (stopwords = 'english')",
            "ALTER",
            NamedObject("d", T.TEXT_SEARCH_DICTIONARY, "altered", "s"),
        ),
        (
            "DROP TEXT SEARCH DICTIONARY IF EXISTS d",
            "DROP",
            NamedObject("d", T.TEXT_SEARCH_DICTIONARY, "dropped"),
        ),
        (
            "CREATE TEXT SEARCH CONFIGURATION c (COPY = simple)",
            "CREATE",
            NamedObject("c", T.TEXT_SEARCH_CONFIGURATION, "created"),
        ),
        (
            "ALTER TEXT SEARCH CONFIGURATION s.c RENAME TO c2",
            "ALTER",
            NamedObject("c", T.TEXT_SEARCH_CONFIGURATION, "altered", "s"),
        ),
        (
            "DROP TEXT SEARCH CONFIGURATION IF EXISTS s.c",
            "DROP",
            NamedObject("c", T.TEXT_SEARCH_CONFIGURATION, "dropped", "s"),
        ),
        (
            "CREATE TEXT SEARCH PARSER p (START = a, GETTOKEN = b, END = c, LEXTYPES = d)",
            "CREATE",
            NamedObject("p", T.TEXT_SEARCH_PARSER, "created"),
        ),
        (
            "ALTER TEXT SEARCH PARSER s.p RENAME TO p2",
            "ALTER",
            NamedObject("p", T.TEXT_SEARCH_PARSER, "altered", "s"),
        ),
        (
            "DROP TEXT SEARCH PARSER IF EXISTS p",
            "DROP",
            NamedObject("p", T.TEXT_SEARCH_PARSER, "dropped"),
        ),
        (
            "CREATE TEXT SEARCH TEMPLATE tm (LEXIZE = x)",
            "CREATE",
            NamedObject("tm", T.TEXT_SEARCH_TEMPLATE, "created"),
        ),
        (
            "ALTER TEXT SEARCH TEMPLATE s.tm RENAME TO tm2",
            "ALTER",
            NamedObject("tm", T.TEXT_SEARCH_TEMPLATE, "altered", "s"),
        ),
        (
            "DROP TEXT SEARCH TEMPLATE IF EXISTS s.tm",
            "DROP",
            NamedObject("tm", T.TEXT_SEARCH_TEMPLATE, "dropped", "s"),
        ),
        # Measured 2026-10-24 on PostgreSQL 16.14: CREATE TABLESPACE, quoted or not, fails with
        # 58P01 (the directory does not exist), ALTER TABLESPACE and DROP TABLESPACE with 42704,
        # and DROP TABLESPACE IF EXISTS succeeds, all after the parser.
        (
            "CREATE TABLESPACE ts LOCATION '/nonexistent/f669'",
            "CREATE",
            NamedObject("ts", T.TABLESPACE, "created"),
        ),
        (
            "ALTER TABLESPACE ts SET (seq_page_cost = 1)",
            "ALTER",
            NamedObject("ts", T.TABLESPACE, "altered"),
        ),
        ("ALTER TABLESPACE ts RENAME TO ts2", "ALTER", NamedObject("ts", T.TABLESPACE, "altered")),
        ("DROP TABLESPACE ts", "DROP", NamedObject("ts", T.TABLESPACE, "dropped")),
        ("DROP TABLESPACE IF EXISTS ts", "DROP", NamedObject("ts", T.TABLESPACE, "dropped")),
        (
            "CREATE TABLESPACE \"Ts\" LOCATION '/x'",
            "CREATE",
            NamedObject("Ts", T.TABLESPACE, "created"),
        ),
    ],
)
def test_a_command_kind_is_named_from_its_head(sql, operation, named):
    facts = _pg(sql)

    assert (facts.operation, facts.kind, facts.objects) == (operation, "DDL", (named,))
    assert facts.opaque
    assert facts.diagnostic.startswith(named.type.value.lower().replace("_", " ") + ": ")
    assert facts.error is None


@pytest.mark.parametrize(
    "sql",
    [
        "CREATE EVENT TRIGGER s.et ON ddl_command_end EXECUTE FUNCTION f()",
        "DROP EVENT TRIGGER s.et",
        "CREATE FOREIGN DATA WRAPPER s.fdw",
        "ALTER FOREIGN DATA WRAPPER s.fdw OPTIONS (ADD a 'b')",
        "DROP FOREIGN DATA WRAPPER s.fdw",
        "CREATE SERVER s.srv FOREIGN DATA WRAPPER fdw",
        "ALTER SERVER s.srv OPTIONS (ADD host 'x')",
        "DROP SERVER s.srv",
        "CREATE PUBLICATION s.pub FOR TABLE t",
        "ALTER PUBLICATION s.pub SET (publish = 'insert')",
        "DROP PUBLICATION s.pub",
        "CREATE TABLESPACE s.ts LOCATION '/x'",
        "ALTER TABLESPACE s.ts SET (seq_page_cost = 1)",
        "DROP TABLESPACE IF EXISTS s.ts",
    ],
)
def test_a_kind_without_a_schema_never_reads_a_dotted_name_as_schema_dot_name(sql):
    """Measured 2026-10-24 on PostgreSQL 16.14: every one of these fails with SQLSTATE 42601
    (syntax error at or near "."), because event triggers, foreign data wrappers, servers,
    publications and tablespaces belong to the database, not to a schema."""
    facts = _pg(sql)

    assert (facts.kind, facts.objects) == ("DDL", ())
    assert facts.opaque
    assert facts.error is None


def test_create_tablespace_is_not_the_tablespace_clause_of_a_table():
    facts = _pg("CREATE TABLESPACE ts LOCATION '/x'")

    assert "TABLESPACE clause" not in facts.diagnostic


def test_a_table_named_tablespace_still_carries_its_clause():
    facts = _pg("CREATE TABLE tablespace (a int) TABLESPACE ts")

    assert facts.objects == (NamedObject("tablespace", T.TABLE, "created"),)
    assert facts.diagnostic.endswith("postgres TABLESPACE clause is not modelled by the grammar")


@pytest.mark.parametrize("dialect", ["mysql", "oracle", "tsql"])
@pytest.mark.parametrize(
    "sql",
    [
        "CREATE TABLESPACE ts ADD DATAFILE 'x'",
        "CREATE SERVER srv FOREIGN DATA WRAPPER fdw",
        "CREATE PUBLICATION pub",
    ],
)
def test_the_kinds_stay_unnamed_on_other_dialects(sql, dialect):
    assert read_statement_facts(sql, dialect=dialect).objects == ()
