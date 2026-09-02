"""Object recognition in ``SqlAnalyzer.extract_objects``.

``_extract_objects_regex`` historically recognised four statement shapes —
``CREATE TABLE``, ``ALTER TABLE``, ``CREATE [OR REPLACE] VIEW`` and
``CREATE [UNIQUE] INDEX`` — plus a generic ``DROP <word>`` branch. Every other
statement returned no objects at all, so callers saw an empty
``object_type``/``object_name`` for a sequence, a trigger, a routine, a
synonym, a type, a grant, a comment, or any DML.

That gap is not cosmetic for the callers: ``migration_journal`` groups its
per-object execution stats by ``object_type`` (so those statements were absent
from the report entirely), ``_reversers`` decides how to reverse a statement
from it, and ``sql_execution_service`` records the objects a statement touched.

Two invariants this module pins:

* **One vocabulary.** ``object_type`` is a ``SqlObjectType`` member name, so a
  caller can map the string back to the enum rather than matching a spelling
  that varies per branch. Before this, the four original branches returned
  title case ("Table") while the ``DROP`` branch returned whatever word
  followed the verb.
* **Multi-word object types are one type.** ``DROP MATERIALIZED VIEW mv``
  previously reported ``object_type="MATERIALIZED"`` with
  ``object_name="default_schema.VIEW"`` — the type truncated at the first
  word and the *name* silently replaced by the second half of the type, so
  the object being dropped never appeared at all.
"""

import unittest

from dblift.core.migration.sql.sql_analyzer import SqlAnalyzer
from dblift.core.sql_model._base_sql_object import SqlObjectType


def _only(analyzer: SqlAnalyzer, sql: str) -> dict:
    """Return the single object ``sql`` affects, failing if there is not one."""
    objects = analyzer.extract_objects(sql)
    assert len(objects) == 1, f"expected exactly one object for {sql!r}, got {objects!r}"
    return objects[0]


