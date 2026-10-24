"""Db2 statement facts: storage, type, module and synonym heads (issue #661).

Every accepted form below was run on Db2 12.1.5.0 (community edition, UTF-8 database), measured
2026-10-24. A form is accepted when it succeeds or fails after the parse (SQL0204N object missing,
SQL0601N object exists, SQL20026N wrong kind of type); SQL0104N is a syntax error. SQL0108N ("wrong
number of qualifiers") is raised after the name is read, so a qualified name for a one-part object
is a name the reader refuses.
"""

import pytest

from dblift.db.plugins.db2.parser.statement_facts import (
    NAME_NOT_READ,
    NOT_CLASSIFIED,
    Db2StatementFactsReader,
)

READ = Db2StatementFactsReader(None).read


def _objects(sql):
    return [(o.name, o.type.value, o.role, o.schema) for o in READ(sql).objects]


@pytest.mark.parametrize(
    ("sql", "objects"),
    [
        # Measured: CREATE TABLESPACE ts MANAGED BY AUTOMATIC STORAGE USING STOGROUP sg: success;
        # the quoted form "f661Tsq" succeeds and keeps its case.
        (
            "CREATE TABLESPACE f661ts MANAGED BY AUTOMATIC STORAGE USING STOGROUP f661sg",
            [("F661TS", "TABLESPACE", "created", None)],
        ),
        (
            'CREATE TABLESPACE "f661Tsq" MANAGED BY AUTOMATIC STORAGE',
            [("f661Tsq", "TABLESPACE", "created", None)],
        ),
        # Measured: LARGE, REGULAR, TEMPORARY, SYSTEM TEMPORARY and USER TEMPORARY before the
        # word TABLESPACE all succeed.
        (
            "CREATE LARGE TABLESPACE f661tsl MANAGED BY AUTOMATIC STORAGE",
            [("F661TSL", "TABLESPACE", "created", None)],
        ),
        (
            "CREATE REGULAR TABLESPACE f661tsr MANAGED BY AUTOMATIC STORAGE",
            [("F661TSR", "TABLESPACE", "created", None)],
        ),
        (
            "CREATE TEMPORARY TABLESPACE f661tst MANAGED BY AUTOMATIC STORAGE",
            [("F661TST", "TABLESPACE", "created", None)],
        ),
        (
            "CREATE SYSTEM TEMPORARY TABLESPACE f661tss MANAGED BY AUTOMATIC STORAGE",
            [("F661TSS", "TABLESPACE", "created", None)],
        ),
        (
            "CREATE USER TEMPORARY TABLESPACE f661tsu MANAGED BY AUTOMATIC STORAGE",
            [("F661TSU", "TABLESPACE", "created", None)],
        ),
        # Measured: ALTER TABLESPACE ts PREFETCHSIZE 32 and ... REDUCE MAX: success.
        ("ALTER TABLESPACE f661ts PREFETCHSIZE 32", [("F661TS", "TABLESPACE", "altered", None)]),
        ("ALTER TABLESPACE f661ts REDUCE MAX", [("F661TS", "TABLESPACE", "altered", None)]),
        # Measured: DROP TABLESPACE ts: success; a missing one: SQL0204N.
        ("DROP TABLESPACE f661ts", [("F661TS", "TABLESPACE", "dropped", None)]),
        ('DROP TABLESPACE "f661Tsq"', [("f661Tsq", "TABLESPACE", "dropped", None)]),
        # Measured: CREATE STOGROUP sg ON '/tmp/f661sg': success; ALTER STOGROUP sg ADD '/path'
        # and ... OVERHEAD 6.725: success; DROP STOGROUP sg: success.
        (
            "CREATE STOGROUP f661sg ON '/tmp/f661sg'",
            [("F661SG", "STORAGE_GROUP", "created", None)],
        ),
        (
            "ALTER STOGROUP f661sg ADD '/tmp/f661sg2'",
            [("F661SG", "STORAGE_GROUP", "altered", None)],
        ),
        ("ALTER STOGROUP f661sg OVERHEAD 6.725", [("F661SG", "STORAGE_GROUP", "altered", None)]),
        ('DROP STOGROUP "f661SGq"', [("f661SGq", "STORAGE_GROUP", "dropped", None)]),
        ("DROP STOGROUP f661sg", [("F661SG", "STORAGE_GROUP", "dropped", None)]),
        # Measured: CREATE BUFFERPOOL bp SIZE 1000 PAGESIZE 8K: success; IMMEDIATE accepted;
        # ALTER BUFFERPOOL bp SIZE 2000: success; DROP BUFFERPOOL bp: success.
        (
            "CREATE BUFFERPOOL f661bp SIZE 1000 PAGESIZE 8K",
            [("F661BP", "BUFFERPOOL", "created", None)],
        ),
        (
            'CREATE BUFFERPOOL "f661BPq" IMMEDIATE SIZE 1000 PAGESIZE 16K',
            [("f661BPq", "BUFFERPOOL", "created", None)],
        ),
        ("ALTER BUFFERPOOL f661bp SIZE 2000", [("F661BP", "BUFFERPOOL", "altered", None)]),
        ("DROP BUFFERPOOL f661bp", [("F661BP", "BUFFERPOOL", "dropped", None)]),
        # Measured: CREATE TYPE s.t AS INTEGER WITH COMPARISONS: success; AS ROW (...), AS INTEGER
        # ARRAY[10] and the structured AS (a INT) MODE DB2SQL: success; CREATE OR REPLACE TYPE:
        # success (twice); CREATE DISTINCT TYPE: success.
        (
            "CREATE TYPE f661.dt AS INTEGER WITH COMPARISONS",
            [("DT", "TYPE", "created", "F661")],
        ),
        (
            "CREATE TYPE f661dt2 AS VARCHAR(10) WITH COMPARISONS",
            [("F661DT2", "TYPE", "created", None)],
        ),
        (
            "CREATE OR REPLACE TYPE f661.rt AS ROW (a INT, b VARCHAR(10))",
            [("RT", "TYPE", "created", "F661")],
        ),
        ("CREATE TYPE f661.at AS INTEGER ARRAY[10]", [("AT", "TYPE", "created", "F661")]),
        ("CREATE TYPE f661.st AS (a INT) MODE DB2SQL", [("ST", "TYPE", "created", "F661")]),
        (
            "CREATE DISTINCT TYPE f661.dt4 AS INTEGER WITH COMPARISONS",
            [("DT4", "TYPE", "created", "F661")],
        ),
        # Measured: ALTER TYPE s.st ADD ATTRIBUTE b INT: success; on a distinct type: SQL20026N
        # (a post-parse refusal); on a missing type: SQL0204N.
        ("ALTER TYPE f661.st ADD ATTRIBUTE b INT", [("ST", "TYPE", "altered", "F661")]),
        ("ALTER TYPE f661.dt ADD ATTRIBUTE b INT", [("DT", "TYPE", "altered", "F661")]),
        # Measured: DROP TYPE s.t: success; ... RESTRICT: success; DROP DISTINCT TYPE and
        # DROP DATA TYPE: success.
        ("DROP TYPE f661.rt", [("RT", "TYPE", "dropped", "F661")]),
        ("DROP TYPE f661.st RESTRICT", [("ST", "TYPE", "dropped", "F661")]),
        ("DROP DISTINCT TYPE f661.dt4", [("DT4", "TYPE", "dropped", "F661")]),
        ("DROP DATA TYPE f661.dt", [("DT", "TYPE", "dropped", "F661")]),
        ('DROP TYPE "f661Q"', [("f661Q", "TYPE", "dropped", None)]),
        # Measured: CREATE MODULE m: success; CREATE OR REPLACE MODULE s.m: success;
        # ALTER MODULE m ADD VARIABLE v INT, ... PUBLISH FUNCTION f (a INT) RETURNS INT,
        # ... DROP VARIABLE v, and ... ADD FUNCTION f (a INT) RETURNS INT BEGIN RETURN a + 1; END:
        # success; DROP MODULE m: success.
        ("CREATE MODULE f661mod", [("F661MOD", "MODULE", "created", None)]),
        ("CREATE OR REPLACE MODULE f661.mod2", [("MOD2", "MODULE", "created", "F661")]),
        ("ALTER MODULE f661mod ADD VARIABLE v INT", [("F661MOD", "MODULE", "altered", None)]),
        (
            "ALTER MODULE f661mod PUBLISH FUNCTION f661fn (a INT) RETURNS INT",
            [("F661MOD", "MODULE", "altered", None)],
        ),
        (
            "ALTER MODULE f661mb ADD FUNCTION f661fn (a INT) RETURNS INT BEGIN RETURN a + 1; END",
            [("F661MB", "MODULE", "altered", None)],
        ),
        ("DROP MODULE f661.mod2", [("MOD2", "MODULE", "dropped", "F661")]),
        # Measured: CREATE SYNONYM s FOR t: success, and SYSCAT.TABLES holds the object with TYPE
        # 'A', the type of an alias; CREATE OR REPLACE SYNONYM: success; DROP SYNONYM s: success.
        # The reader types it as it types ALIAS: a SYNONYM.
        (
            "CREATE SYNONYM f661syn FOR f661.tab",
            [("F661SYN", "SYNONYM", "created", None)],
        ),
        (
            "CREATE OR REPLACE SYNONYM f661.syn FOR f661.tab",
            [("SYN", "SYNONYM", "created", "F661")],
        ),
        ("DROP SYNONYM f661syn", [("F661SYN", "SYNONYM", "dropped", None)]),
    ],
)
def test_storage_type_module_and_synonym_heads_name_their_object(sql, objects):
    facts = READ(sql)
    assert (facts.operation, facts.kind) == (sql.split()[0], "DDL")
    assert _objects(sql) == objects
    assert not facts.opaque
    assert facts.error is None