class TestObjectTypeVocabulary(unittest.TestCase):
    """Every reported ``object_type`` is a ``SqlObjectType`` member name."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_every_recognised_statement_reports_a_known_object_type(self):
        known = {member.name for member in SqlObjectType}
        statements = [
            "CREATE TABLE users (id INT)",
            "ALTER TABLE users ADD COLUMN email VARCHAR(255)",
            "CREATE VIEW v AS SELECT 1",
            "CREATE INDEX idx ON users (email)",
            "CREATE SEQUENCE users_seq START WITH 1",
            "DROP TABLE users",
            "DROP INDEX idx",
        ]
        for sql in statements:
            with self.subTest(sql=sql):
                self.assertIn(_only(self.analyzer, sql)["object_type"], known)

    def test_original_four_branches_report_enum_names_not_title_case(self):
        # The pre-existing spellings were "Table"/"View"/"Index"; the DROP
        # branch returned the raw keyword. Both now resolve to one vocabulary.
        cases = {
            "CREATE TABLE users (id INT)": "TABLE",
            "ALTER TABLE users ADD COLUMN c INT": "TABLE",
            "CREATE VIEW v AS SELECT 1": "VIEW",
            "CREATE INDEX idx ON users (email)": "INDEX",
            "DROP TABLE users": "TABLE",
        }
        for sql, expected in cases.items():
            with self.subTest(sql=sql):
                self.assertEqual(_only(self.analyzer, sql)["object_type"], expected)


class TestCreateObjectRecognition(unittest.TestCase):
    """``CREATE`` of the object types the four original branches missed."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_create_sequence(self):
        obj = _only(self.analyzer, "CREATE SEQUENCE users_seq START WITH 1 INCREMENT BY 1")
        self.assertEqual(obj["object_type"], "SEQUENCE")
        self.assertIn("users_seq", obj["object_name"])

    def test_create_trigger(self):
        sql = "CREATE TRIGGER users_bi BEFORE INSERT ON users FOR EACH ROW EXECUTE FUNCTION f()"
        obj = _only(self.analyzer, sql)
        self.assertEqual(obj["object_type"], "TRIGGER")
        self.assertIn("users_bi", obj["object_name"])

    def test_create_or_replace_trigger(self):
        sql = "CREATE OR REPLACE TRIGGER orders_bi BEFORE INSERT ON orders FOR EACH ROW BEGIN NULL; END;"
        obj = _only(self.analyzer, sql)
        self.assertEqual(obj["object_type"], "TRIGGER")
        self.assertIn("orders_bi", obj["object_name"])

    def test_create_or_replace_function(self):
        sql = "CREATE OR REPLACE FUNCTION f() RETURNS int AS $$ BEGIN RETURN 1; END; $$ LANGUAGE plpgsql"
        obj = _only(self.analyzer, sql)
        self.assertEqual(obj["object_type"], "FUNCTION")
        self.assertIn("f", obj["object_name"])

    def test_create_procedure(self):
        obj = _only(self.analyzer, "CREATE PROCEDURE p() LANGUAGE SQL AS $$ SELECT 1 $$")
        self.assertEqual(obj["object_type"], "PROCEDURE")

    def test_create_materialized_view_is_not_a_plain_view(self):
        obj = _only(self.analyzer, "CREATE MATERIALIZED VIEW mv AS SELECT * FROM users")
        self.assertEqual(obj["object_type"], "MATERIALIZED_VIEW")
        self.assertIn("mv", obj["object_name"])

    def test_create_type(self):
        obj = _only(self.analyzer, "CREATE TYPE mood AS ENUM ('sad', 'ok')")
        self.assertEqual(obj["object_type"], "TYPE")

    def test_create_schema(self):
        obj = _only(self.analyzer, "CREATE SCHEMA app")
        self.assertEqual(obj["object_type"], "SCHEMA")

    def test_create_extension(self):
        obj = _only(self.analyzer, "CREATE EXTENSION IF NOT EXISTS pgcrypto")
        self.assertEqual(obj["object_type"], "EXTENSION")

    def test_create_synonym(self):
        analyzer = SqlAnalyzer(dialect="oracle")
        obj = _only(analyzer, "CREATE SYNONYM s FOR orders")
        self.assertEqual(obj["object_type"], "SYNONYM")

    def test_create_package(self):
        analyzer = SqlAnalyzer(dialect="oracle")
        obj = _only(analyzer, "CREATE OR REPLACE PACKAGE pkg AS PROCEDURE p; END pkg;")
        self.assertEqual(obj["object_type"], "PACKAGE")

    def test_if_not_exists_does_not_become_the_object_name(self):
        obj = _only(self.analyzer, "CREATE SEQUENCE IF NOT EXISTS s START WITH 1")
        self.assertEqual(obj["object_type"], "SEQUENCE")
        self.assertIn("s", obj["object_name"].rsplit(".", 1)[-1])
        self.assertNotIn("EXISTS", obj["object_name"].upper())


class TestMaterializedViewLogReportsTheTable(unittest.TestCase):
    """``MATERIALIZED VIEW LOG ON <table>`` names the table, not LOG.

    The generic CREATE/DROP shape takes the token after the matched type as
    the name. ``MATERIALIZED VIEW`` wins over ``VIEW``, so
    ``CREATE MATERIALIZED VIEW LOG ON orders`` was reported as a
    ``MATERIALIZED_VIEW`` named ``LOG`` and the table after ``ON`` never
    appeared. These four spellings are the golden parse: the two LOG forms,
    the plain ``mv AS SELECT`` control (asserted *differently* from the LOG
    cases), and ``DROP``.
    """

    def setUp(self):
        self.postgresql = SqlAnalyzer(dialect="postgresql")
        self.oracle = SqlAnalyzer(dialect="oracle")

    def _log_on_table(self, analyzer: SqlAnalyzer, sql: str, expected_name: str) -> None:
        obj = _only(analyzer, sql)
        self.assertEqual(obj["object_type"], SqlObjectType.MATERIALIZED_VIEW_LOG.name)
        self.assertEqual(obj["object_name"], expected_name)
        self.assertNotEqual(obj["object_name"].rsplit(".", 1)[-1].upper(), "LOG")

    def test_create_log_on_unqualified_table(self):
        sql = "CREATE MATERIALIZED VIEW LOG ON orders"
        for analyzer in (self.postgresql, self.oracle):
            with self.subTest(dialect=analyzer.dialect):
                self._log_on_table(analyzer, sql, "default_schema.orders")

    def test_create_log_on_schema_qualified_table(self):
        sql = "CREATE MATERIALIZED VIEW LOG ON hr.employees"
        for analyzer in (self.postgresql, self.oracle):
            with self.subTest(dialect=analyzer.dialect):
                self._log_on_table(analyzer, sql, "hr.employees")

    def test_plain_materialized_view_as_select_is_not_a_log(self):
        # Control: a real materialized view must stay a MATERIALIZED_VIEW
        # named after the view, not collapse to the same answer as LOG ON.
        sql = "CREATE MATERIALIZED VIEW mv AS SELECT 1 FROM orders"
        for analyzer in (self.postgresql, self.oracle):
            with self.subTest(dialect=analyzer.dialect):
                obj = _only(analyzer, sql)
                self.assertEqual(obj["object_type"], SqlObjectType.MATERIALIZED_VIEW.name)
                self.assertEqual(obj["object_name"], "default_schema.mv")
                self.assertNotEqual(obj["object_type"], SqlObjectType.MATERIALIZED_VIEW_LOG.name)
                self.assertNotEqual(obj["object_name"].rsplit(".", 1)[-1].upper(), "LOG")
                self.assertNotEqual(obj["object_name"].rsplit(".", 1)[-1].upper(), "ORDERS")

    def test_drop_log_on_table(self):
        sql = "DROP MATERIALIZED VIEW LOG ON t"
        for analyzer in (self.postgresql, self.oracle):
            with self.subTest(dialect=analyzer.dialect):
                self._log_on_table(analyzer, sql, "default_schema.t")

    def test_materialized_view_named_log_is_still_a_view(self):
        # LOG is a legal view name. Without ON, this is not a log statement
        # and must not be absorbed by the three-word type.
        sql = "CREATE MATERIALIZED VIEW LOG AS SELECT 1 FROM orders"
        for analyzer in (self.postgresql, self.oracle):
            with self.subTest(dialect=analyzer.dialect):
                obj = _only(analyzer, sql)
                self.assertEqual(obj["object_type"], SqlObjectType.MATERIALIZED_VIEW.name)
                self.assertEqual(obj["object_name"], "default_schema.LOG")