@pytest.mark.parametrize(
    "sql",
    [
        # Measured: a qualified name for a tablespace, stogroup or bufferpool is read and then
        # refused, SQL0108N (wrong number of qualifiers); a type or module name has up to two
        # parts, and CREATE TYPE a.b.c / CREATE MODULE a.b.c are refused the same way or
        # with SQL0204N.
        "CREATE STOGROUP f661.sgtwo ON '/tmp/f661sg4'",
        "CREATE TABLESPACE f661.tstwo MANAGED BY AUTOMATIC STORAGE",
        "ALTER TABLESPACE f661.tstwo PREFETCHSIZE 32",
        "CREATE BUFFERPOOL f661.bptwo SIZE 1000 PAGESIZE 8K",
        "ALTER BUFFERPOOL f661.bptwo SIZE 2000",
        "DROP BUFFERPOOL f661.bptwo",
        "DROP TABLESPACE f661.tstwo",
        "DROP STOGROUP f661.sgtwo",
        "CREATE TYPE a.b.c AS INTEGER WITH COMPARISONS",
        "DROP TYPE a.b.c",
        "CREATE MODULE a.b.c",
    ],
)
def test_a_name_with_too_many_parts_is_not_read(sql):
    facts = READ(sql)
    assert facts.objects == () and facts.opaque
    assert facts.diagnostic.startswith("db2 ") and facts.diagnostic.endswith(": name not read")