class TestAlterAndDropRecognition(unittest.TestCase):
    """``ALTER``/``DROP`` beyond the table-and-index shapes."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_alter_sequence(self):
        obj = _only(self.analyzer, "ALTER SEQUENCE users_seq RESTART WITH 100")
        self.assertEqual(obj["object_type"], "SEQUENCE")
        self.assertIn("users_seq", obj["object_name"])

    def test_alter_index(self):
        obj = _only(self.analyzer, "ALTER INDEX idx RENAME TO idx2")
        self.assertEqual(obj["object_type"], "INDEX")

    def test_alter_view(self):
        obj = _only(self.analyzer, "ALTER VIEW v RENAME TO v2")
        self.assertEqual(obj["object_type"], "VIEW")

    def test_drop_materialized_view_keeps_type_and_name_together(self):
        # Regression: this reported object_type="MATERIALIZED" and
        # object_name="default_schema.VIEW" -- the dropped object never
        # appeared, and the type named a keyword that is not an object type.
        obj = _only(self.analyzer, "DROP MATERIALIZED VIEW mv")
        self.assertEqual(obj["object_type"], "MATERIALIZED_VIEW")
        self.assertIn("mv", obj["object_name"])

    def test_drop_sequence(self):
        obj = _only(self.analyzer, "DROP SEQUENCE users_seq")
        self.assertEqual(obj["object_type"], "SEQUENCE")

    def test_drop_trigger(self):
        obj = _only(self.analyzer, "DROP TRIGGER users_bi ON users")
        self.assertEqual(obj["object_type"], "TRIGGER")
        self.assertIn("users_bi", obj["object_name"])

    def test_drop_if_exists_does_not_become_the_object_name(self):
        obj = _only(self.analyzer, "DROP TABLE IF EXISTS users")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])


class TestIndexModifiers(unittest.TestCase):
    """Index builds carrying a modifier between the keyword and the name.

    ``CONCURRENTLY`` is routine in PostgreSQL migrations -- it is the
    non-blocking form this tool's own advice recommends -- and an index build
    that reports no object at all is invisible to every caller that reads
    these results.
    """

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_create_index_concurrently(self):
        obj = _only(self.analyzer, "CREATE INDEX CONCURRENTLY idx ON orders (email)")
        self.assertEqual(obj["object_type"], "INDEX")
        self.assertIn("idx", obj["object_name"])
        self.assertIn("orders", obj["on_object"])

    def test_create_unique_index_concurrently(self):
        obj = _only(self.analyzer, "CREATE UNIQUE INDEX CONCURRENTLY idx ON orders (email)")
        self.assertEqual(obj["object_type"], "INDEX")
        self.assertIn("idx", obj["object_name"])

    def test_create_index_concurrently_if_not_exists(self):
        obj = _only(self.analyzer, "CREATE INDEX CONCURRENTLY IF NOT EXISTS idx ON orders (email)")
        self.assertEqual(obj["object_type"], "INDEX")
        self.assertIn("idx", obj["object_name"])
        self.assertNotIn("EXISTS", obj["object_name"].upper())


class TestIndexTypeModifiers(unittest.TestCase):
    """An index build is an INDEX whatever index *type* it declares.

    ``BITMAP`` (Oracle), ``FULLTEXT``/``SPATIAL`` (MySQL) and
    ``CLUSTERED COLUMNSTORE`` (SQL Server) are index-type keywords, not a
    different kind of object. Reporting them as UNKNOWN loses the one fact
    every downstream consumer needs about an index build -- including which
    table it scans, which is the whole cost of the operation.
    """

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_bitmap_index(self):
        obj = _only(self.analyzer, "CREATE BITMAP INDEX bx ON orders (status)")
        self.assertEqual(obj["object_type"], "INDEX")
        self.assertIn("bx", obj["object_name"])
        self.assertIn("orders", obj["on_object"])

    def test_fulltext_index(self):
        obj = _only(self.analyzer, "CREATE FULLTEXT INDEX ftx ON orders (note)")
        self.assertEqual(obj["object_type"], "INDEX")
        self.assertIn("orders", obj["on_object"])

    def test_clustered_index_reports_its_table(self):
        # Pre-existing gap: the index branch's guard admitted only
        # CREATE INDEX / CREATE UNIQUE INDEX, so this got a type but no
        # on_object -- an index build whose target table was never recorded.
        obj = _only(self.analyzer, "CREATE CLUSTERED INDEX cx ON orders (id)")
        self.assertEqual(obj["object_type"], "INDEX")
        self.assertIn("orders", obj["on_object"])


class TestPublicModifier(unittest.TestCase):
    """``PUBLIC`` is an ordinary Oracle modifier, not part of the name."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="oracle")

    def test_create_public_synonym(self):
        obj = _only(self.analyzer, "CREATE PUBLIC SYNONYM s FOR app.orders")
        self.assertEqual(obj["object_type"], "SYNONYM")
        self.assertIn("s", obj["object_name"].rsplit(".", 1)[-1])

    def test_drop_public_synonym(self):
        obj = _only(self.analyzer, "DROP PUBLIC SYNONYM s")
        self.assertEqual(obj["object_type"], "SYNONYM")

    def test_create_public_database_link(self):
        obj = _only(self.analyzer, "CREATE PUBLIC DATABASE LINK dl CONNECT TO u IDENTIFIED BY p")
        self.assertEqual(obj["object_type"], "DATABASE_LINK")
        self.assertIn("dl", obj["object_name"].rsplit(".", 1)[-1])


class TestUnmodelledObjectKeywords(unittest.TestCase):
    """A keyword outside the enum still reports the object, typed UNKNOWN.

    Before object recognition was extended, ``DROP TABLESPACE ts`` reported
    ``object_type="TABLESPACE"`` -- the raw keyword. Reporting nothing at all
    instead would be a straight loss of coverage for the callers that consume
    these results, so an unrecognised keyword degrades to ``UNKNOWN`` (a real
    ``SqlObjectType`` member, which keeps the one-vocabulary invariant) while
    the object *name* is still reported.
    """

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_drop_tablespace_still_names_the_object(self):
        obj = _only(self.analyzer, "DROP TABLESPACE ts")
        self.assertEqual(obj["object_type"], "UNKNOWN")
        self.assertIn("ts", obj["object_name"])

    def test_drop_publication_still_names_the_object(self):
        obj = _only(self.analyzer, "DROP PUBLICATION pub")
        self.assertEqual(obj["object_type"], "UNKNOWN")
        self.assertIn("pub", obj["object_name"])


class TestMultiWordAndUnmodelledTypesNameTheRightObject(unittest.TestCase):
    """A keyword must never end up in the object *name* slot.

    Reporting ``UNKNOWN`` for a type nobody models is honest. Reporting a
    keyword as the object's name is not: it is a confidently wrong answer, and
    it is what the callers display and key their lookups on. These are the
    shapes where a modifier-skipping parse can put the wrong token in that slot
    -- either by taking one word of a multi-word type as the type and the next
    as the name, or by skipping past the real subject to a modelled keyword
    appearing later in the statement.
    """

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_multi_word_unmodelled_type_does_not_name_a_keyword(self):
        obj = _only(self.analyzer, "CREATE TEXT SEARCH DICTIONARY d (TEMPLATE = simple)")
        self.assertEqual(obj["object_type"], "UNKNOWN")
        self.assertIn("d", obj["object_name"].rsplit(".", 1)[-1])
        self.assertNotIn("SEARCH", obj["object_name"].upper())

    def test_event_trigger_is_not_reported_as_an_event_named_trigger(self):
        # EVENT is a modelled type (MySQL scheduled events); PostgreSQL's
        # EVENT TRIGGER is a different, unmodelled two-word type.
        obj = _only(
            self.analyzer, "CREATE EVENT TRIGGER et ON ddl_command_end EXECUTE FUNCTION f()"
        )
        self.assertNotIn("TRIGGER", obj["object_name"].upper())
        self.assertIn("et", obj["object_name"].rsplit(".", 1)[-1])

    def test_alter_publication_reports_the_publication_not_the_table(self):
        # The statement alters `pub`. A modelled keyword appearing later in the
        # statement (`TABLE t`) must not displace the real subject.
        obj = _only(self.analyzer, "ALTER PUBLICATION pub ADD TABLE t")
        self.assertIn("pub", obj["object_name"].rsplit(".", 1)[-1])
        self.assertNotEqual(obj["object_name"].rsplit(".", 1)[-1], "t")

    def test_create_server_reports_the_server_not_its_wrapper(self):
        # CREATE SERVER always carries a FOREIGN DATA WRAPPER clause, so this
        # is the standard form, not an edge case.
        obj = _only(self.analyzer, "CREATE SERVER srv FOREIGN DATA WRAPPER fdw")
        self.assertIn("srv", obj["object_name"].rsplit(".", 1)[-1])
        self.assertNotIn("fdw", obj["object_name"])

    def test_create_foreign_data_wrapper_is_typed(self):
        obj = _only(self.analyzer, "CREATE FOREIGN DATA WRAPPER fdw HANDLER h")
        self.assertEqual(obj["object_type"], "FOREIGN_DATA_WRAPPER")
        self.assertIn("fdw", obj["object_name"].rsplit(".", 1)[-1])