@pytest.mark.parametrize(
    "sql",
    [
        # Measured: DROP TABLESPACE, BUFFERPOOL, STOGROUP, TYPE, MODULE and SYNONYM with
        # IF EXISTS are all SQL0104N ("EXISTS" is the unexpected token), and so are
        # CREATE TYPE IF NOT EXISTS and CREATE MODULE IF NOT EXISTS: no object is named.
        "DROP TABLESPACE IF EXISTS f661nots",
        "DROP BUFFERPOOL IF EXISTS f661nobp",
        "DROP STOGROUP IF EXISTS f661nosg",
        "DROP TYPE IF EXISTS f661.nope",
        "DROP MODULE IF EXISTS f661.nope",
        "DROP SYNONYM IF EXISTS f661nosyn",
        "CREATE TYPE IF NOT EXISTS f661.dt3 AS INTEGER WITH COMPARISONS",
        "CREATE MODULE IF NOT EXISTS f661.mod3",
        # Measured: DROP TABLESPACE a, b succeeds and drops both; two names are not one object.
        "DROP TABLESPACE f661tsl, f661tsr",
    ],
)
def test_a_form_the_engine_rejects_or_that_names_several_objects_names_none(sql):
    facts = READ(sql)
    assert facts.objects == () and facts.opaque
    assert facts.diagnostic.endswith(": name not read")