class TestStatementsThatNameATargetTable(unittest.TestCase):
    """``TRUNCATE``/``COMMENT``/``GRANT``/DML all identify a table."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_truncate_table(self):
        obj = _only(self.analyzer, "TRUNCATE TABLE users")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])

    def test_truncate_without_the_table_keyword(self):
        obj = _only(self.analyzer, "TRUNCATE users")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])

    def test_comment_on_table_reports_the_table(self):
        obj = _only(self.analyzer, "COMMENT ON TABLE users IS 'people'")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])

    def test_comment_on_column_reports_the_table_it_belongs_to(self):
        obj = _only(self.analyzer, "COMMENT ON COLUMN users.email IS 'contact'")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])

    def test_grant_reports_the_granted_object(self):
        obj = _only(self.analyzer, "GRANT SELECT ON users TO analyst")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])

    def test_insert_reports_the_target_table(self):
        obj = _only(self.analyzer, "INSERT INTO users (id) VALUES (1)")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])

    def test_update_reports_the_target_table(self):
        obj = _only(self.analyzer, "UPDATE users SET email = 'x' WHERE id = 1")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])

    def test_delete_reports_the_target_table(self):
        obj = _only(self.analyzer, "DELETE FROM users WHERE id = 1")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])

    def test_merge_reports_the_target_table(self):
        sql = "MERGE INTO users u USING staged s ON (u.id = s.id) WHEN MATCHED THEN UPDATE SET u.email = s.email"
        obj = _only(self.analyzer, sql)
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("users", obj["object_name"])


class TestNoFalsePositives(unittest.TestCase):
    """Statements that genuinely name no object must stay empty."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_empty_input(self):
        self.assertEqual(self.analyzer.extract_objects(""), [])
        self.assertEqual(self.analyzer.extract_objects("   "), [])

    def test_plain_select_names_no_affected_object(self):
        # A read-only query affects nothing; reporting the queried table as an
        # "affected object" would put reads into the journal's change stats.
        self.assertEqual(self.analyzer.extract_objects("SELECT * FROM users"), [])

    def test_object_keyword_inside_a_string_literal_is_not_an_object(self):
        # A DDL statement, so the DDL patterns actually run over it -- with a
        # DML statement here the `elif` chain routes to the DML branch before
        # any DDL regex is consulted, and the test would pass with every
        # anchor removed.
        sql = "CREATE TABLE audit (note VARCHAR(50) DEFAULT 'CREATE SEQUENCE fake_seq')"
        obj = _only(self.analyzer, sql)
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("audit", obj["object_name"])

    def test_ddl_nested_in_a_routine_body_does_not_displace_the_routine(self):
        # Pins the \A anchoring. Mutation testing showed removing the anchors
        # left the whole suite green while this statement reported the nested
        # index instead of the trigger.
        sql = (
            "CREATE TRIGGER tg AFTER INSERT ON u FOR EACH ROW " "BEGIN CREATE INDEX i ON u (c); END"
        )
        obj = _only(self.analyzer, sql)
        self.assertEqual(obj["object_type"], "TRIGGER")
        self.assertIn("tg", obj["object_name"])

    def test_dml_nested_in_a_dollar_quoted_body_does_not_displace_the_function(self):
        sql = (
            "CREATE FUNCTION f() RETURNS void AS $$ BEGIN "
            "DELETE FROM huge_table; END $$ LANGUAGE plpgsql"
        )
        obj = _only(self.analyzer, sql)
        self.assertEqual(obj["object_type"], "FUNCTION")
        self.assertNotIn("huge_table", obj["object_name"])