@pytest.mark.parametrize(
    ("sql", "operation"),
    [
        # Measured: DROP TABLESPACES a, b succeeds (the plural keyword); not a head of the table.
        ("DROP TABLESPACES f661tsu, f661tss", "DROP"),
        # Measured: CREATE LOB TABLESPACE is SQL0104N (a z/OS form).
        ("CREATE LOB TABLESPACE f661tslob MANAGED BY SYSTEM", "CREATE"),
        # Measured: CREATE PUBLIC SYNONYM and DROP PUBLIC SYNONYM succeed, and the object is
        # created in SYSPUBLIC: a one-part name would carry the wrong schema, so it stays opaque,
        # as CREATE PUBLIC ALIAS does.
        ("CREATE PUBLIC SYNONYM f661psyn FOR f661.tab", "CREATE"),
        ("DROP PUBLIC SYNONYM f661psyn", "DROP"),
        # Measured: CREATE TYPE MAPPING and DROP TYPE MAPPING are federated statements (SQL20076N
        # here: the instance is not enabled for federation), not types.
        ("CREATE TYPE MAPPING f661tm FROM SYSIBM.INTEGER TO SERVER f661srv TYPE integer", "CREATE"),
        ("DROP TYPE MAPPING f661tm", "DROP"),
        # Measured: DROP TYPE BODY is SQL0104N.
        ("DROP TYPE BODY f661.nope", "DROP"),
    ],
)
def test_forms_outside_the_heads_stay_opaque(sql, operation):
    facts = READ(sql)
    assert (facts.operation, facts.kind, facts.objects) == (operation, "DDL", ())
    assert facts.opaque


@pytest.mark.parametrize(
    "sql",
    [
        # Measured: through the driver (ibm_db) and in the CLP, EXECUTE IMMEDIATE outside a
        # compound statement or routine body is SQL0104N; inside BEGIN ... END it runs and the
        # statement it executes (CREATE TABLE f661eit) takes effect. The object is inside a string
        # or a variable, so the reader does not name it (owner decision, db2.md section 13).
        "EXECUTE IMMEDIATE 'DROP TABLE temp'",
        "EXECUTE IMMEDIATE stmt",
    ],
)
def test_execute_immediate_stays_opaque(sql):
    facts = READ(sql)
    assert (facts.operation, facts.kind, facts.objects) == ("EXECUTE", "UNKNOWN", ())
    assert facts.opaque
    assert facts.diagnostic == NOT_CLASSIFIED.format(word="EXECUTE")


@pytest.mark.parametrize("sql", ["DROP DATABASE f661db", "DROP DB f661db"])
def test_drop_database_names_no_object(sql):
    """Measured: in the CLP, DROP DATABASE db and DROP DB db run as commands (DB20000I; a missing
    alias: SQL1013N). Sent as SQL through the driver, both are SQL0104N ("DATABASE" and "DB" are
    unexpected following DROP), so there is no database object to name. The lexical
    specification keeps them out of the refused client commands (db2.md section 6), and the
    reader leaves them unclassified."""
    facts = READ(sql)
    assert (facts.operation, facts.kind, facts.objects) == ("DROP", "DDL", ())
    assert facts.diagnostic == NOT_CLASSIFIED.format(word="DROP")


def test_a_tablespace_named_like_a_kind_word_is_read_as_the_name():
    """``LARGE`` is no reserved word: the name after TABLESPACE is not taken for a kind word."""
    assert _objects("CREATE TABLESPACE large MANAGED BY AUTOMATIC STORAGE") == [
        ("LARGE", "TABLESPACE", "created", None)
    ]


def test_an_unreadable_storage_name_leaves_the_statement_opaque():
    facts = READ("CREATE BUFFERPOOL")
    assert facts.objects == ()
    assert facts.diagnostic == NAME_NOT_READ.format(operation="CREATE", type="BUFFERPOOL")