class TestAKeywordIsNeverTheObjectName(unittest.TestCase):
    """Returning ``[]`` is acceptable. Naming a keyword is not.

    Every statement here is valid SQL that previously returned ``[]``. A
    confidently wrong name is the worst outcome this function can produce: it
    is what callers display, group their stats by, and build undo statements
    from. If the name cannot be identified with confidence, report nothing.
    """

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def _name_of(self, sql: str):
        objects = self.analyzer.extract_objects(sql)
        if not objects:
            return None
        return objects[0]["object_name"].rsplit(".", 1)[-1].upper()

    def test_no_statement_reports_a_bare_keyword_as_its_name(self):
        cases = {
            # (statement, the keyword that must not become the name)
            "GRANT USAGE ON FOREIGN SERVER srv TO u": "FOREIGN",
            "CREATE OR ALTER PROCEDURE p AS SELECT 1": "ALTER",
            "CREATE OR REPLACE FORCE EDITIONABLE VIEW v AS SELECT 1": "EDITIONABLE",
            "ALTER DEFAULT PRIVILEGES IN SCHEMA s GRANT SELECT ON TABLES TO r": "PRIVILEGES",
            "CREATE OPERATOR CLASS oc FOR TYPE int USING btree AS OPERATOR 1 =": "CLASS",
            "TRUNCATE TABLE ONLY users": "ONLY",
            "CREATE INDEX ON orders (email)": "ON",
            "CREATE INDEX CONCURRENTLY ON orders (email)": "CONCURRENTLY",
            "ALTER TABLE ONLY users ADD COLUMN c INT": "ONLY",
            "DROP INDEX CONCURRENTLY idx": "CONCURRENTLY",
        }
        for sql, forbidden in cases.items():
            with self.subTest(sql=sql):
                self.assertNotEqual(self._name_of(sql), forbidden)

    def test_only_modifier_still_finds_the_real_table(self):
        # ONLY is PostgreSQL's no-inheritance modifier; the real object is
        # named right after it, so this should resolve rather than decline.
        for sql in ("TRUNCATE TABLE ONLY users", "ALTER TABLE ONLY users ADD COLUMN c INT"):
            with self.subTest(sql=sql):
                self.assertEqual(self._name_of(sql), "USERS")

    def test_an_unnamed_index_build_reports_no_index_name(self):
        # PostgreSQL allows CREATE INDEX with no name (it auto-names). There
        # is no index name to report; the table it builds on still is.
        objects = self.analyzer.extract_objects("CREATE INDEX ON orders (email)")
        for obj in objects:
            self.assertNotEqual(obj["object_name"].rsplit(".", 1)[-1].upper(), "ON")
            if "on_object" in obj:
                self.assertIn("orders", obj["on_object"])


class TestClauseKeywordGuardDoesNotRejectRealObjects(unittest.TestCase):
    """The guard must not discard an object a modelled keyword vouched for.

    A table may legitimately be named ``checkpoint``, ``set`` or ``enable``.
    When the statement says ``ON TABLE checkpoint``, the keyword ``TABLE``
    identifies what follows as an object name, so the clause-keyword safety
    net must not fire there -- it exists for the case where nothing vouches.
    """

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_a_vouched_name_survives_the_guard(self):
        obj = _only(self.analyzer, "GRANT SELECT ON TABLE checkpoint TO r")
        self.assertEqual(obj["object_type"], "TABLE")
        self.assertIn("checkpoint", obj["object_name"])

    def test_an_unvouched_clause_keyword_is_still_rejected(self):
        # The guard's real job: nothing identifies a name here.
        self.assertEqual(self.analyzer.extract_objects("DROP OWNED BY r"), [])
        self.assertEqual(self.analyzer.extract_objects("CREATE USER MAPPING FOR u SERVER s"), [])

    def test_leading_comment_does_not_hide_the_statement(self):
        sql = "-- create the sequence\nCREATE SEQUENCE users_seq START WITH 1"
        obj = _only(self.analyzer, sql)
        self.assertEqual(obj["object_type"], "SEQUENCE")


class TestSchemaQualification(unittest.TestCase):
    """Schema handling matches the existing branches' convention."""

    def setUp(self):
        self.analyzer = SqlAnalyzer(dialect="postgresql")

    def test_qualified_name_keeps_its_schema(self):
        obj = _only(self.analyzer, "CREATE SEQUENCE app.users_seq START WITH 1")
        self.assertEqual(obj["object_name"], "app.users_seq")

    def test_unqualified_name_uses_the_default_schema_placeholder(self):
        obj = _only(self.analyzer, "CREATE SEQUENCE users_seq START WITH 1")
        self.assertEqual(obj["object_name"], "default_schema.users_seq")

    def test_quoted_identifier_is_one_atom(self):
        obj = _only(self.analyzer, 'CREATE SEQUENCE "app"."users seq" START WITH 1')
        self.assertEqual(obj["object_type"], "SEQUENCE")
        self.assertIn("users seq", obj["object_name"])


if __name__ == "__main__":
    unittest.main()
